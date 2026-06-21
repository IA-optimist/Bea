"""
core/evaluation/model_router.py — Minimal model class router for Béa.

Chooses a model *class* (not a provider) based on task type, mission context,
and past model_result memories. The actual provider mapping is left to the
LLM factory so this module stays dependency-free.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.memory.memory_item import MemoryItemType
from core.memory.operational_memory import OperationalMemoryStore, get_operational_memory_store


class ModelClass(str, Enum):
    """Model capability classes used by Béa."""

    SMALL_FAST = "SMALL_FAST"              # summary, classification, simple recall
    MEDIUM_TOOL_USE = "MEDIUM_TOOL_USE"    # patch simple, tool calls
    STRONG_REASONING = "STRONG_REASONING"  # complex bugs, refactoring
    STRONG_CODE_REVIEW = "STRONG_CODE_REVIEW"  # security, self-improvement critical
    LOCAL_FALLBACK = "LOCAL_FALLBACK"      # offline / cost-limited


# Default mapping from task_type keywords to model class
_TASK_RULES: dict[ModelClass, tuple[str, ...]] = {
    ModelClass.SMALL_FAST: ("summary", "classify", "classifier", "retrieve", "search", "memory", "recall"),
    ModelClass.MEDIUM_TOOL_USE: ("patch", "simple", "tool", "edit", "modify", "apply"),
    ModelClass.STRONG_REASONING: ("bug", "fix", "refactor", "complex", "reason", "debug"),
    ModelClass.STRONG_CODE_REVIEW: ("review", "security", "self-improvement", "critical", "promote", "sign"),
    ModelClass.LOCAL_FALLBACK: ("offline", "local", "cheap", "budget"),
}


_STRONG_CODE_REVIEW_KEYWORDS: tuple[str, ...] = ("security", "self-improvement", "critical", "review")


def _class_for_task(task_type: str) -> ModelClass:
    tt = task_type.lower()
    # Security / critical wins over everything
    if any(k in tt for k in _TASK_RULES[ModelClass.STRONG_CODE_REVIEW]):
        return ModelClass.STRONG_CODE_REVIEW
    if any(k in tt for k in _TASK_RULES[ModelClass.LOCAL_FALLBACK]):
        return ModelClass.LOCAL_FALLBACK
    if any(k in tt for k in _TASK_RULES[ModelClass.STRONG_REASONING]):
        return ModelClass.STRONG_REASONING
    if any(k in tt for k in _TASK_RULES[ModelClass.MEDIUM_TOOL_USE]):
        return ModelClass.MEDIUM_TOOL_USE
    if any(k in tt for k in _TASK_RULES[ModelClass.SMALL_FAST]):
        return ModelClass.SMALL_FAST
    return ModelClass.MEDIUM_TOOL_USE  # default safe middle ground


@dataclass
class RouterDecision:
    """Output of the model router."""

    model_class: ModelClass
    reason: str
    memory_evidence: list[dict[str, Any]] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.memory_evidence is None:
            self.memory_evidence = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_class": self.model_class.value,
            "reason": self.reason,
            "memory_evidence": self.memory_evidence,
        }


# Upgrade path when base class is historically failing
_UPGRADE: dict[ModelClass, ModelClass] = {
    ModelClass.SMALL_FAST: ModelClass.MEDIUM_TOOL_USE,
    ModelClass.MEDIUM_TOOL_USE: ModelClass.STRONG_REASONING,
    ModelClass.STRONG_REASONING: ModelClass.STRONG_CODE_REVIEW,
    ModelClass.STRONG_CODE_REVIEW: ModelClass.STRONG_CODE_REVIEW,
    ModelClass.LOCAL_FALLBACK: ModelClass.LOCAL_FALLBACK,
}


class ModelRouter:
    """
    Choose a model class for a mission.

    Reads past model_result memories. If a class historically fails on this
    task_type, it is deprioritized. If a class succeeds often, it is favored.
    """

    def __init__(self, store: OperationalMemoryStore | None = None) -> None:
        self.store = store or get_operational_memory_store()
        self._current_task = ""

    def choose(
        self,
        task_type: str,
        protected_files: list[str] | None = None,
        budget_cloud: bool = True,
    ) -> RouterDecision:
        """Choose the model class for a task."""
        protected_files = protected_files or []

        # Strong override: protected / security files → code review class
        is_security = any(k in task_type.lower() for k in _STRONG_CODE_REVIEW_KEYWORDS)
        if protected_files or is_security:
            # Still allow local fallback if cloud budget is explicitly off
            if not budget_cloud:
                return RouterDecision(
                    ModelClass.LOCAL_FALLBACK,
                    "Cloud budget disabled; local fallback requested for protected task.",
                )
            return RouterDecision(
                ModelClass.STRONG_CODE_REVIEW,
                "Protected files or security-critical task require strong code review.",
            )

        # No cloud budget → local fallback
        if not budget_cloud:
            return RouterDecision(
                ModelClass.LOCAL_FALLBACK,
                "Cloud budget disabled.",
            )

        base_class = _class_for_task(task_type)
        self._current_task = task_type

        # Adjust based on history
        history = self._history_for_task(task_type)
        if history:
            best, deprioritized = self._best_class_from_history(history)
            if best and best != base_class:
                return RouterDecision(
                    best,
                    f"Base rule selected {base_class.value}, but past model_result memories favor {best.value}.",
                    memory_evidence=history,
                )
            if base_class.value in deprioritized:
                upgraded = _UPGRADE.get(base_class, base_class)
                if upgraded != base_class:
                    return RouterDecision(
                        upgraded,
                        f"{base_class.value} historically fails on this task type; upgraded to {upgraded.value}.",
                        memory_evidence=history,
                    )

        return RouterDecision(
            base_class,
            f"Task type '{task_type}' matches {base_class.value} rule.",
            memory_evidence=history,
        )

    def _history_for_task(self, task_type: str) -> list[dict[str, Any]]:
        """Fetch model_result memories relevant to this task_type."""
        results = self.store.ranked_search(
            type=MemoryItemType.MODEL_RESULT,
            query=task_type,
            include_obsolete=False,
            limit=50,
        )
        history: list[dict[str, Any]] = []
        task_lower = task_type.lower()
        for item, _ in results:
            recorded = str(item.metadata.get("task_type", "")).lower()
            tag_match = task_lower in [t.lower() for t in item.tags]
            type_match = bool(recorded) and (recorded in task_lower or task_lower in recorded)
            if not (type_match or tag_match):
                continue
            history.append({
                "id": item.id,
                "model": item.metadata.get("model", ""),
                "model_class": item.metadata.get("model_class", ""),
                "success": item.metadata.get("success", False),
                "duration_ms": item.metadata.get("duration_ms", 0),
                "cost_estimate": item.metadata.get("cost_estimate") or 0.0,
            })
        return history

    def _best_class_from_history(self, history: list[dict[str, Any]]) -> tuple[ModelClass | None, set[str]]:
        """Return (best class, deprioritized classes) from history."""
        if len(history) < 2:
            return None, set()
        stats: dict[str, dict[str, float]] = {}
        for h in history:
            cls = h.get("model_class", "")
            if not cls:
                continue
            if cls not in stats:
                stats[cls] = {"total": 0.0, "success": 0.0, "cost": 0.0}
            weight = 1.0  # future: recency weighting
            stats[cls]["total"] += weight
            if h.get("success"):
                stats[cls]["success"] += weight
            stats[cls]["cost"] += h.get("cost_estimate", 0.0) or 0.0

        min_samples = 2.0
        deprioritized: set[str] = set()
        for cls, s in stats.items():
            if s["total"] >= 3 and s["success"] / s["total"] < 0.34:
                deprioritized.add(cls)

        best_class: str | None = None
        best_score = float("-inf")
        for cls, s in stats.items():
            if s["total"] < min_samples:
                continue
            success_rate = s["success"] / s["total"]
            # Penalize high cost per sample above $0.02
            avg_cost = s["cost"] / s["total"]
            cost_penalty = max(0.0, (avg_cost - 0.02) * 10.0)
            # Favor LOCAL_FALLBACK for simple tasks when it succeeds
            local_boost = 0.0
            if cls == ModelClass.LOCAL_FALLBACK.value and success_rate >= 0.6:
                if any(k in self._current_task.lower() for k in _TASK_RULES[ModelClass.SMALL_FAST]):
                    local_boost = 0.3
            score = success_rate - cost_penalty + local_boost
            if score > best_score and success_rate >= 0.5:
                best_score = score
                best_class = cls

        if best_class in deprioritized:
            best_class = None

        try:
            return (ModelClass(best_class) if best_class else None), deprioritized
        except ValueError:
            return None, deprioritized
