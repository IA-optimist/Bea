"""
OrchestrationGuard — retry policy, fallback agents, timeout supervision for pulse-ops.
Works alongside existing orchestrator without replacing it.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class TaskAttempt:
    task_id: str
    agent_id: str
    attempt_number: int
    started_at: float
    status: str = "running"  # running | success | failed | timeout
    result: Any = None
    error: str = ""
    duration_ms: int = 0


@dataclass
class GuardedTaskResult:
    task_id: str
    success: bool
    result: Any = None
    error: str = ""
    attempts: list[TaskAttempt] = field(default_factory=list)
    fallback_used: bool = False
    fallback_agent_id: str = ""
    total_duration_ms: int = 0


class OrchestrationGuard:
    """
    Wraps task execution with:
    - max_retries: retry on failure (default 3)
    - timeout_s: per-attempt timeout (default 60s)
    - fallback_agents: ordered list of agent IDs to try on final failure
    - persistent log: workspace/orchestration_log.jsonl
    """

    DEFAULT_MAX_RETRIES = 3
    DEFAULT_TIMEOUT_S = 60
    FALLBACK_MAP = {
        "shadow-advisor": ["lens-reviewer", "self-critic"],
        "forge-builder": ["recovery-agent", "debug-agent"],
        "pulse-ops": ["parallel-executor", "workflow-agent"],
        "map-planner": ["orchestrator-v2"],
    }

    def __init__(self, workspace_dir: str = "workspace"):
        self.workspace_dir = Path(workspace_dir)
        self._log_path = self.workspace_dir / "orchestration_log.jsonl"
        self._lock = threading.Lock()

    def execute(
        self,
        task_id: str,
        agent_id: str,
        fn: Callable,
        args: tuple = (),
        kwargs: dict = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        use_fallback: bool = True,
    ) -> GuardedTaskResult:
        """Retry loop with exponential backoff, timeout per attempt, fallback on exhaustion."""
        kwargs = kwargs or {}
        attempts: list[TaskAttempt] = []
        global_start = time.perf_counter()

        # Backoff delays: 0.5s, 1s, 2s, 4s, ...
        backoff_delays = [0.5 * (2 ** i) for i in range(max_retries)]

        for attempt_num in range(1, max_retries + 1):
            attempt = TaskAttempt(
                task_id=task_id,
                agent_id=agent_id,
                attempt_number=attempt_num,
                started_at=time.time(),
            )
            t0 = time.perf_counter()

            result, error = self._run_with_timeout(fn, args, kwargs, timeout_s)
            duration_ms = int((time.perf_counter() - t0) * 1000)
            attempt.duration_ms = duration_ms

            if error == "__timeout__":
                attempt.status = "timeout"
                attempt.error = f"Timed out after {timeout_s}s"
            elif error:
                attempt.status = "failed"
                attempt.error = error
            else:
                attempt.status = "success"
                attempt.result = result

            attempts.append(attempt)
            self._log_attempt(attempt)

            if attempt.status == "success":
                total_ms = int((time.perf_counter() - global_start) * 1000)
                return GuardedTaskResult(
                    task_id=task_id,
                    success=True,
                    result=result,
                    attempts=attempts,
                    total_duration_ms=total_ms,
                )

            # Wait before next retry (except last attempt)
            if attempt_num < max_retries:
                delay = backoff_delays[attempt_num - 1]
                time.sleep(delay)

        # All retries exhausted — try fallbacks
        last_error = attempts[-1].error if attempts else "unknown"

        if use_fallback:
            for fallback_agent in self._get_fallbacks(agent_id):
                attempt = TaskAttempt(
                    task_id=task_id,
                    agent_id=fallback_agent,
                    attempt_number=len(attempts) + 1,
                    started_at=time.time(),
                )
                t0 = time.perf_counter()
                result, error = self._run_with_timeout(fn, args, kwargs, timeout_s)
                duration_ms = int((time.perf_counter() - t0) * 1000)
                attempt.duration_ms = duration_ms

                if error == "__timeout__":
                    attempt.status = "timeout"
                    attempt.error = f"Fallback timed out after {timeout_s}s"
                elif error:
                    attempt.status = "failed"
                    attempt.error = error
                else:
                    attempt.status = "success"
                    attempt.result = result

                attempts.append(attempt)
                self._log_attempt(attempt)

                if attempt.status == "success":
                    total_ms = int((time.perf_counter() - global_start) * 1000)
                    return GuardedTaskResult(
                        task_id=task_id,
                        success=True,
                        result=result,
                        attempts=attempts,
                        fallback_used=True,
                        fallback_agent_id=fallback_agent,
                        total_duration_ms=total_ms,
                    )

        total_ms = int((time.perf_counter() - global_start) * 1000)
        return GuardedTaskResult(
            task_id=task_id,
            success=False,
            error=last_error,
            attempts=attempts,
            total_duration_ms=total_ms,
        )

    def _run_with_timeout(
        self,
        fn: Callable,
        args: tuple,
        kwargs: dict,
        timeout_s: int,
    ) -> tuple[Any, str]:
        """
        Run fn(*args, **kwargs) in a thread with timeout.
        Returns (result, "") on success, (None, error_str) on failure/timeout.
        """
        result_holder: list = [None]
        error_holder: list = [""]

        def _target():
            try:
                result_holder[0] = fn(*args, **kwargs)
            except Exception as e:
                error_holder[0] = str(e)

        t = threading.Thread(target=_target, daemon=True)
        t.start()
        t.join(timeout=timeout_s)

        if t.is_alive():
            # Thread still running — timed out
            return None, "__timeout__"

        if error_holder[0]:
            return None, error_holder[0]

        return result_holder[0], ""

    def _get_fallbacks(self, agent_id: str) -> list[str]:
        """Return ordered fallback agent IDs for given agent."""
        return self.FALLBACK_MAP.get(agent_id, [])

    def _log_attempt(self, attempt: TaskAttempt) -> None:
        """Append JSON line to orchestration_log.jsonl, thread-safe."""
        try:
            self.workspace_dir.mkdir(parents=True, exist_ok=True)
            entry = {
                "task_id": attempt.task_id,
                "agent_id": attempt.agent_id,
                "attempt_number": attempt.attempt_number,
                "started_at": attempt.started_at,
                "status": attempt.status,
                "error": attempt.error,
                "duration_ms": attempt.duration_ms,
            }
            line = json.dumps(entry) + "\n"
            with self._lock:
                with open(self._log_path, "a", encoding="utf-8") as f:
                    f.write(line)
        except Exception:
            pass  # fail-open

    def get_recent_failures(self, n: int = 20) -> list[dict]:
        """Read last N lines of log file, filter status=='failed'|'timeout'."""
        try:
            if not self._log_path.exists():
                return []

            with open(self._log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # Read last 200 lines max, then filter
            recent_lines = lines[-200:]
            failures = []
            for line in recent_lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("status") in ("failed", "timeout"):
                        failures.append(entry)
                except Exception:
                    _silent_log.debug("suppressed_exception", src='orchestration_guard.py')

            return failures[-n:]
        except Exception:
            return []


_guard: OrchestrationGuard | None = None


def get_guard() -> OrchestrationGuard:
    global _guard
    if _guard is None:
        _guard = OrchestrationGuard()
    return _guard
