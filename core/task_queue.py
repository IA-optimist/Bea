"""
DEPRECATED: Use core.actions.action_model.CanonicalAction for new code.

BEA MAX — CoreTaskQueue
Queue async pour les tâches de fond avec retry et backoff exponentiel.

Architecture :
    CoreTaskQueue
    ├── asyncio.Queue — FIFO thread-safe
    ├── dict[id, BackgroundTask] — registre en mémoire
    └── asyncio.Lock — opérations atomiques sur le registre

Usage :
    queue = get_core_task_queue()
    task  = await queue.enqueue("ma_tache", payload={"key": "val"})
    task  = await queue.dequeue(timeout=1.0)   # None si vide
    await queue.mark_done(task.id)
    await queue.mark_failed(task.id, "raison")
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── States ────────────────────────────────────────────────────

class TaskState(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    DONE      = "done"
    FAILED    = "failed"
    CANCELLED = "cancelled"


# ── Task dataclass ────────────────────────────────────────────

@dataclass
class BackgroundTask:
    id:           str       = field(default_factory=lambda: str(uuid.uuid4()))
    name:         str       = ""
    state:        TaskState = TaskState.PENDING
    payload:      dict      = field(default_factory=dict)
    result:       Any       = None
    error:        str       = ""
    created_at:   float     = field(default_factory=time.time)
    updated_at:   float     = field(default_factory=time.time)
    attempts:     int       = 0
    max_retries:  int       = 3
    base_delay_s: float     = 1.0
    max_delay_s:  float     = 60.0
    mission_id:   str       = ""
    kind:         str       = "task"   # "task" | "conversation"

    # ── Retry helpers ──────────────────────────────────────────

    def retry_delay(self) -> float:
        """Exponential backoff: base * 2^attempts, capped at max_delay_s."""
        delay = self.base_delay_s * (2 ** self.attempts)
        return min(delay, self.max_delay_s)

    def can_retry(self) -> bool:
        return self.attempts < self.max_retries

    def is_terminal(self) -> bool:
        return self.state in (TaskState.DONE, TaskState.FAILED, TaskState.CANCELLED)

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "name":        self.name,
            "state":       self.state.value,
            "payload":     self.payload,
            "result":      self.result,
            "error":       self.error,
            "created_at":  self.created_at,
            "updated_at":  self.updated_at,
            "attempts":    self.attempts,
            "max_retries": self.max_retries,
            "mission_id":  self.mission_id,
            "kind":        self.kind,
        }


# ── Queue ─────────────────────────────────────────────────────

class CoreTaskQueue:
    """
    Async task queue backed by asyncio.Queue.

    Thread-safe via asyncio.Lock for registry mutations.
    dequeue() returns None on timeout (non-blocking check pattern).
    """

    def __init__(self) -> None:
        self._q:        asyncio.Queue[BackgroundTask] = asyncio.Queue()
        self._registry: dict[str, BackgroundTask]     = {}
        self._lock:     asyncio.Lock                  = asyncio.Lock()

    # ── Enqueue ──────────────────────────────────────────────

    async def enqueue(
        self,
        name:         str,
        payload:      dict          = None,
        max_retries:  int           = 3,
        base_delay_s: float         = 1.0,
        max_delay_s:  float         = 60.0,
        mission_id:   str           = "",
        kind:         str           = "task",
        task_id:      str | None    = None,
    ) -> BackgroundTask:
        task = BackgroundTask(
            id           = task_id or str(uuid.uuid4()),
            name         = name,
            state        = TaskState.PENDING,
            payload      = payload or {},
            max_retries  = max_retries,
            base_delay_s = base_delay_s,
            max_delay_s  = max_delay_s,
            mission_id   = mission_id,
            kind         = kind,
        )
        async with self._lock:
            self._registry[task.id] = task
        await self._q.put(task)
        return task

    # ── Dequeue ──────────────────────────────────────────────

    async def dequeue(self, timeout: float = 1.0) -> BackgroundTask | None:
        """
        Returns the next PENDING task, or None on timeout.
        Marks returned task as RUNNING.
        """
        try:
            task = await asyncio.wait_for(self._q.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

        async with self._lock:
            # Task may have been cancelled while queued
            stored = self._registry.get(task.id)
            if stored and stored.state == TaskState.CANCELLED:
                return None
            if stored:
                stored.state      = TaskState.RUNNING
                stored.updated_at = time.time()
        return task

    # ── Requeue (retry) ──────────────────────────────────────

    async def requeue(self, task: BackgroundTask) -> None:
        """Put a task back as PENDING after a failure (for retry logic)."""
        async with self._lock:
            stored = self._registry.get(task.id)
            if stored:
                stored.state      = TaskState.PENDING
                stored.updated_at = time.time()
        await self._q.put(task)

    # ── Terminal state setters ────────────────────────────────

    async def mark_done(self, task_id: str, result: Any = None) -> None:
        async with self._lock:
            t = self._registry.get(task_id)
            if t:
                t.state      = TaskState.DONE
                t.result     = result
                t.updated_at = time.time()

    async def mark_failed(self, task_id: str, error: str = "") -> None:
        async with self._lock:
            t = self._registry.get(task_id)
            if t:
                t.state      = TaskState.FAILED
                t.error      = error
                t.updated_at = time.time()

    async def cancel(self, task_id: str) -> bool:
        """Mark a task as CANCELLED. Returns True if found."""
        async with self._lock:
            t = self._registry.get(task_id)
            if t and not t.is_terminal():
                t.state      = TaskState.CANCELLED
                t.updated_at = time.time()
                return True
        return False

    # ── Queries ───────────────────────────────────────────────

    async def list_tasks(
        self,
        state:      TaskState | None = None,
        mission_id: str | None       = None,
        kind:       str | None       = None,
        limit:      int              = 100,
    ) -> list[BackgroundTask]:
        async with self._lock:
            tasks = list(self._registry.values())

        if state:
            tasks = [t for t in tasks if t.state == state]
        if mission_id:
            tasks = [t for t in tasks if t.mission_id == mission_id]
        if kind:
            tasks = [t for t in tasks if t.kind == kind]

        tasks.sort(key=lambda t: t.created_at)
        return tasks[:limit]

    async def get(self, task_id: str) -> BackgroundTask | None:
        async with self._lock:
            return self._registry.get(task_id)

    async def stats(self) -> dict:
        async with self._lock:
            tasks = list(self._registry.values())
        counts = {s.value: 0 for s in TaskState}
        for t in tasks:
            counts[t.state.value] += 1
        return {
            "total":   len(tasks),
            "pending": counts[TaskState.PENDING.value],
            "running": counts[TaskState.RUNNING.value],
            "done":    counts[TaskState.DONE.value],
            "failed":  counts[TaskState.FAILED.value],
            "cancelled": counts[TaskState.CANCELLED.value],
            "queue_size": self._q.qsize(),
        }


# ── Singleton ─────────────────────────────────────────────────

_queue: CoreTaskQueue | None = None


def get_core_task_queue() -> CoreTaskQueue:
    global _queue
    if _queue is None:
        _queue = CoreTaskQueue()
    return _queue
