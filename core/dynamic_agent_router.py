"""
JARVIS — Dynamic Agent Router
=================================
Replaces static agent selection with measured specialization signals.

Called from AgentSelector.select_agents() as an intelligence overlay.
Falls back to static MISSION_ROUTING when insufficient data.

Data sources (all fail-open):
1. mission_performance_tracker — per-agent domain success rates
2. tool_performance_tracker — which tools are healthy (affects agent utility)
3. decision_memory — historical pattern stats

Routing logic:
1. Get candidate agents from MISSION_ROUTING (static base)
2. Score each candidate using real performance data
3. Rerank by measured effectiveness
4. Add high-performers not in static list if data supports it
5. Remove consistent underperformers if alternatives exist

Feature flag: JARVIS_DYNAMIC_ROUTING=1 (default OFF)

Minimum data threshold: 5 missions of same type before overriding static routing.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("jarvis.dynamic_routing")

# Minimum missions before we trust performance data for a type
MIN_DATA_THRESHOLD = 5
# Minimum agent missions before we trust agent-level data
MIN_AGENT_MISSIONS = 3
# Score below which an agent is considered underperforming
UNDERPERFORM_THRESHOLD = 0.35
# Score above which an agent is boosted into selection
BOOST_THRESHOLD = 0.75


def is_enabled() -> bool:
    return os.environ.get("JARVIS_DYNAMIC_ROUTING", "").lower() in ("1", "true", "yes")


@dataclass
class AgentScore:
    """Scored agent candidate."""
    agent: str
    base_score: float         # 0.5 if in static routing, 0.3 if not
    perf_score: float         # from mission_performance_tracker
    domain_score: float       # domain-specific success rate
    tool_health_bonus: float  # bonus if agent's tools are healthy
    final_score: float = 0.0
    data_points: int = 0
    source: str = ""          # "static", "performance", "boost", "fallback"

    def compute_final(self):
        """Weighted: performance 50%, domain 30%, base 15%, tool health 5%."""
        if self.data_points < MIN_AGENT_MISSIONS:
            # Insufficient data — lean on static routing
            self.final_score = self.base_score * 0.7 + self.perf_score * 0.3
            self.source = "fallback"
        else:
            self.final_score = (
                self.perf_score * 0.50
                + self.domain_score * 0.30
                + self.base_score * 0.15
                + self.tool_health_bonus * 0.05
            )
            self.source = "performance"


def route_agents(
    goal: str,
    mission_type: str,
    complexity: str,
    risk_level: str,
    static_candidates: list[str],
    max_agents: int = 5,
) -> list[str]:
    """
    Dynamic agent routing using real performance data.

    Args:
        goal: mission goal text
        mission_type: classified mission type
        complexity: low/medium/high
        risk_level: LOW/MEDIUM/HIGH
        static_candidates: agents from MISSION_ROUTING (fallback)
        max_agents: maximum agents to return

    Returns:
        Reranked list of agents. Always returns at least 1 agent.
    """
    if not is_enabled():
        return static_candidates

    if not static_candidates:
        return static_candidates

    try:
        return _route_with_data(
            goal, mission_type, complexity, risk_level,
            static_candidates, max_agents,
        )
    except Exception as e:
        logger.warning("dynamic_routing_fallback", err=str(e)[:80])
        return static_candidates


def _route_with_data(
    goal: str,
    mission_type: str,
    complexity: str,
    risk_level: str,
    static_candidates: list[str],
    max_agents: int,
) -> list[str]:
    """Internal routing logic with performance data."""

    # All known agents
    ALL_AGENTS = [
        "scout-research", "map-planner", "shadow-advisor",
        "forge-builder", "lens-reviewer", "vault-memory", "pulse-ops",
    ]

    # 1. Get performance data
    mission_tracker = _get_mission_tracker()
    tool_tracker = _get_tool_tracker()

    # 2. Check data sufficiency
    type_stats = None
    if mission_tracker:
        type_stats = mission_tracker._type_stats.get(mission_type)

    has_enough_data = (
        type_stats is not None
        and type_stats.total >= MIN_DATA_THRESHOLD
    )

    if not has_enough_data:
        logger.debug(
            "dynamic_routing_insufficient_data",
            mission_type=mission_type,
            data_points=type_stats.total if type_stats else 0,
        )
        return static_candidates

    # 3. Score all candidate agents
    candidates = list(set(static_candidates + ALL_AGENTS))
    scores: list[AgentScore] = []

    for agent in candidates:
        score = _score_agent(
            agent, mission_type, complexity,
            static_candidates, mission_tracker, tool_tracker,
        )
        scores.append(score)

    # 4. Sort by final score
    scores.sort(key=lambda s: s.final_score, reverse=True)

    # 5. Build result
    result = []
    removed = []

    for s in scores:
        if len(result) >= max_agents:
            break

        # Skip underperformers IF alternatives exist
        if (
            s.data_points >= MIN_AGENT_MISSIONS
            and s.final_score < UNDERPERFORM_THRESHOLD
            and s.agent in static_candidates
            and len(result) >= 1  # always keep at least 1
        ):
            removed.append(s.agent)
            continue

        # Include if: in static list, or high performer with data
        if s.agent in static_candidates:
            result.append(s.agent)
        elif s.final_score >= BOOST_THRESHOLD and s.data_points >= MIN_AGENT_MISSIONS:
            result.append(s.agent)

    # Safety: always return at least 1 agent
    if not result:
        result = static_candidates[:1]

    # Complexity cap
    if complexity == "low":
        result = result[:1]
    elif complexity == "medium":
        result = result[:3]

    if removed:
        logger.info(
            "dynamic_routing_removed_underperformers",
            removed=removed,
            mission_type=mission_type,
        )

    if result != static_candidates:
        logger.info(
            "dynamic_routing_override",
            static=static_candidates,
            dynamic=result,
            mission_type=mission_type,
        )

    return result


def _score_agent(
    agent: str,
    mission_type: str,
    complexity: str,
    static_candidates: list[str],
    mission_tracker,
    tool_tracker,
) -> AgentScore:
    """Score a single agent for this mission context."""

    # Base score: higher if in static routing
    base = 0.5 if agent in static_candidates else 0.3

    # Performance score from mission tracker
    perf = 0.5  # neutral default
    domain = 0.5
    data_points = 0

    if mission_tracker:
        agent_stats = mission_tracker._agent_stats.get(agent)
        if agent_stats and agent_stats.total_missions > 0:
            perf = agent_stats.success_rate
            data_points = agent_stats.total_missions
            domain = agent_stats.domain_success_rate(mission_type)

    # Tool health bonus
    tool_bonus = 0.0
    if tool_tracker:
        # Check if agent's typical tools are healthy
        _agent_tools = _get_agent_tools(agent, mission_type)
        if _agent_tools:
            healthy = sum(
                1 for t in _agent_tools
                if (tool_tracker.get_stats(t) or type('X', (), {'health_status': 'unknown'})()).health_status == "healthy"  # noqa
            )
            tool_bonus = healthy / max(len(_agent_tools), 1)

    score = AgentScore(
        agent=agent,
        base_score=base,
        perf_score=perf,
        domain_score=domain,
        tool_health_bonus=tool_bonus,
        data_points=data_points,
    )
    score.compute_final()
    return score


def _get_agent_tools(agent: str, mission_type: str) -> list[str]:
    """Return tools typically used by an agent for a mission type."""
    # Static mapping — could be enriched by performance data later
    _AGENT_TOOL_MAP = {
        "forge-builder":   ["write_file", "run_command_safe", "search_codebase"],
        "scout-research":  ["search_codebase", "read_file", "vector_search"],
        "lens-reviewer":   ["read_file", "search_codebase"],
        "map-planner":     ["read_file", "search_codebase"],
        "shadow-advisor":  ["read_file", "check_logs"],
        "pulse-ops":       ["check_logs", "run_command_safe", "test_endpoint"],
        "vault-memory":    ["vector_search", "read_file"],
    }
    return _AGENT_TOOL_MAP.get(agent, [])


def _get_mission_tracker():
    try:
        from core.mission_performance_tracker import get_mission_performance_tracker
        return get_mission_performance_tracker()
    except ImportError:
        return None


def _get_tool_tracker():
    try:
        from core.tool_performance_tracker import get_tool_performance_tracker
        return get_tool_performance_tracker()
    except ImportError:
        return None


# ═══════════════════════════════════════════════════════════════
# Agent Performance Query API (for planner + UI)
# ═══════════════════════════════════════════════════════════════

def get_agent_specialization_map() -> dict:
    """
    Returns agent specialization data for UI display.
    Shows each agent's domain performance and reliability.
    """
    result = {"agents": [], "data_sufficient": False}

    try:
        mt = _get_mission_tracker()
        if not mt:
            return result

        total_missions = sum(s.total for s in mt._type_stats.values())
        result["data_sufficient"] = total_missions >= MIN_DATA_THRESHOLD

        for agent, stats in mt._agent_stats.items():
            domains = {}
            for mt_name, counts in stats.domain_success.items():
                if len(counts) >= 2 and counts[1] >= 2:
                    domains[mt_name] = {
                        "success_rate": round(counts[0] / max(counts[1], 1), 3),
                        "missions": counts[1],
                    }

            best_domain = max(domains.items(), key=lambda x: x[1]["success_rate"])[0] if domains else ""
            worst_domain = min(domains.items(), key=lambda x: x[1]["success_rate"])[0] if domains else ""

            result["agents"].append({
                "agent": agent,
                "total_missions": stats.total_missions,
                "overall_success_rate": round(stats.success_rate, 3),
                "domains": domains,
                "best_domain": best_domain,
                "worst_domain": worst_domain if worst_domain != best_domain else "",
                "reliability": "high" if stats.success_rate >= 0.8 else
                              "medium" if stats.success_rate >= 0.5 else "low",
            })

        result["agents"].sort(key=lambda a: a["total_missions"], reverse=True)
    except Exception as e:
        logger.debug("specialization_map_err", err=str(e)[:60])

    return result


def get_routing_explanation(
    mission_type: str,
    complexity: str,
    static_agents: list[str],
) -> dict:
    """
    Explain why specific agents were chosen.
    Used for mission reasoning panel in UI.
    """
    explanation = {
        "mission_type": mission_type,
        "complexity": complexity,
        "routing_mode": "static",
        "agents": [],
    }

    if is_enabled():
        explanation["routing_mode"] = "dynamic"

    mt = _get_mission_tracker()
    if not mt:
        explanation["agents"] = [
            {"agent": a, "reason": "static routing (no performance data)"}
            for a in static_agents
        ]
        return explanation

    for agent in static_agents:
        agent_stats = mt._agent_stats.get(agent)
        if agent_stats and agent_stats.total_missions >= MIN_AGENT_MISSIONS:
            domain_rate = agent_stats.domain_success_rate(mission_type)
            explanation["agents"].append({
                "agent": agent,
                "reason": f"domain success: {domain_rate:.0%} over {agent_stats.total_missions} missions",
                "success_rate": round(agent_stats.success_rate, 3),
                "domain_rate": round(domain_rate, 3),
                "data_points": agent_stats.total_missions,
            })
        else:
            explanation["agents"].append({
                "agent": agent,
                "reason": "static routing (insufficient data)",
                "data_points": agent_stats.total_missions if agent_stats else 0,
            })

    return explanation


# ═══════════════════════════════════════════════════════════════
# MULTIMODAL ROUTING
# ═══════════════════════════════════════════════════════════════

# Keywords that indicate multimodal input
_IMAGE_KEYWORDS = {"image", "photo", "picture", "screenshot", "diagram", "visual", "draw", "generate image"}
_AUDIO_KEYWORDS = {"audio", "voice", "transcribe", "speech", "listen", "recording", "podcast"}
_DOCUMENT_KEYWORDS = {"document", "pdf", "file", "spreadsheet", "csv", "report"}

# Multimodal capability mapping — which agents handle multimodal
MULTIMODAL_AGENTS = {
    "image": ["forge-builder", "scout-research"],
    "audio": ["scout-research", "shadow-advisor"],
    "document": ["scout-research", "vault-memory"],
}


def detect_multimodal_type(goal: str) -> Optional[str]:
    """Detect if a goal requires multimodal processing."""
    goal_lower = goal.lower()
    for kw in _IMAGE_KEYWORDS:
        if kw in goal_lower:
            return "image"
    for kw in _AUDIO_KEYWORDS:
        if kw in goal_lower:
            return "audio"
    for kw in _DOCUMENT_KEYWORDS:
        if kw in goal_lower:
            return "document"
    return None


def get_multimodal_agents(modal_type: str) -> list[str]:
    """Get agents capable of handling a multimodal type."""
    return MULTIMODAL_AGENTS.get(modal_type, [])
