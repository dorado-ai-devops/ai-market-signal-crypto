import { HealthResponse, StateResponse, Signal, Item, MetricsResponse } from '@/types';

type HistoryBootstrap = {
  asset: string;
  minutes: number;
  mentions: Array<{ ts: string; count: number }>;
  prices: {
    symbol: string;
    timeframe: string;
    candles: Array<{ ts: string; o: number; h: number; l: number; c: number; v: number }>;
  };
  signals: Array<{ ts: string; action: string; ema15: number; mentions: number }>;
};

const generateMockSignals = (hours: number): Signal[] => {
  const signals: Signal[] = [];
  const now = new Date();
  for (let i = 0; i < hours * 60; i++) {
    const time = new Date(now.getTime() - i * 60 * 1000);
    const ema15 = -1 + Math.random() * 2;
    const mentions = Math.floor(Math.random() * 50) + 10;
    let action = 'hold' as Signal['action'];
    if (ema15 >= 0.6) action = 'accumulate';
    else if (ema15 <= -0.6) action = 'wait';
    signals.push({
      ts: time.toISOString(),
      ema15: Number(ema15.toFixed(3)),
      mentions,
      action,
    });
  }
  return signals.reverse();
};

const generateMockItems = (count: number): Item[] => {
  const sources: Item['source'][] = ['rss', 'x', 'tg', 'seed'];
  const labels = ['news', 'tweet', 'telegram', 'analysis'];
  const items: Item[] = [];
  for (let i = 0; i < count; i++) {
    const time = new Date(Date.now() - i * 2 * 60 * 1000);
    const score = -1 + Math.random() * 2;
    items.push({
      ts: time.toISOString(),
      source: sources[Math.floor(Math.random() * sources.length)],
      label: labels[Math.floor(Math.random() * labels.length)],
      score: Number(score.toFixed(3)),
      text: `Mock news item ${i + 1}: ETH market analysis showing ${score > 0 ? 'positive' : 'negative'} sentiment indicators.`,
    });
  }
  return items;
};

export const MockService = {
  getHealth: (): Promise<HealthResponse> =>
    Promise.resolve({ ok: true }),

  getState: (): Promise<StateResponse> => {
    const ema15 = -1 + Math.random() * 2;
    let action: 'hold' | 'accumulate' | 'wait' = 'hold';
    if (ema15 >= 0.6) action = 'accumulate';
    else if (ema15 <= -0.6) action = 'wait';
    return Promise.resolve({
      asset: 'ETH-USD',
      ema15: Number(ema15.toFixed(3)),
      mentions_15m: Math.floor(Math.random() * 50) + 10,
      baseline_7d: Math.floor(Math.random() * 30) + 20,
      action,
      updated_at: new Date().toISOString(),
    });
  },

  getSignals: (limit = 200): Promise<Signal[]> =>
    Promise.resolve(generateMockSignals(24).slice(-limit)),

  getItems: (limit = 100): Promise<Item[]> =>
    Promise.resolve(generateMockItems(limit)),

  getMetrics: (): Promise<MetricsResponse> =>
    Promise.resolve({
      items_total: 1250,
      signals_total: 890,
      items_last_15m: Math.floor(Math.random() * 10) + 5,
      avg_score_1h: Number((-0.5 + Math.random()).toFixed(3)),
    }),

  getHistoryBootstrap: (
    minutes: number,
    symbol = 'ETH/USDT',
    timeframe = '1m',
    asset = 'ETH-USD'
  ): Promise<HistoryBootstrap> => {
    const now = Date.now();
    const candles: Array<{ ts: string; o: number; h: number; l: number; c: number; v: number }> = [];
    let last = 3000 + Math.random() * 200;
    for (let i = minutes - 1; i >= 0; i--) {
      const ts = new Date(now - i * 60 * 1000).toISOString();
      const o = last;
      const c = o + (Math.random() - 0.5) * 10;
      const h = Math.max(o, c) + Math.random() * 5;
      const l = Math.min(o, c) - Math.random() * 5;
      const v = Math.random() * 100;
      candles.push({ ts, o, h, l, c, v });
      last = c;
    }
    const mentions = Array.from({ length: minutes }).map((_, i) => {
      const ts = new Date(now - (minutes - 1 - i) * 60 * 1000).toISOString();
      const count = Math.floor(Math.random() * 50);
      return { ts, count };
    });
    const signals = generateMockSignals(Math.max(1, Math.ceil(minutes / 60))).map(s => ({
      ts: s.ts,
      action: s.action,
      ema15: s.ema15,
      mentions: s.mentions || 0,
    }));
    return Promise.resolve({
      asset,
      minutes,
      mentions,
      prices: { symbol, timeframe, candles },
      signals,
    });
  },

  getSeriesSignals: async (
    minutes: number,
    asset?: string
  ): Promise<{ asset: string; minutes: number; signals: Signal[] }> => {
    const hours = Math.max(1, Math.ceil(minutes / 60));
    return {
      asset: asset || 'ETH-USD',
      minutes,
      signals: generateMockSignals(hours),
    };
  },
};
