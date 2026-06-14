"""
BEA — Objective Primitives (sections 4, 8)
Persistent objective tracking and portfolio management.
"""
from __future__ import annotations

import os
import time
import structlog
from dataclasses import asdict, dataclass, field
from typing import Optional

logger = structlog.get_logger("bea.operating_primitives")
log = logger


# ═══════════════════════════════════════════════════════════════
# 4. OBJECTIVE PERSISTENCE
# ═══════════════════════════════════════════════════════════════

@dataclass
class PersistentObjective:
    """A multi-session objective that spans multiple missions."""
    objective_id: str = ""
    title: str = ""
    description: str = ""
    mission_type: str = ""
    status: str = "active"  # active, paused, completed, failed
    created_at: float = 0.0
    updated_at: float = 0.0
    missions: list = field(default_factory=list)  # mission_ids
    total_missions: int = 0
    successful_missions: int = 0
    current_strategy: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def success_rate(self) -> float:
        return self.successful_missions / max(self.total_missions, 1)

    @property
    def is_active(self) -> bool:
        return self.status == "active"


class ObjectiveTracker:
    """Track multi-session objectives. Persists to disk."""
    MAX_OBJECTIVES = 50
    PERSIST_FILE = "workspace/objectives.json"

    def __init__(self, persist_path: Optional[str] = None):
        self._objectives: dict[str, PersistentObjective] = {}
        self._persist_path = persist_path or self.PERSIST_FILE
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            self.load()
            self._loaded = True

    def create(self, title: str, description: str = "", mission_type: str = "") -> PersistentObjective:
        """Create a new persistent objective."""
        self._ensure_loaded()
        import uuid
        obj = PersistentObjective(
            objective_id=str(uuid.uuid4())[:8],
            title=title[:200],
            description=description[:500],
            mission_type=mission_type,
            status="active",
            created_at=time.time(),
            updated_at=time.time(),
        )
        # Evict oldest if at capacity
        if len(self._objectives) >= self.MAX_OBJECTIVES:
            oldest = min(self._objectives.values(), key=lambda o: o.updated_at)
            del self._objectives[oldest.objective_id]
        self._objectives[obj.objective_id] = obj
        self.save()
        return obj

    def record_mission(self, objective_id: str, mission_id: str, success: bool):
        """Record a mission result against an objective."""
        self._ensure_loaded()
        obj = self._objectives.get(objective_id)
        if not obj:
            return
        obj.missions.append(mission_id)
        obj.total_missions += 1
        if success:
            obj.successful_missions += 1
        obj.updated_at = time.time()
        # Keep missions list bounded
        if len(obj.missions) > 100:
            obj.missions = obj.missions[-100:]
        self.save()

    def complete(self, objective_id: str):
        self._ensure_loaded()
        obj = self._objectives.get(objective_id)
        if obj:
            obj.status = "completed"
            obj.updated_at = time.time()
            self.save()

    def get(self, objective_id: str) -> Optional[PersistentObjective]:
        self._ensure_loaded()
        return self._objectives.get(objective_id)

    def list_active(self) -> list[PersistentObjective]:
        self._ensure_loaded()
        return [o for o in self._objectives.values() if o.is_active]

    def get_dashboard(self) -> dict:
        self._ensure_loaded()
        active = [o for o in self._objectives.values() if o.status == "active"]
        completed = [o for o in self._objectives.values() if o.status == "completed"]
        return {
            "total": len(self._objectives),
            "active": len(active),
            "completed": len(completed),
            "avg_success_rate": round(
                sum(o.success_rate for o in self._objectives.values())
                / max(len(self._objectives), 1), 3
            ),
            "objectives": [o.to_dict() for o in sorted(
                self._objectives.values(), key=lambda o: o.updated_at, reverse=True
            )[:20]],
        }

    def save(self):
        try:
            import json
            os.makedirs(os.path.dirname(self._persist_path) or ".", exist_ok=True)
            data = {oid: o.to_dict() for oid, o in self._objectives.items()}
            with open(self._persist_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning("objective_save_failed: %s", str(e)[:80])

    def load(self):
        import json
        if not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path) as f:
                data = json.load(f)
            for oid, d in data.items():
                obj = PersistentObjective(**{k: v for k, v in d.items()
                                            if k in PersistentObjective.__dataclass_fields__})
                self._objectives[oid] = obj
            logger.info("objectives_loaded: %d", len(self._objectives))
        except Exception as e:
            logger.warning("objective_load_failed: %s", str(e)[:80])


# Singleton
_tracker: Optional[ObjectiveTracker] = None

def get_objective_tracker() -> ObjectiveTracker:
    global _tracker
    if _tracker is None:
        _tracker = ObjectiveTracker()
    return _tracker


# ═══════════════════════════════════════════════════════════════
# 8. OBJECTIVE PORTFOLIO MANAGEMENT
# ═══════════════════════════════════════════════════════════════

OBJECTIVE_DOMAINS = [
    "product_creation", "market_research", "automation",
    "content_generation", "process_optimization", "general",
]


class ObjectivePortfolio:
    """Manages a portfolio of objectives with economic tracking."""

    def __init__(self, tracker: Optional[ObjectiveTracker] = None):
        self._tracker = tracker or get_objective_tracker()

    def get_portfolio_summary(self) -> dict:
        """Full portfolio status."""
        objectives = list(self._tracker._objectives.values())
        active = [o for o in objectives if o.status == "active"]
        by_domain = {}
        for o in objectives:
            d = o.mission_type or "general"
            by_domain.setdefault(d, []).append(o)

        total_missions = sum(o.total_missions for o in objectives)
        total_success = sum(o.successful_missions for o in objectives)

        return {
            "total_objectives": len(objectives),
            "active": len(active),
            "by_domain": {d: len(objs) for d, objs in by_domain.items()},
            "total_missions": total_missions,
            "overall_success_rate": round(total_success / max(total_missions, 1), 3),
            "stalled": [o.to_dict() for o in self.detect_stalled()],
            "top_priority": [o.to_dict() for o in self.prioritize()[:5]],
        }

    def prioritize(self) -> list[PersistentObjective]:
        """Rank active objectives by economic priority."""
        active = self._tracker.list_active()
        scored = []
        for obj in active:
            # Score: success_rate × recency × inverse_age
            age_days = (time.time() - obj.created_at) / 86400
            recency = 1.0 / max(1, (time.time() - obj.updated_at) / 3600)  # hours since update
            score = obj.success_rate * 0.4 + min(recency, 1.0) * 0.3 + (1 / max(age_days, 1)) * 0.3
            scored.append((score, obj))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [obj for _, obj in scored]

    def detect_stalled(self, stale_hours: float = 48) -> list[PersistentObjective]:
        """Find objectives with no progress in stale_hours."""
        stale_threshold = time.time() - (stale_hours * 3600)
        return [
            o for o in self._tracker.list_active()
            if o.updated_at < stale_threshold
        ]

    def suggest_termination(self) -> list[dict]:
        """Suggest objectives that should be terminated (low value, stalled)."""
        suggestions = []
        for obj in self._tracker.list_active():
            if obj.total_missions >= 5 and obj.success_rate < 0.2:
                suggestions.append({
                    "objective_id": obj.objective_id,
                    "title": obj.title,
                    "reason": f"Low success rate ({obj.success_rate:.0%}) after {obj.total_missions} missions",
                    "recommendation": "terminate",
                })
            elif obj.total_missions >= 10 and obj.success_rate < 0.4:
                suggestions.append({
                    "objective_id": obj.objective_id,
                    "title": obj.title,
                    "reason": f"Declining returns ({obj.success_rate:.0%}) after {obj.total_missions} missions",
                    "recommendation": "pivot",
                })
        return suggestions

    def allocate_slots(self, total_slots: int = 5) -> list[dict]:
        """Allocate execution slots to highest-priority objectives."""
        prioritized = self.prioritize()
        allocations = []
        for i, obj in enumerate(prioritized[:total_slots]):
            allocations.append({
                "objective_id": obj.objective_id,
                "title": obj.title,
                "slot": i + 1,
                "success_rate": obj.success_rate,
            })
        return allocations
