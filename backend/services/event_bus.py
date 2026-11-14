import asyncio
import time
from collections import deque
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional
from pydantic import BaseModel, Field

class EventCategory(str, Enum):
    CONSENSUS = "CONSENSUS"
    REPLICATION = "REPLICATION"
    LOCK = "LOCK"
    FAULT = "FAULT"
    RPC = "RPC"
    METRICS = "METRICS"
    TELEMETRY_WARNING = "TELEMETRY_WARNING"

class ClusterEvent(BaseModel):
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    timestamp_micros: int = Field(default_factory=lambda: int(time.time() * 1_000_000))
    node_id: str
    term: int
    category: EventCategory
    action: str
    details: dict[str, Any] = Field(default_factory=dict)
    latency_ms: Optional[float] = None

class EventBus:
    """
    Lightweight, thread-safe, bounded in-memory event bus.
    Maintains a ring buffer of the most recent events (default maxlen=500).
    Supports asynchronous subscribers (e.g. WebSockets) via asyncio.Queue.
    """
    def __init__(self, maxlen: int = 500):
        self._maxlen = maxlen
        self._history: deque[ClusterEvent] = deque(maxlen=maxlen)
        self._subscribers: set[asyncio.Queue] = set()
        self._subscriber_dropped_counts: dict[asyncio.Queue, int] = {}
        self.total_events_published: int = 0
        self.total_events_dropped: int = 0
        self._lock = asyncio.Lock()

    def publish_nowait(self, event: ClusterEvent) -> None:
        """Synchronously append event to bounded history and push to subscribers without blocking."""
        self.total_events_published += 1
        self._history.append(event)
        # Push to all active subscriber queues (drop if subscriber queue full to prevent OOM)
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Observable overflow: increment dropped counters
                self.total_events_dropped += 1
                self._subscriber_dropped_counts[q] = self._subscriber_dropped_counts.get(q, 0) + 1
                try:
                    q.get_nowait()  # Evict oldest unread message
                    # Push a synthetic overflow warning event so the subscriber knows it missed events
                    # and must fetch a full topology/lock snapshot
                    overflow_alert = ClusterEvent(
                        node_id="event_bus",
                        term=event.term,
                        category=EventCategory.FAULT,
                        action="SUBSCRIBER_QUEUE_OVERFLOW",
                        details={
                            "message": "Subscriber queue overflow: events were dropped. Re-synchronize snapshot.",
                            "dropped_for_client": self._subscriber_dropped_counts[q],
                            "total_dropped": self.total_events_dropped
                        }
                    )
                    q.put_nowait(overflow_alert)
                except Exception:
                    pass

    async def publish(
        self,
        node_id: str,
        term: int,
        category: EventCategory,
        action: str,
        details: Optional[dict[str, Any]] = None,
        latency_ms: Optional[float] = None
    ) -> ClusterEvent:
        event = ClusterEvent(
            node_id=node_id,
            term=term,
            category=category,
            action=action,
            details=details or {},
            latency_ms=latency_ms
        )
        async with self._lock:
            self.publish_nowait(event)
        return event

    def get_history(self, limit: Optional[int] = None, category: Optional[EventCategory] = None) -> list[dict[str, Any]]:
        """Retrieve recent historical events strictly from the bounded buffer."""
        events = list(self._history)
        if category:
            events = [e for e in events if e.category == category]
        if limit:
            events = events[-limit:]
        return [e.model_dump() for e in events]

    def subscribe(self, max_queue_size: int = 100) -> asyncio.Queue:
        """Register a new consumer queue (e.g. WebSocket connection)."""
        q = asyncio.Queue(maxsize=max_queue_size)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Remove a disconnected consumer queue."""
        self._subscribers.discard(q)
        self._subscriber_dropped_counts.pop(q, None)

    def get_overflow_stats(self) -> dict[str, int]:
        """Return drop and queue statistics for observability."""
        return {
            "total_events_published": self.total_events_published,
            "total_events_dropped": self.total_events_dropped,
            "active_subscribers": len(self._subscribers)
        }

    def clear(self) -> None:
        """Clear event history (used in test teardowns)."""
        self._history.clear()
        self.total_events_published = 0
        self.total_events_dropped = 0
        self._subscriber_dropped_counts.clear()

# Global singleton event bus instance for node runtime
cluster_event_bus = EventBus(maxlen=500)
