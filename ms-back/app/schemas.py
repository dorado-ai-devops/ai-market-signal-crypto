# app/schemas.py
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class State(BaseModel):
    asset: str
    ema15: float
    mentions_15m: int
    baseline_7d: float
    action: str
    updated_at: datetime


class SignalOut(BaseModel):
    ts: datetime
    ema15: float
    mentions: int
    action: str
    # extras opcionales (si tu tabla signals los tiene)
    price_close: Optional[float] = None
    rsi14: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    atr_pct: Optional[float] = None
    price_bias: Optional[str] = None


class ItemOut(BaseModel):
    ts: datetime
    source: str
    label: Optional[str] = None
    score: float
    text: str
    impact: Optional[float] = None
    url: Optional[str] = None   # nuevo

class ImpactItemOut(BaseModel):
    ts: datetime
    source: str
    label: Optional[str] = None
    score: float
    impact: float
    text: str


class Metrics(BaseModel):
    items_total: int
    signals_total: int
    items_last_15m: int
    avg_score_1h: float
