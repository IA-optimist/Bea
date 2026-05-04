"""
JARVIS MAX — Dynamic LLM Routing Policy Engine

AI-OS-grade model selection that goes beyond static role mapping.
Selects models based on task characteristics, not just agent role.

Routing dimensions:
  CODE_HEAVY, CODE_LIGHT, RESEARCH_DEEP, RESEARCH_FAST,
  MEMORY_CHEAP, VISION, LOW_COST_WORKER, CRITICAL_REASONING,
  LOCAL_ONLY, FALLBACK_ONLY

Scoring factors:
  - estimated_quality   (0-1)
  - estimated_cost      (0-1, lower = cheaper)
  - estimated_latency   (0-1, lower = faster)
  - model_health        (0-1, from reliability tracker)
  - past_success_rate   (0-1)
  - context_window_fit  (0 or 1, binary)

Budget modes: cheap | balanced | premium
Latency modes: fast | normal | deep

Integration: LLMFactory.get() calls resolve_route() before building.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

import structlog

log = structlog.get_logger()


# ═══════════════════════════════════════════════════════════════
# ROUTING DIMENSIONS
# ═══════════════════════════════════════════════════════════════

class RoutingDimension(str, Enum):
    CODE_HEAVY         = "code_heavy"
    CODE_LIGHT         = "code_light"
    RESEARCH_DEEP      = "research_deep"
    RESEARCH_FAST      = "research_fast"
    MEMORY_CHEAP       = "memory_cheap"
    VISION             = "vision"
    LOW_COST_WORKER    = "low_cost_worker"
    CRITICAL_REASONING = "critical_reasoning"
    LOCAL_ONLY         = "local_only"
    FALLBACK_ONLY      = "fallback_only"


class BudgetMode(str, Enum):
    CHEAP    = "cheap"
    BALANCED = "balanced"
    PREMIUM  = "premium"


class LatencyMode(str, Enum):
    FAST   = "fast"
    NORMAL = "normal"
    DEEP   = "deep"


# ═══════════════════════════════════════════════════════════════
# ROUTING CONTEXT — what the caller provides
# ═══════════════════════════════════════════════════════════════

@dataclass
class RoutingContext:
    """Task context for routing decisions."""
    role: str = "default"                           # Original agent role
    mission_id: str = ""
    task_description: str = ""
    task_type: str = ""                             # coding, research, memory, ops, etc.
    complexity: float = 0.5                         # 0-1
    token_estimate: int = 0                         # Estimated input tokens
    budget: BudgetMode = BudgetMode.BALANCED
    latency: LatencyMode = LatencyMode.NORMAL
    require_local: bool = False
    require_code: bool = False
    require_vision: bool = False
    require_research: bool = False
    mission_budget_usd: float = 0.0                 # 0 = no limit


# ═══════════════════════════════════════════════════════════════
# ROUTING DECISION — what the policy outputs
# ═══════════════════════════════════════════════════════════════

@dataclass
class RoutingDecision:
    """The output of the routing policy."""
    resolved_role: str                              # May differ from input role
    model_id: str                                   # OpenRouter model ID
    settings_attr: str                              # Settings attribute name
    dimension: RoutingDimension
    score: float                                    # Composite 0-1
    reason: str
    budget_mode: str
    latency_mode: str
    locality: str                                   # cloud | local
    fallback_used: bool = False
    rejected: list[str] = field(default_factory=list)
    expected_cost_tier: str = "medium"              # free | cheap | medium | expensive | premium


# ═══════════════════════════════════════════════════════════════
# MODEL PROFILES — static metadata per model
# ═══════════════════════════════════════════════════════════════

@dataclass
class ModelProfile:
    """Static characteristics of a model."""
    model_id: str
    settings_attr: str
    quality: float          # 0-1, higher = better
    cost: float             # 0-1, higher = more expensive
    latency: float          # 0-1, higher = slower
    context_window: int     # Max tokens
    strengths: set[str]     # Routing dimensions this model excels at
    cost_tier: str          # free | cheap | medium | expensive | premium
    is_local: bool = False


# Canonical model profiles — these match the OpenRouter config
_MODEL_PROFILES: dict[str, ModelProfile] = {
    "orchestrator": ModelProfile(
        model_id="anthropic/claude-sonnet-4.6",
        settings_attr="openrouter_orchestrator_model",
        quality=0.95, cost=0.70, latency=0.55, context_window=1_000_000,
        strengths={RoutingDimension.CRITICAL_REASONING, RoutingDimension.CODE_HEAVY,
                   RoutingDimension.RESEARCH_DEEP},
        cost_tier="expensive",
    ),
    "heavy_coder": ModelProfile(
        model_id="openai/gpt-5.3-codex",
        settings_attr="openrouter_heavy_coder_model",
        quality=0.92, cost=0.60, latency=0.50, context_window=400_000,
        strengths={RoutingDimension.CODE_HEAVY, RoutingDimension.CODE_LIGHT},
        cost_tier="expensive",
    ),
    "cheap_worker": ModelProfile(
        model_id="minimax/minimax-m2.7",
        settings_attr="openrouter_cheap_worker_model",
        quality=0.72, cost=0.15, latency=0.30, context_window=204_800,
        strengths={RoutingDimension.LOW_COST_WORKER, RoutingDimension.CODE_LIGHT,
                   RoutingDimension.MEMORY_CHEAP},
        cost_tier="cheap",
    ),
    "research": ModelProfile(
        model_id="google/gemini-2.5-pro",
        settings_attr="openrouter_research_model",
        quality=0.93, cost=0.50, latency=0.60, context_window=1_048_576,
        strengths={RoutingDimension.RESEARCH_DEEP, RoutingDimension.RESEARCH_FAST},
        cost_tier="medium",
    ),
    "fast_router": ModelProfile(
        model_id="openai/gpt-5.4-nano",
        settings_attr="openrouter_fast_router_model",
        quality=0.65, cost=0.05, latency=0.10, context_window=400_000,
        strengths={RoutingDimension.LOW_COST_WORKER, RoutingDimension.RESEARCH_FAST,
                   RoutingDimension.MEMORY_CHEAP},
        cost_tier="cheap",
    ),
    "memory": ModelProfile(
        model_id="google/gemini-2.5-flash-lite",
        settings_attr="openrouter_memory_model",
        quality=0.68, cost=0.03, latency=0.15, context_window=1_048_576,
        strengths={RoutingDimension.MEMORY_CHEAP, RoutingDimension.LOW_COST_WORKER},
        cost_tier="free",
    ),
    "multimodal": ModelProfile(
        model_id="xiaomi/mimo-v2-omni",
        settings_attr="openrouter_multimodal_model",
        quality=0.80, cost=0.30, latency=0.45, context_window=262_144,
        strengths={RoutingDimension.VISION},
        cost_tier="medium",
    ),
    "fallback": ModelProfile(
        model_id="deepseek/deepseek-v3.2",
        settings_attr="openrouter_fallback_model",
        quality=0.82, cost=0.10, latency=0.35, context_window=163_840,
        strengths={RoutingDimension.CODE_LIGHT, RoutingDimension.LOW_COST_WORKER,
                   RoutingDimension.FALLBACK_ONLY},
        cost_tier="cheap",
    ),
}


# ═══════════════════════════════════════════════════════════════
# DIMENSION CLASSIFIER — infer routing dimension from context
# ═══════════════════════════════════════════════════════════════

_DIMENSION_KEYWORDS: dict[RoutingDimension, list[str]] = {
    RoutingDimension.CODE_HEAVY: [
        "refactor", "multi-file", "rewrite", "implement", "build feature",
        "complex code", "architecture", "migrate",
    ],
    RoutingDimension.CODE_LIGHT: [
        "fix", "patch", "tweak", "small edit", "one-liner", "typo",
        "format", "lint", "rename",
    ],
    RoutingDimension.RESEARCH_DEEP: [
        "research", "analyze", "compare", "synthesize", "deep dive",
        "literature", "comprehensive",
    ],
    RoutingDimension.RESEARCH_FAST: [
        "lookup", "find", "quick check", "what is", "summarize briefly",
    ],
    RoutingDimension.MEMORY_CHEAP: [
        "summarize", "compress", "condense", "memory", "context window",
        "reduce tokens",
    ],
    RoutingDimension.VISION: [
        "image", "screenshot", "visual", "picture", "photo", "diagram",
        "ui layout", "ui review", "multimodal",
    ],
    RoutingDimension.CRITICAL_REASONING: [
        "critical", "important", "architecture decision", "security review",
        "production", "deploy decision", "risk assessment",
    ],
    RoutingDimension.LOW_COST_WORKER: [
        "simple", "trivial", "routine", "repeat", "batch", "transform",
        "classify", "tag", "label",
    ],
}


def classify_dimension(ctx: RoutingContext) -> RoutingDimension:
    """Infer the routing dimension from task context."""
    # Explicit constraints first
    if ctx.require_local:
        return RoutingDimension.LOCAL_ONLY
    if ctx.require_vision:
        return RoutingDimension.VISION

    desc = (ctx.task_description + " " + ctx.task_type).lower()

    # Score each dimension by keyword matches
    best_dim = RoutingDimension.LOW_COST_WORKER
    best_score = 0

    for dim, keywords in _DIMENSION_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in desc)
        if score > best_score:
            best_score = score
            best_dim = dim

    # Complexity-based overrides
    if best_score == 0:
        # No keyword match — use complexity
        if ctx.complexity >= 0.8:
            if ctx.require_code:
                return RoutingDimension.CODE_HEAVY
            return RoutingDimension.CRITICAL_REASONING
        elif ctx.complexity >= 0.5:
            if ctx.require_code:
                return RoutingDimension.CODE_LIGHT
            return RoutingDimension.RESEARCH_FAST
        else:
            return RoutingDimension.LOW_COST_WORKER

    # Budget can downgrade dimensions
    if ctx.budget == BudgetMode.CHEAP:
        upgrades = {
            RoutingDimension.CODE_HEAVY: RoutingDimension.CODE_LIGHT,
            RoutingDimension.RESEARCH_DEEP: RoutingDimension.RESEARCH_FAST,
            RoutingDimension.CRITICAL_REASONING: RoutingDimension.CODE_LIGHT,
        }
        best_dim = upgrades.get(best_dim, best_dim)

    # Latency can downgrade dimensions
    if ctx.latency == LatencyMode.FAST:
        upgrades = {
            RoutingDimension.RESEARCH_DEEP: RoutingDimension.RESEARCH_FAST,
            RoutingDimension.CODE_HEAVY: RoutingDimension.CODE_LIGHT,
        }
        best_dim = upgrades.get(best_dim, best_dim)

    return best_dim


# ═══════════════════════════════════════════════════════════════
# ROLE → DIMENSION MAPPING (for static-role callers)
# ═══════════════════════════════════════════════════════════════

_ROLE_DEFAULT_DIMENSION: dict[str, RoutingDimension] = {
    "director":    RoutingDimension.CRITICAL_REASONING,
    "planner":     RoutingDimension.CRITICAL_REASONING,
    "reviewer":    RoutingDimension.CRITICAL_REASONING,
    "improve":     RoutingDimension.CODE_HEAVY,
    "builder":     RoutingDimension.CODE_HEAVY,
    "code":        RoutingDimension.CODE_HEAVY,
    "research":    RoutingDimension.RESEARCH_DEEP,
    "context":     RoutingDimension.RESEARCH_DEEP,
    "fast":        RoutingDimension.LOW_COST_WORKER,
    "default":     RoutingDimension.LOW_COST_WORKER,
    "ops":         RoutingDimension.LOW_COST_WORKER,
    "memory":      RoutingDimension.MEMORY_CHEAP,
    "advisor":     RoutingDimension.MEMORY_CHEAP,
    "vision":      RoutingDimension.VISION,
    "uncensored":  RoutingDimension.LOCAL_ONLY,
}


# ═══════════════════════════════════════════════════════════════
# SCORER — composite model scoring
# ═══════════════════════════════════════════════════════════════

# Budget mode weights: how much each factor matters
_BUDGET_WEIGHTS: dict[BudgetMode, dict[str, float]] = {
    BudgetMode.CHEAP: {
        "quality": 0.15, "cost": 0.50, "latency": 0.10,
        "health": 0.10, "strength": 0.15,
    },
    BudgetMode.BALANCED: {
        "quality": 0.30, "cost": 0.20, "latency": 0.15,
        "health": 0.15, "strength": 0.20,
    },
    BudgetMode.PREMIUM: {
        "quality": 0.45, "cost": 0.05, "latency": 0.10,
        "health": 0.15, "strength": 0.25,
    },
}


def score_model(profile: ModelProfile, dimension: RoutingDimension,
                ctx: RoutingContext,
                health: float = 1.0) -> tuple[float, str]:
    """
    Score a model for a routing dimension + context.

    Returns (score 0-1, reasoning string).
    """
    weights = _BUDGET_WEIGHTS.get(ctx.budget, _BUDGET_WEIGHTS[BudgetMode.BALANCED])
    reasons = []

    # Quality score (higher = better)
    q = profile.quality * weights["quality"]
    reasons.append(f"q={profile.quality:.2f}")

    # Cost score (lower cost = higher score)
    c = (1.0 - profile.cost) * weights["cost"]
    reasons.append(f"cost={profile.cost:.2f}")

    # Latency score
    if ctx.latency == LatencyMode.FAST:
        # Strongly prefer low-latency models
        l = (1.0 - profile.latency) * weights["latency"] * 2.0
    elif ctx.latency == LatencyMode.DEEP:
        # Don't penalize slow models
        l = (1.0 - profile.latency * 0.3) * weights["latency"]
    else:
        l = (1.0 - profile.latency) * weights["latency"]
    reasons.append(f"lat={profile.latency:.2f}")

    # Health score
    h = health * weights["health"]

    # Strength match bonus
    if dimension in profile.strengths:
        s = 1.0 * weights["strength"]
        reasons.append("strength_match")
    else:
        s = 0.2 * weights["strength"]
        reasons.append("no_strength_match")

    # Context window fit (hard filter)
    if ctx.token_estimate > 0 and ctx.token_estimate > profile.context_window * 0.9:
        # Doesn't fit — heavy penalty
        reasons.append("ctx_overflow")
        return 0.01, " ".join(reasons)

    total = q + c + l + h + s
    return round(min(total, 1.0), 4), " ".join(reasons)


# ═══════════════════════════════════════════════════════════════
# RELIABILITY TRACKER — model health history
# ═══════════════════════════════════════════════════════════════

class ModelHealthTracker:
    """Track model success/failure rates for routing decisions."""

    def __init__(self):
        self._records: dict[str, dict] = {}  # model_id -> {calls, successes, last_failure_ts}

    def record(self, model_id: str, success: bool) -> None:
        if model_id not in self._records:
            self._records[model_id] = {"calls": 0, "successes": 0, "last_failure_ts": 0.0}
        r = self._records[model_id]
        r["calls"] += 1
        if success:
            r["successes"] += 1
        else:
            r["last_failure_ts"] = time.time()

    def health(self, model_id: str) -> float:
        """Return health score 0-1. Unknown models get 0.8 (optimistic default)."""
        r = self._records.get(model_id)
        if not r or r["calls"] == 0:
            return 0.8
        base = r["successes"] / r["calls"]
        # Recent failure penalty (decays over 10 min)
        if r["last_failure_ts"] > 0:
            age_s = time.time() - r["last_failure_ts"]
            if age_s < 600:
                base *= 0.5 + 0.5 * (age_s / 600)
        return round(max(0.1, base), 3)

    def get_all(self) -> dict[str, float]:
        return {mid: self.health(mid) for mid in self._records}


# Singleton
_health_tracker = ModelHealthTracker()


def get_health_tracker() -> ModelHealthTracker:
    return _health_tracker


# ═══════════════════════════════════════════════════════════════
# MAIN ROUTING FUNCTION
# ═══════════════════════════════════════════════════════════════

def resolve_route(ctx: RoutingContext) -> RoutingDecision:
    """
    Main entry: resolve a routing decision from task context.

    Steps:
    1. Classify routing dimension (from task or role)
    2. Score all candidate models
    3. Apply constraints (local-only, budget, latency)
    4. Select highest-scoring model
    5. Log and return decision
    """
    # Step 1: Classify dimension
    if ctx.task_description or ctx.task_type:
        dimension = classify_dimension(ctx)
    else:
        dimension = _ROLE_DEFAULT_DIMENSION.get(ctx.role, RoutingDimension.LOW_COST_WORKER)

    # Step 2: Hard constraints
    if dimension == RoutingDimension.LOCAL_ONLY or ctx.require_local:
        return RoutingDecision(
            resolved_role=ctx.role,
            model_id="ollama",
            settings_attr="",
            dimension=RoutingDimension.LOCAL_ONLY,
            score=1.0,
            reason="local_only constraint",
            budget_mode=ctx.budget.value,
            latency_mode=ctx.latency.value,
            locality="local",
            expected_cost_tier="free",
        )

    # Step 3: Score all candidates
    candidates: list[tuple[str, ModelProfile, float, str]] = []
    for name, profile in _MODEL_PROFILES.items():
        if profile.is_local:
            continue  # Skip local-only models in cloud routing
        h = _health_tracker.health(profile.model_id)
        s, reasoning = score_model(profile, dimension, ctx, health=h)
        candidates.append((name, profile, s, reasoning))

    # Sort by score descending
    candidates.sort(key=lambda x: x[2], reverse=True)

    if not candidates:
        return RoutingDecision(
            resolved_role=ctx.role,
            model_id="ollama",
            settings_attr="",
            dimension=dimension,
            score=0.0,
            reason="no candidates available",
            budget_mode=ctx.budget.value,
            latency_mode=ctx.latency.value,
            locality="local",
            fallback_used=True,
            expected_cost_tier="free",
        )

    # Step 4: Select winner
    winner_name, winner_profile, winner_score, winner_reasoning = candidates[0]
    rejected = [
        f"{name}({score:.3f})" for name, _, score, _ in candidates[1:5]
    ]

    # Map to the appropriate role for LLMFactory
    profile_to_role: dict[str, str] = {
        "orchestrator": "director",
        "heavy_coder":  "builder",
        "cheap_worker": "ops",
        "research":     "research",
        "fast_router":  "fast",
        "memory":       "memory",
        "multimodal":   "vision",
        "fallback":     "default",
    }
    resolved_role = profile_to_role.get(winner_name, ctx.role)

    decision = RoutingDecision(
        resolved_role=resolved_role,
        model_id=winner_profile.model_id,
        settings_attr=winner_profile.settings_attr,
        dimension=dimension,
        score=winner_score,
        reason=winner_reasoning,
        budget_mode=ctx.budget.value,
        latency_mode=ctx.latency.value,
        locality="cloud",
        rejected=rejected,
        expected_cost_tier=winner_profile.cost_tier,
    )

    # Step 5: Structured log
    log.info(
        "ROUTE_DECISION",
        mission_id=ctx.mission_id or "-",
        role=ctx.role,
        resolved_role=resolved_role,
        dimension=dimension.value,
        selected_model=winner_profile.model_id,
        score=winner_score,
        rejected=rejected[:3],
        budget_mode=ctx.budget.value,
        latency_mode=ctx.latency.value,
        locality="cloud",
        fallback_used=False,
        expected_cost_tier=winner_profile.cost_tier,
        reason=winner_reasoning[:80],
    )

    return decision


# ═══════════════════════════════════════════════════════════════
# CONVENIENCE: role-only routing (for backward compatibility)
# ═══════════════════════════════════════════════════════════════

def resolve_role(role: str, budget: str = "balanced",
                 latency: str = "normal",
                 task_description: str = "",
                 complexity: float = 0.5,
                 mission_id: str = "") -> RoutingDecision:
    """
    Simplified entry point for callers that only have a role string.
    Builds a RoutingContext and delegates to resolve_route().
    """
    ctx = RoutingContext(
        role=role,
        mission_id=mission_id,
        task_description=task_description,
        complexity=complexity,
        budget=BudgetMode(budget) if budget in ("cheap", "balanced", "premium") else BudgetMode.BALANCED,
        latency=LatencyMode(latency) if latency in ("fast", "normal", "deep") else LatencyMode.NORMAL,
        require_local=(role == "uncensored"),
        require_code=(role in ("builder", "code", "improve")),
        require_vision=(role == "vision"),
        require_research=(role in ("research", "context")),
    )
    return resolve_route(ctx)


# ═══════════════════════════════════════════════════════════════
# RECENT DECISIONS BUFFER — for diagnostics
# ═══════════════════════════════════════════════════════════════

_recent_decisions: list[dict] = []
_MAX_RECENT = 50


def record_decision(decision: RoutingDecision) -> None:
    """Store a decision for diagnostics."""
    _recent_decisions.append({
        "ts": time.time(),
        "role": decision.resolved_role,
        "model": decision.model_id,
        "dimension": decision.dimension.value,
        "score": decision.score,
        "budget": decision.budget_mode,
        "latency": decision.latency_mode,
        "cost_tier": decision.expected_cost_tier,
    })
    if len(_recent_decisions) > _MAX_RECENT:
        _recent_decisions.pop(0)


def get_recent_decisions(limit: int = 20) -> list[dict]:
    """Return recent routing decisions for diagnostics."""
    return list(reversed(_recent_decisions[-limit:]))
