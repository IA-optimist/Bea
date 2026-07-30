"""
DEPRECATED: Use core.actions.action_model.CanonicalAction for new code.

BEA MAX â€” CoreTaskQueue
Queue async pour les tÃ¢ches de fond avec retry et backoff exponentiel.

Architecture :
    CoreTaskQueue
    â”œâ”€â”€ asyncio.Queue â€” FIFO thread-safe
    â”œâ”€â”€ dict[id, BackgroundTask] â€” registre en mÃ©moire
    â””â”€â”€ asyncio.Lock â€” opÃ©rations atomiques sur le registre

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


# â”€â”€ States â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class TaskState(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    DONE      = "done"
    FAILED    = "failed"
    CANCELLED = "cancelled"


# â”€â”€ Task dataclass â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

    # â”€â”€ Retry helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


# â”€â”€ Queue â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

    # â”€â”€ Enqueue â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

    # â”€â”€ Dequeue â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

    # â”€â”€ Requeue (retry) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def requeue(self, task: BackgroundTask) -> None:
        """Put a task back as PENDING after a failure (for retry logic)."""
        async with self._lock:
            stored = self._registry.get(task.id)
            if stored:
                stored.state      = TaskState.PENDING
                stored.updated_at = time.time()
        await self._q.put(task)

    # â”€â”€ Terminal state setters â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

    async def cancel_mission(self, mission_id: str) -> bool:
        """Alias métier: annule la tâche de fond associée à une mission.

        Marque l'état CANCELLED via cancel(). La vraie annulation de coroutine
        se fait côté registre API (_active_mission_tasks), qui détient les
        asyncio.Task.
        """
        cancelled = await self.cancel(mission_id)
        async with self._lock:
            task_ids = [
                t.id
                for t in self._registry.values()
                if t.mission_id == mission_id and not t.is_terminal()
            ]
        for task_id in task_ids:
            cancelled = (await self.cancel(task_id)) or cancelled
        return cancelled
    # â”€â”€ Queries â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


# â”€â”€ Singleton â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_queue: CoreTaskQueue | None = None


def get_core_task_queue() -> CoreTaskQueue:
    global _queue
    if _queue is None:
        _queue = CoreTaskQueue()
    return _queue

