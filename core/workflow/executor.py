"""
BEA Workflow — Execution Engine (Phase 2)
==========================================
WorkflowEngine: create, execute, pause, resume, cancel multi-step workflows.
Dataclasses (WorkflowStep, WorkflowExecution) live in state.py.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Callable, Optional

import structlog

from .boundaries import (
    MAX_CONCURRENT_WORKFLOWS,
    MAX_WORKFLOW_DEPTH,
    MAX_RETRY_CYCLES,
    MAX_WORKFLOW_HISTORY,
)
from .state import WorkflowExecution, WorkflowStep

logger = structlog.get_logger("bea.workflow_runtime")


class WorkflowEngine:
    """
    Executes persistent multi-step workflows with resume capability.
    Bounded: MAX_CONCURRENT_WORKFLOWS active, MAX_WORKFLOW_HISTORY total.
    """

    PERSIST_FILE = "workspace/workflow_executions.json"

    def __init__(self, persist_path: Optional[str] = None):
        self._executions: dict[str, WorkflowExecution] = {}
        self._persist_path = persist_path or self.PERSIST_FILE
        self._loaded = False
        self._step_executors: dict[str, Callable] = {}

    def _ensure_loaded(self):
        if not self._loaded:
            self.load()
            self._loaded = True

    def register_step_executor(self, action: str, executor: Callable) -> None:
        """Register a callable for a step action type."""
        self._step_executors[action] = executor

    def create_workflow(self, name: str, steps: list[dict],
                        version: int = 1, metadata: dict = None) -> WorkflowExecution:
        """Create a new workflow execution."""
        self._ensure_loaded()

        # Enforce boundaries
        active = sum(1 for e in self._executions.values()
                     if e.status in ("created", "running", "paused"))
        if active >= MAX_CONCURRENT_WORKFLOWS:
            raise ValueError(f"Max concurrent workflows reached ({MAX_CONCURRENT_WORKFLOWS})")

        if len(steps) > MAX_WORKFLOW_DEPTH:
            raise ValueError(f"Workflow too deep ({len(steps)} > {MAX_WORKFLOW_DEPTH})")

        # Build steps
        workflow_steps = []
        for i, s in enumerate(steps):
            step = WorkflowStep(
                step_id=i,
                name=s.get("name", f"step_{i}"),
                action=s.get("action", ""),
                params=s.get("params", {}),
                max_retries=min(s.get("max_retries", 3), MAX_RETRY_CYCLES),
                depends_on=s.get("depends_on", []),
            )
            workflow_steps.append(step.to_dict())

        execution = WorkflowExecution(
            execution_id=str(uuid.uuid4())[:8],
            workflow_name=name,
            version=version,
            steps=workflow_steps,
            status="created",
            created_at=time.time(),
            metadata=metadata or {},
        )

        # Evict oldest if at capacity
        if len(self._executions) >= MAX_WORKFLOW_HISTORY:
            oldest = min(self._executions.values(), key=lambda e: e.created_at)
            del self._executions[oldest.execution_id]

        self._executions[execution.execution_id] = execution
        self.save()
        return execution

    def execute_step(self, execution_id: str, step_idx: int) -> dict:
        """Execute a specific step in a workflow."""
        self._ensure_loaded()
        execution = self._executions.get(execution_id)
        if not execution:
            return {"success": False, "error": "execution not found"}

        if step_idx >= len(execution.steps):
            return {"success": False, "error": "step index out of range"}

        step = execution.steps[step_idx]
        if isinstance(step, WorkflowStep):
            step = step.to_dict()
            execution.steps[step_idx] = step

        # Check dependencies
        for dep_idx in step.get("depends_on", []):
            if dep_idx < len(execution.steps):
                dep = execution.steps[dep_idx]
                dep_status = dep.get("status") if isinstance(dep, dict) else dep.status
                if dep_status not in ("completed", "skipped"):
                    return {"success": False, "error": f"dependency step {dep_idx} not completed"}

        step["status"] = "running"
        step["started_at"] = time.time()
        execution.status = "running"
        if not execution.started_at:
            execution.started_at = time.time()
        execution.current_step = step_idx

        action = step.get("action", "")
        params = step.get("params", {})

        # Try connector first, then registered executor
        result = None
        error = ""
        success = False

        try:
            from core.connectors import CONNECTOR_REGISTRY, execute_connector
            if action in CONNECTOR_REGISTRY:
                cr = execute_connector(action, params)
                success = cr.success
                result = cr.data if cr.success else None
                error = cr.error or ""
            elif action in self._step_executors:
                r = self._step_executors[action](params)
                success = bool(r.get("success", True) if isinstance(r, dict) else r)
                result = r
                error = r.get("error", "") if isinstance(r, dict) else ""
            else:
                success = True  # No-op step (placeholder)
                result = {"action": action, "status": "no_executor_registered"}
        except Exception as e:
            error = str(e)[:200]

        if success:
            step["status"] = "completed"
            step["result"] = result
        else:
            step["retries"] = step.get("retries", 0) + 1
            if step["retries"] >= step.get("max_retries", 3):
                step["status"] = "failed"
                step["error"] = error
            else:
                step["status"] = "pending"  # Will be retried
                step["error"] = error

        step["completed_at"] = time.time()
        execution.steps[step_idx] = step

        self._update_workflow_status(execution)
        self.save()

        return {"success": success, "step": step, "error": error}

    def run_next_step(self, execution_id: str) -> dict:
        """Run the next pending step in order."""
        self._ensure_loaded()
        execution = self._executions.get(execution_id)
        if not execution:
            return {"success": False, "error": "execution not found"}

        if execution.status in ("completed", "failed", "cancelled"):
            return {"success": False, "error": f"workflow is {execution.status}"}

        if execution.status == "paused":
            return {"success": False, "error": "workflow is paused"}

        for i, step in enumerate(execution.steps):
            s = step if isinstance(step, dict) else step.to_dict()
            if s.get("status") == "pending":
                return self.execute_step(execution_id, i)

        return {"success": True, "error": "", "done": True}

    def run_all(self, execution_id: str) -> dict:
        """Run all remaining steps sequentially."""
        self._ensure_loaded()
        execution = self._executions.get(execution_id)
        if not execution:
            return {"success": False, "error": "execution not found"}

        results = []
        step_count = 0
        while step_count < MAX_WORKFLOW_DEPTH:
            r = self.run_next_step(execution_id)
            if r.get("done") or not r.get("success", True):
                results.append(r)
                break
            results.append(r)
            step_count += 1

            execution = self._executions.get(execution_id)
            if not execution or execution.status in ("completed", "failed", "cancelled", "paused"):
                break

        return {
            "execution_id": execution_id,
            "steps_run": step_count,
            "results": results,
            "final_status": execution.status if execution else "unknown",
        }

    def pause(self, execution_id: str) -> bool:
        self._ensure_loaded()
        execution = self._executions.get(execution_id)
        if execution and execution.status in ("created", "running"):
            execution.status = "paused"
            execution.paused_at = time.time()
            self.save()
            return True
        return False

    def resume(self, execution_id: str) -> bool:
        self._ensure_loaded()
        execution = self._executions.get(execution_id)
        if execution and execution.status == "paused":
            execution.status = "running"
            execution.paused_at = 0.0
            self.save()
            return True
        return False

    def cancel(self, execution_id: str) -> bool:
        self._ensure_loaded()
        execution = self._executions.get(execution_id)
        if execution and execution.status not in ("completed", "failed"):
            execution.status = "cancelled"
            execution.completed_at = time.time()
            self.save()
            return True
        return False

    def get_execution(self, execution_id: str) -> Optional[dict]:
        self._ensure_loaded()
        e = self._executions.get(execution_id)
        return e.to_dict() if e else None

    def list_executions(self, status_filter: str = "") -> list[dict]:
        self._ensure_loaded()
        execs = list(self._executions.values())
        if status_filter:
            execs = [e for e in execs if e.status == status_filter]
        return [e.to_dict() for e in sorted(execs, key=lambda e: e.created_at, reverse=True)[:50]]

    def _update_workflow_status(self, execution: WorkflowExecution) -> None:
        """Update workflow status based on step states."""
        steps = execution.steps
        all_done = all(
            (s.get("status") if isinstance(s, dict) else s.status)
            in ("completed", "skipped")
            for s in steps
        )
        any_failed = any(
            (s.get("status") if isinstance(s, dict) else s.status) == "failed"
            for s in steps
        )

        if all_done:
            execution.status = "completed"
            execution.completed_at = time.time()
        elif any_failed:
            execution.status = "failed"
            execution.completed_at = time.time()
            failed_names = [
                (s.get("name") if isinstance(s, dict) else s.name)
                for s in steps
                if (s.get("status") if isinstance(s, dict) else s.status) == "failed"
            ]
            execution.error_summary = f"Failed steps: {', '.join(failed_names)}"

        execution.total_retries = sum(
            (s.get("retries", 0) if isinstance(s, dict) else s.retries)
            for s in steps
        )

    def save(self):
        try:
            os.makedirs(os.path.dirname(self._persist_path) or ".", exist_ok=True)
            with open(self._persist_path, "w") as f:
                json.dump({k: v.to_dict() for k, v in self._executions.items()}, f, indent=2)
        except Exception as e:
            logger.warning("workflow_save_failed: %s", str(e)[:80])

    def load(self):
        if not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path) as f:
                data = json.load(f)
            for eid, d in data.items():
                self._executions[eid] = WorkflowExecution(
                    **{k: v for k, v in d.items() if k in WorkflowExecution.__dataclass_fields__}
                )
        except Exception as e:
            logger.warning("workflow_load_failed: %s", str(e)[:80])
