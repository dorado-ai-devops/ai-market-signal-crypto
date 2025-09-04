export interface HealthResponse {
  ok: boolean;
}

export interface StateResponse {
  asset: string;
  ema15: number;
  mentions_15m: number;
  baseline_7d: number;
  action: 'hold' | 'accumulate' | 'wait';
  updated_at: string;
}

export interface Signal {
  ts: string;
  ema15: number;
  mentions?: number;
  action: 'hold' | 'accumulate' | 'wait' | string;
  price_close?: number | null;
  rsi14?: number | null;
  macd?: number | null;
  macd_signal?: number | null;
  atr_pct?: number | null;
  price_bias?: number | null;
  mentions_z?: number;
  sentiment_ema?: number;
}

export interface Item {
  ts: string;
  source: 'rss' | 'x' | 'tg' | 'seed' | string;
  label?: string | null;
  score: number;
  text: string;
  impact?: number | null;
  impact_meta?: { norm60?: number } | null;
  url?: string | null;
}

export interface MetricsResponse {
  items_total: number;
  signals_total: number;
  items_last_15m: number;
  avg_score_1h: number;
}

export interface SSEEvent {
  type: 'state' | 'signal' | 'item';
  data: StateResponse | Signal | Item;
}

export interface ImpactItem {
  ts: string;
  source: string;
  label: string;
  score: number;
  impact: number;
  text: string;
}

export type RefreshInterval = 5 | 10 | 30;
export type TimeRange = '1h' | '6h' | '24h';
