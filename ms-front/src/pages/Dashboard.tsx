import { useState, useEffect, useRef } from 'react';
import { useAppStore } from '@/store/state';
import { apiService } from '@/api/service';
import { HealthIndicator } from '@/components/HealthIndicator';
import { RefreshSelector } from '@/components/RefreshSelector';
import { KpiCard } from '@/components/KpiCard';
import { SignalsChart } from '@/components/SignalsChart';
import { ItemsTable } from '@/components/ItemsTable';
import { LiveFeed } from '@/components/LiveFeed';
import { useToast } from '@/hooks/use-toast';
import { Signal, Item } from '@/types';
import { httpClient } from '@/api/http';
import { Commentary } from '@/components/Commentary';

interface LiveEvent {
  type: 'state' | 'signal' | 'item';
  timestamp: string;
  summary: string;
  details?: string[];
}

type ApiEvent = {
  id: number;
  type: 'state' | 'signal' | 'item' | 'price';
  timestamp: number;
  summary: string;
  payload?: any;
};

const minutesFromRange = (r: '1h' | '6h' | '24h') => (r === '1h' ? 60 : r === '6h' ? 360 : 1440);

export const Dashboard = () => {
  const {
    isLoading, health, state, signals, items, metrics,
    refreshInterval, timeRange,
    setLoading, setError, setHealth, setState, setSignals, setItems, setMetrics,
    setRefreshInterval, setTimeRange, addSignal, addItem,
  } = useAppStore();

  const [liveEvents, setLiveEvents] = useState<LiveEvent[]>([]);
  const [isSSEConnected, setIsSSEConnected] = useState(false);
  const { toast } = useToast();

  const intervalRef = useRef<NodeJS.Timeout>();
  const healthIntervalRef = useRef<NodeJS.Timeout>();
  const eventSourceRef = useRef<EventSource | null>(null);
  const pollTimerRef = useRef<NodeJS.Timeout>();
  const lastEventIdRef = useRef<number | null>(null);
  const softItemsRefreshRef = useRef<NodeJS.Timeout>();

  const pushLive = (e: LiveEvent) => {
    setLiveEvents(prev => [e, ...prev].slice(0, 10));
  };

  const loadData = async () => {
    try {
      setLoading(true);
      const minutes = minutesFromRange(timeRange as any);
      const [stateData, itemsData, metricsData, histSignals] = await Promise.all([
        apiService.getState(),
        apiService.getItems(100),
        apiService.getMetrics(),
        apiService.getHistorySignals(minutes, 'ETH/USDT', '1m'),
      ]);
      setState(stateData);
      setItems(itemsData);
      setMetrics(metricsData);
      setSignals(histSignals);
    } catch {
      setError('Failed to load dashboard data');
      toast({ title: 'Error', description: 'Failed to load dashboard data', variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  };

  const checkHealth = async () => {
    try {
      const healthData = await apiService.getHealth();
      setHealth(healthData.ok);
      if (!healthData.ok) {
        toast({ title: 'Health Check Failed', description: 'Backend service is not healthy', variant: 'destructive' });
      }
    } catch {
      setHealth(false);
    }
  };

  const handleSSEEvent = (event: any) => {
    try {
      const now = new Date().toISOString();
      const t = event?.type as 'state' | 'signal' | 'item' | 'price' | undefined;
      const data = event?.data ?? {};
      if (!t) return;

      if (t === 'state') {
        if (data && typeof data === 'object') setState(data);
        const ema = typeof data?.ema15 === 'number' ? data.ema15.toFixed(2) : '-';
        const act = typeof data?.action === 'string' ? data.action.toUpperCase() : 'HOLD';
        pushLive({ type: 'state', timestamp: now, summary: `State updated: ${act} (EMA: ${ema})` });
        return;
      }

      if (t === 'signal') {
        if (data) addSignal(data as Signal);
        const ema = typeof data?.ema15 === 'number' ? data.ema15.toFixed(2) : '-';
        const act = typeof data?.action === 'string' ? data.action.toUpperCase() : 'HOLD';
        const details: string[] | undefined = Array.isArray(data?.reason) ? data.reason.slice(0, 6) : undefined;
        pushLive({ type: 'signal', timestamp: now, summary: `New signal: ${act} (EMA: ${ema})`, details });
        return;
      }

      if (t === 'item') {
        if (data?.source) {
          const src = String(data.source).toUpperCase();
          const score = typeof data?.score === 'number' ? data.score.toFixed(2) : '-';
          pushLive({ type: 'item', timestamp: now, summary: `New item from ${src}: ${score}` });
        } else if (typeof data?.count === 'number') {
          const src = data?.source ? String(data.source) : '';
          pushLive({ type: 'item', timestamp: now, summary: `${data.count} ${src} items inserted (batch)` });
          if (data.source === 'rss' && data.count > 0) {
            apiService.getItems(100).then(setItems).catch(() => {});
          }
        } else {
          pushLive({ type: 'item', timestamp: now, summary: `New items ingested` });
        }
        if (data?.source && data?.text) addItem(data as Item);
        return;
      }
    } catch {}
  };

  const setupSSE = () => {
    const es = apiService.openEventStream(handleSSEEvent);
    if (es) {
      setIsSSEConnected(true);
      eventSourceRef.current = es;
      es.addEventListener('error', () => {
        setIsSSEConnected(false);
        es.close();
      });
    } else {
      setIsSSEConnected(false);
    }
  };

  const startPollingEvents = () => {
    if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    const tick = async () => {
      try {
        const base = (httpClient.defaults.baseURL || '').replace(/\/+$/, '');
        const url = new URL(`${base}/api/events`);
        if (lastEventIdRef.current !== null) url.searchParams.set('since_id', String(lastEventIdRef.current));
        url.searchParams.set('limit', '50');
        const res = await fetch(url.toString(), { headers: { Accept: 'application/json' } });
        if (!res.ok) throw new Error('events polling failed');
        const data: ApiEvent[] = await res.json();
        if (data.length) {
          lastEventIdRef.current = data[data.length - 1].id;
          for (const e of data) {
            const nowISO = new Date(e.timestamp * 1000).toISOString();
            const p = e.payload || {};
            if (e.type === 'signal') {
              const ema = typeof p?.ema15 === 'number' ? p.ema15.toFixed(2) : '-';
              const act = typeof p?.action === 'string' ? p.action.toUpperCase() : 'HOLD';
              const details: string[] | undefined = Array.isArray(p?.reason) ? p.reason.slice(0, 6) : undefined;
              pushLive({ type: 'signal', timestamp: nowISO, summary: `New signal: ${act} (EMA: ${ema})`, details });
            } else if (e.type === 'item') {
              if (typeof p?.count === 'number') {
                const src = p?.source ? String(p.source) : '';
                pushLive({ type: 'item', timestamp: nowISO, summary: `${p.count} ${src} items inserted (batch)` });
                if (p.source === 'rss' && p.count > 0) {
                  apiService.getItems(100).then(setItems).catch(() => {});
                }
              } else if (p?.source) {
                const src = String(p.source).toUpperCase();
                const score = typeof p?.score === 'number' ? p.score.toFixed(2) : '-';
                pushLive({ type: 'item', timestamp: nowISO, summary: `New item from ${src}: ${score}` });
              } else {
                pushLive({ type: 'item', timestamp: nowISO, summary: e.summary || 'New items ingested' });
              }
            } else if (e.type === 'state') {
              pushLive({ type: 'state', timestamp: nowISO, summary: e.summary || 'State updated' });
            }
          }
        }
      } catch {}
    };
    tick();
    pollTimerRef.current = setInterval(tick, 2000);
  };

  const stopPollingEvents = () => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = undefined;
    }
  };

  const refreshStateAndMetrics = async () => {
    try {
      const [stateData, metricsData] = await Promise.all([apiService.getState(), apiService.getMetrics()]);
      setState(stateData);
      setMetrics(metricsData);
    } catch {}
  };

  const refreshSignalsAndItems = async () => {
    try {
      const minutes = minutesFromRange(timeRange as any);
      const [histSignals, itemsData] = await Promise.all([
        apiService.getHistorySignals(minutes, 'ETH/USDT', '1m'),
        apiService.getItems(100),
      ]);
      setSignals(histSignals);
      setItems(itemsData);
    } catch {}
  };

  useEffect(() => {
    loadData();
    checkHealth();
    setupSSE();
    healthIntervalRef.current = setInterval(checkHealth, 5000);
    softItemsRefreshRef.current = setInterval(() => {
      apiService.getItems(100).then(setItems).catch(() => {});
    }, 30000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
      if (healthIntervalRef.current) clearInterval(healthIntervalRef.current);
      if (softItemsRefreshRef.current) clearInterval(softItemsRefreshRef.current);
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        setIsSSEConnected(false);
      }
      stopPollingEvents();
    };
  }, []);

  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    intervalRef.current = setInterval(() => {
      refreshStateAndMetrics();
    }, refreshInterval * 1000);
    const signalsInterval = setInterval(() => {
      if (!isSSEConnected) {
        refreshSignalsAndItems();
      }
    }, 10000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
      clearInterval(signalsInterval);
    };
  }, [refreshInterval, isSSEConnected]);

  useEffect(() => {
    if (isSSEConnected) {
      stopPollingEvents();
    } else {
      startPollingEvents();
    }
  }, [isSSEConnected]);

  useEffect(() => {
    const minutes = minutesFromRange(timeRange as any);
    apiService.getHistorySignals(minutes, 'ETH/USDT', '1m').then(setSignals).catch(() => {});
  }, [timeRange]);

  const handleForceRefresh = () => {
    loadData();
    checkHealth();
  };

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b bg-card/50 backdrop-blur supports-[backdrop-filter]:bg-card/50">
        <div className="container mx-auto px-4 py-3">
          <div className="flex items-center justify-between">
            <h1 className="text-xl font-bold">Market Signal – ETH</h1>
            <HealthIndicator isHealthy={health} isLoading={false} />
            <RefreshSelector
              interval={refreshInterval}
              onIntervalChange={setRefreshInterval}
              onRefresh={handleForceRefresh}
              isLoading={isLoading}
            />
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-6 space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <KpiCard title="EMA(15m)" value={state?.ema15 || 0} type="ema" isLoading={isLoading} />
          <KpiCard title="Mentions 15m" value={state?.mentions_15m || 0} type="mentions" isLoading={isLoading} />
          <KpiCard title="Baseline 7d" value={state?.baseline_7d || 0} type="baseline" isLoading={isLoading} />
          <KpiCard title="Action" value={state?.action || 'hold'} type="action" action={state?.action} isLoading={isLoading} />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">
            <SignalsChart
              signals={signals}
              timeRange={timeRange}
              onTimeRangeChange={setTimeRange}
              isLoading={isLoading}
            />
            <ItemsTable items={items} isLoading={isLoading} />
          </div>

          <div className="space-y-6">
            <LiveFeed events={liveEvents} isConnected={isSSEConnected} />
            <Commentary />
          </div>
        </div>
      </main>
    </div>
  );
};
