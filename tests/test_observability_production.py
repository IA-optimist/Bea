"""
Tests — Production Observability Layer

Coverage:
  O1. Counter increment and label isolation
  O2. Histogram stats computation (avg, p50, p95, p99, max)
  O3. Gauge set/get
  O4. Failure aggregation by category
  O5. Cost tracking by model
  O6. Convenience emitters (emit_mission_*, emit_tool_*, etc.)
  O7. Snapshot structure (no secrets, all required fields)
  O8. Human summary generation
  O9. Trace intelligence — success summary
  O10. Trace intelligence — failure analysis
  O11. Trace intelligence — timing breakdown
  O12. Trace intelligence — empty trace
  O13. Diagnostics endpoint stability (FastAPI routes)
  O14. No secrets in metrics output
  O15. Reset works (for test isolation)
  O16. Thread safety basic check
  O17. Failure pattern top-N ordering
"""
import json
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═══════════════════════════════════════════════════════════════
# METRICS STORE
# ═══════════════════════════════════════════════════════════════

class TestCounter:
    """O1: Counter increment and label isolation."""

    def test_basic_increment(self):
        from core.metrics_store import Counter
        c = Counter()
        c.inc("", 1)
        c.inc("", 1)
        assert c.get("") == 2

    def test_labeled_isolation(self):
        from core.metrics_store import Counter
        c = Counter()
        c.inc("model_id=gpt4", 1)
        c.inc("model_id=claude", 3)
        assert c.get("model_id=gpt4") == 1
        assert c.get("model_id=claude") == 3
        assert c.total() == 4

    def test_missing_label_returns_zero(self):
        from core.metrics_store import Counter
        c = Counter()
        assert c.get("nonexistent") == 0


class TestHistogram:
    """O2: Histogram stats computation."""

    def test_basic_stats(self):
        from core.metrics_store import Histogram
        h = Histogram()
        for v in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
            h.observe(v)
        s = h.stats()
        assert s["count"] == 10
        assert s["avg"] == 55.0
        assert s["min"] == 10
        assert s["max"] == 100
        assert s["p50"] >= 50
        assert s["p95"] >= 90

    def test_empty_histogram(self):
        from core.metrics_store import Histogram
        h = Histogram()
        s = h.stats()
        assert s["count"] == 0
        assert s["avg"] == 0

    def test_sliding_window(self):
        from core.metrics_store import Histogram
        h = Histogram(max_samples=5)
        for v in range(100):
            h.observe(v)
        s = h.stats()
        assert s["count"] == 5  # Only last 5 kept
        assert s["min"] >= 95   # Last 5 values: 95-99


class TestGauge:
    """O3: Gauge set/get."""

    def test_basic_gauge(self):
        from core.metrics_store import Gauge
        g = Gauge()
        g.set(42)
        assert g.get() == 42
        g.set(0)
        assert g.get() == 0

    def test_labeled_gauge(self):
        from core.metrics_store import Gauge
        g = Gauge()
        g.set(1, "state=open")
        g.set(0, "state=closed")
        assert g.get("state=open") == 1
        assert g.get("state=closed") == 0


class TestFailureAggregator:
    """O4: Failure aggregation by category."""

    def test_record_and_aggregate(self):
        from core.metrics_store import FailureAggregator, FailureRecord
        fa = FailureAggregator()
        fa.record(FailureRecord(category="timeout", component="executor", message="timed out"))
        fa.record(FailureRecord(category="timeout", component="executor", message="timed out again"))
        fa.record(FailureRecord(category="auth", component="api", message="401"))

        by_cat = fa.by_category(window_s=3600)
        assert by_cat["timeout"] == 2
        assert by_cat["auth"] == 1

    def test_top_failures_ordered(self):
        """O17: Top failures are ordered by count descending."""
        from core.metrics_store import FailureAggregator, FailureRecord
        fa = FailureAggregator()
        for _ in range(5):
            fa.record(FailureRecord(category="timeout", component="executor", message="timeout"))
        for _ in range(2):
            fa.record(FailureRecord(category="auth", component="api", message="auth fail"))
        for _ in range(8):
            fa.record(FailureRecord(category="provider", component="openrouter", message="503"))

        top = fa.top_failures(limit=3)
        assert len(top) == 3
        assert top[0]["category"] == "provider"  # Most frequent first
        assert top[0]["count"] == 8
        assert top[1]["category"] == "timeout"
        assert top[1]["count"] == 5


class TestCostTracker:
    """O5: Cost tracking by model."""

    def test_estimated_cost(self):
        from core.metrics_store import CostTracker
        ct = CostTracker()
        ct.record("gpt-4o", tokens=1_000_000, cost_tier="standard")
        ct.record("gpt-4o", tokens=500_000, cost_tier="standard")
        snap = ct.snapshot()
        assert snap["total_estimated_usd"] > 0
        assert "gpt-4o" in snap["by_model"]

    def test_actual_cost_override(self):
        from core.metrics_store import CostTracker
        ct = CostTracker()
        ct.record("custom-model", tokens=0, actual_cost=0.05)
        snap = ct.snapshot()
        assert snap["total_estimated_usd"] == 0.05

    def test_mission_tracking(self):
        from core.metrics_store import CostTracker
        ct = CostTracker()
        ct.record("gpt-4o", tokens=100_000, cost_tier="standard", mission_id="m1")
        ct.record("gpt-4o", tokens=200_000, cost_tier="standard", mission_id="m1")
        snap = ct.snapshot()
        assert "m1" in snap["top_missions"]
        assert snap["top_missions"]["m1"] > 0


# ═══════════════════════════════════════════════════════════════
# CONVENIENCE EMITTERS (O6)
# ═══════════════════════════════════════════════════════════════

class TestEmitters:
    """O6: Convenience emitter functions."""

    def test_mission_lifecycle(self):
        from core.metrics_store import (
            reset_metrics, emit_mission_submitted, emit_mission_completed,
            emit_mission_failed, emit_mission_timeout
        )
        m = reset_metrics()
        emit_mission_submitted("code_review")
        emit_mission_submitted("code_review")
        emit_mission_completed("code_review", duration_ms=4200)
        emit_mission_failed("deploy", reason="container crash")
        emit_mission_timeout("research")

        assert m.get_counter("missions_submitted_total", {"type": "code_review"}) == 2
        assert m.get_counter("missions_completed_total", {"type": "code_review"}) == 1
        assert m.get_counter("missions_failed_total", {"type": "deploy"}) == 1
        assert m.get_counter("mission_timeout_total", {"type": "research"}) == 1
        assert m.get_histogram("mission_duration_ms", {"type": "code_review"})["count"] == 1

    def test_tool_emitters(self):
        from core.metrics_store import reset_metrics, emit_tool_invocation, emit_tool_timeout
        m = reset_metrics()
        emit_tool_invocation("shell_command", success=True, duration_ms=150)
        emit_tool_invocation("shell_command", success=False, duration_ms=5000)
        emit_tool_timeout("web_search")

        assert m.get_counter("tool_invocations_total", {"tool": "shell_command"}) == 2
        assert m.get_counter("tool_failures_total", {"tool": "shell_command"}) == 1
        assert m.get_counter("tool_timeout_total", {"tool": "web_search"}) == 1

    def test_model_emitters(self):
        from core.metrics_store import (
            reset_metrics, emit_model_selected, emit_model_failure,
            emit_model_latency, emit_fallback_used
        )
        m = reset_metrics()
        emit_model_selected("claude-sonnet", locality="cloud")
        emit_model_selected("ollama-qwen", locality="local")
        emit_model_failure("claude-sonnet", error="rate limited")
        emit_model_latency("claude-sonnet", 3200)
        emit_fallback_used(from_model="claude-sonnet", to_model="gpt-4o")

        assert m.get_counter("model_selected_total", {"model_id": "claude-sonnet"}) == 1
        assert m.get_counter("cloud_route_total") == 1
        assert m.get_counter("local_only_route_total") == 1
        assert m.get_counter("model_failure_total", {"model_id": "claude-sonnet"}) == 1
        assert m.get_counter_total("fallback_used_total") >= 1

    def test_memory_emitters(self):
        from core.metrics_store import reset_metrics, emit_memory_search
        m = reset_metrics()
        emit_memory_search(hit=True, latency_ms=45)
        emit_memory_search(hit=False, latency_ms=120)

        assert m.get_counter("memory_search_total") == 2
        assert m.get_counter("memory_search_hits") == 1

    def test_experiment_emitters(self):
        from core.metrics_store import reset_metrics, emit_experiment
        m = reset_metrics()
        emit_experiment("promoted", score_delta=0.15)
        emit_experiment("rejected", score_delta=-0.05)
        emit_experiment("blocked", score_delta=0)

        assert m.get_counter("experiments_started_total") == 3
        assert m.get_counter("experiments_promoted_total") == 1
        assert m.get_counter("experiments_rejected_total") == 1
        assert m.get_counter("regressions_blocked_total") == 1
        assert m.get_counter("lessons_learned_total") == 3

    def test_multimodal_emitters(self):
        from core.metrics_store import reset_metrics, emit_multimodal_task
        m = reset_metrics()
        emit_multimodal_task("vision", success=True, latency_ms=800)
        emit_multimodal_task("vision", success=False, latency_ms=0)

        assert m.get_counter("multimodal_tasks_total", {"modality": "vision"}) == 2
        assert m.get_counter("multimodal_failures_total", {"modality": "vision"}) == 1

    def test_circuit_breaker_emitters(self):
        from core.metrics_store import reset_metrics, emit_circuit_breaker
        m = reset_metrics()
        emit_circuit_breaker("open")
        assert m.get_counter("circuit_breaker_open_total") == 1
        assert m.get_gauge("circuit_breaker_state") == 2  # open=2

    def test_orchestrator_timing(self):
        from core.metrics_store import reset_metrics, emit_orchestrator_timing
        m = reset_metrics()
        emit_orchestrator_timing("classify", 150)
        emit_orchestrator_timing("planning", 2400)
        emit_orchestrator_timing("routing", 80)

        assert m.get_histogram("classify_latency_ms")["count"] == 1
        assert m.get_histogram("planning_latency_ms")["avg"] == 2400

    def test_retry_emitter(self):
        from core.metrics_store import reset_metrics, emit_retry
        m = reset_metrics()
        emit_retry("executor")
        emit_retry("executor")
        assert m.get_counter("retry_attempts_total", {"component": "executor"}) == 2


# ═══════════════════════════════════════════════════════════════
# SNAPSHOT & HUMAN SUMMARY (O7, O8)
# ═══════════════════════════════════════════════════════════════

class TestSnapshot:
    """O7: Snapshot structure."""

    def test_snapshot_has_required_sections(self):
        from core.metrics_store import reset_metrics
        m = reset_metrics()
        snap = m.snapshot()
        assert "counters" in snap
        assert "histograms" in snap
        assert "gauges" in snap
        assert "failure_patterns" in snap
        assert "top_failures" in snap
        assert "costs" in snap
        assert "uptime_s" in snap
        assert "snapshot_at" in snap

    def test_snapshot_json_serializable(self):
        from core.metrics_store import reset_metrics, emit_mission_submitted
        m = reset_metrics()
        emit_mission_submitted("test")
        snap = m.snapshot()
        # Must not throw
        json_str = json.dumps(snap, default=str)
        assert len(json_str) > 0


class TestNoSecrets:
    """O14: No secrets in metrics output."""

    def test_no_secrets_in_snapshot(self):
        from core.metrics_store import reset_metrics, emit_model_selected
        m = reset_metrics()
        emit_model_selected("claude-sonnet")
        snap = json.dumps(m.snapshot(), default=str)
        # These should never appear
        for secret_keyword in ["api_key", "token", "secret", "password", "bearer"]:
            assert secret_keyword not in snap.lower(), f"Found '{secret_keyword}' in snapshot!"

    def test_no_secrets_in_human_summary(self):
        from core.metrics_store import reset_metrics
        m = reset_metrics()
        text = m.human_summary()
        for secret_keyword in ["api_key", "token", "secret", "password"]:
            assert secret_keyword not in text.lower()


class TestHumanSummary:
    """O8: Human summary generation."""

    def test_summary_readable(self):
        from core.metrics_store import (
            reset_metrics, emit_mission_submitted, emit_mission_completed,
            emit_mission_failed, emit_tool_invocation, emit_model_selected,
        )
        m = reset_metrics()
        emit_mission_submitted("code_review")
        emit_mission_completed("code_review", duration_ms=5000)
        emit_mission_failed("deploy", reason="crash")
        emit_tool_invocation("shell", True, 100)
        emit_model_selected("claude-sonnet")

        text = m.human_summary()
        assert "JARVISMAX SYSTEM STATUS" in text
        assert "Missions" in text
        assert "Submitted" in text


class TestReset:
    """O15: Reset works for test isolation."""

    def test_reset_clears_all(self):
        from core.metrics_store import reset_metrics, emit_mission_submitted
        m = reset_metrics()
        emit_mission_submitted("test")
        assert m.get_counter_total("missions_submitted_total") == 1
        m.reset()
        assert m.get_counter_total("missions_submitted_total") == 0


class TestThreadSafety:
    """O16: Basic thread safety."""

    def test_concurrent_increments(self):
        from core.metrics_store import reset_metrics
        m = reset_metrics()
        n_threads = 10
        n_increments = 100

        def worker():
            for _ in range(n_increments):
                m.inc("concurrent_test")

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert m.get_counter("concurrent_test") == n_threads * n_increments


# ═══════════════════════════════════════════════════════════════
# TRACE INTELLIGENCE (O9-O12)
# ═══════════════════════════════════════════════════════════════

class TestTraceIntelligence:

    def test_success_trace(self):
        """O9: Success summary with models and tools."""
        from core.trace_intelligence import TraceSummarizer
        events = [
            {"ts": 1000, "component": "planner", "event": "plan_generated", "duration_ms": 500},
            {"ts": 1001, "component": "model_router", "event": "model_selected",
             "model_id": "claude-sonnet", "duration_ms": 200},
            {"ts": 1002, "component": "tool_executor", "event": "tool_executed",
             "tool": "shell_command", "ok": True, "duration_ms": 150},
            {"ts": 1003, "component": "tool_executor", "event": "tool_executed",
             "tool": "file_write", "ok": True, "duration_ms": 50},
            {"ts": 1004, "component": "executor", "event": "mission_completed", "duration_ms": 0},
        ]
        summary = TraceSummarizer.summarize_events("m-001", events)

        assert summary.status == "success"
        assert summary.event_count == 5
        assert len(summary.tool_calls) == 2
        assert len(summary.model_calls) == 1
        assert summary.primary_model == "claude-sonnet"
        assert summary.primary_tool == "shell_command"
        assert summary.timing.planning_ms == 500
        assert summary.duration_ms > 0

    def test_failure_trace(self):
        """O10: Failure analysis with root cause."""
        from core.trace_intelligence import TraceSummarizer
        events = [
            {"ts": 1000, "component": "planner", "event": "plan_generated", "duration_ms": 200},
            {"ts": 1001, "component": "tool_executor", "event": "tool_executed",
             "tool": "shell_command", "ok": False, "duration_ms": 5000,
             "error": "tool timed out"},
            {"ts": 1002, "component": "executor", "event": "mission_failed",
             "error": "max retries exceeded"},
        ]
        summary = TraceSummarizer.summarize_events("m-002", events)

        assert summary.status == "failed"
        assert summary.failure.failed is True
        assert summary.failure.primary_cause == "tool_crash"
        assert summary.failure.recoverable is True
        assert len(summary.failure.error_chain) >= 1

    def test_timing_breakdown(self):
        """O11: Timing percentages add up reasonably."""
        from core.trace_intelligence import TraceSummarizer
        events = [
            {"ts": 1000.0, "component": "planner", "event": "plan", "duration_ms": 500},
            {"ts": 1001.0, "component": "executor", "event": "execute", "duration_ms": 1500},
            {"ts": 1003.0, "component": "executor", "event": "mission_completed"},
        ]
        summary = TraceSummarizer.summarize_events("m-003", events)
        assert summary.timing.total_ms == 3000
        assert summary.timing.planning_ms == 500
        assert summary.timing.execution_ms == 1500
        pct = summary.timing.breakdown_pct
        assert "planning" in pct
        assert "execution" in pct

    def test_empty_trace(self):
        """O12: Empty trace produces valid summary."""
        from core.trace_intelligence import TraceSummarizer
        summary = TraceSummarizer.summarize_events("m-empty", [])
        assert summary.status == "no_trace"
        assert summary.event_count == 0
        assert summary.duration_ms == 0

    def test_digest_is_string(self):
        from core.trace_intelligence import TraceSummarizer
        events = [
            {"ts": 1000, "component": "executor", "event": "mission_completed"},
        ]
        summary = TraceSummarizer.summarize_events("m-004", events)
        digest = summary.digest()
        assert isinstance(digest, str)
        assert "m-004" in digest

    def test_timeout_trace(self):
        from core.trace_intelligence import TraceSummarizer
        events = [
            {"ts": 1000, "component": "executor", "event": "execution_timeout"},
        ]
        summary = TraceSummarizer.summarize_events("m-005", events)
        assert summary.status == "timeout"
        assert summary.failure.primary_cause == "timeout"

    def test_model_call_extraction(self):
        from core.trace_intelligence import TraceSummarizer
        events = [
            {"ts": 1000, "component": "llm", "event": "model_call",
             "model_id": "gpt-4o", "role": "planner", "duration_ms": 3000, "tokens": 500},
            {"ts": 1001, "component": "llm", "event": "model_call",
             "model_id": "gpt-4o", "role": "executor", "duration_ms": 2000, "tokens": 300},
            {"ts": 1002, "component": "llm", "event": "model_call",
             "model_id": "claude-sonnet", "role": "reviewer", "duration_ms": 1500, "tokens": 200},
            {"ts": 1003, "component": "executor", "event": "mission_completed"},
        ]
        summary = TraceSummarizer.summarize_events("m-006", events)
        assert len(summary.model_calls) == 3
        assert summary.primary_model == "gpt-4o"  # 2 calls vs 1


# ═══════════════════════════════════════════════════════════════
# DIAGNOSTICS ENDPOINTS (O13)
# ═══════════════════════════════════════════════════════════════

class TestDiagnosticsEndpoints:
    """O13: Verify route imports don't crash."""

    def test_observability_router_importable(self):
        from api.routes.observability import router
        assert router is not None

    def test_router_has_expected_routes(self):
        from api.routes.observability import router
        paths = [r.path for r in router.routes]
        prefix = "/api/v3/observability"
        assert f"{prefix}/health" in paths
        assert f"{prefix}/metrics" in paths
        assert f"{prefix}/status" in paths
        assert f"{prefix}/failures" in paths
        assert f"{prefix}/costs" in paths
        assert f"{prefix}/trace/{{mission_id}}" in paths
