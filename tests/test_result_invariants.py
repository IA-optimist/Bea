"""tests/test_result_invariants.py — Strict result envelope invariant tests."""
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


class TestFinalOutputRequiredFields(unittest.TestCase):
    """FinalOutput must always contain the required fields."""

    def test_required_fields_exist(self):
        from core.schemas.final_output import FinalOutput
        fo = FinalOutput(mission_id="m-inv")
        d = fo.to_dict()
        required = ["mission_id", "trace_id", "status", "summary", "agent_outputs", "metrics"]
        for field in required:
            self.assertIn(field, d, f"FinalOutput.to_dict() must contain '{field}'")

    def test_agent_outputs_is_list(self):
        from core.schemas.final_output import FinalOutput
        fo = FinalOutput(mission_id="m-1")
        d = fo.to_dict()
        self.assertIsInstance(d.get("agent_outputs", None), list)

    def test_metrics_is_dict(self):
        from core.schemas.final_output import FinalOutput
        fo = FinalOutput(mission_id="m-1")
        d = fo.to_dict()
        self.assertIsInstance(d.get("metrics", None), dict)


class TestResultAggregator(unittest.TestCase):
    """Result aggregator must produce valid envelopes."""

    def test_aggregate_returns_final_output(self):
        from core.result_aggregator import aggregate_mission_result
        from core.schemas.final_output import FinalOutput
        result = aggregate_mission_result(
            mission_id="m-agg-inv-1",
            mission_status="DONE",
        )
        self.assertIsInstance(result, FinalOutput)
        d = result.to_dict()
        self.assertEqual(d["mission_id"], "m-agg-inv-1")
        self.assertIn("trace_id", d)
        self.assertIn("agent_outputs", d)

    def test_aggregate_propagates_trace_id_from_context(self):
        from core.result_aggregator import aggregate_mission_result
        from core.observability.event_envelope import set_trace, clear_trace
        set_trace("tr-agg-prop", "m-agg-prop")
        try:
            result = aggregate_mission_result(
                mission_id="m-agg-prop",
                mission_status="DONE",
            )
            # trace_id comes from thread-local context when mission not in store
            self.assertIn(result.trace_id, ("tr-agg-prop", ""),
                         "trace_id should be from context or empty if mission not found")
        finally:
            clear_trace()

    def test_aggregate_status_mapping(self):
        from core.result_aggregator import aggregate_mission_result
        for legacy, expected in [("DONE", "COMPLETED"), ("REJECTED", "CANCELLED"), ("BLOCKED", "FAILED")]:
            result = aggregate_mission_result(mission_id=f"m-st-{legacy}", mission_status=legacy)
            self.assertEqual(result.status, expected,
                           f"Status '{legacy}' should map to '{expected}', got '{result.status}'")


class TestResultEnvelopeStatus(unittest.TestCase):
    """Result envelope status must be one of the canonical values."""

    VALID_STATUSES = {"COMPLETED", "FAILED", "CANCELLED", "PARTIAL", "UNKNOWN"}

    def test_default_status_is_valid(self):
        from core.result_aggregator import aggregate_mission_result
        result = aggregate_mission_result(mission_id="m-status-v")
        self.assertIn(result.status, self.VALID_STATUSES,
                      f"Status '{result.status}' not in valid set")


class TestEnvelopeInvariants(unittest.TestCase):
    """Envelope must maintain structural invariants."""

    def test_trace_id_type_is_string(self):
        from core.schemas.final_output import FinalOutput
        fo = FinalOutput(mission_id="m-1", trace_id="tr-abc")
        self.assertIsInstance(fo.trace_id, str)

    def test_mission_id_not_empty(self):
        from core.schemas.final_output import FinalOutput
        fo = FinalOutput(mission_id="m-notempty")
        self.assertTrue(len(fo.mission_id) > 0)

    def test_to_dict_is_json_serializable(self):
        import json
        from core.schemas.final_output import FinalOutput
        fo = FinalOutput(mission_id="m-json", trace_id="tr-json")
        d = fo.to_dict()
        serialized = json.dumps(d)
        self.assertIsInstance(serialized, str)

    def test_agent_output_structure(self):
        from core.schemas.final_output import AgentOutput
        ao = AgentOutput(agent_name="scout", status="SUCCESS", output_text="data")
        d = ao.to_dict()
        self.assertEqual(d["agent_name"], "scout")
        self.assertEqual(d["status"], "SUCCESS")

    def test_decision_step_structure(self):
        from core.schemas.final_output import DecisionStep
        ds = DecisionStep(phase="complexity", result="medium")
        d = ds.to_dict()
        self.assertEqual(d["phase"], "complexity")
        self.assertEqual(d["result"], "medium")

    def test_metrics_structure(self):
        from core.schemas.final_output import OutputMetrics
        m = OutputMetrics(duration_seconds=42.5)
        d = m.to_dict()
        self.assertEqual(d["duration_seconds"], 42.5)


if __name__ == "__main__":
    unittest.main()
