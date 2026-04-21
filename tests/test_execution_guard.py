"""Tests for core/execution_guard.py — post-action verification."""
import os
import tempfile
import pytest


def test_import():
    pass


# ── GuardResult ───────────────────────────────────────────────

def test_guard_result_summary_ok():
    from core.execution_guard import GuardResult, StepResult
    r = GuardResult(
        passed=True, action_type="write_file", target="/tmp/test.py",
        steps=[StepResult("exists", True), StepResult("read", True)],
    )
    assert "[GUARD OK]" in r.summary()


def test_guard_result_summary_fail():
    from core.execution_guard import GuardResult, StepResult
    r = GuardResult(
        passed=False, action_type="write_file", target="/tmp/test.py",
        steps=[StepResult("exists", False, "ABSENT")],
        error="File not found",
    )
    assert "[GUARD FAIL]" in r.summary()
    assert r.failed_step().step == "exists"


def test_guard_result_to_dict():
    from core.execution_guard import GuardResult
    r = GuardResult(passed=True, action_type="test", target="/tmp/x")
    d = r.to_dict()
    assert d["passed"] is True
    assert d["action_type"] == "test"


# ── guard_write ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_guard_write_success():
    from core.execution_guard import ExecutionGuard
    guard = ExecutionGuard()
    content = "print('hello')\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(content)
        path = f.name
    try:
        result = await guard.guard_write(path, content)
        assert result.passed
        assert len(result.steps) == 3  # exists, read, validate
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_guard_write_missing_file():
    from core.execution_guard import ExecutionGuard
    guard = ExecutionGuard()
    result = await guard.guard_write("/tmp/nonexistent_guard_test_99999.py", "content")
    assert not result.passed
    assert result.failed_step().step == "exists"


@pytest.mark.asyncio
async def test_guard_write_content_mismatch():
    from core.execution_guard import ExecutionGuard
    guard = ExecutionGuard()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("actual content")
        path = f.name
    try:
        result = await guard.guard_write(path, "expected content")
        assert not result.passed
        assert result.failed_step().step == "validate"
    finally:
        os.unlink(path)


# ── guard_replace ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_guard_replace_success():
    from core.execution_guard import ExecutionGuard
    guard = ExecutionGuard()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("x = 'new_value'\n")
        path = f.name
    try:
        result = await guard.guard_replace(path, "old_value", "new_value")
        assert result.passed
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_guard_replace_old_still_present():
    from core.execution_guard import ExecutionGuard
    guard = ExecutionGuard()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("x = 'old_value'\ny = 'new_value'\n")
        path = f.name
    try:
        result = await guard.guard_replace(path, "old_value", "new_value")
        assert not result.passed  # old_value still present
    finally:
        os.unlink(path)


# ── Syntax validation ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_guard_replace_syntax_check():
    from core.execution_guard import ExecutionGuard
    guard = ExecutionGuard()
    # Valid Python after replacement
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("x = 42\n")
        path = f.name
    try:
        result = await guard.guard_replace(path, "old_str", "x = 42")
        assert result.passed  # new_str present, old_str different from new_str and absent
    finally:
        os.unlink(path)


# ── Singleton ─────────────────────────────────────────────────

def test_singleton():
    from core.execution_guard import get_guard
    g1 = get_guard()
    g2 = get_guard()
    assert g1 is g2
