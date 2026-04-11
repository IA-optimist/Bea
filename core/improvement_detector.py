"""
JARVIS — Improvement Detector
=================================
Scans real performance data and generates improvement proposals.

Called periodically (from heartbeat, status endpoint, or manual trigger).
Reads from: tool_performance_tracker, mission_performance_tracker.
Writes to: improvement_proposals (ProposalStore).

Detections:
1. Repeatedly failing tools → propose retry-wrap or replacement
2. Failing mission types → propose planning adjustments
3. Underperforming agents → propose routing changes
4. Missing tool capabilities → propose new tools
5. Latency outliers → propose caching or optimization

All proposals go through the approval queue — nothing auto-executes.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional
_silent_log = __import__("structlog").get_logger(__name__)

logger = logging.getLogger("jarvis.improvement_detector")


# Rate limiter: minimum seconds between detection runs
_MIN_DETECTION_INTERVAL = int(os.environ.get("JARVIS_DETECTION_INTERVAL", "60"))
_last_detection_time: float = 0.0
# Max proposals per detection run (prevents runaway generation)
_MAX_PROPOSALS_PER_RUN = 20
# Max total stored proposals (prevents unbounded growth)
_MAX_STORED_PROPOSALS = 500


def detect_improvements(dry_run: bool = True) -> list[dict]:
    """
    Scan all performance data and generate improvement proposals.

    Rate-limited: runs at most once per JARVIS_DETECTION_INTERVAL seconds.
    Max proposals per run: 20. Max stored proposals: 500.

    Args:
        dry_run: If True, return proposals but don't store them.
                 If False, store proposals in ProposalStore.

    Returns:
        List of generated proposals (as dicts).
    """
    global _last_detection_time

    # Rate limiter — prevent self-amplifying detection loops
    now = time.time()
    if not dry_run and (now - _last_detection_time) < _MIN_DETECTION_INTERVAL:
        logger.debug("detection_rate_limited", seconds_since_last=round(now - _last_detection_time))
        return []
    _last_detection_time = now

    # Safety check
    try:
        from core.safety_controls import is_proposals_enabled
        if not is_proposals_enabled():
            logger.info("improvement_detection_disabled_by_safety")
            return []
    except ImportError:
        _silent_log.debug("suppressed_exception", src='improvement_detector.py')

    proposals = []

    # 1. Failing tools
    proposals.extend(_detect_tool_issues())

    # 2. Failing mission types
    proposals.extend(_detect_mission_issues())

    # 3. Agent routing improvements
    proposals.extend(_detect_agent_issues())

    # 4. Tool capability gaps
    proposals.extend(_detect_tool_gaps())

    # Cap proposals per run
    proposals = proposals[:_MAX_PROPOSALS_PER_RUN]

    # Score proposals by execution impact
    for p in proposals:
        p["impact_score"] = _compute_impact_score(p)

    # Sort by impact
    proposals.sort(key=lambda p: p.get("impact_score", 0), reverse=True)

    if not dry_run and proposals:
        try:
            from core.improvement_proposals import get_proposal_store, ImprovementProposal
            store = get_proposal_store()
            for p_dict in proposals:
                proposal = ImprovementProposal(
                    proposal_type=p_dict["type"],
                    title=p_dict["title"],
                    description=p_dict["description"],
                    affected_components=p_dict.get("components", []),
                    estimated_benefit=p_dict.get("benefit", ""),
                    risk_score=p_dict.get("risk_score", 5),
                    source="auto_detector",
                )
                store.add(proposal)
            logger.info("improvement_proposals_generated", count=len(proposals))
        except Exception as e:
            logger.warning("proposal_store_failed", err=str(e)[:80])

    return proposals


def _compute_impact_score(proposal: dict) -> float:
    """
    Compute execution reliability impact score for a proposal.
    Higher = bigger positive impact if implemented.

    Factors:
    - Type weight (tool fixes have immediate reliability impact)
    - Frequency (how often the issue occurs)
    - Severity (success rate of affected component)
    """
    TYPE_IMPACT = {
        "tool_fix": 8.0,
        "tool_optimization": 5.0,
        "retry_policy": 6.0,
        "routing_optimization": 7.0,
        "planning_rule": 4.0,
        "agent_config": 3.0,
        "new_tool": 2.0,
    }
    base = TYPE_IMPACT.get(proposal.get("type", ""), 1.0)
    risk = max(1, min(10, proposal.get("risk_score", 5)))
    risk_penalty = risk / 10.0  # higher risk = lower net impact

    return round(base * (1.0 - risk_penalty * 0.5), 2)


def _detect_tool_issues() -> list[dict]:
    """Detect problematic tools from real performance data."""
    issues = []
    try:
        from core.tool_performance_tracker import get_tool_performance_tracker
        tracker = get_tool_performance_tracker()

        for tool_name, stats in tracker.get_all_stats().items():
            if stats.total_calls < 5:
                continue

            # Failing tool (success < 60%)
            if stats.recent_success_rate < 0.60:
                top_err = stats.top_errors[0] if stats.top_errors else ("unknown", 0)
                issues.append({
                    "type": "tool_fix",
                    "title": f"Tool '{tool_name}' failing ({stats.recent_success_rate:.0%} success)",
                    "description": (
                        f"Tool '{tool_name}' has {stats.recent_success_rate:.0%} recent success rate "
                        f"over {stats.total_calls} calls. "
                        f"Top error: {top_err[0]} ({top_err[1]} occurrences). "
                        f"Last error: {stats.last_error[:100]}. "
                        f"Consider adding retry logic, fixing the underlying issue, "
                        f"or providing a fallback tool."
                    ),
                    "components": [f"core/tool_executor.py::{tool_name}"],
                    "benefit": f"Improve {tool_name} reliability from {stats.recent_success_rate:.0%} to >90%",
                    "risk_score": 3,
                })

            # High latency tool (avg > 3s)
            if stats.avg_latency_ms > 3000 and stats.total_calls >= 10:
                issues.append({
                    "type": "tool_optimization",
                    "title": f"Tool '{tool_name}' slow (avg {stats.avg_latency_ms:.0f}ms)",
                    "description": (
                        f"Tool '{tool_name}' averages {stats.avg_latency_ms:.0f}ms latency "
                        f"(max: {stats.max_latency_ms:.0f}ms). "
                        f"Consider caching frequent requests, reducing timeout, "
                        f"or optimizing the underlying implementation."
                    ),
                    "components": [f"core/tool_executor.py::{tool_name}"],
                    "benefit": f"Reduce {tool_name} latency from {stats.avg_latency_ms:.0f}ms to <1000ms",
                    "risk_score": 2,
                })

            # High retry rate (>20%)
            retry_rate = stats.retries / max(stats.total_calls, 1)
            if retry_rate > 0.20 and stats.total_calls >= 10:
                issues.append({
                    "type": "retry_policy",
                    "title": f"Tool '{tool_name}' retries too often ({retry_rate:.0%})",
                    "description": (
                        f"Tool '{tool_name}' requires retries on {retry_rate:.0%} of calls. "
                        f"This wastes time and resources. Consider fixing root cause "
                        f"or adjusting retry policy."
                    ),
                    "components": [f"core/tool_executor.py::{tool_name}"],
                    "benefit": f"Reduce retry overhead for {tool_name}",
                    "risk_score": 2,
                })

    except ImportError:
        _silent_log.debug("suppressed_exception", src='improvement_detector.py')
    except Exception as e:
        logger.debug("tool_issue_detection_err", err=str(e)[:60])

    return issues


def _detect_mission_issues() -> list[dict]:
    """Detect problematic mission types from real performance data."""
    issues = []
    try:
        from core.mission_performance_tracker import get_mission_performance_tracker
        tracker = get_mission_performance_tracker()

        for mt, stats in tracker._type_stats.items():
            if stats.total < 5:
                continue

            # Failing mission type
            if stats.recent_success_rate < 0.50:
                top_err = sorted(
                    stats.error_patterns.items(), key=lambda x: x[1], reverse=True
                )[:1]
                err_info = f"Top error: {top_err[0][0]} ({top_err[0][1]}x)" if top_err else ""
                issues.append({
                    "type": "planning_rule",
                    "title": f"Mission type '{mt}' failing ({stats.recent_success_rate:.0%})",
                    "description": (
                        f"Mission type '{mt}' has {stats.recent_success_rate:.0%} success rate "
                        f"over {stats.total} missions. {err_info}. "
                        f"Consider adjusting planning templates, changing agent selection, "
                        f"or adding pre-execution validation for this type."
                    ),
                    "components": [f"core/planner.py::{mt}", "core/mission_planner.py"],
                    "benefit": f"Improve {mt} success rate from {stats.recent_success_rate:.0%} to >80%",
                    "risk_score": 4,
                })

    except ImportError:
        _silent_log.debug("suppressed_exception", src='improvement_detector.py')
    except Exception as e:
        logger.debug("mission_issue_detection_err", err=str(e)[:60])

    return issues


def _detect_agent_issues() -> list[dict]:
    """Detect underperforming agents and routing improvements."""
    issues = []
    try:
        from core.mission_performance_tracker import get_mission_performance_tracker
        tracker = get_mission_performance_tracker()

        for agent_name, ap in tracker._agent_stats.items():
            if ap.total_missions < 5:
                continue

            # Underperforming agent (overall < 50%)
            if ap.success_rate < 0.50:
                weak_domains = [
                    (mt, counts[0] / max(counts[1], 1))
                    for mt, counts in ap.domain_success.items()
                    if counts[1] >= 3 and counts[0] / max(counts[1], 1) < 0.50
                ]
                domain_info = ", ".join(
                    f"{mt} ({rate:.0%})" for mt, rate in weak_domains[:3]
                ) if weak_domains else "general"

                issues.append({
                    "type": "agent_config",
                    "title": f"Agent '{agent_name}' underperforming ({ap.success_rate:.0%})",
                    "description": (
                        f"Agent '{agent_name}' has {ap.success_rate:.0%} success rate "
                        f"over {ap.total_missions} missions. "
                        f"Weak domains: {domain_info}. "
                        f"Consider reducing assignment to weak domains "
                        f"or adjusting agent configuration."
                    ),
                    "components": [f"agents/::{agent_name}"],
                    "benefit": f"Reduce failures by routing around {agent_name}'s weak domains",
                    "risk_score": 3,
                })

            # Agent-domain mismatch: agent assigned to domain where it fails
            for mt, counts in ap.domain_success.items():
                if len(counts) >= 2 and counts[1] >= 5:
                    rate = counts[0] / max(counts[1], 1)
                    if rate < 0.40:
                        # Check if better agent exists for this domain
                        best = tracker.get_best_agents_for_type(mt, top_k=1)
                        alt = best[0] if best and best[0] != agent_name else ""
                        issues.append({
                            "type": "routing_optimization",
                            "title": f"'{agent_name}' weak for '{mt}' ({rate:.0%})",
                            "description": (
                                f"Agent '{agent_name}' has only {rate:.0%} success on "
                                f"'{mt}' missions ({counts[1]} total). "
                                + (f"Agent '{alt}' performs better for this type. " if alt else "")
                                + "Consider adjusting MISSION_ROUTING to prefer better agents."
                            ),
                            "components": ["agents/crew.py::MISSION_ROUTING"],
                            "benefit": f"Route '{mt}' missions to more effective agents",
                            "risk_score": 2,
                        })

    except ImportError:
        _silent_log.debug("suppressed_exception", src='improvement_detector.py')
    except Exception as e:
        logger.debug("agent_issue_detection_err", err=str(e)[:60])

    return issues


def _detect_tool_gaps() -> list[dict]:
    """Detect missing tools based on execution patterns."""
    issues = []
    try:
        from core.mission_performance_tracker import get_mission_performance_tracker
        tracker = get_mission_performance_tracker()

        # Find mission types with high failure but no specific tool failures
        for mt, stats in tracker._type_stats.items():
            if stats.total < 5:
                continue
            if stats.success_rate < 0.60 and not stats.error_patterns:
                issues.append({
                    "type": "new_tool",
                    "title": f"Mission type '{mt}' may need better tooling",
                    "description": (
                        f"'{mt}' missions have {stats.success_rate:.0%} success rate "
                        f"without specific tool errors. This suggests missing capabilities "
                        f"rather than broken tools. Consider analyzing what tools would "
                        f"help this mission type succeed."
                    ),
                    "components": ["core/tool_registry.py"],
                    "benefit": f"Improve '{mt}' mission success through better tooling",
                    "risk_score": 4,
                })

    except ImportError:
        _silent_log.debug("suppressed_exception", src='improvement_detector.py')
    except Exception as e:
        logger.debug("tool_gap_detection_err", err=str(e)[:60])

    return issues
