"""
BEA — Mission Lifecycle Tracker
======================================
Tracks every mission through its full lifecycle.

Every mission gets a LifecycleRecord that accumulates signals as
the mission progresses through stages. This creates a complete
audit trail and enables lifecycle validation.

Stages (in expected order):
1. mission_received     — mission submitted via API
2. plan_generated       — planner produced structured plan
3. agents_selected      — agent routing chose agents
4. tools_executed       — execution engine ran tool chain
5. results_evaluated    — post-mission evaluation computed
6. memory_updated       — knowledge/mission memory ingested
7. proposals_checked    — improvement detector ran

Called from:
- mission_system.submit()     — records stage 1
- planner.build_plan()        — records stage 2
- crew.select_agents()        — records stage 3
- tool_runner                 — records stage 4
- execution_engine.evaluate   — records stage 5
- mission_system.complete()   — records stages 6, 7

Exposes via /api/v3/performance/lifecycle for cockpit.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("bea.lifecycle")


@dataclass
class LifecycleRecord:
    """Complete lifecycle record for a single mission."""
    mission_id: str
    stages: dict[str, float] = field(default_factory=dict)  # stage → timestamp
    errors: list[str] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0

    def record_stage(self, stage: str) -> None:
        self.stages[stage] = time.time()

    def record_error(self, stage: str, error: str) -> None:
        self.errors.append(f"{stage}: {error[:100]}")

    @property
    def is_complete(self) -> bool:
        from core.safety_controls import EXPECTED_LIFECYCLE
        return all(s in self.stages for s in EXPECTED_LIFECYCLE)

    @property
    def coverage(self) -> float:
        from core.safety_controls import EXPECTED_LIFECYCLE
        return len(set(self.stages.keys()) & set(EXPECTED_LIFECYCLE)) / len(EXPECTED_LIFECYCLE)

    @property
    def duration_s(self) -> float:
        if self.finished_at and self.started_at:
            return self.finished_at - self.started_at
        if self.stages:
            return max(self.stages.values()) - min(self.stages.values())
        return 0.0

    def to_dict(self) -> dict:
        return {
            "mission_id": self.mission_id,
            "stages": self.stages,
            "stage_count": len(self.stages),
            "is_complete": self.is_complete,
            "coverage": round(self.coverage, 3),
            "duration_s": round(self.duration_s, 2),
            "errors": self.errors,
        }


class LifecycleTracker:
    """
    Tracks lifecycle for all missions.
    Bounded: 500 recent records.
    """

    MAX_RECORDS = 500

    def __init__(self):
        self._records: dict[str, LifecycleRecord] = {}

    def start(self, mission_id: str) -> LifecycleRecord:
        """Start tracking a mission."""
        if len(self._records) >= self.MAX_RECORDS:
            oldest = min(self._records.values(), key=lambda r: r.started_at)
            del self._records[oldest.mission_id]

        record = LifecycleRecord(mission_id=mission_id, started_at=time.time())
        record.record_stage("mission_received")
        self._records[mission_id] = record
        return record

    def record(self, mission_id: str, stage: str) -> None:
        """Record a lifecycle stage for a mission."""
        rec = self._records.get(mission_id)
        if not rec:
            rec = self.start(mission_id)
        rec.record_stage(stage)

    def record_error(self, mission_id: str, stage: str, error: str) -> None:
        """Record an error at a lifecycle stage."""
        rec = self._records.get(mission_id)
        if rec:
            rec.record_error(stage, error)

    def finish(self, mission_id: str) -> Optional[LifecycleRecord]:
        """Mark a mission as finished."""
        rec = self._records.get(mission_id)
        if rec:
            rec.finished_at = time.time()
        return rec

    def get(self, mission_id: str) -> Optional[LifecycleRecord]:
        return self._records.get(mission_id)

    def get_dashboard_data(self) -> dict:
        """Lifecycle dashboard for cockpit."""
        records = list(self._records.values())
        if not records:
            return {"total": 0, "complete": 0, "avg_coverage": 0, "recent": []}

        complete = sum(1 for r in records if r.is_complete)
        avg_coverage = sum(r.coverage for r in records) / len(records)
        errored = sum(1 for r in records if r.errors)

        # Stage completion rates
        from core.safety_controls import EXPECTED_LIFECYCLE
        stage_rates = {}
        for stage in EXPECTED_LIFECYCLE:
            count = sum(1 for r in records if stage in r.stages)
            stage_rates[stage] = round(count / max(len(records), 1), 3)

        return {
            "total": len(records),
            "complete": complete,
            "complete_rate": round(complete / max(len(records), 1), 3),
            "avg_coverage": round(avg_coverage, 3),
            "errored": errored,
            "stage_rates": stage_rates,
            "recent": [r.to_dict() for r in sorted(
                records, key=lambda r: r.started_at, reverse=True,
            )[:10]],
        }


_tracker: Optional[LifecycleTracker] = None


def get_lifecycle_tracker() -> LifecycleTracker:
    global _tracker
    if _tracker is None:
        _tracker = LifecycleTracker()
    return _tracker
