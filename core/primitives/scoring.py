"""
BEA — Scoring Primitives (sections 1-3)
Feasibility scoring, value estimation, and strategy selection.
"""
from __future__ import annotations

import structlog
from dataclasses import asdict, dataclass, field

logger = structlog.get_logger("bea.operating_primitives")
log = logger


# ═══════════════════════════════════════════════════════════════
# 1. FEASIBILITY SCORING
# ═══════════════════════════════════════════════════════════════

@dataclass
class FeasibilityScore:
    """How feasible is a mission given current capabilities?"""
    tool_coverage: float = 0.0      # % of required tools available and healthy
    agent_readiness: float = 0.0    # agents have relevant experience
    strategy_confidence: float = 0.0  # prior strategies exist
    complexity_fit: float = 0.0     # complexity within system capacity
    overall: float = 0.0
    missing_tools: list = field(default_factory=list)
    recommended_agents: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def score_feasibility(
    goal: str,
    mission_type: str,
    required_tools: list[str],
    complexity: str = "medium",
) -> FeasibilityScore:
    """Score how feasible a mission is given current system state."""
    result = FeasibilityScore()

    # 1. Tool coverage: are required tools available and healthy?
    try:
        from core.tool_performance_tracker import get_tool_performance_tracker
        tpt = get_tool_performance_tracker()
        healthy = 0
        for tool in required_tools:
            stats = tpt.get_stats(tool)
            if stats and stats.success_rate >= 0.5:
                healthy += 1
            elif stats and stats.success_rate < 0.5:
                result.missing_tools.append(f"{tool} (degraded: {stats.success_rate:.0%})")
            else:
                result.missing_tools.append(f"{tool} (no data)")
                healthy += 0.5  # unknown = partial credit
        result.tool_coverage = healthy / max(len(required_tools), 1)
    except Exception:
        result.tool_coverage = 0.5  # fail-open: assume moderate coverage

    # 2. Agent readiness: do agents have domain experience?
    try:
        from core.mission_performance_tracker import get_mission_performance_tracker
        mpt = get_mission_performance_tracker()
        strategy = mpt.get_strategy_for_type(mission_type)
        if strategy and strategy.get("sample_size", 0) >= 3:
            result.agent_readiness = min(1.0, strategy.get("success_rate", 0.5))
            best_agents = mpt.get_best_agents_for_type(mission_type)
            if best_agents:
                result.recommended_agents = best_agents[:3]
        else:
            result.agent_readiness = 0.4  # no experience, moderate default
            result.notes.append("No prior missions of this type")
    except Exception:
        result.agent_readiness = 0.4

    # 3. Strategy confidence: have we solved similar problems?
    try:
        from core.mission_memory import get_mission_memory
        mm = get_mission_memory()
        best = mm.get_best_strategy(mission_type)
        if best:
            result.strategy_confidence = best.get("confidence", 0.3)
        else:
            result.strategy_confidence = 0.2
            result.notes.append("No proven strategy for this mission type")
    except Exception:
        result.strategy_confidence = 0.2

    # 4. Complexity fit
    complexity_scores = {"low": 1.0, "medium": 0.8, "high": 0.6, "critical": 0.4}
    result.complexity_fit = complexity_scores.get(complexity, 0.7)

    # Overall: weighted average
    result.overall = round(
        result.tool_coverage * 0.30
        + result.agent_readiness * 0.25
        + result.strategy_confidence * 0.25
        + result.complexity_fit * 0.20,
        3,
    )
    return result


# ═══════════════════════════════════════════════════════════════
# 2. VALUE ESTIMATION
# ═══════════════════════════════════════════════════════════════

@dataclass
class ValueEstimate:
    """Estimated value of completing a mission."""
    execution_cost: str = "low"       # low/medium/high (tool + time cost)
    expected_benefit: str = "medium"  # low/medium/high
    risk_level: str = "low"
    net_value_score: float = 0.0      # -1 to 1 (negative = not worth it)
    reasoning: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def estimate_value(
    goal: str,
    mission_type: str,
    complexity: str = "medium",
    plan_steps: int = 1,
    risk_score: int = 0,
) -> ValueEstimate:
    """Estimate the value of executing a mission."""
    result = ValueEstimate()

    # Cost estimation based on complexity + steps
    if plan_steps <= 2 and complexity == "low":
        result.execution_cost = "low"
        cost_score = 0.9
    elif plan_steps <= 5 and complexity in ("low", "medium"):
        result.execution_cost = "medium"
        cost_score = 0.6
    else:
        result.execution_cost = "high"
        cost_score = 0.3

    # Benefit estimation based on mission type
    high_value_types = {"coding_task", "architecture_task", "system_task", "debug_task"}
    medium_value_types = {"research_task", "planning_task", "evaluation_task"}
    if mission_type in high_value_types:
        result.expected_benefit = "high"
        benefit_score = 0.9
    elif mission_type in medium_value_types:
        result.expected_benefit = "medium"
        benefit_score = 0.6
    else:
        result.expected_benefit = "low"
        benefit_score = 0.4

    # Risk
    if risk_score <= 3:
        result.risk_level = "low"
        risk_factor = 1.0
    elif risk_score <= 6:
        result.risk_level = "medium"
        risk_factor = 0.7
    else:
        result.risk_level = "high"
        risk_factor = 0.4

    result.net_value_score = round(
        (benefit_score - (1 - cost_score) * 0.5) * risk_factor, 3
    )
    result.reasoning = (
        f"Cost={result.execution_cost} ({plan_steps} steps, {complexity}), "
        f"Benefit={result.expected_benefit} ({mission_type}), "
        f"Risk={result.risk_level} (score={risk_score})"
    )
    return result


# ═══════════════════════════════════════════════════════════════
# 3. STRATEGY SELECTION
# ═══════════════════════════════════════════════════════════════

@dataclass
class StrategyRecommendation:
    """Recommended approach for a mission."""
    agents: list = field(default_factory=list)
    tools: list = field(default_factory=list)
    plan_steps: int = 0
    confidence: float = 0.0
    source: str = "default"  # "memory", "performance", "default"
    reasoning: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def select_strategy(
    goal: str,
    mission_type: str,
    complexity: str = "medium",
) -> StrategyRecommendation:
    """Select the best strategy based on all available intelligence."""
    result = StrategyRecommendation()

    # 1. Check mission memory for proven strategies
    try:
        from core.mission_memory import get_mission_memory
        mm = get_mission_memory()
        best = mm.get_best_strategy(mission_type)
        if best and best.get("confidence", 0) >= 0.4:
            result.agents = best.get("agents", [])
            result.tools = best.get("tools", [])
            result.plan_steps = best.get("plan_steps", 0)
            result.confidence = best.get("confidence", 0)
            result.source = "memory"
            result.reasoning = f"Proven strategy: {best.get('successes',0)} successes"
            return result
    except Exception as _exc:
        log.warning("swallowed_exception", action="proven_strategy_lookup", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # 2. Check performance data for best agents/tools
    try:
        from core.mission_performance_tracker import get_mission_performance_tracker
        mpt = get_mission_performance_tracker()
        strategy = mpt.get_strategy_for_type(mission_type)
        if strategy and strategy.get("sample_size", 0) >= 3:
            result.agents = mpt.get_best_agents_for_type(mission_type) or []
            tools_data = strategy.get("recommended_tools", [])
            result.tools = [t[0] for t in tools_data[:5]] if tools_data else []
            result.confidence = min(0.8, strategy.get("success_rate", 0.5))
            result.source = "performance"
            result.reasoning = f"Performance data: {strategy['sample_size']} missions, {strategy.get('success_rate',0):.0%} success"
            return result
    except Exception as _exc:
        log.warning("swallowed_exception", action="strategy_performance_data", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # 3. Default strategy based on mission type
    defaults = {
        "coding_task": (["forge-builder", "lens-reviewer"], ["read_file", "write_file", "shell_command"]),
        "debug_task": (["forge-builder", "lens-reviewer"], ["read_file", "shell_command"]),
        "research_task": (["scout-research"], ["http_get", "vector_search"]),
        "system_task": (["forge-builder", "pulse-ops"], ["shell_command"]),
        "architecture_task": (["map-planner", "lens-reviewer"], ["read_file", "search_codebase"]),
        "evaluation_task": (["lens-reviewer"], ["read_file", "shell_command"]),
        "planning_task": (["map-planner", "scout-research"], ["read_file"]),
    }
    agents, tools = defaults.get(mission_type, (["scout-research"], ["read_file"]))
    result.agents = agents
    result.tools = tools
    result.plan_steps = {"low": 2, "medium": 4, "high": 6}.get(complexity, 3)
    result.confidence = 0.3
    result.source = "default"
    result.reasoning = "No prior data, using default strategy"
    return result
