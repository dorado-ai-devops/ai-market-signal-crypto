from collections import deque
from threading import Lock
from typing import Any, Dict, List, Optional
import time

MAX_EVENTS = 500

_lock = Lock()
_events: deque[Dict[str, Any]] = deque(maxlen=MAX_EVENTS)
_next_id = 0

def emit(event_type: str, summary: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    global _next_id
    evt = {
        "id": _next_id,
        "type": event_type,
        "timestamp": time.time(),
        "summary": summary,
        "payload": payload or {},
    }
    with _lock:
        _events.append(evt)
        _next_id += 1
    return evt

def list_since(since_id: Optional[int] = None, limit: int = 50) -> List[Dict[str, Any]]:
    limit = max(1, min(200, limit))
    with _lock:
        if since_id is None:
            return list(_events)[-limit:]
        out = [e for e in _events if e["id"] > since_id]
        return out[:limit]
