"""
core/planning/learning_memory.py — Execution learning memory for mission improvement.

Supplements ExecutionMemory (execution_memory.py) with learning features:
goal similarity search, best-model-per-skill tracking, retry recommendations.

Design:
  - Singleton via get_learning_memory()
  - JSON persistence at workspace/data/learning_memory.json
  - Goal similarity via keyword Jaccard (threshold 0.3)
  - Capped at 500 missions, 2000 steps (FIFO eviction)
  - All operations fail-open
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
import structlog

log = structlog.get_logger("planning.learning_memory")

_MAX_MISSIONS = 500
_MAX_STEPS = 2000
_SIMILARITY_THRESHOLD = 0.3


@dataclass
class MissionStrategy:
    """Recommended strategy based on past successful missions."""
    playbook_id: str
    budget_mode: str
    model_recommendations: dict[str, str] = field(default_factory=dict)
    expected_quality: float = 0.0
    expected_duration_ms: float = 0.0
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """Keyword Jaccard similarity between two texts."""
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union) if union else 0.0


class LearningMemory:
    """
    Persistent learning memory for mission improvement.

    Records outcomes and provides recommendations for future missions.
    Complements ExecutionMemory — focused on learning, not history.
    """

    def __init__(self, data_dir: str | Path | None = None):
        if data_dir:
            self._data_dir = Path(data_dir)
        else:
            self._data_dir = Path("workspace/data")
        self._file = self._data_dir / "learning_memory.json"
        self._missions: list[dict] = []
        self._steps: list[dict] = []
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            if self._file.exists():
                data = json.loads(self._file.read_text())
                self._missions = data.get("missions", [])
                self._steps = data.get("steps", [])
        except Exception as e:
            log.debug("learning_memory_load_failed", err=str(e)[:60])

    def _save(self) -> None:
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            tmp = self._file.with_suffix(".tmp")
            tmp.write_text(json.dumps({
                "missions": self._missions[-_MAX_MISSIONS:],
                "steps": self._steps[-_MAX_STEPS:],
                "version": 1,
                "updated_at": time.time(),
            }, default=str))
            tmp.replace(self._file)
        except Exception as e:
            log.debug("learning_memory_save_failed", err=str(e)[:60])

    def record_mission(
        self, mission_id: str, goal: str, playbook_id: str,
        success: bool, quality_score: float = 0.0,
        model_used: str = "", cost: float = 0.0, duration_ms: float = 0.0,
    ) -> None:
        self._ensure_loaded()
        self._missions.append({
            "mission_id": mission_id, "goal": goal, "playbook_id": playbook_id,
            "success": success, "quality_score": quality_score,
            "model_used": model_used, "cost": cost, "duration_ms": duration_ms,
            "timestamp": time.time(),
        })
        if len(self._missions) > _MAX_MISSIONS:
            self._missions = self._missions[-_MAX_MISSIONS:]
        self._save()

    def record_step_outcome(
        self, step_id: str, skill_id: str, model_used: str = "",
        success: bool = True, quality_score: float = 0.0,
        retry_count: int = 0, issues: list[str] | None = None,
    ) -> None:
        self._ensure_loaded()
        self._steps.append({
            "step_id": step_id, "skill_id": skill_id,
            "model_used": model_used, "success": success,
            "quality_score": quality_score, "retry_count": retry_count,
            "issues": issues or [], "timestamp": time.time(),
        })
        if len(self._steps) > _MAX_STEPS:
            self._steps = self._steps[-_MAX_STEPS:]
        self._save()

    def get_strategy_for_goal(self, goal: str) -> MissionStrategy | None:
        self._ensure_loaded()
        best_match, best_sim = None, 0.0
        for m in self._missions:
            if not m.get("success"):
                continue
            sim = _jaccard_similarity(goal, m.get("goal", ""))
            if sim > best_sim and sim >= _SIMILARITY_THRESHOLD:
                best_sim = sim
                best_match = m
        if not best_match:
            return None

        model_recs: dict[str, str] = {}
        for s in self._steps:
            if s.get("success") and s.get("model_used"):
                sid = s.get("skill_id", "")
                if sid and sid not in model_recs:
                    model_recs[sid] = s["model_used"]

        similar_count = sum(
            1 for m in self._missions
            if m.get("success") and _jaccard_similarity(goal, m.get("goal", "")) >= _SIMILARITY_THRESHOLD
        )

        return MissionStrategy(
            playbook_id=best_match.get("playbook_id", ""),
            budget_mode="normal",
            model_recommendations=model_recs,
            expected_quality=best_match.get("quality_score", 0.0),
            expected_duration_ms=best_match.get("duration_ms", 0.0),
            confidence=min(1.0, similar_count / 5.0),
        )

    def get_best_model_for_skill(self, skill_id: str) -> str | None:
        self._ensure_loaded()
        model_scores: dict[str, list[float]] = {}
        for s in self._steps:
            if s.get("skill_id") == skill_id and s.get("success") and s.get("model_used"):
                model_scores.setdefault(s["model_used"], []).append(s.get("quality_score", 0.0))
        if not model_scores:
            return None
        return max(model_scores.keys(), key=lambda m: sum(model_scores[m]) / len(model_scores[m]))

    def get_retry_recommendation(self, skill_id: str, error_type: str) -> str | None:
        self._ensure_loaded()
        for s in reversed(self._steps):
            if s.get("skill_id") == skill_id and s.get("success") and s.get("retry_count", 0) > 0:
                if any(error_type.lower() in i.lower() for i in s.get("issues", [])):
                    return "retry_with_adaptation"
        return None

    def get_stats(self) -> dict:
        self._ensure_loaded()
        total = len(self._missions)
        successful = sum(1 for m in self._missions if m.get("success"))
        skill_counts: dict[str, int] = {}
        for s in self._steps:
            sid = s.get("skill_id", "unknown")
            skill_counts[sid] = skill_counts.get(sid, 0) + 1
        model_counts: dict[str, int] = {}
        for s in self._steps:
            mid = s.get("model_used", "")
            if mid:
                model_counts[mid] = model_counts.get(mid, 0) + 1

        return {
            "total_missions": total,
            "success_rate": successful / total if total else 0.0,
            "total_steps": len(self._steps),
            "avg_quality": sum(m.get("quality_score", 0) for m in self._missions) / total if total else 0.0,
            "top_skills": sorted(skill_counts.items(), key=lambda x: -x[1])[:5],
            "top_models": sorted(model_counts.items(), key=lambda x: -x[1])[:5],
        }


_instance: LearningMemory | None = None


def get_learning_memory() -> LearningMemory:
    global _instance
    if _instance is None:
        _instance = LearningMemory()
    return _instance
