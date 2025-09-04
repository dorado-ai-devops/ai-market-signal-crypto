# app/prices.py
import logging
from datetime import datetime, timezone
from typing import List, Tuple

import ccxt
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.settings import settings
from app.storage import get_session, Price
from app import events

log = logging.getLogger("ms.price")


def _fetch_ohlcv(symbol: str, timeframe: str, limit: int = 300) -> List[Tuple[int, float, float, float, float, float]]:
    ex = ccxt.binance()
    return ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)


def _upsert_prices(rows: List[Tuple[int, float, float, float, float, float]], symbol: str, timeframe: str) -> int:
    if not rows:
        return 0
    s = get_session()
    try:
        payload = []
        for ts_ms, o, h, l, c, v in rows:
            ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            payload.append(
                {"symbol": symbol, "timeframe": timeframe, "ts": ts, "o": o, "h": h, "l": l, "c": c, "v": v}
            )

        stmt = sqlite_insert(Price.__table__).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "timeframe", "ts"],
            set_={
                "o": stmt.excluded.o,
                "h": stmt.excluded.h,
                "l": stmt.excluded.l,
                "c": stmt.excluded.c,
                "v": stmt.excluded.v,
            },
        )
        res = s.execute(stmt)
        s.commit()

        count = res.rowcount if res.rowcount is not None else len(payload)
        log.info("inserted %d price candles for %s", count, symbol)

        if count:
            events.emit(
                "price",
                f"inserted {count} price candles for {symbol}",
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "count": count,
                    "last_close": float(payload[-1]["c"]),
                },
            )
        return count
    finally:
        s.close()


def loop(stop_event):
    symbol = getattr(settings, "price_symbol", "ETH/USDT")
    timeframe = getattr(settings, "price_timeframe", "1m")
    pull = getattr(settings, "price_max_candles_per_pull", 300)

    while not stop_event.is_set():
        try:
            rows = _fetch_ohlcv(symbol, timeframe, pull)
            _upsert_prices(rows, symbol, timeframe)
        except Exception:
            log.exception("price loop error")
        stop_event.wait(60)
