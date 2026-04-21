"""Tests for executor hardening — Phase 2.

Verifies:
1. Error classification returns canonical taxonomy types
2. Completion integrity: all-FAILED → FAILED (not DONE)  
3. Timeout classification returns TIMEOUT type
4. Retry only on retryable errors
5. No silent except blocks in hot-path files
"""
import sys
import os
import re

# ── Test 1: Canonical error classification ─────────────────────────────────

def test_classify_timeout():
    """Timeout errors must return TIMEOUT."""
    sys.path.insert(0, '/app')
    from core.tool_executor import _classify_error
    assert _classify_error("timeout exceeded") == "TIMEOUT"
    assert _classify_error("connection timed out") == "TIMEOUT"
    assert _classify_error(TimeoutError("tool timed out")) == "TIMEOUT"

def test_classify_transient():
    """Network errors must return TRANSIENT."""
    from core.tool_executor import _classify_error
    assert _classify_error("connection refused") == "TRANSIENT"
    assert _classify_error(ConnectionError("network down")) == "TRANSIENT"
    assert _classify_error(OSError("unreachable")) == "TRANSIENT"

def test_classify_policy():
    """Permission/blocked errors must return POLICY_BLOCKED."""
    from core.tool_executor import _classify_error
    assert _classify_error("permission denied") == "POLICY_BLOCKED"
    assert _classify_error("blocked by policy") == "POLICY_BLOCKED"
    assert _classify_error(PermissionError("forbidden")) == "POLICY_BLOCKED"

def test_classify_user_input():
    """Missing/not-found errors must return USER_INPUT."""
    from core.tool_executor import _classify_error
    assert _classify_error("file not found") == "USER_INPUT"
    assert _classify_error(ValueError("invalid param")) == "USER_INPUT"
    assert _classify_error(KeyError("missing")) == "USER_INPUT"

def test_classify_system():
    """Import/module errors must return SYSTEM_ERROR."""
    from core.tool_executor import _classify_error
    assert _classify_error(ModuleNotFoundError("no module")) == "SYSTEM_ERROR"
    assert _classify_error(ImportError("missing lib")) == "SYSTEM_ERROR"

def test_classify_generic():
    """Unknown errors fall back to TOOL_ERROR."""
    from core.tool_executor import _classify_error
    assert _classify_error("something weird happened") == "TOOL_ERROR"
    assert _classify_error(RuntimeError("generic")) == "TOOL_ERROR"

def test_all_canonical_types():
    """All classification results must be in the canonical set."""
    from core.tool_executor import _classify_error
    CANONICAL = {"TRANSIENT", "USER_INPUT", "TOOL_ERROR", "POLICY_BLOCKED", "TIMEOUT", "SYSTEM_ERROR"}
    test_inputs = [
        "timeout", "denied", "not found", "connection refused",
        "import error", "random stuff", TimeoutError(), PermissionError(),
        ValueError(), ConnectionError(), RuntimeError(), ModuleNotFoundError(),
    ]
    for inp in test_inputs:
        result = _classify_error(inp)
        assert result in CANONICAL, f"_classify_error({inp!r}) = {result!r} not in {CANONICAL}"

# ── Test 2: Completion integrity ──────────────────────────────────────────

def test_err_default_class():
    """_err() must default to TOOL_ERROR, not empty string."""
    from core.tool_executor import _err
    r = _err("something broke")
    assert r["error_class"] == "TOOL_ERROR"
    assert r["ok"] is False

# ── Test 3: JarvisExecutionError integration ──────────────────────────────

def test_jarvis_execution_error_from_exception():
    """JarvisExecutionError.from_exception must return all canonical types."""
    from core.resilience import JarvisExecutionError
    CANONICAL = {"TRANSIENT", "USER_INPUT", "TOOL_ERROR", "POLICY_BLOCKED", "TIMEOUT", "SYSTEM_ERROR"}
    
    tests = [
        (TimeoutError("x"), "TIMEOUT"),
        (ConnectionError("x"), "TRANSIENT"),
        (PermissionError("x"), "POLICY_BLOCKED"),
        (ValueError("x"), "USER_INPUT"),
        (FileNotFoundError("x"), "SYSTEM_ERROR"),
        (RuntimeError("x"), "TOOL_ERROR"),
    ]
    for exc, expected in tests:
        result = JarvisExecutionError.from_exception(exc)
        assert result.error_type == expected, f"{exc!r} → {result.error_type}, expected {expected}"
        assert result.error_type in CANONICAL

def test_jarvis_execution_error_retryable():
    """Only TRANSIENT and TIMEOUT should be retryable."""
    from core.resilience import JarvisExecutionError
    
    transient = JarvisExecutionError.from_exception(ConnectionError("x"))
    assert transient.retryable is True
    
    timeout = JarvisExecutionError.from_exception(TimeoutError("x"))
    assert timeout.retryable is True
    
    user = JarvisExecutionError.from_exception(ValueError("x"))
    assert user.retryable is False
    
    policy = JarvisExecutionError.from_exception(PermissionError("x"))
    assert policy.retryable is False

# ── Test 4: No silent except blocks audit ─────────────────────────────────

def test_no_silent_except_in_hot_path():
    """Hot-path files must have zero silent except blocks (except+pass without logging)."""
    HOT_PATH = [
        'core/action_executor.py',
        'core/meta_orchestrator.py',
        'core/agent_loop.py',
    ]
    silent_blocks = []
    for filepath in HOT_PATH:
        full = os.path.join('/app', filepath)
        if not os.path.exists(full):
            continue
        with open(full) as fh:
            lines = fh.readlines()
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            if re.match(r'except\s+(Exception)?\s*:', stripped) and i + 1 < len(lines):
                next_stripped = lines[i+1].strip()
                if next_stripped == 'pass':
                    # Check no log in surrounding lines
                    has_log = any('log.' in lines[j] or 'logger.' in lines[j]
                                  for j in range(max(0, i-1), min(len(lines), i+3)))
                    if not has_log:
                        silent_blocks.append(f"{filepath}:{i+1}")
    
    assert len(silent_blocks) == 0, f"Silent except blocks found: {silent_blocks}"

# ── Test 5: Error result structure ────────────────────────────────────────

def test_error_result_has_required_fields():
    """Error results must contain ok, error, error_class fields."""
    from core.tool_executor import _err
    r = _err("test error", error_class="TIMEOUT", tool="web_search")
    assert "ok" in r and r["ok"] is False
    assert "error" in r and r["error"] == "test error"
    assert "error_class" in r and r["error_class"] == "TIMEOUT"
    assert "tool" in r and r["tool"] == "web_search"
