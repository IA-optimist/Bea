"""tests/test_v1_invariants.py — Hard invariant tests for v1 architecture.

These tests MUST pass before any merge to master.
If they fail, the architecture has regressed.
"""
import os
import sys
import json
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


class TestCanonicalActionStatusesUnchanged(unittest.TestCase):
    """INVARIANT 1: CanonicalAction statuses must remain exactly these 7."""

    REQUIRED_STATUSES = {
        "PENDING", "APPROVAL_REQUIRED", "APPROVED",
        "RUNNING", "COMPLETED", "FAILED", "CANCELLED",
    }

    def test_all_statuses_valid(self):
        from core.actions.action_model import CanonicalAction
        for status in self.REQUIRED_STATUSES:
            a = CanonicalAction(status=status)
            self.assertEqual(a.status, status)

    def test_terminal_states_are_stable(self):
        """Terminal states must not accept further transitions."""
        from core.actions.action_model import CanonicalAction
        for terminal in ("COMPLETED", "FAILED", "CANCELLED"):
            a = CanonicalAction(status=terminal)
            self.assertTrue(a.is_terminal, f"{terminal} must be terminal")

    def test_non_terminal_states(self):
        from core.actions.action_model import CanonicalAction
        for non_terminal in ("PENDING", "APPROVAL_REQUIRED", "APPROVED", "RUNNING"):
            a = CanonicalAction(status=non_terminal)
            self.assertFalse(a.is_terminal, f"{non_terminal} must NOT be terminal")


class TestResultEnvelopeRequiredFields(unittest.TestCase):
    """INVARIANT 2: Result envelope always contains required fields."""

    REQUIRED_FIELDS = ["mission_id", "trace_id", "status", "summary",
                       "agent_outputs", "decision_trace", "metrics"]

    def test_all_required_fields_present(self):
        from core.schemas.final_output import FinalOutput
        fo = FinalOutput(mission_id="m-invariant")
        d = fo.to_dict()
        for field in self.REQUIRED_FIELDS:
            self.assertIn(field, d, f"INVARIANT VIOLATED: '{field}' missing from FinalOutput")

    def test_failure_state_has_valid_envelope(self):
        from core.schemas.final_output import FinalOutput
        fo = FinalOutput(mission_id="m-fail", status="FAILED", summary="Agent timeout")
        d = fo.to_dict()
        for field in self.REQUIRED_FIELDS:
            self.assertIn(field, d, f"INVARIANT VIOLATED: '{field}' missing in FAILED state")
        self.assertEqual(d["status"], "FAILED")

    def test_cancelled_state_has_valid_envelope(self):
        from core.schemas.final_output import FinalOutput
        fo = FinalOutput(mission_id="m-cancel", status="CANCELLED")
        d = fo.to_dict()
        for field in self.REQUIRED_FIELDS:
            self.assertIn(field, d, f"INVARIANT VIOLATED: '{field}' missing in CANCELLED state")


class TestTraceIdPropagation(unittest.TestCase):
    """INVARIANT 3: trace_id propagates end-to-end."""

    def test_trace_id_in_event_envelope(self):
        from core.observability.event_envelope import EventEnvelope
        e = EventEnvelope(trace_id="tr-inv3", mission_id="m", component="test", event_type="test")
        self.assertEqual(e.to_dict()["trace_id"], "tr-inv3")

    def test_trace_id_in_canonical_action(self):
        from core.actions.action_model import CanonicalAction
        a = CanonicalAction(trace_id="tr-inv3", mission_id="m")
        self.assertEqual(a.to_dict()["trace_id"], "tr-inv3")

    def test_trace_id_in_final_output(self):
        from core.schemas.final_output import FinalOutput
        fo = FinalOutput(mission_id="m", trace_id="tr-inv3")
        self.assertEqual(fo.to_dict()["trace_id"], "tr-inv3")

    def test_full_chain(self):
        from core.observability.event_envelope import generate_trace_id, set_trace, clear_trace, EventCollector, EventEnvelope
        from core.actions.action_model import CanonicalAction
        from core.schemas.final_output import FinalOutput

        tid = generate_trace_id()
        set_trace(tid, "m-chain")

        collector = EventCollector()
        collector.emit(EventEnvelope(trace_id=tid, mission_id="m-chain",
                                     component="orchestrator", event_type="status_update"))

        action = CanonicalAction(trace_id=tid, mission_id="m-chain")
        action.start()
        action.complete("ok")

        fo = FinalOutput(mission_id="m-chain", trace_id=tid)

        # All must share same trace_id
        events = collector.get_trace(tid)
        self.assertGreater(len(events), 0)
        self.assertEqual(events[0]["trace_id"], tid)
        self.assertEqual(action.to_dict()["trace_id"], tid)
        self.assertEqual(fo.to_dict()["trace_id"], tid)

        clear_trace()


class TestCanonicalTerminalStatuses(unittest.TestCase):
    """INVARIANT 4: Canonical terminal statuses remain present."""

    def test_final_output_accepts_canonical_statuses(self):
        from core.schemas.final_output import FinalOutput
        for status in ("COMPLETED", "FAILED", "CANCELLED"):
            fo = FinalOutput(mission_id="m", status=status)
            self.assertEqual(fo.status, status)

    def test_result_aggregator_maps_correctly(self):
        from core.result_aggregator import aggregate_mission_result
        mappings = {"DONE": "COMPLETED", "REJECTED": "CANCELLED", "BLOCKED": "FAILED"}
        for legacy, canonical in mappings.items():
            result = aggregate_mission_result(mission_id=f"m-map-{legacy}", mission_status=legacy)
            self.assertEqual(result.status, canonical,
                           f"Legacy '{legacy}' should map to '{canonical}', got '{result.status}'")


class TestProductionStartupGuard(unittest.TestCase):
    """INVARIANT 5: Production startup fails if auth token missing."""

    def test_prod_fails_without_token(self):
        from core.security.startup_guard import run_all_checks, StartupGuardError
        old_env = os.environ.get("JARVIS_ENV")
        old_token = os.environ.get("JARVIS_API_TOKEN")
        old_key = os.environ.get("JARVIS_SECRET_KEY")
        os.environ["JARVIS_ENV"] = "production"
        os.environ.pop("JARVIS_API_TOKEN", None)
        os.environ.pop("JARVIS_SECRET_KEY", None)
        try:
            with self.assertRaises(StartupGuardError):
                run_all_checks()
        finally:
            if old_env: os.environ["JARVIS_ENV"] = old_env
            else: os.environ.pop("JARVIS_ENV", None)
            if old_token: os.environ["JARVIS_API_TOKEN"] = old_token
            if old_key: os.environ["JARVIS_SECRET_KEY"] = old_key

    def test_dev_passes_without_token(self):
        from core.security.startup_guard import run_all_checks
        old_env = os.environ.get("JARVIS_ENV")
        old_token = os.environ.get("JARVIS_API_TOKEN")
        os.environ["JARVIS_ENV"] = "development"
        os.environ.pop("JARVIS_API_TOKEN", None)
        try:
            result = run_all_checks()
            self.assertFalse(result["is_production"])
        finally:
            if old_env: os.environ["JARVIS_ENV"] = old_env
            else: os.environ.pop("JARVIS_ENV", None)
            if old_token: os.environ["JARVIS_API_TOKEN"] = old_token

    def test_prod_rejects_weak_token(self):
        from core.security.startup_guard import run_all_checks, StartupGuardError
        old_env = os.environ.get("JARVIS_ENV")
        old_token = os.environ.get("JARVIS_API_TOKEN")
        os.environ["JARVIS_ENV"] = "production"
        os.environ["JARVIS_API_TOKEN"] = "test"
        try:
            with self.assertRaises(StartupGuardError):
                run_all_checks()
        finally:
            if old_env: os.environ["JARVIS_ENV"] = old_env
            else: os.environ.pop("JARVIS_ENV", None)
            if old_token: os.environ["JARVIS_API_TOKEN"] = old_token
            else: os.environ.pop("JARVIS_API_TOKEN", None)


class TestCanonicalAPISchema(unittest.TestCase):
    """INVARIANT 6: Canonical schemas remain JSON-serializable."""

    def test_final_output_serializable(self):
        from core.schemas.final_output import FinalOutput, AgentOutput, DecisionStep, OutputMetrics
        fo = FinalOutput(
            mission_id="m-1",
            trace_id="tr-schema",
            status="COMPLETED",
            summary="test",
            agent_outputs=[AgentOutput(agent_name="scout", status="SUCCESS", output_text="data")],
            decision_trace=[DecisionStep(phase="classify", result="research")],
            metrics=OutputMetrics(duration_seconds=42.5),
        )
        serialized = json.dumps(fo.to_dict())
        parsed = json.loads(serialized)
        self.assertEqual(parsed["mission_id"], "m-1")
        self.assertEqual(len(parsed["agent_outputs"]), 1)

    def test_canonical_action_serializable(self):
        from core.actions.action_model import CanonicalAction
        a = CanonicalAction(mission_id="m-1", trace_id="tr-s", tool_name="web_search")
        serialized = json.dumps(a.to_dict())
        parsed = json.loads(serialized)
        self.assertEqual(parsed["tool_name"], "web_search")

    def test_event_envelope_serializable(self):
        from core.observability.event_envelope import EventEnvelope
        e = EventEnvelope(trace_id="tr-s", mission_id="m", component="tool", event_type="call")
        serialized = json.dumps(e.to_dict())
        parsed = json.loads(serialized)
        self.assertEqual(parsed["component"], "tool")


class TestLegacyAliasesNotCanonical(unittest.TestCase):
    """INVARIANT 7: Legacy aliases do not accidentally become canonical."""

    def test_deprecated_modules_have_header(self):
        """Deprecated modules must have deprecation notice."""
        deprecated = [
            "core/action_queue.py",
            "core/task_queue.py",
            "core/approval_queue.py",
            "core/orchestrator.py",
        ]
        for path in deprecated:
            full_path = os.path.join(_ROOT, path)
            if os.path.exists(full_path):
                with open(full_path, "r", encoding="utf-8") as f:
                    header = f.read(500)
                self.assertIn("DEPRECATED", header,
                             f"INVARIANT VIOLATED: {path} missing DEPRECATED header")

    def test_canonical_action_model_exists(self):
        """CanonicalAction must be importable."""
        from core.actions.action_model import CanonicalAction
        a = CanonicalAction()
        self.assertIsNotNone(a.action_id)

    def test_canonical_final_output_exists(self):
        """FinalOutput must be importable."""
        from core.schemas.final_output import FinalOutput
        fo = FinalOutput(mission_id="m")
        self.assertIsNotNone(fo)


if __name__ == "__main__":
    unittest.main()
