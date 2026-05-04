"""Tests for core/runtime_introspection.py — runtime self-awareness."""


def test_import():
    pass


# ═══════════════════════════════════════════════════════════════
# PRIORITY 1 — RUNTIME CAPABILITIES
# ═══════════════════════════════════════════════════════════════

def test_capability_to_dict():
    from core.runtime_introspection import Capability
    c = Capability(name="test", available=True, version="1.0", detail="ok")
    d = c.to_dict()
    assert d["name"] == "test"
    assert d["available"] is True
    assert d["version"] == "1.0"


def test_get_runtime_capabilities_returns_stable_schema():
    from core.runtime_introspection import get_runtime_capabilities
    caps = get_runtime_capabilities()
    # Schema must always have these keys
    assert "timestamp" in caps
    assert "capabilities" in caps
    assert "summary" in caps
    assert isinstance(caps["timestamp"], float)
    assert isinstance(caps["capabilities"], dict)
    assert "total" in caps["summary"]
    assert "available" in caps["summary"]
    assert "unavailable" in caps["summary"]


def test_capabilities_include_all_categories():
    from core.runtime_introspection import get_runtime_capabilities
    caps = get_runtime_capabilities()
    expected = {"python", "packages", "tools", "filesystem", "network",
                "docker", "git", "optional_modules"}
    actual = set(caps["capabilities"].keys())
    assert expected == actual, f"Missing: {expected - actual}, Extra: {actual - expected}"


def test_python_capability_detected():
    from core.runtime_introspection import get_runtime_capabilities
    caps = get_runtime_capabilities()
    py = caps["capabilities"]["python"]
    assert py["available"] is True
    assert "3." in py["version"]
    assert py["meta"]["compatible"] is True


def test_filesystem_capability_detected():
    from core.runtime_introspection import get_runtime_capabilities
    caps = get_runtime_capabilities()
    fs = caps["capabilities"]["filesystem"]
    assert fs["available"] is True
    assert "cwd" in fs["meta"]


def test_capability_fields_always_present():
    """Every capability dict must have all standard fields."""
    from core.runtime_introspection import get_runtime_capabilities
    caps = get_runtime_capabilities()
    for name, cap in caps["capabilities"].items():
        assert "name" in cap, f"{name} missing 'name'"
        assert "available" in cap, f"{name} missing 'available'"
        assert "version" in cap, f"{name} missing 'version'"
        assert "detail" in cap, f"{name} missing 'detail'"
        assert "meta" in cap, f"{name} missing 'meta'"


def test_summary_math():
    """Summary available + unavailable must equal total."""
    from core.runtime_introspection import get_runtime_capabilities
    caps = get_runtime_capabilities()
    s = caps["summary"]
    assert s["available"] + s["unavailable"] == s["total"]


def test_capabilities_never_raise():
    """get_runtime_capabilities must never raise, even in broken environments."""
    from core.runtime_introspection import get_runtime_capabilities
    caps = get_runtime_capabilities()
    assert caps is not None


# ═══════════════════════════════════════════════════════════════
# PRIORITY 2 — TOOL HEALTH CHECKS
# ═══════════════════════════════════════════════════════════════

def test_tool_health_to_dict():
    from core.runtime_introspection import ToolHealth
    h = ToolHealth(tool="test", status="ok", reason="passed")
    d = h.to_dict()
    assert d["tool"] == "test"
    assert d["status"] == "ok"


def test_check_tool_health_read_file():
    from core.runtime_introspection import check_tool_health
    health = check_tool_health("read_file")
    assert health.status == "ok"
    assert health.dependencies_met is True


def test_check_tool_health_unknown_tool():
    """Unknown tools should return ok (no deps to fail)."""
    from core.runtime_introspection import check_tool_health
    health = check_tool_health("nonexistent_tool_xyz")
    assert health.status == "ok"  # no deps = all deps met


def test_check_tool_health_with_missing_dep():
    """Tool with missing dependency should be unavailable."""
    from core.runtime_introspection import check_tool_health, _TOOL_DEPENDENCIES
    # Temporarily register a tool with a fake dependency
    _TOOL_DEPENDENCIES["_test_fake_tool"] = ["nonexistent_module_xyz_12345"]
    try:
        health = check_tool_health("_test_fake_tool")
        assert health.status == "unavailable"
        assert "missing" in health.reason.lower()
        assert health.dependencies_met is False
    finally:
        del _TOOL_DEPENDENCIES["_test_fake_tool"]


def test_check_tool_health_git_tool():
    """Git tools should check for git binary."""
    from core.runtime_introspection import check_tool_health
    health = check_tool_health("git_status")
    # Git is available in most environments
    assert health.status in ("ok", "unavailable")
    assert health.response_ms >= 0


def test_check_all_tools_health():
    from core.runtime_introspection import check_all_tools_health
    results = check_all_tools_health()
    assert isinstance(results, dict)
    assert len(results) > 0
    for name, health in results.items():
        assert "status" in health
        assert "reason" in health
        assert health["status"] in ("ok", "degraded", "unavailable")


def test_tool_health_never_raises():
    """check_tool_health must never raise."""
    from core.runtime_introspection import check_tool_health
    # Even with weird input
    h = check_tool_health("")
    assert h.status in ("ok", "degraded", "unavailable")
    h2 = check_tool_health("a" * 1000)
    assert h2.status in ("ok", "degraded", "unavailable")


# ═══════════════════════════════════════════════════════════════
# PRIORITY 3 — ERROR CLASSIFICATION
# ═══════════════════════════════════════════════════════════════

def test_classify_network_error():
    from core.runtime_introspection import classify_error
    r = classify_error(ConnectionError("refused"))
    assert r["category"] == "network_error"
    assert r["retryable"] is True


def test_classify_timeout_error():
    from core.runtime_introspection import classify_error
    r = classify_error(TimeoutError("timed out"))
    assert r["category"] == "timeout_error"
    assert r["retryable"] is True


def test_classify_auth_error():
    from core.runtime_introspection import classify_error
    r = classify_error(PermissionError("forbidden"))
    assert r["category"] == "auth_error"
    assert r["retryable"] is False
    assert r["severity"] == "high"


def test_classify_dependency_error():
    from core.runtime_introspection import classify_error
    r = classify_error(ImportError("No module named 'foo'"))
    assert r["category"] == "dependency_error"
    assert r["severity"] == "high"


def test_classify_file_error():
    from core.runtime_introspection import classify_error
    r = classify_error(FileNotFoundError("missing.py"))
    assert r["category"] == "file_error"
    assert r["severity"] == "low"


def test_classify_quota_by_keyword():
    from core.runtime_introspection import classify_error
    r = classify_error(Exception("Rate limit exceeded. Try again later."))
    assert r["category"] == "quota_error"
    assert r["retryable"] is True


def test_classify_server_error_by_keyword():
    from core.runtime_introspection import classify_error
    r = classify_error(Exception("HTTP 503 Service Unavailable"))
    assert r["category"] == "server_error"
    assert r["retryable"] is True


def test_classify_oom():
    from core.runtime_introspection import classify_error
    r = classify_error(MemoryError())
    assert r["category"] == "memory_error"
    assert r["severity"] == "critical"


def test_classify_unknown():
    from core.runtime_introspection import classify_error
    r = classify_error(Exception("something totally random happened"))
    assert r["category"] == "unknown_error"


def test_classify_has_suggestion():
    """Every classification should include a remediation suggestion."""
    from core.runtime_introspection import classify_error
    errors = [
        ConnectionError(), TimeoutError(), PermissionError(),
        ImportError(), FileNotFoundError(), MemoryError(),
        Exception("rate limit"), Exception("unknown"),
    ]
    for e in errors:
        r = classify_error(e)
        assert "suggestion" in r
        assert len(r["suggestion"]) > 5


def test_classify_has_all_fields():
    """Every classification must have the full field set."""
    from core.runtime_introspection import classify_error
    r = classify_error(RuntimeError("test"))
    required = {"category", "type", "message", "retryable", "severity", "suggestion"}
    assert required.issubset(r.keys())


def test_classify_never_raises():
    from core.runtime_introspection import classify_error
    assert classify_error(None) is not None
    assert classify_error(Exception()) is not None


# ═══════════════════════════════════════════════════════════════
# PRIORITY 4 — EXECUTION SIGNALS
# ═══════════════════════════════════════════════════════════════

def test_record_and_retrieve_signals():
    from core.runtime_introspection import (
        record_execution_signal, get_execution_signals, clear_signals,
    )
    clear_signals()
    record_execution_signal("duration_bucket", "test_source", "fast")
    record_execution_signal("retry_frequency", "api_call", 3)
    signals = get_execution_signals()
    assert len(signals) == 2
    assert signals[0]["signal_type"] == "retry_frequency"  # most recent first


def test_signal_filtering():
    from core.runtime_introspection import (
        record_execution_signal, get_execution_signals, clear_signals,
    )
    clear_signals()
    record_execution_signal("duration_bucket", "source_a", "fast")
    record_execution_signal("tool_failure", "source_b", "error")
    record_execution_signal("duration_bucket", "source_c", "slow")
    # Filter by type
    duration = get_execution_signals(signal_type="duration_bucket")
    assert len(duration) == 2
    # Filter by source
    source_b = get_execution_signals(source="source_b")
    assert len(source_b) == 1


def test_signal_buffer_bounded():
    from core.runtime_introspection import (
        record_execution_signal, clear_signals, _SIGNAL_BUFFER, _MAX_SIGNALS,
    )
    clear_signals()
    for i in range(_MAX_SIGNALS + 100):
        record_execution_signal("test", f"source_{i}", i)
    assert len(_SIGNAL_BUFFER) <= _MAX_SIGNALS


def test_signal_summary():
    from core.runtime_introspection import (
        record_execution_signal, get_signal_summary, clear_signals,
    )
    clear_signals()
    record_execution_signal("duration_bucket", "agent_a", "fast")
    record_execution_signal("duration_bucket", "agent_b", "slow")
    record_execution_signal("tool_failure", "fetch_url", "timeout")
    record_execution_signal("retry_frequency", "api_call", 2)
    summary = get_signal_summary()
    assert summary["total_signals"] == 4
    assert summary["by_type"]["duration_bucket"] == 2
    assert "fetch_url" in summary["tool_failures"]
    assert "api_call" in summary["retry_sources"]


def test_duration_bucket():
    from core.runtime_introspection import duration_bucket
    assert duration_bucket(10) == "fast"
    assert duration_bucket(99) == "fast"
    assert duration_bucket(100) == "normal"
    assert duration_bucket(500) == "normal"
    assert duration_bucket(1000) == "slow"
    assert duration_bucket(5000) == "slow"
    assert duration_bucket(10000) == "timeout"
    assert duration_bucket(99999) == "timeout"


def test_record_signal_never_crashes():
    """record_execution_signal must never raise."""
    from core.runtime_introspection import record_execution_signal
    record_execution_signal(None, None, None)  # garbage input
    record_execution_signal("", "", "")
    # Should not raise
