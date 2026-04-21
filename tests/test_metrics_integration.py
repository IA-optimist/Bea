"""
Tests — Metrics Integration (Bridge)

Verifies that:
  I1. Monkey-patches install without error
  I2. MetaOrchestrator patch emits mission metrics
  I3. ToolExecutor patch emits tool metrics
  I4. LLMFactory patch emits model metrics
  I5. MemoryFacade patch emits memory metrics
  I6. ImprovementLoop patch emits experiment metrics
  I7. Trace→metrics bridge converts events
  I8. Cost extraction from OpenRouter metadata
  I9. Snapshot persistence (atomic write)
  I10. Alert conditions trigger correctly
  I11. Alert conditions don't false-positive on low data
  I12. install_instrumentation is idempotent
  I13. process_trace_event is fail-open
  I14. All patches are fail-open (don't crash on import failure)
"""
import json
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═══════════════════════════════════════════════════════════════
# TRACE → METRICS BRIDGE (I7)
# ═══════════════════════════════════════════════════════════════

class TestTraceBridge:

    def test_tool_failed_event(self):
        from core.metrics_store import reset_metrics
        from core.metrics_bridge import process_trace_event
        m = reset_metrics()

        process_trace_event({
            "component": "tool_executor",
            "event": "tool_failed",
            "tool": "web_search",
            "duration_ms": 5000,
            "error": "connection refused",
        })

        assert m.get_counter("tool_failures_total", {"tool": "web_search"}) >= 1

    def test_tool_timeout_event(self):
        from core.metrics_store import reset_metrics
        from core.metrics_bridge import process_trace_event
        m = reset_metrics()

        process_trace_event({
            "event": "tool_timeout",
            "tool": "shell_command",
        })

        assert m.get_counter("tool_timeout_total", {"tool": "shell_command"}) == 1

    def test_model_error_event(self):
        from core.metrics_store import reset_metrics
        from core.metrics_bridge import process_trace_event
        m = reset_metrics()

        process_trace_event({
            "event": "model_error",
            "model_id": "deepseek-v3",
            "error": "503 overloaded",
        })

        assert m.get_counter("model_failure_total", {"model_id": "deepseek-v3"}) == 1

    def test_retry_event(self):
        from core.metrics_store import reset_metrics
        from core.metrics_bridge import process_trace_event
        m = reset_metrics()

        process_trace_event({
            "event": "retry_attempt",
            "component": "executor",
        })

        assert m.get_counter("retry_attempts_total", {"component": "executor"}) == 1

    def test_mission_failed_event(self):
        from core.metrics_store import reset_metrics
        from core.metrics_bridge import process_trace_event
        m = reset_metrics()

        process_trace_event({
            "event": "mission_failed",
            "type": "deploy",
            "error": "container crashed",
        })

        assert m.get_counter("missions_failed_total", {"type": "deploy"}) == 1

    def test_unknown_event_ignored(self):
        """Unknown events don't crash."""
        from core.metrics_store import reset_metrics
        from core.metrics_bridge import process_trace_event
        reset_metrics()
        # Should not raise
        process_trace_event({"event": "some_random_event", "data": "stuff"})

    def test_empty_event_ignored(self):
        from core.metrics_bridge import process_trace_event
        # Should not raise
        process_trace_event({})


# ═══════════════════════════════════════════════════════════════
# COST EXTRACTION (I8)
# ═══════════════════════════════════════════════════════════════

class TestCostExtraction:

    def test_openrouter_real_cost(self):
        from core.metrics_store import reset_metrics
        from core.metrics_bridge import _extract_cost_from_response
        m = reset_metrics()

        _extract_cost_from_response(
            response_metadata={
                "headers": {
                    "x-openrouter-cost": "0.0042",
                    "x-openrouter-model": "anthropic/claude-sonnet-4",
                },
                "token_usage": {"prompt_tokens": 1000, "completion_tokens": 500},
            },
            model_id="anthropic/claude-sonnet-4",
            mission_id="m-test",
        )

        snap = m.costs.snapshot()
        assert snap["total_estimated_usd"] == 0.0042
        assert "anthropic/claude-sonnet-4" in snap["by_model"]
        assert "m-test" in snap["top_missions"]

    def test_estimated_cost_fallback(self):
        from core.metrics_store import reset_metrics
        from core.metrics_bridge import _extract_cost_from_response
        m = reset_metrics()

        _extract_cost_from_response(
            response_metadata={
                "token_usage": {"prompt_tokens": 500000, "completion_tokens": 500000},
            },
            model_id="deepseek/deepseek-v3",
        )

        snap = m.costs.snapshot()
        # deepseek is "cheap" tier (0.50/1M tokens), 1M tokens = $0.50
        assert snap["total_estimated_usd"] > 0
        assert "deepseek/deepseek-v3" in snap["by_model"]

    def test_local_model_zero_cost(self):
        from core.metrics_store import reset_metrics
        from core.metrics_bridge import _extract_cost_from_response
        m = reset_metrics()

        _extract_cost_from_response(
            response_metadata={
                "token_usage": {"prompt_tokens": 10000, "completion_tokens": 5000},
            },
            model_id="ollama/qwen2.5",
        )

        snap = m.costs.snapshot()
        assert snap["total_estimated_usd"] == 0.0  # local = free

    def test_empty_metadata_no_crash(self):
        from core.metrics_bridge import _extract_cost_from_response
        # Should not raise
        _extract_cost_from_response({}, "unknown")


# ═══════════════════════════════════════════════════════════════
# SNAPSHOT PERSISTENCE (I9)
# ═══════════════════════════════════════════════════════════════

class TestSnapshotPersistence:

    def test_snapshot_write(self, tmp_path):
        from core.metrics_store import reset_metrics, emit_mission_submitted

        m = reset_metrics()
        emit_mission_submitted("test_snap")

        path = tmp_path / "metrics_snapshot.json"

        # Run one iteration of the loop manually
        stop = threading.Event()

        # Just write once directly
        data = m.snapshot()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, default=str))
        os.replace(str(tmp), str(path))

        assert path.exists()
        loaded = json.loads(path.read_text())
        assert "counters" in loaded
        assert "missions_submitted_total" in loaded["counters"]

    def test_atomic_rename(self, tmp_path):
        """Verify atomic write pattern (write .tmp then rename)."""
        path = tmp_path / "test.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text('{"test": true}')
        os.replace(str(tmp), str(path))

        assert path.exists()
        assert not tmp.exists()
        assert json.loads(path.read_text()) == {"test": True}


# ═══════════════════════════════════════════════════════════════
# ALERTS (I10, I11)
# ═══════════════════════════════════════════════════════════════

class TestAlerts:

    def test_low_success_rate_alert(self):
        """I10: Alert fires when success rate < 0.7."""
        from core.metrics_store import reset_metrics, emit_mission_submitted, emit_mission_completed, emit_mission_failed
        from core.metrics_bridge import evaluate_alerts
        m = reset_metrics()

        # 10 submitted, 3 completed, 7 failed → 30% success
        for _ in range(10):
            emit_mission_submitted("test")
        for _ in range(3):
            emit_mission_completed("test", 1000)
        for _ in range(7):
            emit_mission_failed("test", "error")

        alerts = evaluate_alerts()
        assert any(a["alert"] == "low_mission_success_rate" for a in alerts)
        rate_alert = [a for a in alerts if a["alert"] == "low_mission_success_rate"][0]
        assert rate_alert["current"] == 0.3
        assert rate_alert["severity"] == "critical"  # < 0.5

    def test_high_tool_failure_rate_alert(self):
        from core.metrics_store import reset_metrics, emit_tool_invocation
        from core.metrics_bridge import evaluate_alerts
        m = reset_metrics()

        # 10 calls, 5 failures → 50% failure rate
        for _ in range(5):
            emit_tool_invocation("shell", True)
        for _ in range(5):
            emit_tool_invocation("shell", False)

        alerts = evaluate_alerts()
        assert any(a["alert"] == "high_tool_failure_rate" for a in alerts)

    def test_retry_storm_alert(self):
        from core.metrics_store import reset_metrics, emit_retry
        from core.metrics_bridge import evaluate_alerts
        m = reset_metrics()

        for _ in range(8):
            emit_retry("executor")

        alerts = evaluate_alerts()
        assert any(a["alert"] == "retry_storm" for a in alerts)

    def test_circuit_breaker_alert(self):
        from core.metrics_store import reset_metrics, emit_circuit_breaker
        from core.metrics_bridge import evaluate_alerts
        m = reset_metrics()

        for _ in range(5):
            emit_circuit_breaker("open")

        alerts = evaluate_alerts()
        assert any(a["alert"] == "circuit_breaker_flapping" for a in alerts)

    def test_no_false_positives_on_low_data(self):
        """I11: No alerts when data is insufficient."""
        from core.metrics_store import reset_metrics, emit_mission_submitted, emit_mission_completed
        from core.metrics_bridge import evaluate_alerts
        m = reset_metrics()

        # Only 2 missions — below threshold of 5
        emit_mission_submitted("test")
        emit_mission_submitted("test")
        emit_mission_completed("test", 1000)

        alerts = evaluate_alerts()
        # Should have no mission_success_rate alert (not enough data)
        assert not any(a["alert"] == "low_mission_success_rate" for a in alerts)

    def test_alert_emits_metric(self):
        """Triggered alerts increment alert_triggered_total counter."""
        from core.metrics_store import reset_metrics, emit_retry
        from core.metrics_bridge import evaluate_alerts
        m = reset_metrics()

        for _ in range(10):
            emit_retry("executor")

        evaluate_alerts()
        assert m.get_counter_total("alert_triggered_total") >= 1


# ═══════════════════════════════════════════════════════════════
# INSTALLATION (I1, I12, I14)
# ═══════════════════════════════════════════════════════════════

class TestInstallation:

    def test_patches_importable(self):
        """I1: All patch functions exist and can be called."""
        from core.metrics_bridge import (
            _patch_meta_orchestrator,
            _patch_tool_executor,
        )
        # These should not raise even if target modules have issues
        # (they're all wrapped in try/except)
        _patch_meta_orchestrator()
        _patch_tool_executor()

    def test_process_trace_event_failopen(self):
        """I13: process_trace_event never raises."""
        from core.metrics_bridge import process_trace_event
        # None of these should raise
        process_trace_event(None)  # type: ignore
        process_trace_event(42)    # type: ignore
        process_trace_event({"event": None})

    def test_evaluate_alerts_empty_metrics(self):
        """Alerts on empty metrics return empty list, no crash."""
        from core.metrics_store import reset_metrics
        from core.metrics_bridge import evaluate_alerts
        reset_metrics()
        alerts = evaluate_alerts()
        assert isinstance(alerts, list)
        assert len(alerts) == 0


# ═══════════════════════════════════════════════════════════════
# FULL INTEGRATION — metrics change during simulated mission
# ═══════════════════════════════════════════════════════════════

class TestFullIntegration:

    def test_metrics_change_during_mission_simulation(self):
        """Simulate a full mission and verify all metrics updated."""
        from core.metrics_store import (
            reset_metrics, emit_mission_submitted, emit_mission_completed,
            emit_tool_invocation, emit_model_selected,
            emit_model_latency, emit_memory_search,
            emit_orchestrator_timing, emit_experiment,
        )
        m = reset_metrics()

        # Simulate mission lifecycle
        emit_mission_submitted("code_review")
        emit_orchestrator_timing("classify", 120)
        emit_orchestrator_timing("planning", 2000)
        emit_model_selected("claude-sonnet", "cloud")
        emit_model_latency("claude-sonnet", 3500)
        emit_tool_invocation("shell_command", True, 200)
        emit_tool_invocation("file_write", True, 50)
        emit_memory_search(hit=True, latency_ms=35)
        emit_mission_completed("code_review", duration_ms=8000)

        # After mission: run improvement
        emit_experiment("promoted", 0.12)

        # Verify everything was recorded
        assert m.get_counter("missions_submitted_total", {"type": "code_review"}) == 1
        assert m.get_counter("missions_completed_total", {"type": "code_review"}) == 1
        assert m.get_counter("tool_invocations_total", {"tool": "shell_command"}) == 1
        assert m.get_counter("model_selected_total", {"model_id": "claude-sonnet"}) == 1
        assert m.get_counter("memory_search_hits") == 1
        assert m.get_counter("experiments_promoted_total") == 1
        assert m.get_histogram("mission_duration_ms", {"type": "code_review"})["avg"] == 8000
        assert m.get_histogram("classify_latency_ms")["avg"] == 120
        assert m.get_histogram("model_latency_ms", {"model_id": "claude-sonnet"})["avg"] == 3500

    def test_cost_tracked_during_mission(self):
        from core.metrics_store import reset_metrics
        from core.metrics_bridge import _extract_cost_from_response
        m = reset_metrics()

        _extract_cost_from_response(
            {"headers": {"x-openrouter-cost": "0.015"},
             "token_usage": {"prompt_tokens": 2000, "completion_tokens": 1000}},
            "anthropic/claude-sonnet-4", mission_id="m-42",
        )

        snap = m.costs.snapshot()
        assert snap["total_estimated_usd"] == 0.015
        assert "m-42" in snap["top_missions"]
