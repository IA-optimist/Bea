"""
JARVIS — Operating Primitives
=================================
Minimal capability layer enabling real-world economic workflows.

These are SCORING FUNCTIONS, not orchestration. They extend the planner
and mission memory with structured decision-making primitives.

Integrates with:
- mission_memory (strategy data)
- tool_performance_tracker (tool reliability)
- mission_performance_tracker (mission outcomes)
- planner (planning intelligence)
- improvement_proposals (gap detection)

Zero external dependencies. Fail-open everywhere.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

logger = logging.getLogger("jarvis.operating_primitives")


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
    except Exception:
        _silent_log.debug("suppressed_exception", src='operating_primitives.py')

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
    except Exception:
        _silent_log.debug("suppressed_exception", src='operating_primitives.py')

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
# 5. MISSION COORDINATION
# ═══════════════════════════════════════════════════════════════

MAX_CONCURRENT_MISSIONS = int(os.environ.get("JARVIS_MAX_CONCURRENT", "5"))


def can_accept_mission(current_active: int) -> bool:
    """Check if system can accept another mission."""
    return current_active < MAX_CONCURRENT_MISSIONS


def prioritize_missions(missions: list[dict]) -> list[dict]:
    """Sort missions by priority: feasibility × value."""
    scored = []
    for m in missions:
        goal = m.get("goal", "")
        mtype = m.get("mission_type", "info_query")
        complexity = m.get("complexity", "medium")
        tools = m.get("tools", [])

        feasibility = score_feasibility(goal, mtype, tools, complexity)
        value = estimate_value(goal, mtype, complexity, m.get("plan_steps", 1), m.get("risk_score", 0))

        m["_priority_score"] = round(feasibility.overall * 0.6 + max(0, value.net_value_score) * 0.4, 3)
        m["_feasibility"] = feasibility.overall
        m["_value"] = value.net_value_score
        scored.append(m)

    scored.sort(key=lambda m: m.get("_priority_score", 0), reverse=True)
    return scored


# ═══════════════════════════════════════════════════════════════
# 6. OPERATIONAL SIGNALS (for cockpit)
# ═══════════════════════════════════════════════════════════════

def get_operational_signals() -> dict:
    """Aggregate operational intelligence for cockpit."""
    signals = {
        "mission_success_distribution": {},
        "strategy_effectiveness": {},
        "tool_impact": {},
        "planning_confidence": 0.0,
        "execution_stability": 0.0,
        "long_horizon_ratio": 0.0,
    }

    try:
        from core.mission_performance_tracker import get_mission_performance_tracker
        mpt = get_mission_performance_tracker()
        dashboard = mpt.get_dashboard_data()
        signals["mission_success_distribution"] = {
            t: {"success_rate": s.success_rate, "total": s.total}
            for t, s in mpt._type_stats.items()
        }
    except Exception:
        _silent_log.debug("suppressed_exception", src='operating_primitives.py')

    try:
        from core.mission_memory import get_mission_memory
        mm = get_mission_memory()
        for s in list(mm._strategies.values())[:20]:
            signals["strategy_effectiveness"][s.mission_type] = {
                "confidence": s.confidence,
                "success_rate": s.success_rate,
            }
    except Exception:
        _silent_log.debug("suppressed_exception", src='operating_primitives.py')

    try:
        from core.tool_performance_tracker import get_tool_performance_tracker
        tpt = get_tool_performance_tracker()
        for name, stats in list(tpt.get_all_stats().items())[:20]:
            signals["tool_impact"][name] = {
                "success_rate": stats.success_rate,
                "total_calls": stats.total_calls,
                "health": stats.health_status,
            }
    except Exception:
        _silent_log.debug("suppressed_exception", src='operating_primitives.py')

    try:
        from core.execution_engine import get_telemetry_summary
        ts = get_telemetry_summary()
        signals["execution_stability"] = ts.get("avg_stability", 0)
        signals["planning_confidence"] = ts.get("avg_success_rate", 0)
    except Exception:
        _silent_log.debug("suppressed_exception", src='operating_primitives.py')

    try:
        tracker = get_objective_tracker()
        d = tracker.get_dashboard()
        if d["total"] > 0:
            signals["long_horizon_ratio"] = round(d["completed"] / max(d["total"], 1), 3)
    except Exception:
        _silent_log.debug("suppressed_exception", src='operating_primitives.py')

    return signals


# ═══════════════════════════════════════════════════════════════
# 7. ECONOMIC REASONING MODEL
# ═══════════════════════════════════════════════════════════════

@dataclass
class EconomicEstimate:
    """Full economic evaluation of a mission."""
    estimated_cost: float = 0.0       # 0-10 scale (tool + time + complexity)
    estimated_value: float = 0.0      # 0-10 scale (benefit + impact)
    estimated_risk: float = 0.0       # 0-10 scale
    time_to_value_hours: float = 0.0  # estimated hours
    probability_of_success: float = 0.5
    expected_return: float = 0.0      # (value × prob) / (cost + time + risk_penalty)
    priority_score: float = 0.0
    reasoning: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def compute_economics(
    goal: str,
    mission_type: str,
    complexity: str = "medium",
    plan_steps: int = 1,
    risk_score: int = 0,
    required_tools: list[str] | None = None,
) -> EconomicEstimate:
    """Compute full economic estimate for a mission."""
    result = EconomicEstimate()

    # Cost: based on complexity + steps + tool count
    complexity_cost = {"low": 1, "medium": 3, "high": 6, "critical": 9}.get(complexity, 3)
    step_cost = min(plan_steps * 0.5, 5)
    tool_cost = min(len(required_tools or []) * 0.3, 3)
    result.estimated_cost = round(min(10, complexity_cost + step_cost + tool_cost), 1)

    # Value: based on mission type + goal keywords
    type_value = {
        "coding_task": 7, "architecture_task": 8, "system_task": 7,
        "debug_task": 6, "research_task": 5, "planning_task": 6,
        "evaluation_task": 4, "info_query": 2,
    }.get(mission_type, 3)
    # High-value keywords boost
    high_value_kw = {"deploy", "fix", "build", "create", "automate", "optimize", "launch"}
    goal_lower = goal.lower()
    kw_boost = sum(1 for kw in high_value_kw if kw in goal_lower)
    result.estimated_value = round(min(10, type_value + kw_boost * 0.5), 1)

    # Risk
    result.estimated_risk = round(min(10, risk_score + (1 if complexity in ("high", "critical") else 0)), 1)

    # Time to value (hours)
    step_time = {"low": 0.1, "medium": 0.3, "high": 0.8, "critical": 2.0}.get(complexity, 0.3)
    result.time_to_value_hours = round(plan_steps * step_time, 1)

    # Probability of success: from performance data if available
    try:
        from core.mission_performance_tracker import get_mission_performance_tracker
        mpt = get_mission_performance_tracker()
        strategy = mpt.get_strategy_for_type(mission_type)
        if strategy and strategy.get("sample_size", 0) >= 3:
            result.probability_of_success = round(strategy["success_rate"], 2)
        else:
            result.probability_of_success = 0.6  # default moderate
    except Exception:
        result.probability_of_success = 0.6

    # Expected return: (value × probability) / (cost + time + risk_penalty)
    risk_penalty = result.estimated_risk * 0.3
    denominator = max(result.estimated_cost + result.time_to_value_hours + risk_penalty, 0.1)
    result.expected_return = round(
        (result.estimated_value * result.probability_of_success) / denominator, 3
    )

    # Priority score (normalized 0-1)
    result.priority_score = round(min(1.0, result.expected_return / 3.0), 3)

    result.reasoning = (
        f"V={result.estimated_value} × P={result.probability_of_success:.0%} "
        f"/ (C={result.estimated_cost} + T={result.time_to_value_hours}h + R={risk_penalty:.1f}) "
        f"= ER={result.expected_return}"
    )
    return result


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


# ═══════════════════════════════════════════════════════════════
# 9. OPPORTUNITY DETECTION
# ═══════════════════════════════════════════════════════════════

@dataclass
class OpportunitySuggestion:
    """An advisory suggestion for a potential initiative."""
    problem: str = ""
    proposed_solution: str = ""
    estimated_value: str = "medium"  # low/medium/high
    estimated_complexity: str = "medium"
    confidence: float = 0.0
    source: str = ""  # "tool_gap", "failure_pattern", "repetition"
    required_tools: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# Rate limiter for opportunity detection
_last_opportunity_scan: float = 0.0
_OPPORTUNITY_SCAN_INTERVAL = 300  # 5 minutes
_MAX_SUGGESTIONS = 10


def detect_opportunities() -> list[OpportunitySuggestion]:
    """Detect operational opportunities from system patterns. Advisory only."""
    global _last_opportunity_scan
    now = time.time()
    if (now - _last_opportunity_scan) < _OPPORTUNITY_SCAN_INTERVAL:
        return []
    _last_opportunity_scan = now

    suggestions = []

    # 1. Detect missing tools (repeatedly needed but unavailable)
    try:
        from core.tool_gap_analyzer import get_tool_gap_analyzer
        tga = get_tool_gap_analyzer()
        gaps = tga.get_unmet_needs()
        for gap in gaps[:3]:
            suggestions.append(OpportunitySuggestion(
                problem=f"Tool '{gap.get('tool', 'unknown')}' needed but unreliable or missing",
                proposed_solution=f"Build or integrate a reliable {gap.get('category', 'unknown')} tool",
                estimated_value="medium",
                estimated_complexity="medium",
                confidence=0.6,
                source="tool_gap",
                required_tools=[gap.get("tool", "")],
            ))
    except Exception:
        _silent_log.debug("suppressed_exception", src='operating_primitives.py')

    # 2. Detect repeated failure patterns
    try:
        from core.mission_performance_tracker import get_mission_performance_tracker
        mpt = get_mission_performance_tracker()
        for mtype, stats in list(mpt._type_stats.items())[:20]:
            if stats.total >= 5 and stats.success_rate < 0.4:
                suggestions.append(OpportunitySuggestion(
                    problem=f"Mission type '{mtype}' has low success rate ({stats.success_rate:.0%})",
                    proposed_solution=f"Improve strategy for {mtype}: better tools or agents",
                    estimated_value="high",
                    estimated_complexity="medium",
                    confidence=0.7,
                    source="failure_pattern",
                ))
    except Exception:
        _silent_log.debug("suppressed_exception", src='operating_primitives.py')

    # 3. Detect automation opportunities (high-frequency mission types)
    try:
        from core.mission_performance_tracker import get_mission_performance_tracker
        mpt = get_mission_performance_tracker()
        for mtype, stats in list(mpt._type_stats.items())[:20]:
            if stats.total >= 10 and stats.success_rate >= 0.7:
                suggestions.append(OpportunitySuggestion(
                    problem=f"'{mtype}' is frequent ({stats.total} missions) with high success",
                    proposed_solution=f"Create automated workflow template for {mtype}",
                    estimated_value="high",
                    estimated_complexity="low",
                    confidence=0.8,
                    source="repetition",
                ))
    except Exception:
        _silent_log.debug("suppressed_exception", src='operating_primitives.py')

    return suggestions[:_MAX_SUGGESTIONS]


# ═══════════════════════════════════════════════════════════════
# 10. WORKFLOW TEMPLATES
# ═══════════════════════════════════════════════════════════════

@dataclass
class WorkflowTemplate:
    """Reusable workflow structure."""
    template_id: str = ""
    name: str = ""
    mission_type: str = ""
    phases: list = field(default_factory=list)  # ["research", "decision", "execution", "verification"]
    tools_per_phase: dict = field(default_factory=dict)
    success_rate: float = 0.0
    uses: int = 0
    last_used: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


# Standard workflow phases
STANDARD_PHASES = ["research", "decision", "execution", "verification", "iteration"]
MAX_WORKFLOW_DEPTH = 10  # Max phases per workflow


class WorkflowTemplateStore:
    """Store and retrieve proven workflow templates."""
    MAX_TEMPLATES = 50
    PERSIST_FILE = "workspace/workflow_templates.json"

    def __init__(self, persist_path: Optional[str] = None):
        self._templates: dict[str, WorkflowTemplate] = {}
        self._persist_path = persist_path or self.PERSIST_FILE
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            self.load()
            self._loaded = True

    def record_successful_workflow(
        self,
        mission_type: str,
        tools_used: list[str],
        phases_executed: list[str],
    ):
        """Record a successful workflow as a template."""
        self._ensure_loaded()
        key = f"{mission_type}:{','.join(sorted(set(phases_executed)))}"
        if key in self._templates:
            t = self._templates[key]
            t.uses += 1
            t.success_rate = min(1.0, t.success_rate + 0.05)
            t.last_used = time.time()
        else:
            if len(self._templates) >= self.MAX_TEMPLATES:
                oldest_key = min(self._templates, key=lambda k: self._templates[k].last_used)
                del self._templates[oldest_key]
            import uuid
            t = WorkflowTemplate(
                template_id=str(uuid.uuid4())[:8],
                name=f"{mission_type} workflow",
                mission_type=mission_type,
                phases=phases_executed[:MAX_WORKFLOW_DEPTH],
                tools_per_phase={p: tools_used for p in phases_executed},
                success_rate=0.6,
                uses=1,
                last_used=time.time(),
            )
            self._templates[key] = t
        self.save()

    def get_best_template(self, mission_type: str) -> Optional[WorkflowTemplate]:
        """Get the most effective template for a mission type."""
        self._ensure_loaded()
        candidates = [
            t for t in self._templates.values()
            if t.mission_type == mission_type and t.uses >= 2
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda t: t.success_rate * t.uses)

    def get_all(self) -> list[dict]:
        self._ensure_loaded()
        return [t.to_dict() for t in sorted(
            self._templates.values(), key=lambda t: t.uses, reverse=True
        )[:20]]

    def save(self):
        try:
            import json
            os.makedirs(os.path.dirname(self._persist_path) or ".", exist_ok=True)
            with open(self._persist_path, "w") as f:
                json.dump({k: v.to_dict() for k, v in self._templates.items()}, f, indent=2)
        except Exception as e:
            logger.warning("workflow_save_failed: %s", str(e)[:80])

    def load(self):
        import json
        if not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path) as f:
                data = json.load(f)
            for key, d in data.items():
                self._templates[key] = WorkflowTemplate(
                    **{k: v for k, v in d.items() if k in WorkflowTemplate.__dataclass_fields__}
                )
        except Exception as e:
            logger.warning("workflow_load_failed: %s", str(e)[:80])


_workflow_store: Optional[WorkflowTemplateStore] = None

def get_workflow_store() -> WorkflowTemplateStore:
    global _workflow_store
    if _workflow_store is None:
        _workflow_store = WorkflowTemplateStore()
    return _workflow_store


# ═══════════════════════════════════════════════════════════════
# 11. APPROVAL GATING (Supervised Autonomy)
# ═══════════════════════════════════════════════════════════════

# Actions requiring explicit approval
APPROVAL_REQUIRED_ACTIONS = {
    "external_api",       # HTTP calls to external services
    "financial",          # Any money-related action
    "publish",            # Publishing content externally
    "communicate",        # Sending emails/messages
    "deploy",             # Deploying code/services
    "persistent_workflow", # Creating scheduled/persistent workflows
}


def requires_approval(action_type: str, risk_level: str = "low") -> bool:
    """Check if an action requires human approval."""
    if action_type in APPROVAL_REQUIRED_ACTIONS:
        return True
    if risk_level in ("high", "critical"):
        return True
    # Read-only mode requires approval for everything
    if os.environ.get("JARVIS_DISABLE_READ_ONLY_MODE", "").lower() in ("1", "true"):
        return True
    return False


# ═══════════════════════════════════════════════════════════════
# 12. ECONOMIC EXECUTION TRACKING
# ═══════════════════════════════════════════════════════════════

_economic_history: list[dict] = []
_MAX_ECONOMIC_HISTORY = 200


def record_economic_outcome(
    mission_id: str,
    estimated: EconomicEstimate,
    actual_success: bool,
    actual_duration_s: float,
    actual_tools_used: int,
):
    """Record estimated vs actual economic signals."""
    global _economic_history
    actual_cost = min(10, actual_tools_used * 0.5 + actual_duration_s / 60)
    realized_value = estimated.estimated_value if actual_success else 0
    efficiency = realized_value / max(actual_cost, 0.1)

    record = {
        "mission_id": mission_id,
        "estimated_return": estimated.expected_return,
        "actual_success": actual_success,
        "actual_cost": round(actual_cost, 2),
        "realized_value": round(realized_value, 1),
        "efficiency": round(efficiency, 3),
        "estimation_accuracy": round(
            1.0 - abs(estimated.estimated_cost - actual_cost) / max(estimated.estimated_cost, 1), 2
        ),
        "timestamp": time.time(),
    }
    _economic_history.append(record)
    if len(_economic_history) > _MAX_ECONOMIC_HISTORY:
        _economic_history = _economic_history[-_MAX_ECONOMIC_HISTORY:]
    return record


def get_economic_trends() -> dict:
    """Get economic performance trends."""
    if not _economic_history:
        return {"total": 0, "avg_efficiency": 0, "avg_accuracy": 0, "trend": "insufficient_data"}

    recent = _economic_history[-50:]
    avg_eff = sum(r["efficiency"] for r in recent) / len(recent)
    avg_acc = sum(r["estimation_accuracy"] for r in recent) / len(recent)
    success_rate = sum(1 for r in recent if r["actual_success"]) / len(recent)

    # Trend: compare first half vs second half
    if len(recent) >= 10:
        first_half = recent[:len(recent)//2]
        second_half = recent[len(recent)//2:]
        first_eff = sum(r["efficiency"] for r in first_half) / len(first_half)
        second_eff = sum(r["efficiency"] for r in second_half) / len(second_half)
        trend = "improving" if second_eff > first_eff * 1.1 else "declining" if second_eff < first_eff * 0.9 else "stable"
    else:
        trend = "insufficient_data"

    return {
        "total": len(_economic_history),
        "avg_efficiency": round(avg_eff, 3),
        "avg_accuracy": round(avg_acc, 3),
        "success_rate": round(success_rate, 3),
        "trend": trend,
        "recent_count": len(recent),
    }


def get_approval_status() -> dict:
    """Return approval gating state for cockpit."""
    return {
        "approval_required_actions": list(APPROVAL_REQUIRED_ACTIONS),
        "read_only_mode": os.environ.get("JARVIS_DISABLE_READ_ONLY_MODE", "") in ("1", "true"),
        "auto_approve_low_risk": not os.environ.get("JARVIS_REQUIRE_ALL_APPROVAL", ""),
    }


# ═══════════════════════════════════════════════════════════════
# BUSINESS OPERATING LOOP
# ═══════════════════════════════════════════════════════════════

@dataclass
class FocusRecommendation:
    """What Jarvis recommends the user focus on."""
    action: str = ""          # continue | slow_down | stop | reallocate | automate | outreach
    objective_id: str = ""
    reason: str = ""
    priority: float = 0.0     # 0-1
    estimated_value: float = 0.0
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "objective_id": self.objective_id,
            "reason": self.reason,
            "priority": round(self.priority, 3),
            "estimated_value": round(self.estimated_value, 1),
            "confidence": round(self.confidence, 2),
        }


def recommend_focus() -> list[FocusRecommendation]:
    """
    Analyze objectives + pipeline + economics to recommend focus areas.
    Returns prioritized list of recommendations.
    """
    recommendations = []

    # 1. Check objectives
    try:
        tracker = get_objective_tracker()
        active = tracker.list_active()
        for obj in active[:10]:
            if obj.total_missions >= 5 and obj.success_rate < 0.3:
                recommendations.append(FocusRecommendation(
                    action="stop",
                    objective_id=obj.objective_id,
                    reason=f"Low success rate ({obj.success_rate:.0%}) after {obj.total_missions} missions",
                    priority=0.8,
                    confidence=0.7,
                ))
            elif obj.total_missions >= 3 and obj.success_rate >= 0.8:
                recommendations.append(FocusRecommendation(
                    action="continue",
                    objective_id=obj.objective_id,
                    reason=f"Strong performance ({obj.success_rate:.0%})",
                    priority=0.6,
                    estimated_value=obj.estimated_value,
                    confidence=0.8,
                ))
    except Exception:
        _silent_log.debug("suppressed_exception", src='operating_primitives.py')

    # 2. Check business pipeline
    try:
        from core.business_pipeline import get_lead_tracker
        lt = get_lead_tracker()
        summary = lt.get_pipeline_summary()

        if summary["active_leads"] == 0:
            recommendations.append(FocusRecommendation(
                action="outreach",
                reason="No active leads — prospecting needed",
                priority=0.9,
                confidence=0.9,
            ))

        early = (summary["by_stage"].get("lead", {}).get("count", 0) +
                 summary["by_stage"].get("qualified", {}).get("count", 0))
        if early > 5:
            recommendations.append(FocusRecommendation(
                action="continue",
                reason=f"{early} leads need follow-up",
                priority=0.7,
                estimated_value=summary["total_pipeline_value"],
                confidence=0.6,
            ))
    except Exception:
        _silent_log.debug("suppressed_exception", src='operating_primitives.py')

    # 3. Check economic trends
    try:
        trends = get_economic_trends()
        if trends["trend"] == "declining":
            recommendations.append(FocusRecommendation(
                action="reallocate",
                reason="Economic efficiency declining — review resource allocation",
                priority=0.8,
                confidence=0.6,
            ))
    except Exception:
        _silent_log.debug("suppressed_exception", src='operating_primitives.py')

    # 4. Check workflow templates for automation opportunities
    try:
        store = get_workflow_store()
        templates = store.get_all()
        reusable = [t for t in templates if t.success_count >= 3]
        if reusable:
            top = max(reusable, key=lambda t: t.success_count)
            recommendations.append(FocusRecommendation(
                action="automate",
                reason=f"Workflow '{top.mission_type}' succeeded {top.success_count}x — consider automating",
                priority=0.5,
                confidence=0.7,
            ))
    except Exception:
        _silent_log.debug("suppressed_exception", src='operating_primitives.py')

    # Sort by priority
    recommendations.sort(key=lambda r: r.priority, reverse=True)
    return recommendations[:10]


def suggest_playbooks() -> list[dict]:
    """
    Suggest reusable playbooks based on proven workflow patterns.
    Returns structured playbook suggestions.
    """
    playbooks = []

    try:
        store = get_workflow_store()
        templates = store.get_all()
        for t in sorted(templates, key=lambda x: x.success_count, reverse=True)[:10]:
            if t.success_count < 2:
                continue
            playbooks.append({
                "name": f"Playbook: {t.mission_type}",
                "mission_type": t.mission_type,
                "tools": t.tools_used[:8],
                "phases": t.phases[:6],
                "success_count": t.success_count,
                "reusable": t.success_count >= 3,
                "suggestion": (
                    f"This workflow has been successful {t.success_count} times. "
                    f"Use tools: {', '.join(t.tools_used[:4])}."
                ),
            })
    except Exception:
        _silent_log.debug("suppressed_exception", src='operating_primitives.py')

    # Also check mission memory for effective sequences
    try:
        from core.mission_memory import get_mission_memory
        mm = get_mission_memory()
        for mission_type in ["coding_task", "research_task", "debug_task", "business_task"]:
            seqs = mm.get_effective_sequences(mission_type, top_k=2)
            for seq in seqs:
                playbooks.append({
                    "name": f"Pattern: {mission_type}",
                    "mission_type": mission_type,
                    "tools": seq.get("tools", [])[:8],
                    "phases": seq.get("agents", [])[:6],
                    "success_count": seq.get("count", 0),
                    "reusable": True,
                    "suggestion": f"Effective tool sequence for {mission_type}",
                })
    except Exception:
        _silent_log.debug("suppressed_exception", src='operating_primitives.py')

    return playbooks[:15]


def get_operating_summary() -> dict:
    """
    Complete operating summary: objectives + economics + pipeline + recommendations.
    Single endpoint for full business intelligence.
    """
    focus = recommend_focus()
    playbooks = suggest_playbooks()
    economic_trends = get_economic_trends()

    # Objective status
    obj_dashboard = {}
    try:
        obj_dashboard = get_objective_tracker().get_dashboard()
    except Exception:
        _silent_log.debug("suppressed_exception", src='operating_primitives.py')

    # Pipeline status
    pipeline = {}
    try:
        from core.business_pipeline import get_lead_tracker
        pipeline = get_lead_tracker().get_pipeline_summary()
    except Exception:
        _silent_log.debug("suppressed_exception", src='operating_primitives.py')

    # Budget
    budget = {}
    try:
        from core.business_pipeline import get_budget_tracker
        budget = get_budget_tracker().get_summary()
    except Exception:
        _silent_log.debug("suppressed_exception", src='operating_primitives.py')

    return {
        "objectives": obj_dashboard,
        "pipeline": pipeline,
        "budget": budget,
        "economics": economic_trends,
        "recommendations": [r.to_dict() for r in focus],
        "playbooks": playbooks,
        "approval_status": get_approval_status(),
    }
