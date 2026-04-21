"""tests/test_recovery_engine.py — Recovery engine tests."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestErrorClassification:
    def test_timeout(self):
        from core.resilience.recovery_engine import classify_error, ErrorCategory
        assert classify_error(TimeoutError("slow")) == ErrorCategory.TIMEOUT

    def test_connection(self):
        from core.resilience.recovery_engine import classify_error, ErrorCategory
        assert classify_error(ConnectionError("refused")) == ErrorCategory.TRANSIENT

    def test_permission(self):
        from core.resilience.recovery_engine import classify_error, ErrorCategory
        assert classify_error(PermissionError("denied")) == ErrorCategory.POLICY_BLOCKED

    def test_value_error(self):
        from core.resilience.recovery_engine import classify_error, ErrorCategory
        assert classify_error(ValueError("bad input")) == ErrorCategory.USER_INPUT

    def test_rate_limit_string(self):
        from core.resilience.recovery_engine import classify_error, ErrorCategory
        assert classify_error("429 rate_limit exceeded") == ErrorCategory.TRANSIENT

    def test_timeout_string(self):
        from core.resilience.recovery_engine import classify_error, ErrorCategory
        assert classify_error("operation timed out") == ErrorCategory.TIMEOUT

    def test_llm_error(self):
        from core.resilience.recovery_engine import classify_error, ErrorCategory
        assert classify_error("openai api error") == ErrorCategory.LLM_ERROR

    def test_generic_fallback(self):
        from core.resilience.recovery_engine import classify_error, ErrorCategory
        assert classify_error("something weird happened") == ErrorCategory.TOOL_ERROR


class TestRecoveryStrategy:
    def test_transient_retries(self):
        from core.resilience.recovery_engine import get_recovery_engine, RecoveryStrategy
        engine = get_recovery_engine()
        decision = engine.evaluate(ConnectionError("refused"), tool_name="web_search", mission_id="test1")
        assert decision.strategy == RecoveryStrategy.RETRY

    def test_timeout_retries(self):
        from core.resilience.recovery_engine import get_recovery_engine, RecoveryStrategy
        engine = get_recovery_engine()
        decision = engine.evaluate(TimeoutError("slow"), tool_name="http_get", mission_id="test2")
        assert decision.strategy == RecoveryStrategy.RETRY

    def test_tool_error_switches(self):
        from core.resilience.recovery_engine import get_recovery_engine, RecoveryStrategy
        engine = get_recovery_engine()
        decision = engine.evaluate("tool logic failure", tool_name="web_search", mission_id="test3")
        assert decision.strategy == RecoveryStrategy.SWITCH_TOOL
        assert decision.alternative_tool == "web_fetch"

    def test_user_input_asks_clarification(self):
        from core.resilience.recovery_engine import get_recovery_engine, RecoveryStrategy
        engine = get_recovery_engine()
        decision = engine.evaluate(ValueError("invalid input"), tool_name="test", mission_id="test4")
        assert decision.strategy == RecoveryStrategy.ASK_CLARIFICATION

    def test_policy_blocked(self):
        from core.resilience.recovery_engine import get_recovery_engine, RecoveryStrategy
        engine = get_recovery_engine()
        decision = engine.evaluate("permission denied by policy", tool_name="shell", mission_id="test5")
        assert decision.strategy == RecoveryStrategy.ASK_CLARIFICATION

    def test_llm_error_fallback(self):
        from core.resilience.recovery_engine import get_recovery_engine, RecoveryStrategy
        engine = get_recovery_engine()
        decision = engine.evaluate("openai api error", tool_name="llm_call", mission_id="test6")
        assert decision.strategy == RecoveryStrategy.FALLBACK_MODEL


class TestRecoveryContext:
    def test_retry_limit(self):
        from core.resilience.recovery_engine import RecoveryContext
        ctx = RecoveryContext(mission_id="test")
        assert ctx.can_retry("web_search", max_per_tool=2)
        ctx.record_retry("web_search")
        ctx.record_retry("web_search")
        assert not ctx.can_retry("web_search", max_per_tool=2)

    def test_total_retry_limit(self):
        from core.resilience.recovery_engine import RecoveryContext
        ctx = RecoveryContext(mission_id="test", max_total_retries=3)
        ctx.record_retry("tool1")
        ctx.record_retry("tool2")
        ctx.record_retry("tool3")
        assert not ctx.can_retry("tool4")

    def test_record_switch(self):
        from core.resilience.recovery_engine import RecoveryContext
        ctx = RecoveryContext(mission_id="test")
        ctx.record_switch("web_search", "web_fetch")
        assert "web_search→web_fetch" in ctx.switched_tools


class TestRecoveryDecision:
    def test_to_dict(self):
        from core.resilience.recovery_engine import RecoveryDecision, RecoveryStrategy, ErrorCategory
        d = RecoveryDecision(
            strategy=RecoveryStrategy.RETRY,
            error_category=ErrorCategory.TRANSIENT,
            original_error="connection refused",
            reasoning="Retry web_search",
            retry_count=1,
        )
        out = d.to_dict()
        assert out["strategy"] == "retry"
        assert out["error_category"] == "TRANSIENT"
        assert out["retry_count"] == 1


class TestRecoveryExhaustion:
    def test_exhausted_retries_switch_tool(self):
        """After max retries, should switch to alternative tool."""
        from core.resilience.recovery_engine import get_recovery_engine, RecoveryStrategy
        engine = get_recovery_engine()
        # Exhaust retries for web_search
        d1 = engine.evaluate(ConnectionError("err"), tool_name="web_search", mission_id="exhaust1")
        assert d1.strategy == RecoveryStrategy.RETRY
        d2 = engine.evaluate(ConnectionError("err"), tool_name="web_search", mission_id="exhaust1")
        assert d2.strategy == RecoveryStrategy.RETRY
        # Third attempt: retries exhausted → switch tool
        d3 = engine.evaluate(ConnectionError("err"), tool_name="web_search", mission_id="exhaust1")
        # Could be SWITCH_TOOL, FALLBACK_MODEL, or DEGRADE_GRACEFULLY
        assert d3.strategy != RecoveryStrategy.RETRY

    def test_all_strategies_exhausted_aborts(self):
        """When no strategy works, should abort safely."""
        from core.resilience.recovery_engine import get_recovery_engine, RecoveryStrategy
        engine = get_recovery_engine()
        # Tool with no alternatives and exhausted retries
        for i in range(10):
            d = engine.evaluate(TimeoutError("slow"), tool_name="unique_tool_xyz", mission_id="abort_test")
        # Eventually should abort
        assert d.strategy in (RecoveryStrategy.ABORT_SAFELY, RecoveryStrategy.DEGRADE_GRACEFULLY)

    def test_cleanup_removes_context(self):
        from core.resilience.recovery_engine import get_recovery_engine, _active_contexts
        engine = get_recovery_engine()
        engine.evaluate(TimeoutError("x"), tool_name="t", mission_id="cleanup_test")
        assert "cleanup_test" in _active_contexts
        engine.cleanup("cleanup_test")
        assert "cleanup_test" not in _active_contexts


class TestRecoveryEngineStats:
    def test_stats(self):
        from core.resilience.recovery_engine import get_recovery_engine
        stats = get_recovery_engine().stats()
        assert "active_contexts" in stats
        assert "total_strategies" in stats
        assert stats["total_strategies"] == 7
        assert "tool_alternatives" in stats


class TestBackoff:
    def test_backoff_increases(self):
        from core.resilience.recovery_engine import _calculate_backoff
        w0 = _calculate_backoff(0, base=1.0)
        w1 = _calculate_backoff(1, base=1.0)
        w2 = _calculate_backoff(2, base=1.0)
        # Average should increase (with ±20% jitter)
        assert w0 < 3  # ~1s ± jitter
        assert w2 > w0 * 1.5  # Should be noticeably larger

    def test_backoff_capped(self):
        from core.resilience.recovery_engine import _calculate_backoff
        w = _calculate_backoff(100, base=1.0, max_wait=30.0)
        assert w <= 36  # 30 + 20% jitter max
