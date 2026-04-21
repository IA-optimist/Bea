"""
Tests — Tool Reliability Engine

Coverage:
  T1. Problem detection: high failure rate
  T2. Problem detection: timeout frequency
  T3. Problem detection: slow latency
  T4. Problem detection: error patterns
  T5. Problem detection: retry waste
  T6. No problems on healthy tool
  T7. Minimum calls threshold (< 5 calls → no diagnosis)
  T8. Fix proposal: retry increase for critical failure
  T9. Fix proposal: timeout increase for timeouts
  T10. Fix proposal: error normalization for error patterns
  T11. Fix proposal: input validation for retry waste
  T12. Safe targets: correct file mapping
  T13. Forbidden targets: critical files blocked
  T14. Full diagnosis from metrics_store
  T15. get_tool_fixes returns ranked fixes
  T16. get_reliability_summary structure
  T17. ToolDiagnosis.needs_attention and worst_severity
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.tool_reliability import (
    ToolDiagnosis, ToolProblem, _detect_problems, _propose_fixes,
    _get_safe_target, _is_safe_target,
    diagnose_tools, get_tool_fixes, get_reliability_summary,
)


# ═══════════════════════════════════════════════════════════════
# PROBLEM DETECTION (T1-T7)
# ═══════════════════════════════════════════════════════════════

class TestProblemDetection:

    def test_high_failure_critical(self):
        """T1: < 60% success → critical failure."""
        stats = {"total_calls": 20, "success_rate": 0.45, "recent_success_rate": 0.40,
                 "avg_latency_ms": 200, "timeout_count": 0, "retries": 0, "top_errors": []}
        problems = _detect_problems("test_tool", stats)
        assert any(p.problem_type == "high_failure" and p.severity == "critical" for p in problems)

    def test_high_failure_degraded(self):
        """T1: < 85% success → high severity."""
        stats = {"total_calls": 20, "success_rate": 0.75, "recent_success_rate": 0.75,
                 "avg_latency_ms": 200, "timeout_count": 0, "retries": 0, "top_errors": []}
        problems = _detect_problems("test_tool", stats)
        assert any(p.problem_type == "high_failure" and p.severity == "high" for p in problems)

    def test_timeout_critical(self):
        """T2: >= 8 timeouts → critical."""
        stats = {"total_calls": 20, "success_rate": 0.9, "recent_success_rate": 0.9,
                 "avg_latency_ms": 200, "timeout_count": 10, "retries": 0, "top_errors": []}
        problems = _detect_problems("test_tool", stats)
        assert any(p.problem_type == "timeout" and p.severity == "critical" for p in problems)

    def test_timeout_warning(self):
        """T2: >= 3 timeouts → medium."""
        stats = {"total_calls": 20, "success_rate": 0.9, "recent_success_rate": 0.9,
                 "avg_latency_ms": 200, "timeout_count": 4, "retries": 0, "top_errors": []}
        problems = _detect_problems("test_tool", stats)
        assert any(p.problem_type == "timeout" and p.severity == "medium" for p in problems)

    def test_slow_latency(self):
        """T3: avg > 5000ms → medium."""
        stats = {"total_calls": 20, "success_rate": 0.95, "recent_success_rate": 0.95,
                 "avg_latency_ms": 8000, "timeout_count": 0, "retries": 0, "top_errors": []}
        problems = _detect_problems("test_tool", stats)
        assert any(p.problem_type == "slow_latency" for p in problems)

    def test_slow_latency_critical(self):
        """T3: avg > 15000ms → high."""
        stats = {"total_calls": 20, "success_rate": 0.95, "recent_success_rate": 0.95,
                 "avg_latency_ms": 20000, "timeout_count": 0, "retries": 0, "top_errors": []}
        problems = _detect_problems("test_tool", stats)
        assert any(p.problem_type == "slow_latency" and p.severity == "high" for p in problems)

    def test_error_pattern(self):
        """T4: Same error >= 3 times."""
        stats = {"total_calls": 20, "success_rate": 0.8, "recent_success_rate": 0.8,
                 "avg_latency_ms": 200, "timeout_count": 0, "retries": 0,
                 "top_errors": [("connection_refused", 5), ("auth_fail", 1)]}
        problems = _detect_problems("test_tool", stats)
        assert any(p.problem_type == "error_pattern" for p in problems)

    def test_retry_waste(self):
        """T5: > 30% retries."""
        stats = {"total_calls": 20, "success_rate": 0.8, "recent_success_rate": 0.8,
                 "avg_latency_ms": 200, "timeout_count": 0, "retries": 8, "top_errors": []}
        problems = _detect_problems("test_tool", stats)
        assert any(p.problem_type == "retry_waste" for p in problems)

    def test_healthy_no_problems(self):
        """T6: No problems on healthy tool."""
        stats = {"total_calls": 50, "success_rate": 0.98, "recent_success_rate": 0.98,
                 "avg_latency_ms": 150, "timeout_count": 0, "retries": 1, "top_errors": []}
        problems = _detect_problems("test_tool", stats)
        assert len(problems) == 0

    def test_min_calls_threshold(self):
        """T7: < 5 calls → no diagnosis."""
        stats = {"total_calls": 3, "success_rate": 0.33, "recent_success_rate": 0.33,
                 "avg_latency_ms": 500, "timeout_count": 2, "retries": 0, "top_errors": []}
        problems = _detect_problems("test_tool", stats)
        assert len(problems) == 0


# ═══════════════════════════════════════════════════════════════
# FIX PROPOSALS (T8-T11)
# ═══════════════════════════════════════════════════════════════

class TestFixProposals:

    def test_retry_increase_for_failure(self):
        """T8: Critical failure → retry + fallback."""
        problems = [ToolProblem("high_failure", "critical", 0.45, 0.6, "failing")]
        fixes = _propose_fixes("shell_command", problems)
        assert any(f.fix_type == "retry_increase" for f in fixes)
        assert any(f.fix_type == "fallback_add" for f in fixes)

    def test_timeout_increase(self):
        """T9: Timeout → timeout increase."""
        problems = [ToolProblem("timeout", "medium", 5, 3, "5 timeouts")]
        fixes = _propose_fixes("web_search", problems)
        assert any(f.fix_type == "timeout_increase" for f in fixes)

    def test_error_normalization(self):
        """T10: Error pattern → error normalization."""
        problems = [ToolProblem("error_pattern", "medium", 5, 3, "Repeated")]
        fixes = _propose_fixes("shell_command", problems)
        assert any(f.fix_type == "error_normalization" for f in fixes)

    def test_input_validation(self):
        """T11: Retry waste → input validation."""
        problems = [ToolProblem("retry_waste", "medium", 0.4, 0.3, "retries")]
        fixes = _propose_fixes("github", problems)
        assert any(f.fix_type == "input_validation" for f in fixes)


# ═══════════════════════════════════════════════════════════════
# SAFE TARGETS (T12, T13)
# ═══════════════════════════════════════════════════════════════

class TestSafeTargets:

    def test_tool_file_mapping(self):
        """T12: Known tools map to correct files."""
        assert "dev_tools" in _get_safe_target("shell_command")
        assert "file_tool" in _get_safe_target("file_write")
        assert "web_research" in _get_safe_target("web_search")
        assert "github_tool" in _get_safe_target("github")

    def test_unknown_tool_default(self):
        assert _get_safe_target("unknown_tool_xyz") == "core/tool_runner.py"

    def test_forbidden_targets_blocked(self):
        """T13: Critical files are not safe targets."""
        assert not _is_safe_target("core/tool_executor.py")
        assert not _is_safe_target("core/policy_engine.py")
        assert not _is_safe_target("core/auth/token.py")
        assert not _is_safe_target("config/settings.py")

    def test_safe_targets_allowed(self):
        assert _is_safe_target("core/tools/dev_tools.py")
        assert _is_safe_target("core/tool_runner.py")
        assert _is_safe_target("tools/browser_tool.py")


# ═══════════════════════════════════════════════════════════════
# FULL DIAGNOSIS (T14)
# ═══════════════════════════════════════════════════════════════

class TestFullDiagnosis:

    def test_diagnosis_from_metrics(self):
        """T14: diagnose_tools reads from metrics_store."""
        from core.metrics_store import reset_metrics, emit_tool_invocation, emit_tool_timeout
        reset_metrics()

        # Simulate unstable tool
        for _ in range(15):
            emit_tool_invocation("web_search", True, 200)
        for _ in range(5):
            emit_tool_invocation("web_search", False, 5000)
        for _ in range(4):
            emit_tool_timeout("web_search")

        # Simulate healthy tool
        for _ in range(20):
            emit_tool_invocation("file_write", True, 50)

        diagnoses = diagnose_tools()

        # Find the web_search diagnosis
        web_diag = [d for d in diagnoses if d.tool_name == "web_search"]
        assert len(web_diag) >= 1
        d = web_diag[0]
        assert d.success_rate < 0.85
        assert d.needs_attention

        # File write should be healthy
        file_diag = [d for d in diagnoses if d.tool_name == "file_write"]
        if file_diag:
            assert file_diag[0].health == "healthy"


# ═══════════════════════════════════════════════════════════════
# TOP-LEVEL API (T15, T16, T17)
# ═══════════════════════════════════════════════════════════════

class TestTopLevelAPI:

    def test_get_tool_fixes(self):
        """T15: get_tool_fixes returns ranked list."""
        from core.metrics_store import reset_metrics, emit_tool_invocation
        reset_metrics()

        for _ in range(5):
            emit_tool_invocation("broken_tool", True, 100)
        for _ in range(10):
            emit_tool_invocation("broken_tool", False, 5000)

        fixes = get_tool_fixes(top_n=3)
        assert isinstance(fixes, list)
        if fixes:
            assert "tool" in fixes[0]
            assert "fix_type" in fixes[0]
            assert "impact" in fixes[0]
            # Sorted by impact descending
            if len(fixes) >= 2:
                assert fixes[0]["impact"] >= fixes[1]["impact"]

    def test_reliability_summary(self):
        """T16: Summary has correct structure."""
        from core.metrics_store import reset_metrics, emit_tool_invocation
        reset_metrics()

        for _ in range(10):
            emit_tool_invocation("good_tool", True, 100)
        for _ in range(5):
            emit_tool_invocation("bad_tool", True, 100)
        for _ in range(10):
            emit_tool_invocation("bad_tool", False, 100)

        summary = get_reliability_summary()
        assert "total_tools" in summary
        assert "healthy" in summary
        assert "degraded" in summary
        assert "failing" in summary
        assert "fixes_available" in summary

    def test_diagnosis_needs_attention(self):
        """T17: ToolDiagnosis.needs_attention and worst_severity."""
        # Healthy
        d1 = ToolDiagnosis(tool_name="good", health="healthy",
                           success_rate=0.99, recent_success_rate=0.99,
                           avg_latency_ms=100, timeout_count=0,
                           retry_count=0, total_calls=50,
                           reliability_score=0.99)
        assert not d1.needs_attention
        assert d1.worst_severity == "none"

        # Problematic
        d2 = ToolDiagnosis(tool_name="bad", health="failing",
                           success_rate=0.40, recent_success_rate=0.30,
                           avg_latency_ms=10000, timeout_count=10,
                           retry_count=8, total_calls=50,
                           reliability_score=0.30,
                           problems=[
                               ToolProblem("high_failure", "critical", 0.40, 0.60, "failing"),
                               ToolProblem("timeout", "medium", 10, 3, "timeouts"),
                           ])
        assert d2.needs_attention
        assert d2.worst_severity == "critical"
