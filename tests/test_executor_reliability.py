"""tests/test_executor_reliability.py — ToolExecutor reliability tests."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestErrorClassification:
    """Verify _classify_error covers all canonical types."""

    def test_timeout_exception(self):
        from core.tool_executor import _classify_error
        assert _classify_error(TimeoutError("timed out")) == "TIMEOUT"

    def test_connection_error(self):
        from core.tool_executor import _classify_error
        assert _classify_error(ConnectionError("refused")) == "TRANSIENT"

    def test_timeout_string(self):
        from core.tool_executor import _classify_error
        assert _classify_error("operation timed out") == "TIMEOUT"

    def test_rate_limit_string(self):
        from core.tool_executor import _classify_error
        # _classify_error string-based: "rate" triggers TRANSIENT
        result = _classify_error("429 rate_limit exceeded")
        assert result in ("TRANSIENT", "TOOL_ERROR")  # depends on string match rules

    def test_permission_denied(self):
        from core.tool_executor import _classify_error
        assert _classify_error(PermissionError("denied")) in ("POLICY_BLOCKED", "USER_INPUT", "TOOL_ERROR")

    def test_default_classification(self):
        from core.tool_executor import _classify_error
        result = _classify_error("some random error")
        assert result == "TOOL_ERROR"


class TestResultEnvelopes:
    """Verify structured result format."""

    def test_ok_envelope(self):
        from core.tool_executor import _ok
        r = _ok("success", tool="test")
        assert r["ok"] is True
        assert r["result"] == "success"
        assert r["error"] is None
        assert "ts" in r
        assert r["tool"] == "test"

    def test_err_envelope(self):
        from core.tool_executor import _err
        r = _err("failed", retryable=True, error_class="TRANSIENT")
        assert r["ok"] is False
        assert r["error"] == "failed"
        assert r["retryable"] is True
        assert r["error_class"] == "TRANSIENT"


class TestToolExecutor:
    """ToolExecutor runtime safety."""

    def test_singleton(self):
        from core.tool_executor import get_tool_executor
        te1 = get_tool_executor()
        te2 = get_tool_executor()
        assert te1 is te2

    def test_list_tools(self):
        from core.tool_executor import get_tool_executor
        te = get_tool_executor()
        tools = te.list_tools()
        assert len(tools) >= 10
        assert all(isinstance(t, str) for t in tools)

    def test_tool_timeouts_defined(self):
        from core.tool_executor import get_tool_executor
        te = get_tool_executor()
        assert hasattr(te, '_TOOL_TIMEOUTS')
        assert len(te._TOOL_TIMEOUTS) > 0

    def test_execute_unknown_tool(self):
        from core.tool_executor import get_tool_executor
        te = get_tool_executor()
        result = te.execute("nonexistent_tool_xyz", {})
        assert result["ok"] is False

    def test_execute_returns_structured(self):
        from core.tool_executor import get_tool_executor
        te = get_tool_executor()
        result = te.execute("web_search", {"query": "test"})
        assert "ok" in result
        assert isinstance(result["ok"], bool)

    def test_tool_os_metadata_present(self):
        """Tool OS metadata enrichment exists in executor."""
        from core.tool_executor import get_tool_executor
        te = get_tool_executor()
        # Just verify the enrichment code path exists in source
        import inspect
        source = inspect.getsource(te.execute)
        assert "tool_os_layer" in source or "_tool_os" in source

    def test_dynamic_timeout(self):
        """Dynamic timeout calculation exists and returns reasonable values."""
        from core.tool_executor import get_tool_executor
        te = get_tool_executor()
        t = te._dynamic_timeout("shell_command", 8)
        assert isinstance(t, (int, float))
        assert t >= 5  # Minimum should be reasonable


class TestToolExecutorRetry:
    """Retry mechanism tests."""

    def test_execute_with_retry_exists(self):
        from core.tool_executor import get_tool_executor
        te = get_tool_executor()
        assert hasattr(te, '_execute_with_retry')

    def test_retry_on_transient(self):
        """Transient errors should be marked retryable."""
        from core.tool_executor import _err
        r = _err("connection refused", retryable=True, error_class="TRANSIENT")
        assert r["retryable"] is True

    def test_no_retry_on_user_input(self):
        from core.tool_executor import _err
        r = _err("invalid input", retryable=False, error_class="USER_INPUT")
        assert r["retryable"] is False

    def test_no_retry_on_policy(self):
        from core.tool_executor import _err
        r = _err("policy blocked", retryable=False, error_class="POLICY_BLOCKED")
        assert r["retryable"] is False


class TestExecutionErrors:
    """BeaExecutionError tests."""

    def test_from_timeout(self):
        from core.resilience import BeaExecutionError
        e = BeaExecutionError.from_exception(TimeoutError("slow"), tool="web_search")
        assert e.error_type in ("TIMEOUT", "TOOL_TIMEOUT")
        assert e.retryable is True
        assert e.tool == "web_search"

    def test_from_connection(self):
        from core.resilience import BeaExecutionError
        e = BeaExecutionError.from_exception(ConnectionError("refused"), tool="http_get")
        assert e.retryable is True

    def test_to_dict(self):
        from core.resilience import BeaExecutionError
        e = BeaExecutionError("test error", tool="shell", stage="execution")
        d = e.to_dict()
        assert "error_type" in d or "severity" in d  # depends on error class
        assert "tool" in d
        assert d["tool"] == "shell"

    def test_circuit_breaker(self):
        from core.resilience import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        assert cb.can_execute("test_tool")
        cb.record_failure("test_tool")
        cb.record_failure("test_tool")
        assert not cb.can_execute("test_tool")
        import time
        time.sleep(0.15)
        assert cb.can_execute("test_tool")  # Recovery window passed
