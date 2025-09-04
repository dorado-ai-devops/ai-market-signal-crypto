import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { RefreshInterval } from '@/types';

interface RefreshSelectorProps {
  interval: RefreshInterval;
  onIntervalChange: (interval: RefreshInterval) => void;
  onRefresh: () => void;
  isLoading?: boolean;
}

export const RefreshSelector = ({ 
  interval, 
  onIntervalChange, 
  onRefresh, 
  isLoading 
}: RefreshSelectorProps) => {
  return (
    <div className="flex items-center gap-2">
      <Select value={interval.toString()} onValueChange={(value) => onIntervalChange(Number(value) as RefreshInterval)}>
        <SelectTrigger className="w-20">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="5">5s</SelectItem>
          <SelectItem value="10">10s</SelectItem>
          <SelectItem value="30">30s</SelectItem>
        </SelectContent>
      </Select>
      
      <Button 
        variant="outline" 
        size="sm" 
        onClick={onRefresh} 
        disabled={isLoading}
        className="gap-2"
      >
        <RefreshCw className={`h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
        Refresh
      </Button>
    </div>
  );
};