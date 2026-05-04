"""
core/skills/skill_discovery.py — AI OS Skill Discovery & Performance Tracking.

Extends existing SkillRegistry with:
- Performance scoring per skill
- Reliability tracking
- Auto-disable of unreliable skills
- Discovery of new skill patterns from missions
"""
from __future__ import annotations

import time
import structlog
from dataclasses import dataclass
from typing import Optional

from core.skills.skill_registry import SkillRegistry
from core.skills.skill_models import Skill

log = structlog.get_logger("skills.discovery")


# ── Skill Performance ────────────────────────────────────────────────────────

@dataclass
class SkillPerformance:
    """Performance metrics for a single skill."""
    skill_id: str
    total_uses: int = 0
    successes: int = 0
    failures: int = 0
    total_latency_ms: float = 0
    total_cost_usd: float = 0
    last_failure: str = ""
    last_used: float = 0
    disabled: bool = False
    disabled_reason: str = ""

    @property
    def success_rate(self) -> float:
        return self.successes / self.total_uses if self.total_uses > 0 else 0.0

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.total_uses if self.total_uses > 0 else 0.0

    @property
    def cost_per_use(self) -> float:
        return self.total_cost_usd / self.total_uses if self.total_uses > 0 else 0.0

    def score(self) -> float:
        """Composite skill score: success_rate * 0.4 + (1-latency_norm) * 0.3 + cost_efficiency * 0.3"""
        sr = self.success_rate
        # Normalize latency: 0ms=1.0, 10000ms=0.0
        latency_norm = min(1.0, self.avg_latency_ms / 10000)
        latency_score = 1.0 - latency_norm
        # Cost efficiency: cheaper is better
        cost_score = max(0, 1.0 - self.cost_per_use)
        return round(sr * 0.4 + latency_score * 0.3 + cost_score * 0.3, 3)

    def to_dict(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "total_uses": self.total_uses,
            "success_rate": round(self.success_rate, 3),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "cost_per_use": round(self.cost_per_use, 4),
            "score": self.score(),
            "disabled": self.disabled,
            "disabled_reason": self.disabled_reason,
        }


# ── Skill Discovery ─────────────────────────────────────────────────────────

# Thresholds
MIN_USES_FOR_DISABLE = 5
DISABLE_SUCCESS_RATE = 0.3  # Disable if <30% success after 5+ uses
AUTO_REENABLE_AFTER = 3600 * 24  # Re-enable after 24h for retry


class SkillDiscovery:
    """Skill performance tracking and auto-management."""

    def __init__(self, registry: SkillRegistry | None = None):
        self._registry = registry or SkillRegistry()
        self._perf: dict[str, SkillPerformance] = {}

    def record_use(self, skill_id: str, success: bool,
                   latency_ms: float = 0, cost_usd: float = 0,
                   error: str = "") -> None:
        """Record a skill usage event."""
        if skill_id not in self._perf:
            self._perf[skill_id] = SkillPerformance(skill_id=skill_id)

        p = self._perf[skill_id]
        p.total_uses += 1
        p.total_latency_ms += latency_ms
        p.total_cost_usd += cost_usd
        p.last_used = time.time()

        if success:
            p.successes += 1
        else:
            p.failures += 1
            p.last_failure = error[:200]

        # Also update the skill model
        skill = self._registry.get(skill_id)
        if skill:
            skill.record_use(success)
            self._registry.update(skill)

        # Auto-disable check
        self._check_disable(skill_id)

        log.debug("skill_use_recorded", skill=skill_id, success=success,
                  total=p.total_uses, rate=round(p.success_rate, 2))

    def _check_disable(self, skill_id: str) -> None:
        """Auto-disable skills with poor performance."""
        p = self._perf.get(skill_id)
        if not p or p.disabled:
            return
        if p.total_uses >= MIN_USES_FOR_DISABLE and p.success_rate < DISABLE_SUCCESS_RATE:
            p.disabled = True
            p.disabled_reason = f"Auto-disabled: {p.success_rate:.0%} success after {p.total_uses} uses"
            log.warning("skill_auto_disabled", skill=skill_id,
                        rate=round(p.success_rate, 2), uses=p.total_uses)

    def is_skill_enabled(self, skill_id: str) -> bool:
        """Check if a skill is enabled (or auto-re-enable after timeout)."""
        p = self._perf.get(skill_id)
        if not p:
            return True  # Unknown skill = enabled
        if not p.disabled:
            return True
        # Auto re-enable after timeout
        if p.last_used and (time.time() - p.last_used) > AUTO_REENABLE_AFTER:
            p.disabled = False
            p.disabled_reason = ""
            p.failures = 0
            p.successes = 0
            p.total_uses = 0
            log.info("skill_auto_reenabled", skill=skill_id)
            return True
        return False

    def get_performance(self, skill_id: str) -> Optional[SkillPerformance]:
        return self._perf.get(skill_id)

    def ranked_skills(self, problem_type: str = "", limit: int = 10) -> list[dict]:
        """Get skills ranked by composite score."""
        skills = self._registry.all()
        if problem_type:
            skills = [s for s in skills if s.problem_type == problem_type]

        ranked = []
        for skill in skills:
            p = self._perf.get(skill.skill_id)
            score = p.score() if p else 0.5
            enabled = self.is_skill_enabled(skill.skill_id)
            ranked.append({
                "skill_id": skill.skill_id,
                "name": skill.name,
                "problem_type": skill.problem_type,
                "score": score,
                "enabled": enabled,
                "uses": p.total_uses if p else 0,
                "success_rate": round(p.success_rate, 3) if p else 0,
            })

        ranked.sort(key=lambda x: (-x["score"], -x["uses"]))
        return ranked[:limit]

    def dashboard_stats(self) -> dict:
        """Stats for the AI OS dashboard."""
        total = self._registry.count()
        tracked = len(self._perf)
        disabled = sum(1 for p in self._perf.values() if p.disabled)
        avg_score = 0
        if tracked:
            avg_score = round(sum(p.score() for p in self._perf.values()) / tracked, 3)

        return {
            "total_skills": total,
            "tracked": tracked,
            "disabled": disabled,
            "avg_score": avg_score,
            "top_skills": self.ranked_skills(limit=5),
        }

    def discover_from_mission(self, mission_id: str, goal: str,
                              tools_used: list[str], success: bool,
                              steps_summary: str = "") -> Optional[str]:
        """Discover a new skill from a successful mission."""
        if not success:
            return None

        # Don't create duplicate skills
        existing = self._registry.find_by_tags(tools_used, limit=3)
        for s in existing:
            if s.source_mission_id == mission_id:
                return None

        skill = Skill(
            name=f"Learned: {goal[:50]}",
            description=f"Skill derived from mission {mission_id}: {goal}",
            problem_type="auto_discovered",
            tools_used=tools_used,
            tags=tools_used + ["auto_discovered"],
            confidence=0.4,  # Low initial confidence
            source_mission_id=mission_id,
        )
        sid = self._registry.add(skill)
        log.info("skill_discovered", skill_id=sid, mission=mission_id, goal=goal[:60])
        return sid


# ── Singleton ────────────────────────────────────────────────────────────────

_instance: SkillDiscovery | None = None

def get_skill_discovery() -> SkillDiscovery:
    global _instance
    if _instance is None:
        _instance = SkillDiscovery()
    return _instance
