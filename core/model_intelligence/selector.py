"""
core/model_intelligence/selector.py — Model profiling, performance tracking, and selection.

Phases 2-4: Profile models, track performance, select optimally.

Design:
  - ModelProfile: classify models by task suitability
  - ModelPerformanceMemory: track outcomes per model/task
  - ModelSelector: choose best model for task class
  - Deterministic, explainable, fail-open
  - Integrates with LLMFactory without replacing it
"""
from __future__ import annotations

import time
import json
import threading
import structlog
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = structlog.get_logger("model_intelligence.selector")


# ── Task classes ──────────────────────────────────────────────

TASK_CLASSES = [
    "cheap_simple",           # classification, formatting, extraction
    "structured_reasoning",   # business analysis, strategy
    "long_context",           # document analysis, research synthesis
    "coding",                 # code generation, review
    "copywriting",            # marketing copy, content
    "business_reasoning",     # market analysis, financial models
    "high_accuracy_critical", # safety-critical, compliance
    "fallback_only",          # emergency fallback
]

# Skill → task class mapping
SKILL_TASK_MAP: dict[str, str] = {
    "market_research.basic": "business_reasoning",
    "persona.basic": "structured_reasoning",
    "competitor.analysis": "business_reasoning",
    "positioning.basic": "structured_reasoning",
    "offer_design.basic": "structured_reasoning",
    "pricing.strategy": "business_reasoning",
    "value_proposition.design": "copywriting",
    "saas_scope.basic": "structured_reasoning",
    "strategy.reasoning": "business_reasoning",
    "growth.plan": "structured_reasoning",
    "acquisition.basic": "structured_reasoning",
    "automation_opportunity.basic": "structured_reasoning",
    "funnel.design": "structured_reasoning",
    "copywriting.basic": "copywriting",
    "landing.structure": "copywriting",
    "spec.writing": "coding",
}

# Role → task class mapping
ROLE_TASK_MAP: dict[str, str] = {
    "analyst": "business_reasoning",
    "director": "high_accuracy_critical",
    "planner": "structured_reasoning",
    "ops": "structured_reasoning",
    "research": "long_context",
    "builder": "coding",
    "improve": "coding",
    "reviewer": "coding",
    "context": "long_context",
    "fast": "cheap_simple",
    "classify": "cheap_simple",
    "route": "cheap_simple",
    "extract": "cheap_simple",
    "summarize": "cheap_simple",
    "validate": "cheap_simple",
    "format_output": "cheap_simple",
    "vision": "cheap_simple",
    "fallback": "fallback_only",
}


# ── Model Profile ────────────────────────────────────────────

@dataclass
class ModelProfile:
    """Task suitability profile for a model."""
    model_id: str
    # Suitability scores per task class (0.0-1.0)
    scores: dict[str, float] = field(default_factory=dict)
    # Metadata
    cost_tier: str = ""
    context_length: int = 0
    provider: str = ""

    @property
    def best_task(self) -> str:
        if not self.scores:
            return "fallback_only"
        return max(self.scores, key=self.scores.get)

    def score_for(self, task_class: str) -> float:
        return self.scores.get(task_class, 0.0)

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "scores": {k: round(v, 3) for k, v in self.scores.items()},
            "best_task": self.best_task,
            "cost_tier": self.cost_tier,
            "context_length": self.context_length,
            "provider": self.provider,
        }


def build_profile(entry) -> ModelProfile:
    """
    Build a ModelProfile from a ModelEntry using heuristics.

    Classification rules (explainable, not ML):
      - Provider + model name → coding/reasoning capability estimate
      - Context length → long_context suitability
      - Cost tier → cheap_simple vs premium appropriateness
      - Tool support → structured_reasoning boost
    """
    model_id = entry.model_id
    name = (entry.name or model_id).lower()
    provider = entry.provider.lower()
    cost = entry.cost_tier
    ctx = entry.context_length

    scores: dict[str, float] = {}

    # Base scores from provider/model heuristics
    is_claude = "claude" in name or provider == "anthropic"
    is_gpt4 = "gpt-4" in name and "mini" not in name
    is_gpt4_mini = "gpt-4o-mini" in model_id or "gpt-4.1-mini" in model_id or "gpt-4.1-nano" in model_id
    is_sonnet = "sonnet" in name
    is_opus = "opus" in name
    is_haiku = "haiku" in name
    is_gemini = "gemini" in name
    is_gemini_flash = "flash" in name and is_gemini
    is_deepseek = "deepseek" in name
    is_cheap = cost in ("free", "cheap")
    is_premium = cost in ("premium", "ultra")

    # cheap_simple
    if is_cheap or is_gpt4_mini or is_haiku or is_gemini_flash:
        scores["cheap_simple"] = 0.9
    elif is_premium:
        scores["cheap_simple"] = 0.2
    else:
        scores["cheap_simple"] = 0.5

    # structured_reasoning
    if is_claude or is_gpt4 or is_sonnet:
        scores["structured_reasoning"] = 0.9
    elif is_gemini:
        scores["structured_reasoning"] = 0.7
    elif is_deepseek:
        scores["structured_reasoning"] = 0.7
    else:
        scores["structured_reasoning"] = 0.4

    # long_context
    if ctx >= 128_000:
        scores["long_context"] = 0.9
    elif ctx >= 32_000:
        scores["long_context"] = 0.6
    else:
        scores["long_context"] = 0.3

    # coding
    if is_deepseek or "code" in name or "coder" in name:
        scores["coding"] = 0.9
    elif is_sonnet or is_gpt4:
        scores["coding"] = 0.8
    elif is_gemini:
        scores["coding"] = 0.7
    else:
        scores["coding"] = 0.3

    # copywriting
    if is_claude or is_gpt4:
        scores["copywriting"] = 0.85
    elif is_gemini:
        scores["copywriting"] = 0.7
    else:
        scores["copywriting"] = 0.4

    # business_reasoning
    if is_sonnet or is_opus or is_gpt4:
        scores["business_reasoning"] = 0.9
    elif is_claude:
        scores["business_reasoning"] = 0.8
    elif is_gemini:
        scores["business_reasoning"] = 0.7
    else:
        scores["business_reasoning"] = 0.3

    # high_accuracy_critical
    if is_opus or (is_sonnet and is_premium):
        scores["high_accuracy_critical"] = 0.9
    elif is_gpt4 and is_premium:
        scores["high_accuracy_critical"] = 0.85
    elif is_sonnet or is_gpt4:
        scores["high_accuracy_critical"] = 0.7
    else:
        scores["high_accuracy_critical"] = 0.2

    # fallback_only
    if is_cheap:
        scores["fallback_only"] = 0.8
    else:
        scores["fallback_only"] = 0.3

    return ModelProfile(
        model_id=model_id,
        scores=scores,
        cost_tier=cost,
        context_length=ctx,
        provider=entry.provider,
    )


# ── Model Performance Memory ─────────────────────────────────

@dataclass
class ModelPerformanceRecord:
    """Performance stats for a model on a specific task class."""
    model_id: str
    task_class: str
    successes: int = 0
    failures: int = 0
    total_duration_ms: float = 0.0
    total_cost_estimate: float = 0.0
    quality_sum: float = 0.0
    quality_count: int = 0
    last_used: float = 0.0

    @property
    def total(self) -> int:
        return self.successes + self.failures

    @property
    def success_rate(self) -> float:
        return self.successes / self.total if self.total > 0 else 0.5

    @property
    def avg_duration_ms(self) -> float:
        return self.total_duration_ms / self.total if self.total > 0 else 0.0

    @property
    def avg_quality(self) -> float:
        return self.quality_sum / self.quality_count if self.quality_count > 0 else 0.5

    @property
    def avg_cost(self) -> float:
        return self.total_cost_estimate / self.total if self.total > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "task_class": self.task_class,
            "total": self.total,
            "success_rate": round(self.success_rate, 3),
            "avg_duration_ms": round(self.avg_duration_ms, 1),
            "avg_quality": round(self.avg_quality, 3),
            "avg_cost": round(self.avg_cost, 6),
            "last_used": self.last_used,
        }


class ModelPerformanceMemory:
    """Track model performance per task class."""

    def __init__(self, path: Optional[Path] = None):
        self._lock = threading.Lock()
        self._records: dict[str, ModelPerformanceRecord] = {}
        self._path = path or Path("data/model_performance.json")
        self._load()

    def _key(self, model_id: str, task_class: str) -> str:
        return f"{model_id}::{task_class}"

    def _load(self) -> None:
        try:
            if self._path.exists():
                with open(self._path) as f:
                    data = json.load(f)
                for k, v in data.get("records", {}).items():
                    self._records[k] = ModelPerformanceRecord(
                        model_id=v.get("model_id", ""),
                        task_class=v.get("task_class", ""),
                        successes=v.get("successes", 0),
                        failures=v.get("failures", 0),
                        total_duration_ms=v.get("total_duration_ms", 0),
                        total_cost_estimate=v.get("total_cost_estimate", 0),
                        quality_sum=v.get("quality_sum", 0),
                        quality_count=v.get("quality_count", 0),
                        last_used=v.get("last_used", 0),
                    )
        except Exception as _exc:
            log.warning("swallowed_exception", action="selector_1", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump({
                    "version": 1,
                    "records": {k: {
                        "model_id": r.model_id,
                        "task_class": r.task_class,
                        "successes": r.successes,
                        "failures": r.failures,
                        "total_duration_ms": r.total_duration_ms,
                        "total_cost_estimate": r.total_cost_estimate,
                        "quality_sum": r.quality_sum,
                        "quality_count": r.quality_count,
                        "last_used": r.last_used,
                    } for k, r in self._records.items()},
                }, f)
            tmp.replace(self._path)
        except Exception as _exc:
            log.warning("swallowed_exception", action="selector_2", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    def record(
        self,
        model_id: str,
        task_class: str,
        success: bool,
        duration_ms: float = 0.0,
        quality: float = 0.0,
        cost_estimate: float = 0.0,
    ) -> None:
        key = self._key(model_id, task_class)
        with self._lock:
            rec = self._records.get(key)
            if not rec:
                rec = ModelPerformanceRecord(model_id=model_id, task_class=task_class)
                self._records[key] = rec
            if success:
                rec.successes += 1
            else:
                rec.failures += 1
            rec.total_duration_ms += duration_ms
            rec.total_cost_estimate += cost_estimate
            if quality > 0:
                rec.quality_sum += quality
                rec.quality_count += 1
            rec.last_used = time.time()
        self._save()

    def get_stats(self, model_id: str, task_class: str = "") -> list[dict]:
        with self._lock:
            if task_class:
                key = self._key(model_id, task_class)
                rec = self._records.get(key)
                return [rec.to_dict()] if rec else []
            return [r.to_dict() for r in self._records.values()
                    if r.model_id == model_id]

    def get_best_for_task(self, task_class: str, min_samples: int = 2) -> list[dict]:
        """Get models ranked by quality for a task class."""
        with self._lock:
            candidates = [
                r for r in self._records.values()
                if r.task_class == task_class and r.total >= min_samples
            ]
        candidates.sort(key=lambda r: r.avg_quality, reverse=True)
        return [r.to_dict() for r in candidates[:10]]

    def get_all(self) -> list[dict]:
        with self._lock:
            return [r.to_dict() for r in self._records.values()]


# ── Model Selection Policy ────────────────────────────────────

@dataclass
class SelectionResult:
    """Explainable model selection result."""
    model_id: str
    task_class: str
    profile_score: float = 0.0
    performance_score: float = 0.0
    cost_score: float = 0.0
    final_score: float = 0.0
    rationale: str = ""
    is_fallback: bool = False

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "task_class": self.task_class,
            "profile_score": round(self.profile_score, 3),
            "performance_score": round(self.performance_score, 3),
            "cost_score": round(self.cost_score, 3),
            "final_score": round(self.final_score, 3),
            "rationale": self.rationale,
            "is_fallback": self.is_fallback,
        }


class ModelSelector:
    """
    Selects best model for a task based on profile + performance + cost.

    Scoring formula:
      final = profile_score × w_profile + performance_score × w_perf + cost_score × w_cost

    Weights vary by task criticality:
      - critical: profile=0.5, performance=0.4, cost=0.1
      - normal:   profile=0.3, performance=0.3, cost=0.4
      - budget:   profile=0.2, performance=0.2, cost=0.6
    """

    # Known good models (fallback pool)
    FALLBACK_MODELS = {
        "cheap_simple": "openai/gpt-4o-mini",
        "structured_reasoning": "anthropic/claude-sonnet-4.5",
        "business_reasoning": "anthropic/claude-sonnet-4.5",
        "coding": "anthropic/claude-sonnet-4.5",
        "copywriting": "anthropic/claude-sonnet-4.5",
        "long_context": "google/gemini-2.5-flash-lite",
        "high_accuracy_critical": "anthropic/claude-sonnet-4.5",
        "fallback_only": "openai/gpt-4o-mini",
    }

    def __init__(self, catalog=None, performance=None):
        self._catalog = catalog
        self._performance = performance

    def _get_catalog(self):
        if self._catalog:
            return self._catalog
        try:
            from core.model_intelligence.catalog import get_model_catalog
            return get_model_catalog()
        except Exception:
            return None

    def _get_performance(self):
        if self._performance:
            return self._performance
        try:
            return get_model_performance()
        except Exception:
            return None

    def select(
        self,
        task_class: str,
        budget_mode: str = "normal",  # "critical", "normal", "budget"
        required_tools: bool = False,
        min_context: int = 0,
        exclude_models: list[str] | None = None,
    ) -> SelectionResult:
        """
        Select best model for a task class.

        Returns SelectionResult with explanation.
        Falls back to known good model if selection fails.
        """
        catalog = self._get_catalog()
        performance = self._get_performance()

        # Weights based on budget mode
        # normal: profile (quality) dominates — cost is secondary when credits exist
        weights = {
            "critical": (0.5, 0.4, 0.1),
            "normal": (0.50, 0.35, 0.15),
            "budget": (0.2, 0.2, 0.6),
        }.get(budget_mode, (0.50, 0.35, 0.15))
        w_profile, w_perf, w_cost = weights

        candidates: list[SelectionResult] = []
        exclude = set(exclude_models or [])

        if catalog and catalog.count > 0:
            for entry in catalog.list_all():
                if entry.model_id in exclude:
                    continue
                if required_tools and not entry.supports_tools:
                    continue
                if min_context and entry.context_length < min_context:
                    continue

                profile = build_profile(entry)
                profile_score = profile.score_for(task_class)

                # Performance score from memory
                perf_score = 0.5  # default neutral
                if performance:
                    stats = performance.get_stats(entry.model_id, task_class)
                    if stats and stats[0]["total"] >= 2:
                        perf_score = stats[0]["avg_quality"] * 0.6 + stats[0]["success_rate"] * 0.4

                # Cost score (inverse of cost — cheaper = higher score)
                cost_score = {
                    "free": 1.0, "cheap": 0.9, "mid": 0.6,
                    "premium": 0.3, "ultra": 0.1,
                }.get(entry.cost_tier, 0.5)

                final = (
                    profile_score * w_profile
                    + perf_score * w_perf
                    + cost_score * w_cost
                )

                candidates.append(SelectionResult(
                    model_id=entry.model_id,
                    task_class=task_class,
                    profile_score=profile_score,
                    performance_score=perf_score,
                    cost_score=cost_score,
                    final_score=final,
                    rationale=(
                        f"profile={profile_score:.2f} perf={perf_score:.2f} "
                        f"cost={cost_score:.2f} ({entry.cost_tier}) "
                        f"mode={budget_mode}"
                    ),
                ))

        if candidates:
            candidates.sort(key=lambda c: c.final_score, reverse=True)
            return candidates[0]

        # Fallback to known good model — budget-aware
        try:
            from core.model_intelligence.fallback_chain import BUDGET_FALLBACKS
            _valid_modes = ("budget", "normal", "critical")
            fb_mode = budget_mode if budget_mode in _valid_modes else "normal"
            fb_pool = BUDGET_FALLBACKS.get(fb_mode, BUDGET_FALLBACKS["normal"])
            fallback_id = fb_pool.get(task_class, "openai/gpt-4o-mini")
        except Exception:
            fallback_id = self.FALLBACK_MODELS.get(task_class, "openai/gpt-4o-mini")
        return SelectionResult(
            model_id=fallback_id,
            task_class=task_class,
            final_score=0.5,
            rationale=f"Fallback ({budget_mode}): no catalog data, using known good model for {task_class}",
            is_fallback=True,
        )

    def select_for_skill(self, skill_id: str, budget_mode: str = "normal") -> SelectionResult:
        """Select model for a specific skill."""
        task_class = SKILL_TASK_MAP.get(skill_id, "structured_reasoning")
        return self.select(task_class, budget_mode)

    def select_for_role(self, role: str, budget_mode: str = "normal") -> SelectionResult:
        """Select model for a LLM role."""
        task_class = ROLE_TASK_MAP.get(role, "structured_reasoning")
        return self.select(task_class, budget_mode)

    def get_recommendations(self) -> list[dict]:
        """Get recommendations for each task class."""
        recs = []
        for tc in TASK_CLASSES:
            result = self.select(tc, "normal")
            recs.append({
                "task_class": tc,
                "recommended_model": result.model_id,
                "score": result.final_score,
                "is_fallback": result.is_fallback,
                "rationale": result.rationale,
            })
        return recs


# ── Singletons ────────────────────────────────────────────────

_performance: ModelPerformanceMemory | None = None
_selector: ModelSelector | None = None


def get_model_performance() -> ModelPerformanceMemory:
    global _performance
    if _performance is None:
        _performance = ModelPerformanceMemory()
    return _performance


def get_model_selector() -> ModelSelector:
    global _selector
    if _selector is None:
        _selector = ModelSelector()
    return _selector
