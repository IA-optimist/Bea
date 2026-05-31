"""
JARVIS — Tool Gap Analyzer
==============================
Identifies missing tools based on real execution patterns.

Detects:
1. Frequent unmet needs (mission types with no specific tools)
2. Manual fallback patterns (default params used repeatedly)
3. High-failure tool categories (whole category unreliable)
4. Missing integrations (external queries that could be toolified)

Generates tool proposals stored in the improvement proposal queue.

Called from:
- improvement_detector (during detection sweeps)
- /api/v3/performance/tools/gaps (on demand)

Zero external dependencies.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("jarvis.tool_gap_analyzer")
log = logger  # alias for M3 emitter


def analyze_tool_gaps() -> list[dict]:
    """
    Analyze tool ecosystem for gaps and generate proposals.

    Returns list of gap analysis results.
    """
    gaps = []
    gaps.extend(_detect_unmet_mission_needs())
    gaps.extend(_detect_unreliable_categories())
    gaps.extend(_detect_tool_quality_issues())
    gaps.extend(_detect_coverage_holes())
    return gaps


def _detect_unmet_mission_needs() -> list[dict]:
    """Find mission types with poor tooling."""
    gaps = []
    try:
        from core.mission_performance_tracker import get_mission_performance_tracker
        from core.tool_performance_tracker import get_tool_performance_tracker

        mt = get_mission_performance_tracker()
        tt = get_tool_performance_tracker()

        for mission_type, stats in mt._type_stats.items():
            if stats.total < 3:
                continue

            # Low success rate + few tools used = tooling gap
            used_tools = list(stats.best_tools.keys())
            if stats.success_rate < 0.60 and len(used_tools) <= 2:
                gaps.append({
                    "type": "unmet_need",
                    "mission_type": mission_type,
                    "success_rate": round(stats.success_rate, 3),
                    "current_tools": used_tools,
                    "missions_analyzed": stats.total,
                    "suggestion": (
                        f"Mission type '{mission_type}' has {stats.success_rate:.0%} success "
                        f"with only {len(used_tools)} tools. Consider adding specialized tools "
                        f"for this mission type."
                    ),
                })

        # Find tool categories where all tools are degraded
        all_stats = tt.get_all_stats()
        if all_stats:
            # Group by prefix (read_, write_, check_, search_, etc.)
            from collections import defaultdict
            by_prefix = defaultdict(list)
            for name, s in all_stats.items():
                prefix = name.split("_")[0] if "_" in name else name
                by_prefix[prefix].append(s)

            for prefix, tools in by_prefix.items():
                if len(tools) >= 2:
                    avg_health = sum(
                        1 for t in tools if t.health_status in ("degraded", "failing")
                    ) / len(tools)
                    if avg_health > 0.5:
                        gaps.append({
                            "type": "category_weak",
                            "category": prefix,
                            "tools": [t.tool for t in tools],
                            "degraded_pct": round(avg_health, 2),
                            "suggestion": (
                                f"Tool category '{prefix}' has {avg_health:.0%} tools degraded. "
                                f"Consider replacing or adding alternatives."
                            ),
                        })

    except ImportError as _exc:
        log.warning("swallowed_exception", action="tool_gap_analyzer_1", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
    except Exception as e:
        logger.debug("unmet_needs_err", err=str(e)[:60])

    return gaps


def _detect_unreliable_categories() -> list[dict]:
    """Find tool categories with consistently high failure rates."""
    gaps = []
    try:
        from core.tool_performance_tracker import get_tool_performance_tracker
        tt = get_tool_performance_tracker()

        for name, stats in tt.get_all_stats().items():
            if stats.total_calls < 10:
                continue

            # Tool with high retry rate = needs retry-wrapper or replacement
            retry_rate = stats.retries / max(stats.total_calls, 1)
            if retry_rate > 0.25:
                gaps.append({
                    "type": "needs_retry_wrapper",
                    "tool": name,
                    "retry_rate": round(retry_rate, 3),
                    "total_calls": stats.total_calls,
                    "suggestion": (
                        f"Tool '{name}' retries {retry_rate:.0%} of calls. "
                        f"Consider wrapping with smarter retry logic or adding a fallback."
                    ),
                })

            # Tool with high latency variance = needs caching
            if stats.max_latency_ms > stats.avg_latency_ms * 5 and stats.avg_latency_ms > 500:
                gaps.append({
                    "type": "needs_caching",
                    "tool": name,
                    "avg_latency_ms": round(stats.avg_latency_ms, 0),
                    "max_latency_ms": round(stats.max_latency_ms, 0),
                    "suggestion": (
                        f"Tool '{name}' has high latency variance "
                        f"(avg: {stats.avg_latency_ms:.0f}ms, max: {stats.max_latency_ms:.0f}ms). "
                        f"Consider adding result caching."
                    ),
                })

    except ImportError as _exc:
        log.warning("swallowed_exception", action="tool_gap_analyzer_2", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
    except Exception as e:
        logger.debug("unreliable_categories_err", err=str(e)[:60])

    return gaps


def _detect_tool_quality_issues() -> list[dict]:
    """Detect unused, redundant, or overlapping tools."""
    issues = []
    try:
        from core.tool_performance_tracker import get_tool_performance_tracker
        from core.tool_registry import _BASE_TOOLS
        tracker = get_tool_performance_tracker()
        all_stats = tracker.get_all_stats()

        # Find registered tools never used (or < 2 calls)
        registered_names = {t.name for t in _BASE_TOOLS}
        tracked_names = set(all_stats.keys())
        unused = registered_names - tracked_names
        rarely_used = {
            name for name, s in all_stats.items()
            if s.total_calls < 2 and name in registered_names
        }
        stale = unused | rarely_used

        if stale and len(tracked_names) >= 5:  # only flag if we have enough data
            issues.append({
                "type": "unused_tools",
                "tools": sorted(stale),
                "suggestion": (
                    f"Tools {sorted(stale)} have zero or minimal usage. "
                    f"Consider whether they're needed or should be consolidated."
                ),
            })

        # Detect deprecated-quality tools (failing + no recent success)
        import time
        now = time.time()
        for name, stats in all_stats.items():
            if stats.total_calls >= 10 and stats.health_status == "failing":
                days_since_success = (now - stats.last_success) / 86400 if stats.last_success else 999
                if days_since_success > 7:
                    issues.append({
                        "type": "deprecated_candidate",
                        "tool": name,
                        "last_success_days": round(days_since_success, 1),
                        "success_rate": round(stats.success_rate, 3),
                        "suggestion": (
                            f"Tool '{name}' has been failing for {days_since_success:.0f} days. "
                            f"Consider marking as deprecated and removing from routing."
                        ),
                    })

    except ImportError as _exc:
        log.warning("swallowed_exception", action="tool_gap_analyzer_3", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
    except Exception as e:
        logger.debug("tool_quality_err", err=str(e)[:60])

    return issues


def _detect_coverage_holes() -> list[dict]:
    """Find mission types with no mapped tools in MISSION_TOOLS."""
    gaps = []
    try:
        from core.tool_registry import _MISSION_TOOLS
        from core.mission_performance_tracker import get_mission_performance_tracker

        mt = get_mission_performance_tracker()

        for mission_type in mt._type_stats:
            if mission_type not in _MISSION_TOOLS:
                stats = mt._type_stats[mission_type]
                if stats.total >= 3:
                    gaps.append({
                        "type": "no_tool_mapping",
                        "mission_type": mission_type,
                        "missions_seen": stats.total,
                        "suggestion": (
                            f"Mission type '{mission_type}' has {stats.total} missions "
                            f"but no tool mapping in MISSION_TOOLS. Add an entry to "
                            f"core/tool_registry.py."
                        ),
                    })

    except ImportError as _exc:
        log.warning("swallowed_exception", action="tool_gap_analyzer_4", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
    except Exception as e:
        logger.debug("coverage_holes_err", err=str(e)[:60])

    return gaps
