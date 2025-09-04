import { useMemo } from 'react';
import {
  ComposedChart, ResponsiveContainer, CartesianGrid,
  XAxis, YAxis, Tooltip, ReferenceLine, ReferenceArea,
  Line, Bar
} from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Signal, TimeRange } from '@/types';
import { format } from 'date-fns';

interface SignalsChartProps {
  signals: Signal[];
  timeRange: TimeRange;
  onTimeRangeChange: (range: TimeRange) => void;
  onSignalClick?: (signal: Signal) => void;
  isLoading?: boolean;
}

export const SignalsChart = ({
  signals,
  timeRange,
  onTimeRangeChange,
  onSignalClick,
  isLoading
}: SignalsChartProps) => {
  const toMs = (ts: string | Date) => {
    const t = new Date(ts as any).getTime();
    return Number.isFinite(t) ? t : NaN;
  };

  const sorted = useMemo(() => {
    const copy = [...(signals || [])];
    copy.sort((a, b) => toMs(a.ts) - toMs(b.ts));
    return copy;
  }, [signals]);

  const filtered = useMemo(() => {
    if (!sorted.length) return [];
    const lastMs = toMs(sorted[sorted.length - 1].ts);
    if (!Number.isFinite(lastMs)) return [];
    const hours = timeRange === '1h' ? 1 : timeRange === '6h' ? 6 : 24;
    const cutoff = lastMs - hours * 3600 * 1000;
    return sorted.filter(s => {
      const ms = toMs(s.ts);
      return Number.isFinite(ms) && ms >= cutoff;
    });
  }, [sorted, timeRange]);

  const data = useMemo(() => {
    return filtered.map(s => {
      const mentions_z = (s as any).mentions_z ?? undefined;
      const mentions = (s as any).mentions ?? undefined;
      const sentiment_ema = (s as any).sentiment_ema ?? undefined;
      const labelFmt = timeRange === '24h' ? 'dd HH:mm' : 'HH:mm';
      return {
        ...s,
        time: format(new Date(s.ts), labelFmt),
        mentions_z,
        sentiment_ema,
        mentions_series: (mentions_z ?? mentions ?? 0),
      };
    });
  }, [filtered, timeRange]);

  const regimeBands = useMemo(() => {
    if (!data.length) return [];
    const bands: Array<{ x1: string; x2: string; action: string }> = [];
    let start = data[0].time;
    let cur = (data[0].action || 'hold').toLowerCase();
    for (let i = 1; i < data.length; i++) {
      const a = (data[i].action || 'hold').toLowerCase();
      if (a !== cur) {
        bands.push({ x1: start, x2: data[i].time, action: cur });
        start = data[i].time;
        cur = a;
      }
    }
    bands.push({ x1: start, x2: data[data.length - 1].time, action: cur });
    return bands;
  }, [data]);

  const coverageHours = useMemo(() => {
    if (!filtered.length) return 0;
    const first = toMs(filtered[0].ts);
    const last = toMs(filtered[filtered.length - 1].ts);
    if (!Number.isFinite(first) || !Number.isFinite(last) || last <= first) return 0;
    return (last - first) / 3600000;
  }, [filtered]);

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <div className="flex justify-between items-center">
            <CardTitle>Signals Timeline</CardTitle>
            <Skeleton className="h-10 w-20" />
          </div>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-64 w-full" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex justify-between items-center">
          <div className="flex items-center gap-3">
            <CardTitle>Signals Timeline</CardTitle>
            <span className="text-xs text-muted-foreground">
              Covering: {coverageHours.toFixed(1)}h of data.
            </span>
          </div>
          <Select value={timeRange} onValueChange={onTimeRangeChange}>
            <SelectTrigger className="w-20">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="1h">1h</SelectItem>
              <SelectItem value="6h">6h</SelectItem>
              <SelectItem value="24h">24h</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </CardHeader>

      <CardContent>
        {data.length === 0 ? (
          <div className="h-[320px] flex items-center justify-center text-sm text-muted-foreground">
            No data.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={320}>
            <ComposedChart
              data={data}
              onClick={(e: any) => {
                const p = e?.activePayload?.[0]?.payload;
                if (p && onSignalClick) onSignalClick(p as Signal);
              }}
              margin={{ top: 10, right: 18, bottom: 0, left: 0 }}
            >
              {regimeBands.map((b, i) => {
                const a = b.action;
                const fill =
                  a === 'accumulate' ? 'hsl(var(--positive) / 0.06)' :
                  a === 'wait'       ? 'hsl(var(--negative) / 0.06)' :
                                       'hsl(var(--border) / 0.04)';
                return (
                  <ReferenceArea
                    key={i}
                    x1={b.x1}
                    x2={b.x2}
                    y1={-1}
                    y2={1}
                    fill={fill}
                    strokeOpacity={0}
                  />
                );
              })}

              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis
                dataKey="time"
                stroke="hsl(var(--muted-foreground))"
                fontSize={12}
                minTickGap={20}
              />
              <YAxis
                yAxisId="left"
                stroke="hsl(var(--muted-foreground))"
                fontSize={12}
                domain={[-1, 1]}
                ticks={[-1, -0.5, 0, 0.5, 1]}
              />
              <YAxis
                yAxisId="right"
                orientation="right"
                stroke="hsl(var(--muted-foreground))"
                fontSize={12}
                width={30}
                domain={[0, 'dataMax + 5']}
                allowDecimals
              />

              <Tooltip
                contentStyle={{
                  backgroundColor: 'hsl(var(--popover))',
                  border: '1px solid hsl(var(--border))',
                  borderRadius: 6,
                }}
                formatter={(value: any, name: string) => {
                  if (name === 'ema15') return [Number(value).toFixed(2), 'EMA(15)'];
                  if (name === 'sentiment_ema') return [Number(value).toFixed(2), 'Sentiment EMA'];
                  if (name === 'mentions_series') {
                    const label = (data[0]?.mentions_z !== undefined) ? 'Mentions Z' : 'Mentions';
                    return [Number(value).toFixed(2), label];
                  }
                  return [value, name];
                }}
                labelFormatter={(l) => `Time: ${l}`}
              />

              <ReferenceLine y={0} yAxisId="left" stroke="hsl(var(--muted-foreground))" strokeDasharray="1 1" />
              <ReferenceLine y={0.6} yAxisId="left" stroke="hsl(var(--positive))" strokeDasharray="2 2" />
              <ReferenceLine y={-0.6} yAxisId="left" stroke="hsl(var(--negative))" strokeDasharray="2 2" />

              <Bar
                yAxisId="right"
                dataKey="mentions_series"
                name="mentions_series"
                fill="hsl(var(--chart-secondary))"
                opacity={0.28}
                isAnimationActive={false}
              />

              <Line
                yAxisId="left"
                type="monotone"
                dataKey="ema15"
                name="ema15"
                stroke="hsl(var(--chart-primary))"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 3 }}
                isAnimationActive={false}
              />

              <Line
                yAxisId="left"
                type="monotone"
                dataKey="sentiment_ema"
                name="sentiment_ema"
                stroke="hsl(var(--chart-primary) / 0.6)"
                strokeDasharray="4 3"
                strokeWidth={1.5}
                dot={false}
                hide={data.every(d => d.sentiment_ema === undefined)}
                isAnimationActive={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
};
