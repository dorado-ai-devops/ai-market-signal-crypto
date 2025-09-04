import { httpClient } from './http';
import { MockService } from './mock';
import { HealthResponse, StateResponse, Signal, Item, MetricsResponse } from '@/types';

const useMock = import.meta.env.VITE_USE_MOCK === 'true';

// Tipos de la respuesta de /api/history/bootstrap
type HistoryBootstrap = {
  asset: string;
  minutes: number;
  mentions: Array<{ ts: string; count: number }>;
  prices: {
    symbol: string;
    timeframe: string;
    candles: Array<{ ts: string; o: number; h: number; l: number; c: number; v: number }>;
  };
  signals: Array<{ ts: string | Date; action: string; ema15: number; mentions: number }>;
};

const minutesFromRange = (r: '1h' | '6h' | '24h') => (r === '1h' ? 60 : r === '6h' ? 360 : 1440);

export const apiService = {
  getHealth: async (): Promise<HealthResponse> => {
    if (useMock) return MockService.getHealth();
    const response = await httpClient.get<HealthResponse>('/health');
    return response.data;
  },

  getState: async (): Promise<StateResponse> => {
    if (useMock) return MockService.getState();
    const response = await httpClient.get<StateResponse>('/api/state');
    return response.data;
  },

  getSignals: async (limit = 200): Promise<Signal[]> => {
    if (useMock) return MockService.getSignals(limit);
    const response = await httpClient.get<Signal[]>(`/api/signals?limit=${limit}`);
    return response.data;
  },

  getItems: async (limit = 100): Promise<Item[]> => {
    if (useMock) return MockService.getItems(limit);
    const response = await httpClient.get<Item[]>(`/api/items?limit=${limit}`);
    return response.data;
  },

  getMetrics: async (): Promise<MetricsResponse> => {
    if (useMock) return MockService.getMetrics();
    const response = await httpClient.get<MetricsResponse>('/api/metrics');
    return response.data;
  },

  openEventStream: (onEvent: (event: any) => void): EventSource | null => {
    if (useMock) return null;
    try {
      const es = new EventSource('/events');
      const handler = (ev: MessageEvent) => {
        try {
          const data = JSON.parse(ev.data);
          onEvent(data);
        } catch {}
      };
      es.addEventListener('state', handler as EventListener);
      es.addEventListener('signal', handler as EventListener);
      es.addEventListener('item', handler as EventListener);
      es.addEventListener('price', handler as EventListener);
      es.onmessage = handler;
      es.onerror = () => {};
      return es;
    } catch {
      return null;
    }
  },

  getSummary: async (): Promise<{ commentary: string; generated_at?: string; model?: string; facts?: any }> => {
    if (useMock) {
      return {
        commentary: 'Resumen (mock): mercado lateral, sentimiento mixto y volatilidad contenida.',
        generated_at: new Date().toISOString(),
        model: 'mock',
        facts: {},
      };
    }
    const res = await httpClient.get('/api/summary');
    const { commentary, generated_at, model, facts } = res.data || {};
    return {
      commentary: commentary || '',
      generated_at,
      model,
      facts,
    };
  },

  // Histórico: intenta bootstrap y adapta a Signal[]
  getHistorySignals: async (
    minutes: number,
    symbol = 'ETH/USDT',
    timeframe = '1m',
    asset?: string
  ): Promise<Signal[]> => {
    if (useMock) {
      const mock = await MockService.getHistoryBootstrap(minutes, symbol, timeframe, asset);
      return (mock.signals || []).map(s => ({
        ts: typeof s.ts === 'string' ? s.ts : new Date(s.ts as any).toISOString(),
        ema15: Number(s.ema15 || 0),
        mentions: typeof s.mentions === 'number' ? s.mentions : 0,
        action: (s.action || 'hold') as Signal['action'],
      }));
    }
    const q = new URLSearchParams();
    q.set('minutes', String(minutes));
    if (symbol) q.set('symbol', symbol);
    if (timeframe) q.set('timeframe', timeframe);
    if (asset) q.set('asset', asset);
    const res = await httpClient.get<HistoryBootstrap>(`/api/history/bootstrap?${q.toString()}`);
    const raw = res.data;
    const out = (raw?.signals || []).map(s => ({
      ts: typeof s.ts === 'string' ? s.ts : new Date(s.ts as any).toISOString(),
      ema15: Number(s.ema15 || 0),
      mentions: typeof s.mentions === 'number' ? s.mentions : 0,
      action: (s.action || 'hold') as Signal['action'],
    }));
    return out;
  },

  // Fallback automático: histórico -> si falla o viene vacío -> /api/signals
  getSignalsHydrated: async (range: '1h' | '6h' | '24h'): Promise<Signal[]> => {
    const minutes = minutesFromRange(range);
    try {
      const hist = await apiService.getHistorySignals(minutes, 'ETH/USDT', '1m');
      if (Array.isArray(hist) && hist.length > 0) return hist;
    } catch {
      // cae a legacy
    }
    return apiService.getSignals(200);
  },
};
