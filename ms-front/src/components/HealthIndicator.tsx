import { Activity, AlertCircle } from 'lucide-react';
import { Badge } from '@/components/ui/badge';

interface HealthIndicatorProps {
  isHealthy: boolean;
  isLoading?: boolean;
}

export const HealthIndicator = ({ isHealthy, isLoading }: HealthIndicatorProps) => {
  if (isLoading) {
    return (
      <Badge variant="secondary" className="gap-2">
        <Activity className="h-3 w-3 animate-pulse" />
        Checking...
      </Badge>
    );
  }

  return (
    <Badge variant={isHealthy ? "success" : "destructive"} className="gap-2">
      {isHealthy ? (
        <Activity className="h-3 w-3" />
      ) : (
        <AlertCircle className="h-3 w-3" />
      )}
      {isHealthy ? 'Healthy' : 'Offline'}
    </Badge>
  );
};