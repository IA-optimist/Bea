"""tests/test_model_router.py — Cost-aware model routing tests."""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import types
if 'structlog' not in sys.modules:
    _sl = types.ModuleType('structlog')
    class _ML:
        def info(self, *a, **k): pass
        def debug(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def error(self, *a, **k): pass
        def bind(self, **k): return self
    _sl.get_logger = lambda *a, **k: _ML()
    sys.modules['structlog'] = _sl


class TestModelRouting(unittest.TestCase):

    def _router(self):
        from core.model_router import ModelRouter
        return ModelRouter()

    def test_classify_uses_fast(self):
        r = self._router()
        d = r.route(task_type="classify")
        self.assertEqual(d.tier, "FAST")

    def test_plan_uses_standard(self):
        r = self._router()
        d = r.route(task_type="plan")
        self.assertEqual(d.tier, "STANDARD")

    def test_business_analysis_uses_strong(self):
        r = self._router()
        d = r.route(task_type="business_analysis")
        self.assertEqual(d.tier, "STRONG")

    def test_unknown_task_defaults_standard(self):
        r = self._router()
        d = r.route(task_type="unknown_task")
        self.assertEqual(d.tier, "STANDARD")

    def test_complexity_routing(self):
        r = self._router()
        self.assertEqual(r.route(complexity="trivial").tier, "FAST")
        self.assertEqual(r.route(complexity="complex").tier, "STRONG")

    def test_critical_priority_boost(self):
        r = self._router()
        d = r.route(task_type="classify", mission_priority="CRITICAL")
        self.assertNotEqual(d.tier, "FAST")
        self.assertIn("critical_boost", d.reason)

    def test_context_size_upgrade(self):
        r = self._router()
        d = r.route(task_type="classify", estimated_tokens=7000)
        self.assertNotEqual(d.tier, "FAST")
        self.assertIn("context_upgrade", d.reason)

    def test_fallback_tier_exists(self):
        r = self._router()
        d = r.route(task_type="reason")
        self.assertEqual(d.tier, "STRONG")
        self.assertEqual(d.fallback_tier, "STANDARD")

    def test_fast_has_no_fallback_below(self):
        r = self._router()
        d = r.route(task_type="classify")
        self.assertIsNone(d.fallback_tier)

    def test_to_dict(self):
        r = self._router()
        d = r.route(task_type="plan")
        dd = d.to_dict()
        self.assertIn("tier", dd)
        self.assertIn("estimated_cost", dd)
        self.assertIn("reason", dd)


class TestUsageTracking(unittest.TestCase):

    def test_record_and_get(self):
        from core.model_router import ModelRouter
        r = ModelRouter()
        r.record_usage("FAST", tokens=1000)
        r.record_usage("FAST", tokens=500)
        r.record_usage("STRONG", tokens=2000)
        usage = r.get_usage()
        self.assertEqual(usage["FAST"]["calls"], 2)
        self.assertEqual(usage["FAST"]["total_tokens"], 1500)
        self.assertEqual(usage["STRONG"]["calls"], 1)

    def test_savings_calculation(self):
        from core.model_router import ModelRouter
        r = ModelRouter()
        r.record_usage("FAST", tokens=5000)  # cheap
        r.record_usage("STANDARD", tokens=3000)
        savings = r.estimated_savings()
        self.assertGreater(savings["savings"], 0)
        self.assertIn("savings_pct", savings)


class TestToolTemplate(unittest.TestCase):

    def test_tool_result(self):
        from core.tools.tool_template import ToolResult
        r = ToolResult(ok=True, result="done")
        d = r.to_dict()
        self.assertTrue(d["ok"])

    def test_base_tool_schema(self):
        from core.tools.tool_template import BaseTool, ToolResult
        class TestTool(BaseTool):
            name = "test_tool"
            risk_level = "LOW"
            description = "Test tool"
            def execute(self, **params):
                return ToolResult(ok=True, result="ok")
        t = TestTool()
        schema = t.capability_schema()
        self.assertEqual(schema["name"], "test_tool")
        self.assertEqual(schema["risk_level"], "LOW")

    def test_safe_execute_catches_errors(self):
        from core.tools.tool_template import BaseTool
        class FailTool(BaseTool):
            name = "fail_tool"
            risk_level = "LOW"
            def execute(self, **params):
                raise RuntimeError("boom")
        t = FailTool()
        r = t.safe_execute()
        self.assertFalse(r.ok)
        self.assertIn("boom", r.error)

    def test_safe_execute_success(self):
        from core.tools.tool_template import BaseTool, ToolResult
        class OkTool(BaseTool):
            name = "ok_tool"
            risk_level = "LOW"
            def execute(self, **params):
                return ToolResult(ok=True, result="success")
        t = OkTool()
        r = t.safe_execute()
        self.assertTrue(r.ok)
        self.assertGreater(r.duration_ms, 0)


if __name__ == "__main__":
    unittest.main()
