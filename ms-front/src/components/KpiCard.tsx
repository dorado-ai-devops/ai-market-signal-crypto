import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { TrendingUp, TrendingDown, Minus } from 'lucide-react';

interface KpiCardProps {
  title: string;
  value: string | number;
  type?: 'ema' | 'mentions' | 'baseline' | 'action';
  action?: string;
  isLoading?: boolean;
}

export const KpiCard = ({ title, value, type, action, isLoading }: KpiCardProps) => {
  if (isLoading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">
            {title}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-8 w-24" />
        </CardContent>
      </Card>
    );
  }

  const getEmaColor = (val: number) => {
    if (val <= -0.6) return 'text-negative';
    if (val >= 0.6) return 'text-positive';
    return 'text-neutral';
  };

  const getEmaIcon = (val: number) => {
    if (val <= -0.6) return <TrendingDown className="h-4 w-4 text-negative" />;
    if (val >= 0.6) return <TrendingUp className="h-4 w-4 text-positive" />;
    return <Minus className="h-4 w-4 text-neutral" />;
  };

  const getActionVariant = (action: string) => {
    switch (action?.toLowerCase()) {
      case 'accumulate': return 'success';
      case 'wait': return 'destructive';
      default: return 'secondary';
    }
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {type === 'ema' ? (
          <div className="flex items-center gap-2">
            <span className={`text-2xl font-bold ${getEmaColor(Number(value))}`}>
              {Number(value).toFixed(2)}
            </span>
            {getEmaIcon(Number(value))}
          </div>
        ) : type === 'action' ? (
          <Badge variant={getActionVariant(action || '')} className="text-sm font-semibold uppercase">
            {action}
          </Badge>
        ) : (
          <span className="text-2xl font-bold">
            {typeof value === 'number' ? value.toLocaleString() : value}
          </span>
        )}
      </CardContent>
    </Card>
  );
};