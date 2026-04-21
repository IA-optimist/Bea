"""
JARVIS MAX — Tool Reliability Engine
=======================================
Detects unstable tools and proposes safe, bounded improvements.

Reads from: ToolPerformanceTracker, metrics_store
Produces: ToolDiagnosis with proposed fixes
Integrates with: improvement_daemon (as weakness source)

Allowed modifications:
  ✅ tool wrappers, timeout values, retry logic, error parsing
  ❌ security policy, auth, API keys, critical infra connectors

Usage:
    from core.tool_reliability import diagnose_tools, get_tool_fixes
    diagnoses = diagnose_tools()             # all tools
    fixes = get_tool_fixes(top_n=3)          # top 3 actionable fixes
"""
from __future__ import annotations

from dataclasses import dataclass, field
_silent_log = __import__("structlog").get_logger(__name__)

try:
    import structlog
    log = structlog.get_logger(__name__)
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# TOOL DIAGNOSIS
# ═══════════════════════════════════════════════════════════════

@dataclass
class ToolProblem:
    """A specific problem detected for a tool."""
    problem_type: str   # timeout, high_failure, slow_latency, error_pattern, retry_waste
    severity: str       # low, medium, high, critical
    metric_value: float
    threshold: float
    detail: str


@dataclass
class ToolFix:
    """A proposed safe fix for a tool problem."""
    fix_type: str           # retry_increase, timeout_increase, timeout_decrease,
                            # fallback_add, error_normalization, input_validation
    target_file: str        # file to modify
    description: str
    expected_impact: float  # 0-1, higher = more impactful
    safe: bool = True       # always True for allowed modifications


@dataclass
class ToolDiagnosis:
    """Complete diagnosis for a single tool."""
    tool_name: str
    health: str             # healthy, degraded, failing, unknown
    success_rate: float
    recent_success_rate: float
    avg_latency_ms: float
    timeout_count: int
    retry_count: int
    total_calls: int
    reliability_score: float
    problems: list[ToolProblem] = field(default_factory=list)
    proposed_fixes: list[ToolFix] = field(default_factory=list)
    error_distribution: dict[str, int] = field(default_factory=dict)

    @property
    def needs_attention(self) -> bool:
        return len(self.problems) > 0

    @property
    def worst_severity(self) -> str:
        if not self.problems:
            return "none"
        order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        return max(self.problems, key=lambda p: order.get(p.severity, 0)).severity

    @property
    def total_fix_impact(self) -> float:
        return sum(f.expected_impact for f in self.proposed_fixes)

    def to_dict(self) -> dict:
        return {
            "tool": self.tool_name,
            "health": self.health,
            "success_rate": round(self.success_rate, 3),
            "recent_success_rate": round(self.recent_success_rate, 3),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "timeout_count": self.timeout_count,
            "retry_count": self.retry_count,
            "total_calls": self.total_calls,
            "reliability_score": round(self.reliability_score, 3),
            "problems": [{"type": p.problem_type, "severity": p.severity,
                          "value": p.metric_value, "detail": p.detail}
                         for p in self.problems],
            "proposed_fixes": [{"type": f.fix_type, "target": f.target_file,
                                "description": f.description, "impact": f.expected_impact}
                               for f in self.proposed_fixes],
            "error_distribution": self.error_distribution,
            "needs_attention": self.needs_attention,
            "worst_severity": self.worst_severity,
        }


# ═══════════════════════════════════════════════════════════════
# THRESHOLDS
# ═══════════════════════════════════════════════════════════════

THRESHOLDS = {
    "success_rate_degraded": 0.85,
    "success_rate_failing": 0.60,
    "recent_success_rate_warn": 0.80,
    "avg_latency_high_ms": 5000,
    "avg_latency_critical_ms": 15000,
    "timeout_count_warn": 3,
    "timeout_count_critical": 8,
    "retry_waste_ratio": 0.30,     # >30% of calls are retries
    "error_pattern_threshold": 3,   # same error type >= 3 times
    "min_calls_for_diagnosis": 5,
}

# Safe modification targets (by tool category)
_SAFE_TARGETS: dict[str, str] = {
    "shell_command":  "core/tools/dev_tools.py",
    "file_write":     "core/tools/file_tool.py",
    "file_read":      "core/tools/file_tool.py",
    "web_search":     "core/tools/web_research_tool.py",
    "web_scrape":     "core/tools/web_research_tool.py",
    "browser":        "tools/browser_tool.py",
    "docker":         "core/tools/docker_tool.py",
    "github":         "core/tools/github_tool.py",
    "test":           "core/tools/test_toolkit.py",
    "memory":         "core/tools/memory_toolkit.py",
    "app_sync":       "core/tools/app_sync_toolkit.py",
    "n8n":            "tools/n8n/bridge.py",
}

# Default safe target for tools without specific mapping
_DEFAULT_SAFE_TARGET = "core/tool_runner.py"

# Files that must NEVER be modified
_FORBIDDEN_TARGETS = {
    "core/tool_executor.py",     # CRITICAL zone
    "core/policy_engine.py",
    "core/auth",
    "config/settings.py",
}


def _get_safe_target(tool_name: str) -> str:
    """Get the safe modification target for a tool."""
    for prefix, target in _SAFE_TARGETS.items():
        if prefix in tool_name.lower():
            return target
    return _DEFAULT_SAFE_TARGET


def _is_safe_target(target: str) -> bool:
    """Check if a file is safe to modify."""
    return not any(forbidden in target for forbidden in _FORBIDDEN_TARGETS)


# ═══════════════════════════════════════════════════════════════
# PROBLEM DETECTION
# ═══════════════════════════════════════════════════════════════

def _detect_problems(tool_name: str, stats: dict) -> list[ToolProblem]:
    """Detect problems from tool stats."""
    problems: list[ToolProblem] = []
    th = THRESHOLDS

    total = stats.get("total_calls", 0)
    if total < th["min_calls_for_diagnosis"]:
        return problems

    # 1. High failure rate
    success_rate = stats.get("success_rate", 1.0)
    recent_rate = stats.get("recent_success_rate", 1.0)

    if success_rate < th["success_rate_failing"]:
        problems.append(ToolProblem(
            problem_type="high_failure",
            severity="critical",
            metric_value=success_rate,
            threshold=th["success_rate_failing"],
            detail=f"Success rate {success_rate:.0%} — tool is failing",
        ))
    elif success_rate < th["success_rate_degraded"]:
        problems.append(ToolProblem(
            problem_type="high_failure",
            severity="high",
            metric_value=success_rate,
            threshold=th["success_rate_degraded"],
            detail=f"Success rate {success_rate:.0%} — tool is degraded",
        ))

    # Recent trend worse than overall
    if recent_rate < th["recent_success_rate_warn"] and recent_rate < success_rate - 0.05:
        problems.append(ToolProblem(
            problem_type="high_failure",
            severity="high",
            metric_value=recent_rate,
            threshold=th["recent_success_rate_warn"],
            detail=f"Recent success rate {recent_rate:.0%} trending down (overall {success_rate:.0%})",
        ))

    # 2. Timeout frequency
    timeouts = stats.get("timeout_count", 0)
    if timeouts >= th["timeout_count_critical"]:
        problems.append(ToolProblem(
            problem_type="timeout",
            severity="critical",
            metric_value=timeouts,
            threshold=th["timeout_count_critical"],
            detail=f"{timeouts} timeouts — critical timeout frequency",
        ))
    elif timeouts >= th["timeout_count_warn"]:
        problems.append(ToolProblem(
            problem_type="timeout",
            severity="medium",
            metric_value=timeouts,
            threshold=th["timeout_count_warn"],
            detail=f"{timeouts} timeouts",
        ))

    # 3. High latency
    avg_lat = stats.get("avg_latency_ms", 0)
    if avg_lat > th["avg_latency_critical_ms"]:
        problems.append(ToolProblem(
            problem_type="slow_latency",
            severity="high",
            metric_value=avg_lat,
            threshold=th["avg_latency_critical_ms"],
            detail=f"Average latency {avg_lat:.0f}ms — critically slow",
        ))
    elif avg_lat > th["avg_latency_high_ms"]:
        problems.append(ToolProblem(
            problem_type="slow_latency",
            severity="medium",
            metric_value=avg_lat,
            threshold=th["avg_latency_high_ms"],
            detail=f"Average latency {avg_lat:.0f}ms",
        ))

    # 4. Error pattern concentration
    errors = stats.get("top_errors", [])
    for err_type, count in (errors if isinstance(errors, list) else []):
        if count >= th["error_pattern_threshold"]:
            problems.append(ToolProblem(
                problem_type="error_pattern",
                severity="medium",
                metric_value=count,
                threshold=th["error_pattern_threshold"],
                detail=f"Repeated error: '{err_type}' ({count}x)",
            ))

    # 5. Retry waste
    retries = stats.get("retries", 0)
    if total > 0 and retries / total > th["retry_waste_ratio"]:
        problems.append(ToolProblem(
            problem_type="retry_waste",
            severity="medium",
            metric_value=round(retries / total, 3),
            threshold=th["retry_waste_ratio"],
            detail=f"{retries}/{total} calls are retries ({retries/total:.0%})",
        ))

    return problems


# ═══════════════════════════════════════════════════════════════
# FIX PROPOSAL
# ═══════════════════════════════════════════════════════════════

def _propose_fixes(tool_name: str, problems: list[ToolProblem]) -> list[ToolFix]:
    """Propose safe, bounded fixes for detected problems."""
    fixes: list[ToolFix] = []
    target = _get_safe_target(tool_name)

    if not _is_safe_target(target):
        return fixes

    seen_types: set[str] = set()

    for p in problems:
        # Avoid duplicate fix types
        if p.problem_type in seen_types:
            continue

        if p.problem_type == "timeout":
            fixes.append(ToolFix(
                fix_type="timeout_increase",
                target_file=target,
                description=f"Increase timeout for {tool_name} by 50% to reduce timeout failures",
                expected_impact=0.7,
            ))
            seen_types.add("timeout")

        elif p.problem_type == "high_failure":
            if p.severity == "critical":
                fixes.append(ToolFix(
                    fix_type="retry_increase",
                    target_file=target,
                    description=f"Add retry with exponential backoff for {tool_name}",
                    expected_impact=0.8,
                ))
                fixes.append(ToolFix(
                    fix_type="fallback_add",
                    target_file=target,
                    description=f"Add fallback mechanism for {tool_name} when primary fails",
                    expected_impact=0.6,
                ))
            else:
                fixes.append(ToolFix(
                    fix_type="retry_increase",
                    target_file=target,
                    description=f"Increase retry count for {tool_name}",
                    expected_impact=0.5,
                ))
            seen_types.add("high_failure")

        elif p.problem_type == "slow_latency":
            fixes.append(ToolFix(
                fix_type="timeout_decrease",
                target_file=target,
                description=f"Reduce timeout for {tool_name} to fail-fast and retry quicker",
                expected_impact=0.4,
            ))
            seen_types.add("slow_latency")

        elif p.problem_type == "error_pattern":
            fixes.append(ToolFix(
                fix_type="error_normalization",
                target_file=target,
                description=f"Normalize error handling for '{p.detail}' in {tool_name}",
                expected_impact=0.5,
            ))
            seen_types.add("error_pattern")

        elif p.problem_type == "retry_waste":
            fixes.append(ToolFix(
                fix_type="input_validation",
                target_file=target,
                description=f"Add input validation for {tool_name} to prevent futile retries",
                expected_impact=0.6,
            ))
            seen_types.add("retry_waste")

    return fixes


# ═══════════════════════════════════════════════════════════════
# MAIN DIAGNOSIS API
# ═══════════════════════════════════════════════════════════════

def diagnose_tools() -> list[ToolDiagnosis]:
    """
    Diagnose all tools using real metrics.

    Sources (in priority order):
    1. ToolPerformanceTracker (has rich per-tool stats)
    2. metrics_store (has counter-level data)

    Returns list of ToolDiagnosis, sorted by severity (worst first).
    """
    diagnoses: list[ToolDiagnosis] = []

    # Source 1: ToolPerformanceTracker
    try:
        from core.tool_performance_tracker import get_tool_performance_tracker
        tracker = get_tool_performance_tracker()
        for tool_name, stats_obj in tracker.get_all_stats().items():
            stats = stats_obj.to_dict()
            problems = _detect_problems(tool_name, stats)
            fixes = _propose_fixes(tool_name, problems)

            # Get timeout count from metrics_store
            timeout_count = 0
            retry_count = stats.get("retries", 0)
            try:
                from core.metrics_store import get_metrics
                m = get_metrics()
                timeout_count = int(m.get_counter("tool_timeout_total",
                                                   {"tool": tool_name}))
            except Exception:
                _silent_log.debug("suppressed_exception", src='tool_reliability.py')

            diagnoses.append(ToolDiagnosis(
                tool_name=tool_name,
                health=stats.get("health_status", "unknown"),
                success_rate=stats.get("success_rate", 1.0),
                recent_success_rate=stats.get("recent_success_rate", 1.0),
                avg_latency_ms=stats.get("avg_latency_ms", 0),
                timeout_count=timeout_count,
                retry_count=retry_count,
                total_calls=stats.get("total_calls", 0),
                reliability_score=stats.get("reliability_score", 1.0),
                problems=problems,
                proposed_fixes=fixes,
                error_distribution=dict(stats.get("top_errors", [])),
            ))
    except Exception as e:
        log.debug("tool_reliability.tracker_unavailable", err=str(e)[:80])

    # Source 2: metrics_store (supplement with tools not in tracker)
    try:
        from core.metrics_store import get_metrics
        m = get_metrics()
        inv_counter = m._counters.get("tool_invocations_total")
        fail_counter = m._counters.get("tool_failures_total")
        timeout_counter = m._counters.get("tool_timeout_total")

        known_tools = {d.tool_name for d in diagnoses}

        if inv_counter:
            for label_key, calls in inv_counter.get_all().items():
                tool_name = label_key.replace("tool=", "")
                if not tool_name or tool_name in known_tools:
                    continue

                failures = fail_counter.get(label_key) if fail_counter else 0
                timeouts = int(timeout_counter.get(label_key)) if timeout_counter else 0
                success_rate = (calls - failures) / calls if calls > 0 else 1.0

                lat_hist = m._histograms.get("tool_latency_ms")
                avg_lat = 0
                if lat_hist:
                    lat_stats = lat_hist.stats(label_key)
                    avg_lat = lat_stats.get("avg", 0)

                stats_dict = {
                    "total_calls": int(calls),
                    "success_rate": success_rate,
                    "recent_success_rate": success_rate,
                    "avg_latency_ms": avg_lat,
                    "timeout_count": timeouts,
                    "retries": 0,
                    "top_errors": [],
                }
                problems = _detect_problems(tool_name, stats_dict)
                fixes = _propose_fixes(tool_name, problems)

                health = "healthy"
                if success_rate < 0.6:
                    health = "failing"
                elif success_rate < 0.85:
                    health = "degraded"

                diagnoses.append(ToolDiagnosis(
                    tool_name=tool_name,
                    health=health,
                    success_rate=success_rate,
                    recent_success_rate=success_rate,
                    avg_latency_ms=avg_lat,
                    timeout_count=timeouts,
                    retry_count=0,
                    total_calls=int(calls),
                    reliability_score=success_rate * 0.85 + (1 - min(avg_lat / 5000, 1)) * 0.15,
                    problems=problems,
                    proposed_fixes=fixes,
                ))
    except Exception as e:
        log.debug("tool_reliability.metrics_unavailable", err=str(e)[:80])

    # Sort: worst first
    severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1, "none": 0}
    diagnoses.sort(key=lambda d: (severity_order.get(d.worst_severity, 0),
                                   1 - d.reliability_score), reverse=True)

    return diagnoses


def get_tool_fixes(top_n: int = 5) -> list[dict]:
    """
    Get the top N most impactful tool fixes across all tools.

    Returns list of {tool, fix_type, target, description, impact, severity}.
    """
    fixes: list[dict] = []
    for diag in diagnose_tools():
        for fix in diag.proposed_fixes:
            fixes.append({
                "tool": diag.tool_name,
                "fix_type": fix.fix_type,
                "target": fix.target_file,
                "description": fix.description,
                "impact": fix.expected_impact,
                "severity": diag.worst_severity,
                "health": diag.health,
            })

    # Sort by impact descending
    fixes.sort(key=lambda f: f["impact"], reverse=True)
    return fixes[:top_n]


def get_reliability_summary() -> dict:
    """Human-readable tool reliability summary."""
    diagnoses = diagnose_tools()
    if not diagnoses:
        return {"total_tools": 0, "healthy": 0, "degraded": 0, "failing": 0, "fixes_available": 0}

    healthy = sum(1 for d in diagnoses if d.health == "healthy")
    degraded = sum(1 for d in diagnoses if d.health == "degraded")
    failing = sum(1 for d in diagnoses if d.health == "failing")
    total_fixes = sum(len(d.proposed_fixes) for d in diagnoses)

    return {
        "total_tools": len(diagnoses),
        "healthy": healthy,
        "degraded": degraded,
        "failing": failing,
        "fixes_available": total_fixes,
        "worst_tools": [d.to_dict() for d in diagnoses if d.needs_attention][:3],
    }
