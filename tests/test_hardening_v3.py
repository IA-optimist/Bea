"""
Tests for hardening improvements: executor, memory, trace, self-improvement safety.
"""
import pytest
import sys
import os
import types
import unittest
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

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


class TestExecutorResults(unittest.TestCase):
    """Verify executor returns structured results."""

    def test_ok_has_timestamp(self):
        from core.tool_executor import _ok
        r = _ok("test result")
        self.assertTrue(r["ok"])
        self.assertIn("ts", r)
        self.assertIsInstance(r["ts"], float)

    @pytest.mark.stale
    @pytest.mark.skip(reason="stale: taxonomy changed")
    def test_err_has_classification(self):
        from core.tool_executor import _err
        r = _err("connection timeout")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error_class"], "timeout")
        self.assertIn("ts", r)

    def test_err_retryable(self):
        from core.tool_executor import _err
        r = _err("network error", retryable=True)
        self.assertTrue(r["retryable"])

    @pytest.mark.stale
    @pytest.mark.skip(reason="stale: taxonomy changed")
    def test_classify_error(self):
        from core.tool_executor import _classify_error
        self.assertEqual(_classify_error("connection timeout"), "timeout")
        self.assertEqual(_classify_error("permission denied"), "permission")
        self.assertEqual(_classify_error("file not found"), "not_found")
        self.assertEqual(_classify_error("request blocked"), "policy")
        self.assertEqual(_classify_error("something random"), "unknown")


class TestExecutorHealthCheck(unittest.TestCase):
    """Verify tool health check."""

    def test_health_check_structure(self):
        from core.tool_executor import get_tool_executor
        ex = get_tool_executor()
        health = ex.health_check()
        self.assertIn("total_tools", health)
        self.assertIn("risk_distribution", health)
        self.assertIn("kill_switch_active", health)
        self.assertIsInstance(health["total_tools"], int)
        self.assertGreater(health["total_tools"], 0)


class TestMissionTrace(unittest.TestCase):
    """Verify trace system."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def test_record_and_read(self):
        from core.trace import MissionTrace
        trace = MissionTrace("test-123", workspace_dir=self._tmpdir)
        trace.record("planner", "plan_created", steps=3)
        trace.record("executor", "tool_called", tool="shell", ok=True)
        events = trace.get_events()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["component"], "planner")
        self.assertEqual(events[1]["event"], "tool_called")
        self.assertTrue(events[1]["ok"])

    def test_filter_by_component(self):
        from core.trace import MissionTrace
        trace = MissionTrace("test-456", workspace_dir=self._tmpdir)
        trace.record("planner", "plan")
        trace.record("executor", "exec")
        trace.record("planner", "replan")
        planner_events = trace.get_events(component="planner")
        self.assertEqual(len(planner_events), 2)

    def test_summary(self):
        from core.trace import MissionTrace
        trace = MissionTrace("test-789", workspace_dir=self._tmpdir)
        trace.record("executor", "ok", ok=True)
        trace.record("executor", "error", ok=False)
        trace.record("planner", "plan")
        summary = trace.summary()
        self.assertEqual(summary["total_events"], 3)
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(summary["by_component"]["executor"], 2)

    def test_empty_trace(self):
        from core.trace import MissionTrace
        trace = MissionTrace("nonexistent", workspace_dir=self._tmpdir)
        self.assertEqual(trace.get_events(), [])
        self.assertEqual(trace.summary()["total_events"], 0)


class TestMemoryFacadeEnhancements(unittest.TestCase):
    """Verify memory facade improvements."""

    def test_stats_returns_dict(self):
        from core.memory_facade import MemoryFacade
        facade = MemoryFacade(workspace_dir=tempfile.mkdtemp())
        stats = facade.stats()
        self.assertIn("backends", stats)
        self.assertIn("backend_count", stats)

    def test_search_relevant_filters(self):
        from core.memory_facade import MemoryFacade
        facade = MemoryFacade(workspace_dir=tempfile.mkdtemp())
        # search_relevant should return a list (empty if no backends)
        results = facade.search_relevant("test query", min_score=0.5)
        self.assertIsInstance(results, list)


class TestSelfImprovementSafety(unittest.TestCase):
    """Verify self-improvement safety mechanisms."""

    def test_execution_result_has_confidence(self):
        from core.self_improvement.safe_executor import PatchResult as ExecutionResult  # legacy test compat
        r = ExecutionResult(
            success=True, applied_change="test", rollback_triggered=False,
            confidence=0.8, risk_level="low", diff_summary="updated prompt",
        )
        self.assertEqual(r.confidence, 0.8)
        self.assertEqual(r.risk_level, "low")

    def test_protected_paths_exist(self):
        from core.self_improvement.protected_paths import PROTECTED_FILES
        self.assertIn("core/meta_orchestrator.py", PROTECTED_FILES)
        self.assertIn("core/orchestrator.py", PROTECTED_FILES)

    def test_protected_paths_no_telegram_reference(self):
        with open("core/self_improvement/protected_paths.py", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("Telegram", content)


if __name__ == "__main__":
    os.chdir(os.path.join(os.path.dirname(__file__), ".."))
    unittest.main(verbosity=2)
