"""
core/planning/plan_serializer.py — Serialize and persist execution plans.

Plans are stored as JSON files in workspace/plans/.
Supports list, load, save, and history retrieval.
"""
from __future__ import annotations

import os
import time
import threading
import structlog
from pathlib import Path

from core.planning.execution_plan import ExecutionPlan, PlanStatus

log = structlog.get_logger("planning.serializer")

_WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", "workspace"))
_PLANS_DIR = _WORKSPACE / "plans"


class PlanStore:
    """Thread-safe persistent plan store."""

    def __init__(self, persist_dir: str | Path | None = None):
        self._lock = threading.RLock()
        self._dir = Path(persist_dir) if persist_dir else _PLANS_DIR
        self._plans: dict[str, ExecutionPlan] = {}

    def save(self, plan: ExecutionPlan) -> str:
        """Save or update a plan."""
        plan.updated_at = time.time()
        with self._lock:
            self._plans[plan.plan_id] = plan
        self._persist(plan)
        return plan.plan_id

    def get(self, plan_id: str) -> ExecutionPlan | None:
        with self._lock:
            return self._plans.get(plan_id)

    def list_all(self, status: str | None = None) -> list[dict]:
        """List all plans with optional status filter."""
        with self._lock:
            plans = list(self._plans.values())
        if status:
            plans = [p for p in plans if p.status.value == status]
        return [p.to_dict() for p in sorted(plans, key=lambda x: x.created_at, reverse=True)]

    def list_active(self) -> list[dict]:
        """List non-terminal plans."""
        terminal = {PlanStatus.COMPLETED, PlanStatus.FAILED, PlanStatus.CANCELLED}
        with self._lock:
            return [p.to_dict() for p in self._plans.values() if p.status not in terminal]

    def cancel(self, plan_id: str) -> bool:
        """Cancel a plan if not already terminal."""
        with self._lock:
            plan = self._plans.get(plan_id)
            if not plan:
                return False
            if plan.status in {PlanStatus.COMPLETED, PlanStatus.FAILED, PlanStatus.CANCELLED}:
                return False
            plan.status = PlanStatus.CANCELLED
            plan.updated_at = time.time()
        self._persist(plan)
        return True

    def approve(self, plan_id: str, decided_by: str = "operator", reason: str = "") -> bool:
        """Approve a plan that is awaiting approval."""
        with self._lock:
            plan = self._plans.get(plan_id)
            if not plan:
                return False
            if plan.status != PlanStatus.AWAITING_APPROVAL:
                return False
            plan.status = PlanStatus.APPROVED
            plan.approval = {
                "approved": True,
                "decided_by": decided_by,
                "reason": reason,
                "timestamp": time.time(),
            }
            plan.updated_at = time.time()
        self._persist(plan)
        return True

    def stats(self) -> dict:
        with self._lock:
            plans = list(self._plans.values())
        by_status = {}
        for p in plans:
            by_status[p.status.value] = by_status.get(p.status.value, 0) + 1
        return {
            "total": len(plans),
            "by_status": by_status,
        }

    def _persist(self, plan: ExecutionPlan) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            path = self._dir / f"{plan.plan_id}.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(plan.to_json(), "utf-8")
            tmp.replace(path)
        except Exception as e:
            log.debug("plan_persist_failed", plan_id=plan.plan_id, err=str(e)[:80])

    def load_from_disk(self) -> int:
        """Load persisted plans from disk."""
        count = 0
        if not self._dir.is_dir():
            return 0
        for f in self._dir.glob("plan-*.json"):
            try:
                plan = ExecutionPlan.from_json(f.read_text("utf-8"))
                with self._lock:
                    self._plans[plan.plan_id] = plan
                count += 1
            except Exception as e:
                log.debug("plan_load_failed", path=str(f), err=str(e)[:80])
        return count


# ── Singleton ─────────────────────────────────────────────────

_store: PlanStore | None = None
_store_lock = threading.Lock()


def get_plan_store() -> PlanStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = PlanStore()
    return _store
