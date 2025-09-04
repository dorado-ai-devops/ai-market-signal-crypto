# app/summary.py
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

from sqlalchemy import select, desc, func

from app.storage import get_session, Item, Signal, Price
from app.settings import settings
from app import llm

log = logging.getLogger("ms.summary")

# -------------------- Config & caché --------------------
_SUMMARY_MIN_SECONDS = int(getattr(settings, "summary_min_seconds", 60))
_MAX_ITEMS = int(getattr(settings, "summary_max_items", 12))      # límite de items en el contexto
_MAX_TEXT = int(getattr(settings, "summary_max_text_len", 220))   # truncado por item
_CACHE: Optional[Dict[str, Any]] = None
_CACHE_TS: Optional[float] = None
# --------------------------------------------------------


def _fmt_ts(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def _load_facts() -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    s = get_session()
    try:
        # Última señal
        last_sig = s.execute(
            select(Signal).order_by(desc(Signal.ts)).limit(1)
        ).scalar_one_or_none()

        # Precio últimas 60m
        t_from = now - timedelta(minutes=60)
        prices: List[Price] = s.execute(
            select(Price)
            .where(
                Price.symbol == getattr(settings, "price_symbol", "ETH/USDT"),
                Price.timeframe == getattr(settings, "price_timeframe", "1m"),
                Price.ts >= t_from,
            )
            .order_by(Price.ts)
        ).scalars().all()

        px = [{"ts": _fmt_ts(p.ts), "c": float(p.c)} for p in prices]
        pct_60m = None
        if len(prices) >= 2:
            pct_60m = (prices[-1].c / prices[0].c - 1.0) * 100.0

        # Items relevantes recientes (limitados y truncados)
        items: List[Item] = s.execute(
            select(Item)
            .where(Item.llm_relevant.is_(True))
            .order_by(desc(Item.ts))
            .limit(_MAX_ITEMS)
        ).scalars().all()

        it = [
            {
                "ts": _fmt_ts(i.ts),
                "src": i.source,
                "score": float(i.score or 0.0),
                "llm_conf": float(i.llm_score or 0.0),
                "labels": i.llm_labels or "",
                "text": (i.text or "")[:_MAX_TEXT],
            }
            for i in items
        ]

        # Contadores
        last_15m = now - timedelta(minutes=15)
        mentions_15m = s.execute(
            select(func.count())
            .select_from(Item)
            .where(Item.ts >= last_15m, Item.llm_relevant.is_(True))
        ).scalar() or 0

        facts = {
            "now_utc": _fmt_ts(now),
            "asset": getattr(settings, "asset", "ETH-USD"),
            "signal": {
                "ema15": float(getattr(last_sig, "ema15", 0.0) or 0.0),
                "mentions_15m": int(getattr(last_sig, "mentions", 0) or 0),
                # baseline real no está en tabla: mantenemos placeholder 0.0
                "baseline_7d": 0.0,
                "action": getattr(last_sig, "action", "hold") or "hold",
                "ts": _fmt_ts(getattr(last_sig, "ts", now)),
            }
            if last_sig
            else {
                "ema15": 0.0,
                "mentions_15m": mentions_15m,
                "baseline_7d": 0.0,
                "action": "hold",
                "ts": _fmt_ts(now),
            },
            "price": {
                "pct_change_60m": pct_60m,
                "series_close": px[-10:],  # últimos 10 puntos
            },
            "items_sample": it,
            "counts": {
                "items_llm_relevant_15m": mentions_15m,
                "items_sample_count": len(it),
            },
        }
        return facts
    finally:
        s.close()


def _facts_to_text(f: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"now_utc: {f['now_utc']}")
    lines.append(f"asset: {f['asset']}")

    sig = f["signal"]
    lines.append(
        f"signal: action={sig['action']} ema15={sig['ema15']:.2f} mentions_15m={sig['mentions_15m']}"
    )

    pct = f["price"]["pct_change_60m"]
    if pct is not None:
        lines.append(f"price: pct_change_60m={pct:.2f}%")

    series = f["price"]["series_close"]
    if series:
        last = series[-1]
        lines.append(f"price_last: {last['c']:.2f} @ {last['ts']}")

    lines.append(
        f"items: sample_count={f['counts']['items_sample_count']} recent_relevant_15m={f['counts']['items_llm_relevant_15m']}"
    )
    for i in f["items_sample"]:
        lines.append(
            f"- [{i['ts']} {i['src']}] score={i['score']:.2f} llm={i['llm_conf']:.2f} labels={i['labels']} text={i['text']}"
        )
    return "\n".join(lines)


def _call_llm_summarize(facts_text: str) -> Optional[str]:
    """
    Intenta usar llm.summarize si existe; si no, usa simple_generate.
    Devuelve None si falla.
    """
    prompt = (
        "Eres un asistente de mercados cripto. Resume en **máximo 5 viñetas** "
        "(o 3 líneas si es más natural) el estado actual de ETH combinando sentimiento, "
        "momentum y flujo de noticias. Sé específico y conciso. Incluye una línea final "
        "con *sesgo actual* (bullish/neutral/bearish). Responde en **Markdown**.\n\n"
        "Contexto:\n"
        f"{facts_text}\n\n"
        "Salida solo en Markdown, sin prefacios."
    )

    # 1) Si el proyecto ya tiene llm.summarize, úsalo.
    if hasattr(llm, "summarize"):
        try:
            text = llm.summarize(prompt)
            if isinstance(text, str) and text.strip():
                return text.strip()
        except Exception as e:
            log.warning("llm.summarize failed: %s", e)

    # 2) Fallback a simple_generate si existe.
    if hasattr(llm, "simple_generate"):
        try:
            ok, body = llm.simple_generate(prompt)  # type: ignore[attr-defined]
            if ok and isinstance(body, str) and body.strip():
                return body.strip()
        except Exception as e:
            log.warning("llm.simple_generate failed: %s", e)

    return None


def generate_commentary() -> Dict[str, Any]:
    """
    Genera comentario con caché y tolerancia a fallos.
    - Si han pasado menos de SUMMARY_MIN_SECONDS desde el último éxito, devuelve caché.
    - Si el LLM falla, devuelve caché con stale=True. Si no hay caché, devuelve vacío.
    """
    global _CACHE, _CACHE_TS

    # Rate limit por TTL
    now_ts = datetime.now(timezone.utc).timestamp()
    if _CACHE and _CACHE_TS and (now_ts - _CACHE_TS) < _SUMMARY_MIN_SECONDS:
        return {**_CACHE, "stale": False}

    # Construir contexto
    facts = _load_facts()
    facts_text = _facts_to_text(facts)

    # Llamar LLM
    summary = _call_llm_summarize(facts_text)

    if summary:
        res = {
            "commentary": summary,
            "facts": facts,
            "model": getattr(settings, "llm_model", "unknown"),
            "generated_at": facts["now_utc"],
            "stale": False,
        }
        _CACHE, _CACHE_TS = res, now_ts
        return res

    # Fallback: devolver último válido si lo hay
    if _CACHE:
        log.warning("summary: returning cached (stale) due to LLM failure")
        return {**_CACHE, "stale": True}

    # Último recurso: vacío pero no rompemos
    log.warning("summary: unavailable and no cache")
    return {
        "commentary": "",
        "facts": facts,
        "model": getattr(settings, "llm_model", "unknown"),
        "generated_at": facts["now_utc"],
        "stale": True,
        "error": "llm_unavailable",
    }
