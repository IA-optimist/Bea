"""
BEA — Coordination Primitives (sections 5, 6, 9, 11, business loop)
Mission coordination, operational signals, opportunity detection,
approval gating, and business focus recommendations.
"""
from __future__ import annotations

import os
import time
import structlog
from dataclasses import asdict, dataclass, field

logger = structlog.get_logger("bea.operating_primitives")
log = logger

# ═══════════════════════════════════════════════════════════════
# 5. MISSION COORDINATION
# ═══════════════════════════════════════════════════════════════

MAX_CONCURRENT_MISSIONS = int(os.environ.get("BEA_MAX_CONCURRENT", "5"))


def can_accept_mission(current_active: int) -> bool:
    """Check if system can accept another mission."""
    return current_active < MAX_CONCURRENT_MISSIONS


def prioritize_missions(missions: list[dict]) -> list[dict]:
    """Sort missions by priority: feasibility × value."""
    from core.primitives.scoring import score_feasibility, estimate_value
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
        mpt.get_dashboard_data()
        signals["mission_success_distribution"] = {
            t: {"success_rate": s.success_rate, "total": s.total}
            for t, s in mpt._type_stats.items()
        }
    except Exception as _exc:
        log.warning("swallowed_exception", action="mission_pattern_type_stats", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    try:
        from core.mission_memory import get_mission_memory
        mm = get_mission_memory()
        for s in list(mm._strategies.values())[:20]:
            signals["strategy_effectiveness"][s.mission_type] = {
                "confidence": s.confidence,
                "success_rate": s.success_rate,
            }
    except Exception as _exc:
        log.warning("swallowed_exception", action="strategy_success_rate_table", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    try:
        from core.tool_performance_tracker import get_tool_performance_tracker
        tpt = get_tool_performance_tracker()
        for name, stats in list(tpt.get_all_stats().items())[:20]:
            signals["tool_impact"][name] = {
                "success_rate": stats.success_rate,
                "total_calls": stats.total_calls,
                "health": stats.health_status,
            }
    except Exception as _exc:
        log.warning("swallowed_exception", action="connector_health_stats", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    try:
        from core.execution_engine import get_telemetry_summary
        ts = get_telemetry_summary()
        signals["execution_stability"] = ts.get("avg_stability", 0)
        signals["planning_confidence"] = ts.get("avg_success_rate", 0)
    except Exception as _exc:
        log.warning("swallowed_exception", action="execution_stability_signals", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    try:
        from core.primitives.objectives import get_objective_tracker
        tracker = get_objective_tracker()
        d = tracker.get_dashboard()
        if d["total"] > 0:
            signals["long_horizon_ratio"] = round(d["completed"] / max(d["total"], 1), 3)
    except Exception as _exc:
        log.warning("swallowed_exception", action="long_horizon_ratio", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    return signals


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
    except Exception as _exc:
        log.warning("swallowed_exception", action="tool_gap_inference", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

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
    except Exception as _exc:
        log.warning("swallowed_exception", action="failure_pattern_inference", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

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
    except Exception as _exc:
        log.warning("swallowed_exception", action="repetition_pattern_inference", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    return suggestions[:_MAX_SUGGESTIONS]


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
    if os.environ.get("BEA_DISABLE_READ_ONLY_MODE", "").lower() in ("1", "true"):
        return True
    return False


def get_approval_status() -> dict:
    """Return approval gating state for cockpit."""
    return {
        "approval_required_actions": list(APPROVAL_REQUIRED_ACTIONS),
        "read_only_mode": os.environ.get("BEA_DISABLE_READ_ONLY_MODE", "") in ("1", "true"),
        "auto_approve_low_risk": not os.environ.get("BEA_REQUIRE_ALL_APPROVAL", ""),
    }


# ═══════════════════════════════════════════════════════════════
# BUSINESS OPERATING LOOP
# ═══════════════════════════════════════════════════════════════

@dataclass
class FocusRecommendation:
    """What Bea recommends the user focus on."""
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
        from core.primitives.objectives import get_objective_tracker
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
    except Exception as _exc:
        log.warning("swallowed_exception", action="convergence_inference", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

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
    except Exception as _exc:
        log.warning("swallowed_exception", action="capability_gap_inference", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # 3. Check economic trends
    try:
        from core.primitives.economics import get_economic_trends
        trends = get_economic_trends()
        if trends["trend"] == "declining":
            recommendations.append(FocusRecommendation(
                action="reallocate",
                reason="Economic efficiency declining — review resource allocation",
                priority=0.8,
                confidence=0.6,
            ))
    except Exception as _exc:
        log.warning("swallowed_exception", action="cost_pattern_inference", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # 4. Check workflow templates for automation opportunities
    try:
        from core.primitives.workflows import get_workflow_store
        store = get_workflow_store()
        templates = store.get_all()
        reusable = [t for t in templates if t.get("uses", 0) >= 3]
        if reusable:
            top = max(reusable, key=lambda t: t.get("uses", 0))
            recommendations.append(FocusRecommendation(
                action="automate",
                reason=f"Workflow '{top.get('mission_type','')}' succeeded {top.get('uses',0)}x — consider automating",
                priority=0.5,
                confidence=0.7,
            ))
    except Exception as _exc:
        log.warning("swallowed_exception", action="health_degradation_inference", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

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
        from core.primitives.workflows import get_workflow_store
        store = get_workflow_store()
        templates = store.get_all()
        for t in sorted(templates, key=lambda x: x.get("uses", 0), reverse=True)[:10]:
            if t.get("uses", 0) < 2:
                continue
            tools_used = list(t.get("tools_per_phase", {}).values())
            flat_tools: list[str] = []
            for v in tools_used:
                if isinstance(v, list):
                    flat_tools.extend(v)
                elif isinstance(v, str):
                    flat_tools.append(v)
            flat_tools = list(dict.fromkeys(flat_tools))  # dedupe preserving order

            playbooks.append({
                "name": f"Playbook: {t.get('mission_type','')}",
                "mission_type": t.get("mission_type", ""),
                "tools": flat_tools[:8],
                "phases": t.get("phases", [])[:6],
                "success_count": t.get("uses", 0),
                "reusable": t.get("uses", 0) >= 3,
                "suggestion": (
                    f"This workflow has been successful {t.get('uses', 0)} times. "
                    f"Use tools: {', '.join(flat_tools[:4])}."
                ),
            })
    except Exception as _exc:
        log.warning("swallowed_exception", action="learning_opportunity_inference", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

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
    except Exception as _exc:
        log.warning("swallowed_exception", action="effective_tool_sequence", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    return playbooks[:15]


def get_operating_summary() -> dict:
    """
    Complete operating summary: objectives + economics + pipeline + recommendations.
    Single endpoint for full business intelligence.
    """
    from core.primitives.economics import get_economic_trends
    from core.primitives.objectives import get_objective_tracker

    focus = recommend_focus()
    playbooks = suggest_playbooks()
    economic_trends = get_economic_trends()

    # Objective status
    obj_dashboard = {}
    try:
        obj_dashboard = get_objective_tracker().get_dashboard()
    except Exception as _exc:
        log.warning("swallowed_exception", action="objective_dashboard_fetch", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # Pipeline status
    pipeline = {}
    try:
        from core.business_pipeline import get_lead_tracker
        pipeline = get_lead_tracker().get_pipeline_summary()
    except Exception as _exc:
        log.warning("swallowed_exception", action="pipeline_summary_fetch", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # Budget
    budget = {}
    try:
        from core.business_pipeline import get_budget_tracker
        budget = get_budget_tracker().get_summary()
    except Exception as _exc:
        log.warning("swallowed_exception", action="budget_summary_fetch", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    return {
        "objectives": obj_dashboard,
        "pipeline": pipeline,
        "budget": budget,
        "economics": economic_trends,
        "recommendations": [r.to_dict() for r in focus],
        "playbooks": playbooks,
        "approval_status": get_approval_status(),
    }
