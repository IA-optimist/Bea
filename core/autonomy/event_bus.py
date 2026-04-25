"""
core/autonomy/event_bus.py — In-process pub/sub for autonomy events.

Goal : a single hub where every signal that should drive autonomous
decisions is published — cron firings, log anomalies, webhooks, mission
lifecycle, metric thresholds. Subscribers (the autonomy daemon, learning
loop, alerting) get a consistent view without each having to wire
themselves into every source.

Design choices :

- Sync + async subscribers : sync handlers run inline ; async coroutines
  are scheduled with `asyncio.create_task` ; if no loop is running they
  fall back to a thread-pool worker so the publisher never blocks.
- Bounded ring buffer per topic for replay / debugging (default 100).
  Memory bounded — old events are dropped silently.
- Topic = dotted string (e.g. `mission.completed`, `metric.cpu.high`).
  Glob match : `mission.*` matches `mission.completed`, `mission.failed`.
- Fail-isolated : a handler that raises does NOT abort the publish loop
  for other handlers ; the error is logged and counters are bumped.

Public API :
    bus = get_event_bus()                 # process singleton
    bus.subscribe("mission.*", handler)   # sync or async
    bus.unsubscribe(token)                # back-pressure control
    bus.publish("mission.completed", {...})
    bus.replay("mission.*", limit=20)     # last events (debug)
    bus.stats()                           # counters

The bus is intentionally a lightweight in-process primitive. For
cross-process / cross-host coordination, layer Redis pub/sub or NATS on
top — same API surface, swap the backend.
"""
from __future__ import annotations

import asyncio
import fnmatch
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Deque, Dict, List, Optional, Union

import structlog

log = structlog.get_logger(__name__)

# ── Types ────────────────────────────────────────────────────
SyncHandler = Callable[["Event"], None]
AsyncHandler = Callable[["Event"], Awaitable[None]]
Handler = Union[SyncHandler, AsyncHandler]


@dataclass(frozen=True)
class Event:
    """An immutable event published on the bus."""
    topic: str
    payload: Dict[str, Any]
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    ts: float = field(default_factory=time.time)


@dataclass
class _Subscription:
    token: str
    pattern: str
    handler: Handler
    is_async: bool


# ── Bus ──────────────────────────────────────────────────────
class EventBus:
    """In-process pub/sub with glob topics and bounded replay buffer."""

    DEFAULT_BUFFER = 100

    def __init__(self, buffer_size: int = DEFAULT_BUFFER):
        self._subs: Dict[str, _Subscription] = {}
        self._buffers: Dict[str, Deque[Event]] = {}
        self._buffer_size = max(1, int(buffer_size))
        self._lock = threading.RLock()
        self._stats = {"published": 0, "delivered": 0, "errors": 0, "dropped": 0}
        # Thread pool for async handlers when there's no running event loop
        self._fallback_pool = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="autonomy-bus"
        )

    # ── Subscription management ───────────────────────────────
    def subscribe(self, pattern: str, handler: Handler) -> str:
        """Register a handler for events matching the glob pattern.

        Returns a token for unsubscribe.
        """
        token = str(uuid.uuid4())
        is_async = asyncio.iscoroutinefunction(handler)
        with self._lock:
            self._subs[token] = _Subscription(
                token=token,
                pattern=pattern,
                handler=handler,
                is_async=is_async,
            )
        log.debug("event_bus.subscribed", token=token, pattern=pattern, is_async=is_async)
        return token

    def unsubscribe(self, token: str) -> bool:
        with self._lock:
            removed = self._subs.pop(token, None) is not None
        if removed:
            log.debug("event_bus.unsubscribed", token=token)
        return removed

    # ── Publish ───────────────────────────────────────────────
    def publish(self, topic: str, payload: Optional[Dict[str, Any]] = None) -> Event:
        """Publish a topic with an optional payload. Never raises."""
        event = Event(topic=topic, payload=dict(payload or {}))

        # Bounded buffer per topic
        with self._lock:
            buf = self._buffers.setdefault(topic, deque(maxlen=self._buffer_size))
            buf.append(event)
            self._stats["published"] += 1
            handlers = [s for s in self._subs.values() if fnmatch.fnmatchcase(topic, s.pattern)]

        for sub in handlers:
            try:
                self._dispatch(sub, event)
                with self._lock:
                    self._stats["delivered"] += 1
            except Exception as exc:
                with self._lock:
                    self._stats["errors"] += 1
                log.warning(
                    "event_bus.handler_failed",
                    topic=topic,
                    pattern=sub.pattern,
                    err=str(exc)[:120],
                )
        return event

    def _dispatch(self, sub: _Subscription, event: Event) -> None:
        if sub.is_async:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                loop.create_task(sub.handler(event))  # type: ignore[arg-type]
            else:
                self._fallback_pool.submit(_run_async_in_thread, sub.handler, event)
        else:
            sub.handler(event)  # type: ignore[arg-type]

    # ── Replay / debug ────────────────────────────────────────
    def replay(self, pattern: str = "*", limit: int = 50) -> List[Event]:
        """Return the most-recent events matching pattern (oldest → newest)."""
        result: List[Event] = []
        with self._lock:
            for topic, buf in self._buffers.items():
                if fnmatch.fnmatchcase(topic, pattern):
                    result.extend(buf)
        result.sort(key=lambda e: e.ts)
        return result[-limit:] if limit else result

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._stats)

    def reset_stats(self) -> None:
        with self._lock:
            for k in self._stats:
                self._stats[k] = 0


def _run_async_in_thread(handler: AsyncHandler, event: Event) -> None:
    """Run an async handler in a fresh event loop (fallback path)."""
    try:
        asyncio.run(handler(event))
    except Exception as exc:
        log.warning("event_bus.async_fallback_failed", err=str(exc)[:120])


# ── Singleton ────────────────────────────────────────────────
_BUS: Optional[EventBus] = None
_BUS_LOCK = threading.Lock()


def get_event_bus() -> EventBus:
    """Process-wide singleton bus. Cheap to call ; safe across threads."""
    global _BUS
    if _BUS is None:
        with _BUS_LOCK:
            if _BUS is None:
                _BUS = EventBus()
    return _BUS


def reset_event_bus() -> None:
    """Test fixture hook : drop the singleton so subsequent tests start fresh."""
    global _BUS
    with _BUS_LOCK:
        _BUS = None
