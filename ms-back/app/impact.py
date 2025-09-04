# app/impact.py
import math
import json
import logging
from bisect import bisect_left
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, asc, or_
from app.storage import get_session, Item, Price
from app.settings import settings
from app import events

log = logging.getLogger("ms.impact")

SYMBOL = getattr(settings, "price_symbol", "ETH/USDT")
TF = getattr(settings, "price_timeframe", "1m")


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _std(vals):
    n = len(vals)
    if n < 2:
        return 0.0
    m = sum(vals) / n
    var = sum((x - m) * (x - m) for x in vals) / (n - 1)
    return math.sqrt(max(0.0, var))


def _compute_sigma(closes: list[float], k: int) -> float:
    """Desviación típica de retornos k-step (p[i+k]/p[i]-1) sobre la serie."""
    rets = []
    for i in range(0, len(closes) - k):
        p0 = closes[i]
        p1 = closes[i + k]
        if p0 and p1:
            rets.append((p1 / p0) - 1.0)
    return _std(rets)


def run_once(limit: int = 400) -> int:
    """
    Calcula impacto para items sin impact:
      - ret_15m y ret_60m
      - normaliza por sigma15/sigma60
      - guarda 'impact' como el normalizado a 15m (más rápido de ver),
        y 'impact_meta' con JSON detallado para inspección.
    Impact normalizado clamp a [-1, 1].
    """
    s = get_session()
    processed = 0
    try:
        # 1) tomar items pendientes
        items = (
            s.execute(
                select(Item)
                .where(or_(Item.impact.is_(None), Item.impact_meta.is_(None)))
                .order_by(asc(Item.ts))
                .limit(limit)
            )
            .scalars()
            .all()
        )
        if not items:
            return 0

        t_min = items[0].ts
        t_max = items[-1].ts

        # 2) traer velas de precio para rango ampliado
        t0 = t_min - timedelta(hours=6)
        t1 = t_max + timedelta(hours=3)

        prices = (
            s.execute(
                select(Price)
                .where(
                    Price.symbol == SYMBOL,
                    Price.timeframe == TF,
                    Price.ts >= t0,
                    Price.ts <= t1,
                )
                .order_by(asc(Price.ts))
            )
            .scalars()
            .all()
        )
        if len(prices) < 120:  # necesitamos cierto histórico
            log.info("impact: precios insuficientes para el rango pedido")
            return 0

        ts_list = [p.ts for p in prices]
        cl_list = [float(p.c) for p in prices]

        # 3) baselines de volatilidad
        sigma15 = _compute_sigma(cl_list, 15) or 0.004  # ~0.4%
        sigma60 = _compute_sigma(cl_list, 60) or 0.008  # ~0.8%

        for it in items:
            # índice de la vela >= ts del item
            idx = bisect_left(ts_list, it.ts)
            if idx < 0 or idx >= len(cl_list):
                continue

            # necesitamos futuro a 15m
            if idx + 15 >= len(cl_list):
                continue

            p0 = cl_list[idx]
            p15 = cl_list[idx + 15]
            ret15 = (p15 / p0) - 1.0 if (p0 and p15) else 0.0
            norm15 = _clamp(ret15 / (2.0 * sigma15), -1.0, 1.0)

            # 60m opcional si hay velas
            ret60 = None
            norm60 = None
            p60 = None
            if idx + 60 < len(cl_list):
                p60 = cl_list[idx + 60]
                ret60 = (p60 / p0) - 1.0 if (p0 and p60) else 0.0
                norm60 = _clamp(ret60 / (2.0 * sigma60), -1.0, 1.0)

            # guardamos impacto breve (15m) y meta JSON
            it.impact = float(norm15)
            meta = {
                "symbol": SYMBOL,
                "timeframe": TF,
                "p0": p0,
                "p15": p15,
                "p60": p60,
                "ret_15m": ret15,
                "ret_60m": ret60,
                "sigma15": sigma15,
                "sigma60": sigma60,
                "norm_15m": norm15,
                "norm_60m": norm60,
                "computed_at": datetime.now(timezone.utc).isoformat(),
            }
            it.impact_meta = json.dumps(meta, ensure_ascii=False)
            processed += 1

        s.commit()

    finally:
        s.close()

    if processed:
        events.emit("item", f"{processed} impacts computed (batch)", {"count": processed, "source": "impact"})
    log.info("impact: processed=%d", processed)
    return processed


def loop(stop):
    poll = max(30, getattr(settings, "poll_seconds", 60))
    while not stop.is_set():
        try:
            run_once(400)
        except Exception:
            log.exception("impact loop error")
        stop.wait(poll)
