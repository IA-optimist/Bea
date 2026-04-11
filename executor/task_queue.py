"""
JARVIS MAX — Task Queue v2
File de tâches async avec priorité, états et persistence légère.

Caractéristiques :
- asyncio.PriorityQueue sous le capot
- États : pending → assigned → running → succeeded / failed / retrying / cancelled
- Persistence JSON pour survie aux redémarrages
- Thread-safe via asyncio.Lock
- Stats temps réel
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import structlog

from core.contracts import TaskContract, TaskState

log = structlog.get_logger()

_QUEUE_STORAGE = Path("workspace/task_queue.json")


# ═══════════════════════════════════════════════════════════════
# QUEUED TASK
# ═══════════════════════════════════════════════════════════════

@dataclass
class QueuedTask:
    """Tâche en file avec état, retry et méta."""
    task_id:      str
    mission_id:   str
    agent:        str
    task:         str
    priority:     int = 2        # 1=haute → 4=basse
    timeout_s:    int = 120
    status:       str = TaskState.PENDING
    retry_count:  int = 0
    max_retries:  int = 3
    created_at:   float = field(default_factory=time.time)
    started_at:   float | None = None
    completed_at: float | None = None
    error:        str | None = None
    result:       str | None = None
    correlation_id: str = ""
    metadata:     dict[str, Any] = field(default_factory=dict)

    # Clé pour PriorityQueue : (priority, created_at) → tri croissant
    def __lt__(self, other: "QueuedTask") -> bool:
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.created_at < other.created_at

    def is_terminal(self) -> bool:
        return self.status in (
            TaskState.SUCCEEDED, TaskState.FAILED,
            TaskState.CANCELLED, TaskState.SKIPPED,
        )

    def duration_ms(self) -> int:
        if self.started_at is None:
            return 0
        end = self.completed_at or time.time()
        return int((end - self.started_at) * 1000)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_contract(cls, contract: TaskContract) -> "QueuedTask":
        return cls(
            task_id=contract.task_id,
            mission_id=contract.mission_id,
            agent=contract.agent,
            task=contract.task,
            priority=contract.priority,
            timeout_s=contract.timeout_s,
            max_retries=contract.retry_config.max_attempts,
            correlation_id=contract.correlation_id,
            metadata=contract.metadata,
        )


# ═══════════════════════════════════════════════════════════════
# TASK QUEUE
# ═══════════════════════════════════════════════════════════════

class TaskQueue:
    """
    File de tâches async avec priorité et gestion d'état.

    Usage :
        queue = TaskQueue()
        await queue.enqueue(task)
        task = await queue.dequeue()  # bloquant
        await queue.mark_done(task.task_id, result="...")
    """

    def __init__(self, storage: Path = _QUEUE_STORAGE):
        self._pq: asyncio.PriorityQueue[QueuedTask] = asyncio.PriorityQueue()
        self._tasks: dict[str, QueuedTask] = {}
        self._lock = asyncio.Lock()
        self._storage = storage
        self._loaded = False

    # ── Public API ─────────────────────────────────────────────

    async def enqueue(
        self,
        agent: str,
        task: str,
        mission_id: str = "",
        priority: int = 2,
        timeout_s: int = 120,
        max_retries: int = 3,
        correlation_id: str = "",
        metadata: dict | None = None,
        task_id: str | None = None,
    ) -> QueuedTask:
        """Ajoute une tâche en file."""
        qt = QueuedTask(
            task_id=task_id or str(uuid.uuid4())[:12],
            mission_id=mission_id,
            agent=agent,
            task=task,
            priority=priority,
            timeout_s=timeout_s,
            max_retries=max_retries,
            correlation_id=correlation_id,
            metadata=metadata or {},
        )
        async with self._lock:
            self._tasks[qt.task_id] = qt
            await self._pq.put(qt)

        log.info(
            "task_enqueued",
            task_id=qt.task_id,
            agent=agent,
            priority=priority,
            mission_id=mission_id,
        )
        await self._persist()
        return qt

    async def enqueue_from_contract(self, contract: TaskContract) -> QueuedTask:
        """Enqueue depuis un TaskContract typé."""
        qt = QueuedTask.from_contract(contract)
        async with self._lock:
            self._tasks[qt.task_id] = qt
            await self._pq.put(qt)
        log.info("task_enqueued_from_contract", task_id=qt.task_id, agent=qt.agent)
        await self._persist()
        return qt

    async def dequeue(self, timeout: float | None = None) -> QueuedTask | None:
        """Retire la tâche de plus haute priorité de la file. None si timeout."""
        try:
            if timeout is not None:
                qt = await asyncio.wait_for(self._pq.get(), timeout=timeout)
            else:
                qt = await self._pq.get()
            await self.mark_assigned(qt.task_id)
            return qt
        except asyncio.TimeoutError:
            return None

    async def dequeue_nowait(self) -> QueuedTask | None:
        """Retire sans attendre. None si vide."""
        try:
            qt = self._pq.get_nowait()
            await self.mark_assigned(qt.task_id)
            return qt
        except asyncio.QueueEmpty:
            return None

    async def mark_assigned(self, task_id: str) -> None:
        async with self._lock:
            if t := self._tasks.get(task_id):
                t.status = TaskState.ASSIGNED

    async def mark_running(self, task_id: str) -> None:
        async with self._lock:
            if t := self._tasks.get(task_id):
                t.status = TaskState.RUNNING
                t.started_at = time.time()
        log.info("task_running", task_id=task_id)

    async def mark_done(self, task_id: str, result: str = "") -> QueuedTask | None:
        async with self._lock:
            t = self._tasks.get(task_id)
            if not t:
                return None
            t.status = TaskState.SUCCEEDED
            t.result = result
            t.completed_at = time.time()
        log.info(
            "task_succeeded",
            task_id=task_id,
            agent=t.agent,
            duration_ms=t.duration_ms(),
        )
        await self._persist()
        return t

    async def mark_failed(
        self, task_id: str, error: str = "", permanent: bool = False
    ) -> QueuedTask | None:
        async with self._lock:
            t = self._tasks.get(task_id)
            if not t:
                return None
            t.error = error
            t.completed_at = time.time()
            if permanent or t.retry_count >= t.max_retries:
                t.status = TaskState.FAILED
            else:
                t.status = TaskState.RETRYING
                t.retry_count += 1
        log.warning(
            "task_failed",
            task_id=task_id,
            agent=t.agent,
            error=error[:100],
            retry_count=t.retry_count,
            permanent=t.status == TaskState.FAILED,
        )
        await self._persist()
        return t

    async def mark_retrying(self, task_id: str) -> None:
        """Remet une tâche RETRYING dans la file après délai."""
        async with self._lock:
            t = self._tasks.get(task_id)
            if t and t.status == TaskState.RETRYING:
                t.status = TaskState.PENDING
                t.started_at = None
                t.completed_at = None
                await self._pq.put(t)
        log.info("task_requeued", task_id=task_id, retry=t.retry_count if t else 0)

    async def cancel(self, task_id: str, reason: str = "") -> bool:
        """Annule une tâche si elle est encore PENDING ou ASSIGNED."""
        async with self._lock:
            t = self._tasks.get(task_id)
            if not t or t.status not in (TaskState.PENDING, TaskState.ASSIGNED):
                return False
            t.status = TaskState.CANCELLED
            t.error = reason or "Annulé"
            t.completed_at = time.time()
        log.info("task_cancelled", task_id=task_id, reason=reason[:60])
        await self._persist()
        return True

    async def cancel_mission(self, mission_id: str) -> int:
        """Annule toutes les tâches d'une mission. Retourne le nombre annulées."""
        count = 0
        for task_id, t in list(self._tasks.items()):
            if t.mission_id == mission_id and not t.is_terminal():
                if await self.cancel(task_id, reason=f"Mission {mission_id} annulée"):
                    count += 1
        log.info("mission_tasks_cancelled", mission_id=mission_id, count=count)
        return count

    def get(self, task_id: str) -> QueuedTask | None:
        return self._tasks.get(task_id)

    def get_by_mission(self, mission_id: str) -> list[QueuedTask]:
        return [t for t in self._tasks.values() if t.mission_id == mission_id]

    def pending_count(self) -> int:
        return sum(1 for t in self._tasks.values()
                   if t.status == TaskState.PENDING)

    def running_count(self) -> int:
        return sum(1 for t in self._tasks.values()
                   if t.status == TaskState.RUNNING)

    def stats(self) -> dict:
        tasks = list(self._tasks.values())
        by_status: dict[str, int] = {}
        by_agent:  dict[str, int] = {}
        for t in tasks:
            by_status[t.status] = by_status.get(t.status, 0) + 1
            by_agent[t.agent] = by_agent.get(t.agent, 0) + 1

        completed = [t for t in tasks if t.status == TaskState.SUCCEEDED]
        avg_ms = (
            int(sum(t.duration_ms() for t in completed) / len(completed))
            if completed else 0
        )
        return {
            "total":         len(tasks),
            "by_status":     by_status,
            "by_agent":      by_agent,
            "queue_size":    self._pq.qsize(),
            "avg_duration_ms": avg_ms,
        }

    # ── Persistence ────────────────────────────────────────────

    async def _persist(self) -> None:
        """Sauvegarde les tâches non-terminales en JSON."""
        try:
            self._storage.parent.mkdir(parents=True, exist_ok=True)
            live = {
                tid: t.to_dict()
                for tid, t in self._tasks.items()
                if not t.is_terminal()
            }
            data = {"version": 2, "saved_at": time.time(), "tasks": live}
            self._storage.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), "utf-8"
            )
        except Exception as e:
            log.warning("task_queue_persist_failed", err=str(e)[:80])

    async def load(self) -> int:
        """Charge les tâches persistées au démarrage."""
        if self._loaded:
            return 0
        self._loaded = True
        if not self._storage.exists():
            return 0
        try:
            data = json.loads(self._storage.read_text("utf-8"))
            count = 0
            for raw in data.get("tasks", {}).values():
                try:
                    qt = QueuedTask(**raw)
                    # Ne recharger que les tâches PENDING (RUNNING = orphans)
                    if qt.status in (TaskState.PENDING, TaskState.RETRYING):
                        qt.status = TaskState.PENDING
                        self._tasks[qt.task_id] = qt
                        await self._pq.put(qt)
                        count += 1
                except Exception:
                    _silent_log.debug("suppressed_exception", src='task_queue.py')
            log.info("task_queue_loaded", count=count)
            return count
        except Exception as e:
            log.warning("task_queue_load_failed", err=str(e)[:80])
            return 0


# ── Singleton ──────────────────────────────────────────────────

_queue_instance: TaskQueue | None = None


def get_task_queue() -> TaskQueue:
    global _queue_instance
    if _queue_instance is None:
        _queue_instance = TaskQueue()
    return _queue_instance
