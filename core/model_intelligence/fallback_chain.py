"""
core/model_intelligence/fallback_chain.py — Dynamic budget-aware model fallback chains.

Builds ordered lists of models to try for each task class and budget mode.
Tracks which models have failed for which tasks (in-memory).

Design:
  - Chain order: selected model → budget-specific fallback → absolute fallback
  - Failed model tracking per task (resets on restart)
  - Min 2 models in any chain (always has absolute fallback)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import structlog

log = structlog.get_logger("model_intelligence.fallback_chain")

# Absolute fallback — always available, cheapest
_ABSOLUTE_FALLBACK = "openai/gpt-4o-mini"

# Budget-differentiated fallback models
BUDGET_FALLBACKS: dict[str, dict[str, str]] = {
    "budget": {
        "cheap_simple": "openai/gpt-4o-mini",
        "structured_reasoning": "openai/gpt-4o-mini",
        "business_reasoning": "openai/gpt-4o-mini",
        "coding": "openai/gpt-4o-mini",
        "copywriting": "openai/gpt-4o-mini",
        "long_context": "google/gemini-2.5-flash-lite",
        "high_accuracy_critical": "openai/gpt-4o-mini",
        "fallback_only": "openai/gpt-4o-mini",
    },
    "normal": {
        "cheap_simple": "openai/gpt-4o-mini",
        "structured_reasoning": "anthropic/claude-sonnet-4.5",
        "business_reasoning": "anthropic/claude-sonnet-4.5",
        "coding": "anthropic/claude-sonnet-4.5",
        "copywriting": "anthropic/claude-sonnet-4.5",
        "long_context": "google/gemini-2.5-flash-lite",
        "high_accuracy_critical": "anthropic/claude-sonnet-4.5",
        "fallback_only": "openai/gpt-4o-mini",
    },
    "critical": {
        "cheap_simple": "openai/gpt-4o-mini",
        "structured_reasoning": "anthropic/claude-sonnet-4.5",
        "business_reasoning": "anthropic/claude-sonnet-4.5",
        "coding": "anthropic/claude-sonnet-4.5",
        "copywriting": "anthropic/claude-sonnet-4.5",
        "long_context": "anthropic/claude-sonnet-4.5",
        "high_accuracy_critical": "anthropic/claude-sonnet-4.5",
        "fallback_only": "openai/gpt-4o-mini",
    },
}


@dataclass
class FallbackChain:
    """
    Ordered model chain for a specific task class and budget mode.

    Provides next_model() to iterate through the chain, skipping
    already-failed models.
    """
    task_class: str
    budget_mode: str
    chain: list[str] = field(default_factory=list)
    _failed: set[str] = field(default_factory=set, repr=False)

    def next_model(self, failed_models: set[str] | None = None) -> str | None:
        """Return next model in chain that hasn't failed. None if exhausted."""
        skip = self._failed | (failed_models or set())
        for model in self.chain:
            if model not in skip:
                return model
        return None

    def record_failure(self, model_id: str) -> None:
        """Record that a model failed for this chain."""
        self._failed.add(model_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_class": self.task_class,
            "budget_mode": self.budget_mode,
            "chain": self.chain,
            "failed": list(self._failed),
        }


class FallbackChainManager:
    """
    Builds and manages fallback chains per task class.

    Tracks model failures in-memory (resets on restart).
    """

    def __init__(self) -> None:
        self._failure_log: dict[str, set[str]] = {}  # task_class → set of failed model_ids

    def get_chain(
        self, task_class: str, budget_mode: str = "normal", primary_model: str | None = None
    ) -> FallbackChain:
        """
        Build ordered fallback chain for a task.

        Order:
          1. primary_model (if provided, from selector)
          2. Budget-specific fallback for this task class
          3. Absolute fallback (gpt-4o-mini)

        Deduplicates while preserving order.
        """
        if budget_mode not in BUDGET_FALLBACKS:
            budget_mode = "normal"

        chain: list[str] = []
        seen: set[str] = set()

        # 1. Primary model from selector
        if primary_model and primary_model not in seen:
            chain.append(primary_model)
            seen.add(primary_model)

        # 2. Budget-specific fallback
        budget_fb = BUDGET_FALLBACKS[budget_mode].get(task_class, _ABSOLUTE_FALLBACK)
        if budget_fb not in seen:
            chain.append(budget_fb)
            seen.add(budget_fb)

        # 3. Absolute fallback
        if _ABSOLUTE_FALLBACK not in seen:
            chain.append(_ABSOLUTE_FALLBACK)
            seen.add(_ABSOLUTE_FALLBACK)

        fb = FallbackChain(
            task_class=task_class,
            budget_mode=budget_mode,
            chain=chain,
        )
        # Apply known failures
        for model_id in self._failure_log.get(task_class, set()):
            fb.record_failure(model_id)

        return fb

    def record_failure(self, task_class: str, model_id: str) -> None:
        """Record that a model failed for a task class."""
        self._failure_log.setdefault(task_class, set()).add(model_id)

    def get_stats(self) -> dict[str, list[str]]:
        return {
            task: list(models)
            for task, models in self._failure_log.items()
        }


# Singleton
_manager: FallbackChainManager | None = None


def get_fallback_manager() -> FallbackChainManager:
    global _manager
    if _manager is None:
        _manager = FallbackChainManager()
    return _manager
