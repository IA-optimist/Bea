"""tests/test_trace_invariants.py — Strict trace_id propagation invariant tests."""
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


class TestTraceIdGeneration(unittest.TestCase):
    """trace_id must be generated deterministically at mission creation."""

    def test_generate_trace_id_format(self):
        from core.observability.event_envelope import generate_trace_id
        tid = generate_trace_id()
        self.assertTrue(tid.startswith("tr-"), f"trace_id must start with 'tr-': got {tid}")
        self.assertEqual(len(tid), 15, f"trace_id must be 15 chars: got {len(tid)}")

    def test_trace_ids_are_unique(self):
        from core.observability.event_envelope import generate_trace_id
        ids = [generate_trace_id() for _ in range(1000)]
        self.assertEqual(len(set(ids)), 1000, "trace_ids must be unique")


class TestTraceContext(unittest.TestCase):
    """Thread-local trace context must work correctly."""

    def test_context_roundtrip(self):
        from core.observability.event_envelope import set_trace, get_trace_id, get_mission_id, clear_trace
        set_trace("tr-invariant01", "m-inv-01")
        self.assertEqual(get_trace_id(), "tr-invariant01")
        self.assertEqual(get_mission_id(), "m-inv-01")
        clear_trace()
        self.assertIsNone(get_trace_id())

    def test_clear_is_complete(self):
        from core.observability.event_envelope import set_trace, clear_trace, get_trace_id, get_mission_id
        set_trace("tr-xxx", "m-xxx")
        clear_trace()
        self.assertIsNone(get_trace_id())
        self.assertIsNone(get_mission_id())


class TestEventEnvelopeTraceId(unittest.TestCase):
    """Every event must carry a trace_id."""

    def test_envelope_requires_trace_id(self):
        from core.observability.event_envelope import EventEnvelope
        e = EventEnvelope(
            trace_id="tr-required",
            mission_id="m-1",
            component="tool",
            event_type="tool_call",
        )
        d = e.to_dict()
        self.assertIn("trace_id", d)
        self.assertEqual(d["trace_id"], "tr-required")

    def test_envelope_trace_id_in_serialization(self):
        from core.observability.event_envelope import EventEnvelope
        e = EventEnvelope(trace_id="", mission_id="m-1", component="tool", event_type="test")
        d = e.to_dict()
        self.assertIn("trace_id", d)


class TestCanonicalActionTraceId(unittest.TestCase):
    """CanonicalAction must carry and emit trace_id."""

    def test_action_has_trace_id(self):
        from core.actions.action_model import CanonicalAction
        a = CanonicalAction(trace_id="tr-action-1", mission_id="m-1")
        self.assertEqual(a.trace_id, "tr-action-1")

    def test_action_trace_id_in_dict(self):
        from core.actions.action_model import CanonicalAction
        a = CanonicalAction(trace_id="tr-dict-1", mission_id="m-1")
        d = a.to_dict()
        self.assertEqual(d["trace_id"], "tr-dict-1")


class TestFinalOutputTraceId(unittest.TestCase):
    """FinalOutput must always carry trace_id."""

    def test_final_output_has_trace_id(self):
        from core.schemas.final_output import FinalOutput
        fo = FinalOutput(mission_id="m-1", trace_id="tr-fo-1")
        self.assertEqual(fo.trace_id, "tr-fo-1")

    def test_final_output_trace_id_in_dict(self):
        from core.schemas.final_output import FinalOutput
        fo = FinalOutput(mission_id="m-1", trace_id="tr-fo-2")
        d = fo.to_dict()
        self.assertEqual(d["trace_id"], "tr-fo-2")

    def test_final_output_trace_id_defaults_empty(self):
        from core.schemas.final_output import FinalOutput
        fo = FinalOutput(mission_id="m-1")
        self.assertEqual(fo.trace_id, "")


class TestTraceIdPropagatesEndToEnd(unittest.TestCase):
    """
    INVARIANT: trace_id must propagate from generation through
    CanonicalAction, EventEnvelope, and FinalOutput.

    This test simulates the full lifecycle without real orchestration.
    """

    def test_trace_id_propagates_end_to_end(self):
        from core.observability.event_envelope import (
            generate_trace_id, set_trace, clear_trace,
            EventCollector, EventEnvelope,
        )
        from core.actions.action_model import CanonicalAction
        from core.schemas.final_output import FinalOutput

        # 1. Generate trace_id (as mission_system does)
        trace_id = generate_trace_id()
        mission_id = "m-e2e-test"
        self.assertTrue(trace_id.startswith("tr-"))

        # 2. Set thread-local context (as mission_system does)
        set_trace(trace_id, mission_id)

        # 3. Create event (as mission_system does)
        collector = EventCollector()
        collector.emit(EventEnvelope(
            trace_id=trace_id,
            mission_id=mission_id,
            component="orchestrator",
            event_type="status_update",
            payload={"action": "mission_submitted"},
        ))

        # 4. Create action (as executor does)
        action = CanonicalAction(
            trace_id=trace_id,
            mission_id=mission_id,
            tool_name="web_search",
        )
        self.assertEqual(action.trace_id, trace_id)

        # 5. Action lifecycle emits events
        action.start()
        action.complete("results")

        # 6. Build FinalOutput (as result_aggregator does)
        fo = FinalOutput(
            mission_id=mission_id,
            trace_id=trace_id,
        )
        self.assertEqual(fo.trace_id, trace_id)

        # 7. Verify all events share the same trace_id
        events = collector.get_trace(trace_id)
        self.assertGreater(len(events), 0, "Must have at least 1 event")
        for event in events:
            self.assertEqual(event["trace_id"], trace_id,
                            f"Event trace_id mismatch: {event}")

        # 8. Verify FinalOutput dict has trace_id
        fo_dict = fo.to_dict()
        self.assertEqual(fo_dict["trace_id"], trace_id)

        clear_trace()


class TestCollectorTraceConsistency(unittest.TestCase):
    """Events collected for a trace must all have the same trace_id."""

    def test_trace_events_consistent(self):
        from core.observability.event_envelope import EventCollector, EventEnvelope
        c = EventCollector()
        tid = "tr-consistency"
        for i in range(5):
            c.emit(EventEnvelope(
                trace_id=tid, mission_id="m-c",
                component="tool", event_type="tool_call",
                payload={"idx": i},
            ))
        events = c.get_trace(tid)
        for e in events:
            self.assertEqual(e["trace_id"], tid)

    def test_mission_trace_consistent(self):
        from core.observability.event_envelope import EventCollector, EventEnvelope
        c = EventCollector()
        mid = "m-mission-consist"
        for tid in ["tr-mc1", "tr-mc2"]:
            c.emit(EventEnvelope(trace_id=tid, mission_id=mid, component="tool", event_type="test"))
        events = c.get_mission_trace(mid)
        self.assertEqual(len(events), 2)
        for e in events:
            self.assertEqual(e["mission_id"], mid)


class TestStartupGuard(unittest.TestCase):
    """Startup guard must enforce auth in production."""

    def test_dev_mode_passes_without_token(self):
        from core.security.startup_guard import run_all_checks
        old_env = os.environ.get("JARVIS_ENV")
        old_token = os.environ.get("JARVIS_API_TOKEN")
        os.environ["JARVIS_ENV"] = "development"
        os.environ.pop("JARVIS_API_TOKEN", None)
        try:
            result = run_all_checks()
            self.assertFalse(result["auth_token"])
            self.assertFalse(result["is_production"])
        finally:
            if old_env: os.environ["JARVIS_ENV"] = old_env
            else: os.environ.pop("JARVIS_ENV", None)
            if old_token: os.environ["JARVIS_API_TOKEN"] = old_token

    def test_prod_mode_fails_without_token(self):
        from core.security.startup_guard import run_all_checks, StartupGuardError
        old_env = os.environ.get("JARVIS_ENV")
        old_token = os.environ.get("JARVIS_API_TOKEN")
        os.environ["JARVIS_ENV"] = "production"
        os.environ.pop("JARVIS_API_TOKEN", None)
        try:
            with self.assertRaises(StartupGuardError):
                run_all_checks()
        finally:
            if old_env: os.environ["JARVIS_ENV"] = old_env
            else: os.environ.pop("JARVIS_ENV", None)
            if old_token: os.environ["JARVIS_API_TOKEN"] = old_token


if __name__ == "__main__":
    unittest.main()
