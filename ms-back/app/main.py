# app/main.py
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager
from threading import Thread, Event
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func, desc
from sqlalchemy.sql import text as sql_text
from typing import Optional
import logging, sys, json, asyncio

from app.settings import settings
from app.storage import init_db, get_session, Item, Signal
from app.signal import compute_once
from app.schemas import State, SignalOut, ItemOut, Metrics, ImpactItemOut
from app import events
from app import summary as summary_mod

stop_event = Event()
threads: list[Thread] = []

def _setup_logging():
    level_name = (getattr(settings, "log_level", "INFO") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter(fmt="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    ch.setLevel(level)
    root.addHandler(ch)
    logging.getLogger("ms.x").setLevel(level)
    logging.getLogger("ms.llm").setLevel(level)
    logging.getLogger("ms.signal").setLevel(level)
    logging.getLogger("ms.price").setLevel(level)
    logging.getLogger("ms.impact").setLevel(level)
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)

def x_loop(stop: Event):
    try:
        from app.ingestors.x_search_io import run_once as x_run_once
    except Exception:
        x_run_once = None
    while not stop.is_set():
        try:
            if x_run_once:
                x_run_once()
        except Exception:
            logging.getLogger("ms").exception("x_loop error")
        stop.wait(getattr(settings, "poll_seconds", 60))

def signal_loop(stop: Event):
    while not stop.is_set():
        try:
            compute_once()
        except Exception:
            logging.getLogger("ms").exception("signal_loop error")
        stop.wait(getattr(settings, "poll_seconds", 60))

def rss_loop(stop: Event):
    try:
        from app.ingestors import rss as rss_ing
    except Exception:
        rss_ing = None
    while not stop.is_set():
        try:
            if rss_ing:
                rss_ing.run_once()
        except Exception:
            logging.getLogger("ms").exception("rss_loop error")
        stop.wait(getattr(settings, "poll_seconds", 60))

def price_loop(stop: Event):
    try:
        from app.prices import loop as price_worker
        price_worker(stop)
    except Exception:
        logging.getLogger("ms").exception("price_loop error")
        while not stop.is_set():
            stop.wait(getattr(settings, "poll_seconds", 60))

def impact_loop(stop: Event):
    try:
        from app.impact import loop as impact_worker
        impact_worker(stop)
    except Exception:
        logging.getLogger("ms").exception("impact_loop error")
        while not stop.is_set():
            stop.wait(getattr(settings, "poll_seconds", 60))

@asynccontextmanager
async def lifespan(app: FastAPI):
    _setup_logging()
    init_db()
    stop_event.clear()
    for target in (x_loop, signal_loop, price_loop, rss_loop, impact_loop):
        t = Thread(target=target, args=(stop_event,), daemon=True)
        t.start()
        threads.append(t)
    events.emit("state", "backend ready", {"asset": getattr(settings, "asset", "ETH-USD")})
    yield
    stop_event.set()
    for t in threads:
        t.join(timeout=2)

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173","http://127.0.0.1:5173","*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s).astimezone(timezone.utc)
    except Exception:
        return None

def _dt_floor_minute(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/api/state", response_model=State)
def api_state():
    s = get_session()
    try:
        now = datetime.now(timezone.utc)
        t0 = now - timedelta(minutes=15)
        mentions_15m = s.execute(select(func.count()).where(Item.ts >= t0, Item.asset == settings.asset)).scalar_one()
        t7 = now - timedelta(days=7)
        total_7d = s.execute(select(func.count()).where(Item.ts >= t7, Item.asset == settings.asset)).scalar_one()
        baseline = total_7d / max(1, 7 * 24 * 4)
        last_sig = s.execute(select(Signal).order_by(desc(Signal.ts)).limit(1)).scalar_one_or_none()
        if last_sig:
            ema15 = float(last_sig.ema15 or 0.0)
            action = last_sig.action or "hold"
            updated_at = last_sig.ts
        else:
            ema15 = 0.0
            action = "hold"
            updated_at = now
        return {
            "asset": settings.asset,
            "ema15": ema15,
            "mentions_15m": int(mentions_15m),
            "baseline_7d": float(baseline),
            "action": action,
            "updated_at": updated_at,
        }
    finally:
        s.close()

@app.get("/api/signals", response_model=list[SignalOut])
def api_signals(
    limit: int = Query(200, ge=1, le=2000),
    action: Optional[str] = Query(None, pattern="^(hold|accumulate|wait)$"),
    since: Optional[str] = None,
    until: Optional[str] = None,
    order: str = Query("desc", pattern="^(asc|desc)$"),
):
    s = get_session()
    try:
        stmt = select(Signal)
        if action:
            stmt = stmt.where(Signal.action == action)
        dt_since = _parse_dt(since)
        if dt_since:
            stmt = stmt.where(Signal.ts >= dt_since)
        dt_until = _parse_dt(until)
        if dt_until:
            stmt = stmt.where(Signal.ts <= dt_until)
        stmt = stmt.order_by(desc(Signal.ts) if order == "desc" else Signal.ts)
        rows = s.execute(stmt.limit(limit)).scalars().all()
        out: list[SignalOut] = []
        for r in rows:
            out.append({
                "ts": r.ts,
                "ema15": float(r.ema15 or 0.0),
                "mentions": int(r.mentions or 0),
                "action": r.action or "hold",
                "price_close": getattr(r, "price_close", None),
                "rsi14": getattr(r, "rsi14", None),
                "macd": getattr(r, "macd", None),
                "macd_signal": getattr(r, "macd_signal", None),
                "atr_pct": getattr(r, "atr_pct", None),
                "price_bias": getattr(r, "price_bias", None),
            })
        return out
    finally:
        s.close()

@app.get("/api/items", response_model=list[ItemOut])
def api_items(
    limit: int = Query(100, ge=1, le=2000),
    source: Optional[str] = None,
    label: Optional[str] = None,
    q: Optional[str] = None,
    min_score: Optional[float] = None,
    max_score: Optional[float] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    order: str = Query("desc", pattern="^(asc|desc)$"),
    relevant: Optional[int] = None,
):
    s = get_session()
    try:
        stmt = select(Item)
        if source:
            stmt = stmt.where(Item.source == source)
        if label:
            stmt = stmt.where(Item.label == label)
        if min_score is not None:
            stmt = stmt.where(Item.score >= min_score)
        if max_score is not None:
            stmt = stmt.where(Item.score <= max_score)
        dt_since = _parse_dt(since)
        if dt_since:
            stmt = stmt.where(Item.ts >= dt_since)
        dt_until = _parse_dt(until)
        if dt_until:
            stmt = stmt.where(Item.ts <= dt_until)
        if q:
            stmt = stmt.where(Item.text.ilike(f"%{q}%"))
        if relevant is not None:
            if relevant == 1:
                stmt = stmt.where(Item.llm_relevant.is_(True))
            elif relevant == 0:
                stmt = stmt.where((Item.llm_relevant.is_(False)) | (Item.llm_relevant.is_(None)))
        stmt = stmt.order_by(desc(Item.ts) if order == "desc" else Item.ts)
        rows = s.execute(stmt.limit(limit)).scalars().all()
        out = []
        for r in rows:
            out.append({
                "ts": r.ts,
                "source": r.source,
                "label": r.label,
                "score": float(r.score or 0.0),
                "text": r.text,
                "impact": float(r.impact) if r.impact is not None else None,
                "url": r.url, 
            })
        return out
    finally:
        s.close()

@app.get("/api/metrics", response_model=Metrics)
def api_metrics():
    s = get_session()
    try:
        now = datetime.now(timezone.utc)
        items_total = s.execute(select(func.count(Item.id))).scalar_one()
        signals_total = s.execute(select(func.count(Signal.id))).scalar_one()
        items_last_15m = s.execute(select(func.count()).where(Item.ts >= now - timedelta(minutes=15))).scalar_one()
        rows = s.execute(select(Item.score).where(Item.ts >= now - timedelta(hours=1))).all()
        avg_score_1h = float(sum((r[0] or 0.0) for r in rows) / max(1, len(rows)))
        return {"items_total": int(items_total), "signals_total": int(signals_total), "items_last_15m": int(items_last_15m), "avg_score_1h": avg_score_1h}
    finally:
        s.close()

@app.get("/api/events")
def api_events(since_id: Optional[int] = None, limit: int = 50):
    return events.list_since(since_id, limit)

@app.get("/events")
async def sse_events(request: Request, since_id: int | None = None):
    def _json_default(o):
        if isinstance(o, datetime):
            return o.astimezone(timezone.utc).isoformat()
        return str(o)

    async def event_generator():
        last_id = since_id if since_id is not None else -1
        s = get_session()
        try:
            now = datetime.now(timezone.utc)
            t0 = now - timedelta(minutes=15)
            mentions_15m = s.execute(
                select(func.count()).where(Item.ts >= t0, Item.asset == settings.asset)
            ).scalar_one()
            t7 = now - timedelta(days=7)
            total_7d = s.execute(
                select(func.count()).where(Item.ts >= t7, Item.asset == settings.asset)
            ).scalar_one()
            baseline = total_7d / max(1, 7 * 24 * 4)
            last_sig = s.execute(
                select(Signal).order_by(desc(Signal.ts)).limit(1)
            ).scalar_one_or_none()
            ema15 = float(getattr(last_sig, "ema15", 0.0) or 0.0)
            action = getattr(last_sig, "action", "hold") or "hold"
            updated_at_dt = getattr(last_sig, "ts", now)
            state_payload = {
                "asset": settings.asset,
                "ema15": ema15,
                "mentions_15m": int(mentions_15m),
                "baseline_7d": float(baseline),
                "action": action,
                "updated_at": updated_at_dt.astimezone(timezone.utc).isoformat(),
            }
        finally:
            s.close()

        init_evt = {
            "type": "state",
            "data": state_payload,
            "summary": "state snapshot",
            "timestamp": datetime.now(timezone.utc).timestamp(),
        }
        yield f"event: state\ndata: {json.dumps(init_evt, default=_json_default)}\n\n"

        while True:
            if await request.is_disconnected():
                break
            new_events = events.list_since(last_id, limit=200)
            for e in new_events:
                last_id = e["id"]
                out = {
                    "type": e["type"],
                    "data": e.get("payload") or {},
                    "summary": e.get("summary", ""),
                    "timestamp": e.get("timestamp"),
                }
                yield (
                    f"id: {e['id']}\n"
                    f"event: {e['type']}\n"
                    f"data: {json.dumps(out, default=_json_default)}\n\n"
                )
            yield ": keep-alive\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

@app.get("/api/summary")
def api_summary():
    try:
        data = summary_mod.generate_commentary()
        return data
    except Exception:
        logging.getLogger("ms").exception("summary error")
        return {
            "commentary": "",
            "model": getattr(settings, "llm_model", "unknown"),
            "generated_at": datetime.now(timezone.utc).isoformat()
        }

@app.get("/api/impact/top", response_model=list[ImpactItemOut])
def api_impact_top(
    limit: int = Query(20, ge=1, le=200),
    hours: int = Query(6, ge=1, le=168),
    source: Optional[str] = None,
):
    s = get_session()
    try:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        stmt = select(Item).where(Item.ts >= since).where(Item.impact != None)  # noqa: E711
        if source:
            stmt = stmt.where(Item.source == source)
        stmt = stmt.order_by(desc(Item.impact)).limit(limit)
        rows = s.execute(stmt).scalars().all()
        out: list[ImpactItemOut] = []
        for r in rows:
            out.append({
                "ts": r.ts,
                "source": r.source,
                "label": r.label,
                "score": float(r.score or 0.0),
                "impact": float(r.impact or 0.0),
                "text": r.text,
            })
        return out
    finally:
        s.close()

# ==============================
# ENDPOINTS HISTÓRICOS (NUEVOS)
# ==============================

def _fill_minutes(from_dt: datetime, to_dt: datetime, points: dict[int, int]) -> list[dict]:
    """
    Rellena minutos vacíos entre from_dt y to_dt.
    points: dict de epoch_minute -> count
    """
    res = []
    cur = _dt_floor_minute(from_dt)
    end = _dt_floor_minute(to_dt)
    while cur <= end:
        key = int(cur.timestamp() // 60)
        res.append({"ts": cur.isoformat(), "count": int(points.get(key, 0))})
        cur += timedelta(minutes=1)
    return res

@app.get("/api/series/mentions")
def api_series_mentions(
    minutes: int = Query(240, ge=1, le=60*24*7),
    asset: Optional[str] = None,
):
    """
    Serie por minuto de menciones (items) para hidratar el gráfico al arrancar.
    """
    asset = asset or settings.asset
    s = get_session()
    try:
        now = datetime.now(timezone.utc)
        since = now - timedelta(minutes=minutes)

        # Agrupamos por minuto (SQLite)
        rows = s.execute(sql_text(
            "SELECT strftime('%Y-%m-%d %H:%M:00', ts) as bucket, COUNT(*) "
            "FROM items WHERE asset=:asset AND ts >= :since "
            "GROUP BY bucket ORDER BY bucket ASC"
        ), {"asset": asset, "since": since}).fetchall()

        points: dict[int, int] = {}
        for b, cnt in rows:
            # b: "YYYY-mm-dd HH:MM:00"
            try:
                dt = datetime.fromisoformat(b).replace(tzinfo=timezone.utc)
            except Exception:
                dt = datetime.strptime(b, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            key = int(dt.timestamp() // 60)
            points[key] = int(cnt or 0)

        filled = _fill_minutes(since, now, points)
        return {"asset": asset, "minutes": minutes, "points": filled}
    finally:
        s.close()

@app.get("/api/series/prices")
def api_series_prices(
    symbol: str = Query("ETH/USDT"),
    timeframe: str = Query("1m"),
    minutes: int = Query(240, ge=1, le=60*24*7),
):
    """
    Devuelve OHLCV desde ahora - minutes (si existe la tabla prices).
    """
    s = get_session()
    try:
        now = datetime.now(timezone.utc)
        since = now - timedelta(minutes=minutes)
        try:
            rows = s.execute(sql_text(
                "SELECT ts, o, h, l, c, v FROM prices "
                "WHERE symbol=:sym AND timeframe=:tf AND ts >= :since "
                "ORDER BY ts ASC"
            ), {"sym": symbol, "tf": timeframe, "since": since}).fetchall()
        except Exception:
            rows = []

        out = []
        for r in rows:
            ts, o, h, l, c, v = r
            out.append({
                "ts": ts if isinstance(ts, str) else ts.isoformat(),
                "o": float(o or 0.0), "h": float(h or 0.0),
                "l": float(l or 0.0), "c": float(c or 0.0),
                "v": float(v or 0.0),
            })
        return {"symbol": symbol, "timeframe": timeframe, "minutes": minutes, "candles": out}
    finally:
        s.close()

@app.get("/api/series/signals")
def api_series_signals(
    minutes: int = Query(240, ge=1, le=60*24*7),
    asset: Optional[str] = None,
):
    """
    Señales en el rango solicitado (para pintarlas como markers).
    """
    asset = asset or settings.asset
    s = get_session()
    try:
        since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        rows = s.execute(
            select(Signal).where(Signal.asset == asset, Signal.ts >= since).order_by(Signal.ts.asc())
        ).scalars().all()
        return {"asset": asset, "minutes": minutes, "signals": [
            {"ts": r.ts, "action": r.action, "ema15": float(r.ema15 or 0.0), "mentions": int(r.mentions or 0)}
            for r in rows
        ]}
    finally:
        s.close()

@app.get("/api/history/bootstrap")
def api_history_bootstrap(
    minutes: int = Query(240, ge=1, le=60*24*7),
    symbol: str = Query("ETH/USDT"),
    timeframe: str = Query("1m"),
    asset: Optional[str] = None,
):
    """
    Un único payload con:
      - mentions points
      - price candles
      - signals
    Ideal para hidratar el gráfico al abrir la app.
    """
    asset = asset or settings.asset
    s = get_session()
    try:
        # Mentions
        now = datetime.now(timezone.utc)
        since = now - timedelta(minutes=minutes)
        m_rows = s.execute(sql_text(
            "SELECT strftime('%Y-%m-%d %H:%M:00', ts) as bucket, COUNT(*) "
            "FROM items WHERE asset=:asset AND ts >= :since "
            "GROUP BY bucket ORDER BY bucket ASC"
        ), {"asset": asset, "since": since}).fetchall()
        m_points: dict[int, int] = {}
        for b, cnt in m_rows:
            try:
                dt = datetime.fromisoformat(b).replace(tzinfo=timezone.utc)
            except Exception:
                dt = datetime.strptime(b, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            key = int(dt.timestamp() // 60)
            m_points[key] = int(cnt or 0)
        mentions = _fill_minutes(since, now, m_points)

        # Prices (si existe)
        try:
            p_rows = s.execute(sql_text(
                "SELECT ts, o, h, l, c, v FROM prices "
                "WHERE symbol=:sym AND timeframe=:tf AND ts >= :since "
                "ORDER BY ts ASC"
            ), {"sym": symbol, "tf": timeframe, "since": since}).fetchall()
        except Exception:
            p_rows = []
        candles = [{
            "ts": r[0] if isinstance(r[0], str) else r[0].isoformat(),
            "o": float(r[1] or 0.0), "h": float(r[2] or 0.0),
            "l": float(r[3] or 0.0), "c": float(r[4] or 0.0),
            "v": float(r[5] or 0.0),
        } for r in p_rows]

        # Signals
        sig_rows = s.execute(
            select(Signal).where(Signal.asset == asset, Signal.ts >= since).order_by(Signal.ts.asc())
        ).scalars().all()
        signals = [
            {"ts": r.ts, "action": r.action, "ema15": float(r.ema15 or 0.0), "mentions": int(r.mentions or 0)}
            for r in sig_rows
        ]

        return {
            "asset": asset,
            "minutes": minutes,
            "mentions": mentions,
            "prices": {"symbol": symbol, "timeframe": timeframe, "candles": candles},
            "signals": signals,
        }
    finally:
        s.close()

@app.get("/api/loglevel")
def get_loglevel():
    root = logging.getLogger()
    return {"level": logging.getLevelName(root.level)}

@app.post("/api/loglevel")
def set_loglevel(level: str):
    lvl = getattr(logging, level.upper(), None)
    if not isinstance(lvl, int):
        return {"ok": False, "error": "invalid level"}
    logging.getLogger().setLevel(lvl)
    logging.getLogger("ms.x").setLevel(lvl)
    logging.getLogger("ms.llm").setLevel(lvl)
    logging.getLogger("ms.signal").setLevel(lvl)
    logging.getLogger("ms.price").setLevel(lvl)
    logging.getLogger("ms.impact").setLevel(lvl)
    return {"ok": True, "level": logging.getLevelName(lvl)}
