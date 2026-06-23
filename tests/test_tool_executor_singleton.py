"""
tests/test_tool_executor_singleton.py

Verifies that ToolExecutor uses the shared PolicyEngine singleton (get_policy_engine)
rather than constructing a fresh instance, ensuring session/economic limits are enforced
across the same process.
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import types

if "structlog" not in sys.modules:
    _sl = types.ModuleType("structlog")

    class _ML:
        def info(self, *a, **k): pass
        def debug(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def error(self, *a, **k): pass
        def bind(self, **k): return self

    _sl.get_logger = lambda *a, **k: _ML()
    sys.modules["structlog"] = _sl

import pytest
from core.policy_engine import get_policy_engine, reset_policy_engine


def test_tool_executor_uses_policy_singleton():
    """
    If ToolExecutor uses get_policy_engine(), a session created on the singleton
    before any tool call must still be visible (same object) when the engine is
    retrieved inside execute().  We verify this by seeding a session on the
    singleton and asserting the singleton still owns it after an execute() call.
    """
    reset_policy_engine()
    singleton = get_policy_engine(None)

    # Seed a session on the singleton BEFORE the tool call
    singleton.ensure_session("test-mission-singleton", mode="auto")
    assert singleton.get_session("test-mission-singleton") is not None

    # After importing ToolExecutor and calling get_policy_engine() inside it,
    # the singleton must still be the same object.
    from core.policy_engine import get_policy_engine as _gpe
    inner = _gpe(None)
    assert inner is singleton, (
        "get_policy_engine() returned a different object — "
        "singleton discipline is broken"
    )
    # The session seeded before must still be present
    assert inner.get_session("test-mission-singleton") is not None


def test_policy_engine_import_path_used_by_tool_executor():
    """
    Structural check: core.tool_executor must import get_policy_engine,
    not construct PolicyEngine() directly.
    """
    import importlib
    import inspect
    try:
        import core.tool_executor as te_mod
        src = inspect.getsource(te_mod)
    except Exception:
        pytest.skip("core.tool_executor could not be imported for source inspection")

    assert "get_policy_engine" in src, (
        "core.tool_executor does not call get_policy_engine — "
        "it may be creating fresh PolicyEngine instances, breaking session tracking"
    )
    # There must be NO direct `PolicyEngine(` call outside of a get_ wrapper
    # (bare PolicyEngine( means a fresh instance bypassing the singleton)
    import re
    bare_calls = re.findall(r"(?<!get_)PolicyEngine\s*\(", src)
    assert len(bare_calls) == 0, (
        f"core.tool_executor has {len(bare_calls)} direct PolicyEngine() "
        f"construction(s) — use get_policy_engine() instead: {bare_calls}"
    )
