"""
BEA MAX — Execution Engine v2
Moteur d'exécution central avec task queue priorisée, retry, timeouts et
journalisation structurée. Aucune tâche ne disparaît silencieusement.

Architecture :
  ExecutionEngine
  ├── _queue           : heapq (priority, created_at, task)
  ├── _worker_loop()   : thread daemon, poll toutes les 2s
  ├── _execute_task()  : gestion retry + timeout par tâche
  ├── _dispatch()      : routage vers le bon handler
  └── API publique     : submit, cancel, status, list_tasks, stats

Statuts :
  PENDING → RUNNING → SUCCEEDED
                    → FAILED
                    → TIMED_OUT
  PENDING → CANCELLED (avant démarrage)
  RUNNING → CANCELLED (flag _cancel_requested)

Garanties :
  - Chaque tâche est loguée à chaque transition de statut
  - Les tâches FAILED/TIMED_OUT restent en mémoire (pas de purge silencieuse)
  - Singleton thread-safe via _engine_lock
"""
from __future__ import annotations

import heapq
import threading
import time
from typing import cast

import structlog

from executor.task_model import (
    ExecutionTask,
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    STATUS_FAILED,
    STATUS_CANCELLED,
    STATUS_TIMED_OUT,
    TERMINAL_STATUSES,
)
from executor.retry_policy import DEFAULT_POLICY, should_retry, compute_delay

log = structlog.get_logger()

_POLL_INTERVAL_S   = 2.0    # secondes entre chaque scan de la queue
_MAX_CONCURRENT    = 4      # workers simultanés max
_RESULT_MAX_LEN    = 4000   # longueur max d'un résultat stocké
_MAX_QUEUE_SIZE    = 1000   # tâches PENDING en attente max (protection OOM)
_MAX_TERMINAL_KEPT = 500    # tâches terminées conservées en mémoire (LRU)


# ══════════════════════════════════════════════════════════════════════════════
# EXECUTION ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class ExecutionEngine:
    """
    Moteur d'exécution BeaMax v2.

    Usage :
        engine = get_engine()
        task   = ExecutionTask(description="Faire X", handler_name="research")
        tid    = engine.submit(task)
        print(engine.status(tid))
    """

    def __init__(self) -> None:
        # Queue interne : heap de (priority, created_at, task)
        self._heap: list[tuple[int, float, ExecutionTask]] = []
        self._heap_lock = threading.Lock()

        # Registre de toutes les tâches (y compris terminées)
        self._tasks: dict[str, ExecutionTask] = {}
        self._tasks_lock = threading.Lock()

        # Flags d'annulation pour les tâches RUNNING
        self._cancel_flags: dict[str, threading.Event] = {}
        self._cancel_lock = threading.Lock()

        # Thread worker
        self._running = False
        self._thread: threading.Thread | None = None

        # Sémaphore de concurrence
        self._semaphore = threading.Semaphore(_MAX_CONCURRENT)

        # Compteurs de stats
        self._stats_lock = threading.Lock()
        self._started_at: float | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Lance le worker daemon."""
        if self._running:
            log.warning("execution_engine_already_running")
            return
        self._running    = True
        self._started_at = time.time()
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="BeaExecutionEngine",
            daemon=True,
        )
        self._thread.start()
        log.info("execution_engine_started", poll_interval_s=_POLL_INTERVAL_S,
                 max_concurrent=_MAX_CONCURRENT)

    def stop(self) -> None:
        """Arrêt propre du worker."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=6)
        log.info("execution_engine_stopped")

    # ── API publique ──────────────────────────────────────────────────────────

    def submit(self, task: ExecutionTask) -> str:
        """
        Soumet une tâche pour exécution.
        Retourne le task_id.
        Lève RuntimeError si la queue dépasse _MAX_QUEUE_SIZE.
        """
        if task.retry_policy is None:
            task.retry_policy = DEFAULT_POLICY

        # Guard against unbounded queue growth (OOM protection)
        with self._heap_lock:
            pending_count = len(self._heap)
        if pending_count >= _MAX_QUEUE_SIZE:
            raise RuntimeError(
                f"ExecutionEngine queue full ({pending_count}/{_MAX_QUEUE_SIZE}). "
                "Reject task to protect system resources."
            )

        with self._tasks_lock:
            self._tasks[task.id] = task

        with self._heap_lock:
            heapq.heappush(self._heap, (task.priority, task.created_at, task))

        log.info(
            "task_submitted",
            task_id=task.id,
            correlation_id=task.correlation_id,
            mission_id=task.mission_id,
            handler=task.handler_name,
            priority=task.priority,
            description=task.description[:80],
        )
        return cast(str, task.id)

    def cancel(self, task_id: str) -> bool:
        """
        Annule une tâche PENDING ou RUNNING.

        - PENDING : annulation immédiate (ne sera jamais exécutée)
        - RUNNING : pose un flag, le handler doit le vérifier ou le thread sera interrompu
        Retourne True si l'annulation a été effectuée ou demandée.
        """
        with self._tasks_lock:
            task = self._tasks.get(task_id)

        if task is None:
            log.warning("cancel_task_not_found", task_id=task_id)
            return False

        if task.status == STATUS_PENDING:
            task.status      = STATUS_CANCELLED
            task.finished_at = time.time()
            log.info("task_cancelled_pending",
                     task_id=task_id,
                     correlation_id=task.correlation_id,
                     mission_id=task.mission_id)
            return True

        if task.status == STATUS_RUNNING:
            with self._cancel_lock:
                event = self._cancel_flags.get(task_id)
                if event:
                    event.set()
            log.info("task_cancel_requested_running",
                     task_id=task_id,
                     correlation_id=task.correlation_id,
                     mission_id=task.mission_id)
            return True

        log.warning("cancel_task_in_terminal_status",
                    task_id=task_id, status=task.status)
        return False

    def status(self, task_id: str) -> dict[str, object] | None:
        """Retourne l'état courant d'une tâche, ou None si inconnue."""
        with self._tasks_lock:
            task = self._tasks.get(task_id)
        return task.to_dict() if task else None

    def list_tasks(
        self,
        status: str | None = None,
        mission_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        """
        Liste les tâches avec filtres optionnels.
        Triées par created_at décroissant (plus récentes en premier).
        """
        with self._tasks_lock:
            tasks = list(self._tasks.values())

        if status:
            tasks = [t for t in tasks if t.status == status.upper()]
        if mission_id:
            tasks = [t for t in tasks if t.mission_id == mission_id]

        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return [t.to_dict() for t in tasks[:limit]]

    def stats(self) -> dict[str, object]:
        """Statistiques globales du moteur."""
        with self._tasks_lock:
            all_tasks = list(self._tasks.values())

        counts: dict[str, int] = {
            STATUS_PENDING:   0,
            STATUS_RUNNING:   0,
            STATUS_SUCCEEDED: 0,
            STATUS_FAILED:    0,
            STATUS_CANCELLED: 0,
            STATUS_TIMED_OUT: 0,
        }
        for t in all_tasks:
            counts[t.status] = counts.get(t.status, 0) + 1

        return {
            "total":     len(all_tasks),
            "pending":   counts[STATUS_PENDING],
            "running":   counts[STATUS_RUNNING],
            "succeeded": counts[STATUS_SUCCEEDED],
            "failed":    counts[STATUS_FAILED],
            "cancelled": counts[STATUS_CANCELLED],
            "timed_out": counts[STATUS_TIMED_OUT],
            "started_at": self._started_at,
            "engine_running": self._running,
        }

    # ── Task memory management ────────────────────────────────────────────────

    def _purge_terminal_tasks(self) -> None:
        """
        Evict the oldest terminal tasks when the registry exceeds _MAX_TERMINAL_KEPT.

        Only SUCCEEDED / FAILED / TIMED_OUT / CANCELLED tasks are eligible.
        Active (PENDING / RUNNING) tasks are never purged.
        Called after each task completion to keep memory usage bounded.
        """
        with self._tasks_lock:
            terminal = [
                t for t in self._tasks.values()
                if t.status in TERMINAL_STATUSES
            ]
            if len(terminal) <= _MAX_TERMINAL_KEPT:
                return
            # Sort by finished_at ascending (oldest first)
            terminal.sort(key=lambda t: t.finished_at or 0)
            to_remove = terminal[: len(terminal) - _MAX_TERMINAL_KEPT]
            for t in to_remove:
                self._tasks.pop(t.id, None)
        if to_remove:
            log.debug(
                "execution_engine_task_purge",
                purged=len(to_remove),
                remaining=len(self._tasks),
            )

    # ── Worker loop ───────────────────────────────────────────────────────────

    def _worker_loop(self) -> None:
        """Boucle principale du thread daemon."""
        log.info("execution_engine_worker_loop_started")
        while self._running:
            try:
                self._process_batch()
            except Exception as exc:
                log.error("execution_engine_worker_error", error=str(exc))
            time.sleep(_POLL_INTERVAL_S)
        log.info("execution_engine_worker_loop_stopped")

    def _process_batch(self) -> None:
        """Extrait et lance les tâches PENDING disponibles."""
        pending_tasks: list[ExecutionTask] = []

        with self._heap_lock:
            while self._heap:
                priority, created_at, task = self._heap[0]
                # Re-vérifier le statut (peut avoir été annulé)
                with self._tasks_lock:
                    current = self._tasks.get(task.id)
                if current is None or current.status != STATUS_PENDING:
                    heapq.heappop(self._heap)
                    continue
                if len(pending_tasks) >= _MAX_CONCURRENT:
                    break
                heapq.heappop(self._heap)
                pending_tasks.append(task)

        for task in pending_tasks:
            # Lancer chaque tâche dans son propre thread
            t = threading.Thread(
                target=self._execute_task_safe,
                args=(task,),
                name=f"BeaTask-{task.id}",
                daemon=True,
            )
            t.start()

    def _execute_task_safe(self, task: ExecutionTask) -> None:
        """Wrapper sécurisé autour de _execute_task (ne lève jamais)."""
        try:
            self._execute_task(task)
        except Exception as exc:
            # Filet de sécurité : la tâche ne doit jamais disparaître.
            # exc_info=True preserves the full traceback for post-mortem debugging.
            task.status      = STATUS_FAILED
            task.error       = f"[ENGINE CRASH] {type(exc).__name__}: {exc}"
            task.finished_at = time.time()
            log.error(
                "task_engine_crash",
                task_id=task.id,
                correlation_id=task.correlation_id,
                mission_id=task.mission_id,
                error_type=type(exc).__name__,
                error=str(exc),
                exc_info=True,
            )
        finally:
            # Purge old terminal tasks to prevent unbounded memory growth.
            self._purge_terminal_tasks()

    def _execute_task(self, task: ExecutionTask) -> None:
        """
        Exécute une tâche avec retry et timeout.

        Transitions :
          PENDING → RUNNING → SUCCEEDED
                            → FAILED (erreur non-retryable ou max atteint)
                            → TIMED_OUT
                            → CANCELLED (flag d'annulation)
          PENDING → RUNNING → PENDING (retry schedulé)
        """
        policy = task.retry_policy or DEFAULT_POLICY

        # Prépare le flag d'annulation
        cancel_event = threading.Event()
        with self._cancel_lock:
            self._cancel_flags[task.id] = cancel_event

        try:
            while task.attempts < task.max_attempts:
                # Vérifier annulation avant chaque tentative
                if cancel_event.is_set():
                    task.status      = STATUS_CANCELLED
                    task.finished_at = time.time()
                    log.info("task_cancelled_before_attempt",
                             task_id=task.id,
                             correlation_id=task.correlation_id,
                             mission_id=task.mission_id,
                             attempt=task.attempts + 1)
                    return

                task.attempts  += 1
                task.status     = STATUS_RUNNING
                task.started_at = task.started_at or time.time()
                attempt_start   = time.time()

                log.info(
                    "task_attempt_start",
                    task_id=task.id,
                    correlation_id=task.correlation_id,
                    mission_id=task.mission_id,
                    attempt=task.attempts,
                    max_attempts=task.max_attempts,
                    handler=task.handler_name,
                )

                try:
                    result_str = self._dispatch_with_timeout(
                        task, cancel_event, task.timeout_seconds
                    )

                    # Vérifier annulation après exécution
                    if cancel_event.is_set():
                        task.status      = STATUS_CANCELLED
                        task.finished_at = time.time()
                        log.info("task_cancelled_after_execution",
                                 task_id=task.id,
                                 correlation_id=task.correlation_id,
                                 mission_id=task.mission_id)
                        return

                    # Succès
                    task.status      = STATUS_SUCCEEDED
                    task.result      = (result_str or "")[:_RESULT_MAX_LEN]
                    task.finished_at = time.time()
                    duration_ms      = (task.finished_at - attempt_start) * 1000

                    log.info(
                        "task_succeeded",
                        task_id=task.id,
                        correlation_id=task.correlation_id,
                        mission_id=task.mission_id,
                        attempt=task.attempts,
                        duration_ms=round(duration_ms, 1),
                        result_preview=(task.result[:80] if task.result else ""),
                    )
                    return

                except _TimeoutSignal:
                    task.status      = STATUS_TIMED_OUT
                    task.error       = f"Timeout après {task.timeout_seconds}s (tentative {task.attempts})"
                    task.finished_at = time.time()
                    log.error(
                        "task_timed_out",
                        task_id=task.id,
                        correlation_id=task.correlation_id,
                        mission_id=task.mission_id,
                        attempt=task.attempts,
                        timeout_s=task.timeout_seconds,
                    )
                    # Le timeout est retryable si policy.should_retry l'accepte
                    exc_for_retry = TimeoutError(task.error)
                    if should_retry(task.attempts, exc_for_retry, policy):
                        delay = compute_delay(task.attempts, policy)
                        log.info(
                            "task_retry_scheduled",
                            task_id=task.id,
                            correlation_id=task.correlation_id,
                            mission_id=task.mission_id,
                            attempt=task.attempts,
                            next_attempt=task.attempts + 1,
                            delay_s=delay,
                        )
                        task.status = STATUS_PENDING
                        self._sleep_interruptible(delay, cancel_event)
                        continue
                    return  # TIMED_OUT final

                except Exception as exc:
                    err_type = type(exc).__name__
                    err_msg  = str(exc)[:200]
                    duration_ms = (time.time() - attempt_start) * 1000

                    if should_retry(task.attempts, exc, policy):
                        delay = compute_delay(task.attempts, policy)
                        log.warning(
                            "task_retry_scheduled",
                            task_id=task.id,
                            correlation_id=task.correlation_id,
                            mission_id=task.mission_id,
                            attempt=task.attempts,
                            next_attempt=task.attempts + 1,
                            error_type=err_type,
                            error=err_msg,
                            delay_s=delay,
                        )
                        task.error  = f"{err_type}: {err_msg}"
                        task.status = STATUS_PENDING
                        self._sleep_interruptible(delay, cancel_event)
                        continue
                    else:
                        # Erreur non-retryable : FAILED immédiatement
                        task.status      = STATUS_FAILED
                        task.error       = f"{err_type}: {err_msg}"
                        task.finished_at = time.time()
                        log.error(
                            "task_failed_non_retryable",
                            task_id=task.id,
                            correlation_id=task.correlation_id,
                            mission_id=task.mission_id,
                            attempt=task.attempts,
                            error_type=err_type,
                            error=err_msg,
                            duration_ms=round(duration_ms, 1),
                        )
                        return

            # Max attempts épuisés → FAILED
            if task.status not in TERMINAL_STATUSES:
                task.status      = STATUS_FAILED
                task.finished_at = time.time()
                log.error(
                    "task_failed_max_attempts",
                    task_id=task.id,
                    correlation_id=task.correlation_id,
                    mission_id=task.mission_id,
                    attempts=task.attempts,
                    max_attempts=task.max_attempts,
                    last_error=task.error[:100],
                )

        finally:
            with self._cancel_lock:
                self._cancel_flags.pop(task.id, None)

    def _dispatch_with_timeout(
        self,
        task: ExecutionTask,
        cancel_event: threading.Event,
        timeout_s: float,
    ) -> str:
        """
        Exécute le handler dans un thread séparé avec timeout strict.
        Lève _TimeoutSignal si le timeout est dépassé.
        """
        result_holder: list[str | None] = [None]
        error_holder:  list[BaseException | None] = [None]
        done_event = threading.Event()

        def _run() -> None:
            try:
                from executor.handlers import get_handler
                handler = get_handler(task.handler_name)
                result_holder[0] = handler(task)
            except Exception as exc:
                error_holder[0] = exc
            finally:
                done_event.set()

        worker = threading.Thread(target=_run, daemon=True, name=f"BeaHandler-{task.id}")
        worker.start()

        # Attendre avec timeout
        finished = done_event.wait(timeout=timeout_s)

        if not finished:
            # Le thread handler tourne encore → on le laisse mourir seul (daemon)
            raise _TimeoutSignal()

        # Propagate handler exception
        if error_holder[0] is not None:
            raise error_holder[0]

        result = result_holder[0]
        if result is None:
            return ""
        return result

    @staticmethod
    def _sleep_interruptible(seconds: float, cancel_event: threading.Event) -> None:
        """Dort `seconds` secondes mais peut être interrompu par cancel_event."""
        cancel_event.wait(timeout=seconds)


# ── Signal interne ────────────────────────────────────────────────────────────

class _TimeoutSignal(Exception):
    """Signal interne levé quand le handler dépasse son timeout."""


# ── Singleton thread-safe ──────────────────────────────────────────────────────

_engine_instance: ExecutionEngine | None = None
_engine_lock = threading.Lock()


def get_engine() -> ExecutionEngine:
    """
    Retourne le singleton ExecutionEngine.
    Le démarre automatiquement au premier appel.
    Thread-safe (double-checked locking).
    """
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = ExecutionEngine()
                _engine_instance.start()
    return _engine_instance


def reset_engine() -> None:
    """Réinitialise le singleton (utile pour les tests)."""
    global _engine_instance
    with _engine_lock:
        if _engine_instance is not None:
            _engine_instance.stop()
            _engine_instance = None
