import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Activity, TrendingUp, FileText } from 'lucide-react';
import { format } from 'date-fns';

interface LiveEvent {
  type: 'state' | 'signal' | 'item' | 'price';
  timestamp: string;
  summary: string;
  details?: string[];
}

interface LiveFeedProps {
  events: LiveEvent[];
  isConnected: boolean;
}

export const LiveFeed = ({ events, isConnected }: LiveFeedProps) => {
  const getEventIcon = (type: string) => {
    switch (type) {
      case 'state': return <Activity className="h-4 w-4" />;
      case 'signal': return <TrendingUp className="h-4 w-4" />;
      case 'item': return <FileText className="h-4 w-4" />;
      default: return <Activity className="h-4 w-4" />;
    }
  };

  const getEventColor = (type: string) => {
    switch (type) {
      case 'state': return 'bg-primary/20 text-primary';
      case 'signal': return 'bg-green-600/20 text-green-600';
      case 'item': return 'bg-blue-600/20 text-blue-600';
      default: return 'bg-muted';
    }
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Live Activity</CardTitle>
          <Badge variant={isConnected ? "success" : "secondary"} className="gap-1">
            <div className={`h-2 w-2 rounded-full ${isConnected ? 'bg-success animate-pulse' : 'bg-muted'}`} />
            {isConnected ? 'Connected' : 'Polling'}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <ScrollArea className="h-64">
          {events.length === 0 ? (
            <div className="text-center text-muted-foreground py-8">
              <Activity className="h-8 w-8 mx-auto mb-2 opacity-50" />
              <p>No recent activity</p>
            </div>
          ) : (
            <div className="space-y-2">
              {events.map((event, index) => (
                <div key={index} className="flex items-start gap-3 p-2 rounded-lg bg-muted/30">
                  <div className={`p-1 rounded-full ${getEventColor(event.type)}`}>
                    {getEventIcon(event.type)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm">{event.summary}</p>
                    {event.details && event.details.length > 0 && (
                      <ul className="mt-1 text-xs text-muted-foreground list-disc list-inside space-y-0.5">
                        {event.details.slice(0, 6).map((d, i) => (
                          <li key={i} className="truncate">{d}</li>
                        ))}
                      </ul>
                    )}
                    <p className="text-xs text-muted-foreground mt-1">
                      {format(new Date(event.timestamp), 'HH:mm:ss')}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </ScrollArea>
      </CardContent>
    </Card>
  );
};
