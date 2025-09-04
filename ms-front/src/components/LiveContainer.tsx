import { useEffect, useRef, useState } from "react";
import { LiveFeed } from "./LiveFeed";

type ApiEvent = {
  id: number;
  type: "state" | "signal" | "item" | "price";
  timestamp: number;
  summary: string;
  payload?: any;
};

type LiveEvent = {
  type: "state" | "signal" | "item" | "price";
  timestamp: string;
  summary: string;
};

export default function LiveContainer() {
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const lastIdRef = useRef<number | null>(null);

  useEffect(() => {
    let timer: any;
    const poll = async () => {
      try {
        const url = new URL("/api/events", window.location.origin);
        if (lastIdRef.current !== null) url.searchParams.set("since_id", String(lastIdRef.current));
        url.searchParams.set("limit", "50");
        const res = await fetch(url.toString(), { headers: { Accept: "application/json" } });
        if (!res.ok) throw new Error("fetch /api/events failed");
        const data: ApiEvent[] = await res.json();
        if (data.length) {
          lastIdRef.current = data[data.length - 1].id;
          const mapped: LiveEvent[] = data.map(e => ({
            type: e.type,
            summary: e.summary,
            timestamp: new Date(e.timestamp * 1000).toISOString(),
          }));
          setEvents(prev => [...prev, ...mapped].slice(-200));
        }
        setConnected(true);
      } catch {
        setConnected(false);
      } finally {
        timer = setTimeout(poll, 2000);
      }
    };
    poll();
    return () => clearTimeout(timer);
  }, []);

  return <LiveFeed events={events} isConnected={connected} />;
}
