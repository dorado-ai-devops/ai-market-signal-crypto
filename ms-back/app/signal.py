from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional, Tuple
import math
import logging
import time

from sqlalchemy import select, func, desc

from app.settings import settings
from app.storage import get_session, Item, Signal, Price
from app import events

log = logging.getLogger("ms.signal")

_last_emit_ts = 0.0
_last_action: Optional[str] = None

def _to_floats(values: Iterable[Optional[float]]) -> List[float]:
    out: List[float] = []
    for v in values:
        if v is None:
            continue
        try:
            out.append(float(v))
        except Exception:
            continue
    return out

def ema(values: Iterable[Optional[float]], period: int) -> Optional[float]:
    vals = _to_floats(values)
    if period <= 0 or len(vals) == 0:
        return None
    alpha = 2.0 / (period + 1.0)
    e = None
    for v in vals:
        e = v if e is None else alpha * v + (1.0 - alpha) * e
    return e

def rsi(values: Iterable[Optional[float]], period: int = 14) -> Optional[float]:
    vals = _to_floats(values)
    if period <= 0 or len(vals) <= period:
        return None
    gains = 0.0
    losses = 0.0
    prev = vals[0]
    count = 0
    for v in vals[1 : period + 1]:
        change = v - prev
        if change > 0:
            gains += change
        else:
            losses += -change
        prev = v
        count += 1
    if count < period:
        return None
    avg_gain = gains / period
    avg_loss = losses / period
    for v in vals[period + 1 :]:
        change = v - prev
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        prev = v
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def macd(values: Iterable[Optional[float]], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[Optional[float], Optional[float]]:
    vals = _to_floats(values)
    if len(vals) < max(fast, slow) + signal:
        return None, None

    def _ema_series(x: List[float], p: int) -> List[float]:
        a = 2.0 / (p + 1.0)
        out: List[float] = []
        e = None
        for v in x:
            e = v if e is None else a * v + (1.0 - a) * e
            out.append(e)
        return out

    ema_fast = _ema_series(vals, fast)
    ema_slow = _ema_series(vals, slow)
    n = min(len(ema_fast), len(ema_slow))
    macd_line_series = [ema_fast[i] - ema_slow[i] for i in range(n)]
    if len(macd_line_series) < signal:
        last_val = macd_line_series[-1] if macd_line_series else None
        return last_val, None
    macd_signal_series = _ema_series(macd_line_series, signal)
    return macd_line_series[-1], macd_signal_series[-1] if macd_signal_series else None

def atr_pct(prices: List[Price], period: int = 14) -> Optional[float]:
    if len(prices) <= period:
        return None
    trs: List[float] = []
    prev_close = None
    for p in prices:
        if p.h is None or p.l is None or p.c is None:
            prev_close = p.c if p.c is not None else prev_close
            continue
        high = float(p.h)
        low = float(p.l)
        close = float(p.c)
        if prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
        prev_close = close
    if len(trs) <= period:
        return None
    last_trs = trs[-period:]
    atr = sum(last_trs) / period if period > 0 else None
    last_close = float(prices[-1].c) if prices and prices[-1].c is not None else None
    if atr is None or last_close in (None, 0.0):
        return None
    return (atr / last_close) * 100.0

def _get_recent_prices(s, symbol: str, timeframe: str, lookback_minutes: int = 24 * 60) -> List[Price]:
    now = datetime.now(timezone.utc)
    t0 = now - timedelta(minutes=lookback_minutes)
    rows = (
        s.query(Price)
        .filter(Price.symbol == symbol, Price.timeframe == timeframe, Price.ts >= t0, Price.c.isnot(None))
        .order_by(Price.ts.asc())
        .all()
    )
    return rows

def _rolling_high_low(prices: List[Price], window: int) -> Tuple[Optional[float], Optional[float]]:
    if not prices:
        return None, None
    highs = [float(p.h) for p in prices if p.h is not None]
    lows = [float(p.l) for p in prices if p.l is not None]
    if len(highs) == 0 or len(lows) == 0:
        return None, None
    last_high = max(highs[-window:]) if len(highs) >= window else max(highs)
    last_low = min(lows[-window:]) if len(lows) >= window else min(lows)
    return last_high, last_low

def _pct_change(closes: List[float], minutes: int, timeframe_min: int = 1) -> Optional[float]:
    if not closes:
        return None
    steps = max(1, int(minutes / timeframe_min))
    if len(closes) <= steps:
        return None
    ref = float(closes[-steps - 1])
    last = float(closes[-1])
    if ref == 0:
        return None
    return (last - ref) / ref * 100.0

def _vwap(prices: List[Price], minutes: int, timeframe_min: int = 1) -> Optional[float]:
    if not prices:
        return None
    steps = max(1, int(minutes / timeframe_min))
    sub = prices[-steps:] if len(prices) >= steps else prices
    num = 0.0
    den = 0.0
    for p in sub:
        if p.v is None or p.c is None or p.h is None or p.l is None:
            continue
        typical = (float(p.h) + float(p.l) + float(p.c)) / 3.0
        vol = float(p.v)
        num += typical * vol
        den += vol
    return (num / den) if den > 0 else None

def _price_indicators(prices: List[Price], timeframe_min: int = 1) -> Optional[dict]:
    if not prices:
        return None
    closes = [float(p.c) for p in prices if p.c is not None]
    if len(closes) < 30:
        return None

    last_close = closes[-1]
    rsi14 = rsi(closes, 14)
    macd_val, macd_sig = macd(closes, 12, 26, 9)
    atrp = atr_pct(prices, 14)

    ema20_prev = ema(closes[:-1], 20)
    ema20_now = ema(closes, 20)
    price_bias = None
    if ema20_prev is not None and ema20_now is not None:
        if ema20_now > ema20_prev * 1.001:
            price_bias = "up"
        elif ema20_now < ema20_prev * 0.999:
            price_bias = "down"
        else:
            price_bias = "flat"

    chg_15m = _pct_change(closes, 15, timeframe_min=timeframe_min)
    chg_1h = _pct_change(closes, 60, timeframe_min=timeframe_min)
    vwap_1h = _vwap(prices, 60, timeframe_min=timeframe_min)
    vwap_15m = _vwap(prices, 15, timeframe_min=timeframe_min)

    high_4h, low_4h = _rolling_high_low(prices, window=max(1, int(240 / timeframe_min)))
    high_24h, low_24h = _rolling_high_low(prices, window=max(1, int(1440 / timeframe_min)))

    breakout_high_4h = high_4h is not None and last_close > high_4h * 1.0005
    breakout_low_4h = low_4h is not None and last_close < low_4h * 0.9995

    range_24h_pct = None
    if high_24h and low_24h and last_close:
        range_24h_pct = (high_24h - low_24h) / last_close * 100.0

    return {
        "price_close": last_close,
        "rsi14": rsi14,
        "macd": macd_val,
        "macd_signal": macd_sig,
        "atr_pct": atrp,
        "price_bias": price_bias,
        "pct_change_15m": chg_15m,
        "pct_change_1h": chg_1h,
        "vwap_15m": vwap_15m,
        "vwap_1h": vwap_1h,
        "high_4h": high_4h,
        "low_4h": low_4h,
        "high_24h": high_24h,
        "low_24h": low_24h,
        "range_24h_pct": range_24h_pct,
        "breakout_high_4h": breakout_high_4h,
        "breakout_low_4h": breakout_low_4h,
    }

def _ema_sentiment(values: Iterable[Optional[float]], period: int = 15) -> float:
    e = None
    alpha = 2.0 / (1.0 + period)
    for v in values:
        if v is None:
            continue
        e = v if e is None else alpha * v + (1.0 - alpha) * e
    return 0.0 if e is None else float(e)

def _z(x: float, mu: float, sigma: float, clip: float = 3.0) -> float:
    if sigma <= 1e-9:
        return 0.0
    z = (x - mu) / sigma
    if clip:
        z = max(-clip, min(clip, z))
    return z

def _compute_alpha(ema15: float, mentions_15m: int, baseline_7d: float, pi: Optional[dict]) -> Tuple[float, dict]:
    mu = baseline_7d
    sigma = max(1.0, baseline_7d * 0.5)
    z_mentions = _z(mentions_15m, mu, sigma, clip=4.0)

    z_sent = max(-1.0, min(1.0, ema15))

    z_mom_15 = _z((pi.get("pct_change_15m") or 0.0), 0.0, 0.5, clip=4.0) if pi else 0.0
    z_mom_1h = _z((pi.get("pct_change_1h") or 0.0), 0.0, 1.0, clip=4.0) if pi else 0.0

    rsi = pi.get("rsi14") if pi else None
    z_rsi = 0.0
    if rsi is not None:
        if rsi < 30:
            z_rsi = (30.0 - rsi) / 30.0
        elif rsi > 70:
            z_rsi = - (rsi - 70.0) / 30.0

    bo = 0.0
    if pi:
        if pi.get("breakout_high_4h"):
            bo = 0.5
        elif pi.get("breakout_low_4h"):
            bo = -0.5

    bias = pi.get("price_bias") if pi else "flat"
    bias_mult = 1.0
    if bias == "up":
        bias_mult = 1.15
    elif bias == "down":
        bias_mult = 0.85

    atrp = pi.get("atr_pct") if pi else None
    risk_mult = 1.0
    if atrp is not None:
        if atrp > 2.0:
            risk_mult = 0.85
        if atrp > 4.0:
            risk_mult = 0.7

    w_mentions = getattr(settings, "alpha_w_mentions", 0.35)
    w_sent     = getattr(settings, "alpha_w_sent",     0.30)
    w_mom      = getattr(settings, "alpha_w_mom",      0.25)
    w_rsi      = getattr(settings, "alpha_w_rsi",      0.05)
    w_bo       = getattr(settings, "alpha_w_breakout", 0.05)

    z_mom = 0.6 * z_mom_15 + 0.4 * z_mom_1h

    raw = (
        w_mentions * z_mentions +
        w_sent     * z_sent     +
        w_mom      * z_mom      +
        w_rsi      * z_rsi      +
        w_bo       * bo
    )

    alpha = max(-1.0, min(1.0, raw * bias_mult * risk_mult))
    contrib = {
        "z_mentions": z_mentions,
        "z_sent": z_sent,
        "z_mom_15": z_mom_15,
        "z_mom_1h": z_mom_1h,
        "z_rsi": z_rsi,
        "bo": bo,
        "bias_mult": bias_mult,
        "risk_mult": risk_mult,
        "raw": raw,
        "alpha": alpha,
    }
    return alpha, contrib

def compute_once():
    global _last_emit_ts, _last_action

    s = get_session()
    try:
        now = datetime.now(timezone.utc)
        t0 = now - timedelta(minutes=15)

        q_scores = select(Item.score).where(Item.asset == settings.asset, Item.ts >= t0)
        scores = [r[0] for r in s.execute(q_scores)]
        ema15 = _ema_sentiment(scores, 15)

        mentions_15m = s.execute(
            select(func.count()).where(Item.asset == settings.asset, Item.ts >= t0)
        ).scalar_one()

        t7 = now - timedelta(days=7)
        total_7d = s.execute(
            select(func.count()).where(Item.asset == settings.asset, Item.ts >= t7)
        ).scalar_one()
        baseline = total_7d / max(1, 7 * 24 * 4)

        symbol = getattr(settings, "price_symbol", "ETH/USDT")
        timeframe = getattr(settings, "price_timeframe", "1m")
        timeframe_min = 1
        if isinstance(timeframe, str) and timeframe.endswith("m"):
            try:
                timeframe_min = int(timeframe[:-1])
            except Exception:
                timeframe_min = 1

        prices = _get_recent_prices(s, symbol, timeframe, lookback_minutes=24 * 60)
        pi = _price_indicators(prices, timeframe_min=timeframe_min) if prices else None

        alpha, contrib = _compute_alpha(ema15, mentions_15m, baseline, pi or {})

        up_th   = getattr(settings, "alpha_threshold_up",  0.33)
        down_th = getattr(settings, "alpha_threshold_down", -0.33)

        action = "hold"
        if alpha >= up_th:
            action = "accumulate"
        elif alpha <= down_th:
            action = "wait"
        if _last_action and _last_action != action:
            if _last_action == "accumulate" and alpha > 0.2:
                action = "accumulate"
            if _last_action == "wait" and alpha < -0.2:
                action = "wait"

        sig = Signal(
            asset=settings.asset,
            ema15=ema15,
            mentions=int(mentions_15m),
            action=action,
            price_close=pi.get("price_close") if pi else None,
            rsi14=pi.get("rsi14") if pi else None,
            macd=pi.get("macd") if pi else None,
            macd_signal=pi.get("macd_signal") if pi else None,
            atr_pct=pi.get("atr_pct") if pi else None,
            price_bias=pi.get("price_bias") if pi else None,
        )
        s.add(sig)
        s.commit()

        # log
        log.info(
            "signal: ema15=%.3f mentions=%d baseline=%.2f action=%s price_close=%.2f rsi14=%s macd=%.3f macd_sig=%.3f atr%%=%s bias=%s alpha=%.2f",
            ema15, mentions_15m, baseline, action,
            (pi.get("price_close") if pi else float("nan")) or float("nan"),
            f"{pi['rsi14']:.1f}" if pi and pi.get("rsi14") is not None else "n/a",
            (pi.get("macd") if pi else float("nan")) or float("nan"),
            (pi.get("macd_signal") if pi else float("nan")) or float("nan"),
            f"{pi['atr_pct']:.2f}" if pi and pi.get("atr_pct") is not None else "n/a",
            pi.get("price_bias") if pi else "n/a",
            alpha,
        )

        # rate-limit emisión
        emit_min_interval = max(2.0, float(getattr(settings, "signal_emit_min_seconds", 5)))
        should_emit = (time.time() - _last_emit_ts) >= emit_min_interval
        crosses_band = abs(alpha) >= 0.66 or (_last_action != action)

        # razonamiento legible
        reasons: List[str] = []
        reasons.append(f"alpha={alpha:.2f} (raw={contrib['raw']:.2f})")
        reasons.append(f"mentions z={contrib['z_mentions']:.2f} vs baseline~{baseline:.2f} (15m={mentions_15m})")
        reasons.append(f"sentiment ema15={ema15:.2f}")
        if pi:
            reasons.append(f"mom: Δ15m={pi.get('pct_change_15m') or 0:.2f}%, Δ1h={pi.get('pct_change_1h') or 0:.2f}%")
            if pi.get("rsi14") is not None:
                reasons.append(f"RSI14={pi['rsi14']:.1f} ({'OS' if pi['rsi14']<30 else 'OB' if pi['rsi14']>70 else 'neutral'})")
            if pi.get("breakout_high_4h"):
                reasons.append("breakout ↑ 4h")
            if pi.get("breakout_low_4h"):
                reasons.append("breakout ↓ 4h")
            if pi.get("price_bias"):
                reasons.append(f"bias={pi.get('price_bias')} mult={contrib['bias_mult']:.2f}")
            if pi.get("atr_pct") is not None:
                reasons.append(f"ATR%={pi['atr_pct']:.2f} risk_mult={contrib['risk_mult']:.2f}")

        _last_action = action

        if should_emit or crosses_band:
            _last_emit_ts = time.time()

            parts = [
                f"ema15={ema15:.2f}",
                f"mentions={mentions_15m}",
                f"baseline={baseline:.2f}",
                f"action={action.upper()}",
                f"alpha={alpha:.2f}",
            ]
            if pi:
                if pi.get("pct_change_15m") is not None:
                    parts.append(f"Δ15m={pi['pct_change_15m']:.2f}%")
                if pi.get("pct_change_1h") is not None:
                    parts.append(f"Δ1h={pi['pct_change_1h']:.2f}%")
                if pi.get("rsi14") is not None:
                    parts.append(f"RSI={pi['rsi14']:.1f}")
                if pi.get("macd") is not None and pi.get("macd_signal") is not None:
                    parts.append(f"MACD={pi['macd']:.2f}/{pi['macd_signal']:.2f}")
                if pi.get("atr_pct") is not None:
                    parts.append(f"ATR%={pi['atr_pct']:.2f}")
                if pi.get("breakout_high_4h"):
                    parts.append("BO↑4h")
                if pi.get("breakout_low_4h"):
                    parts.append("BO↓4h")

            events.emit(
                "signal",
                " ".join(parts),
                {
                    "asset": getattr(settings, "ASSET", "ETH-USD"),
                    "ema15": ema15,
                    "mentions_15m": mentions_15m,
                    "baseline_7d": baseline,
                    "action": action,
                    "alpha": alpha,
                    "contrib": contrib,
                    "reason": reasons,     # ← explicación legible
                    "price": pi or {},
                },
            )

        return {
            "ema15": ema15,
            "mentions_15m": mentions_15m,
            "baseline_7d": baseline,
            "action": action,
            "alpha": alpha,
            "price": pi or {},
        }
    finally:
        s.close()
