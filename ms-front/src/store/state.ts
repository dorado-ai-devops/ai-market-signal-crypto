import { create } from 'zustand';
import { StateResponse, Signal, Item, MetricsResponse, RefreshInterval, TimeRange } from '@/types';

interface AppState {
  isLoading: boolean;
  error: string | null;
  refreshInterval: RefreshInterval;
  timeRange: TimeRange;
  
  health: boolean;
  state: StateResponse | null;
  signals: Signal[];
  items: Item[];
  metrics: MetricsResponse | null;
  
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setRefreshInterval: (interval: RefreshInterval) => void;
  setTimeRange: (range: TimeRange) => void;
  
  setHealth: (health: boolean) => void;
  setState: (state: StateResponse) => void;
  setSignals: (signals: Signal[]) => void;
  setItems: (items: Item[]) => void;
  setMetrics: (metrics: MetricsResponse) => void;
  
  addSignal: (signal: Signal) => void;
  addItem: (item: Item) => void;
}

export const useAppStore = create<AppState>((set, get) => ({
  isLoading: false,
  error: null,
  refreshInterval: 5,
  timeRange: '6h',
  
  health: false,
  state: null,
  signals: [],
  items: [],
  metrics: null,
  
  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error }),
  setRefreshInterval: (interval) => set({ refreshInterval: interval }),
  setTimeRange: (range) => set({ timeRange: range }),
  
  setHealth: (health) => set({ health }),
  setState: (state) => set({ state }),
  setSignals: (signals) => set({ signals }),
  setItems: (items) => set({ items }),
  setMetrics: (metrics) => set({ metrics }),
  
  addSignal: (signal) => {
    const { signals } = get();
    set({ signals: [signal, ...signals].slice(0, 200) });
  },
  
  addItem: (item) => {
    const { items } = get();
    set({ items: [item, ...items].slice(0, 100) });
  },
}));