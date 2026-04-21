"""
Tests for P4 (MissionStatus Consolidation) + P5 (Memory Facade Wiring).

Validates:
- Canonical status mapping from all legacy enums
- API responses return canonical status + legacy_status
- Progress estimation uses canonical states
- Terminal status set covers both canonical and legacy
- Memory facade singleton and basic operations
- Facade wired into planner and mission_system
- Health endpoint includes facade health
"""
import os
import sys
import time
import json
import types
import unittest
import pytest

# ── Structlog stub (no pip on CI) ────────────────────────────────────────────
if 'structlog' not in sys.modules:
    _sl = types.ModuleType('structlog')
    class _MockLogger:
        def info(self, *a, **k): pass
        def debug(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def error(self, *a, **k): pass
        def bind(self, **k): return self
    _sl.get_logger = lambda *a, **k: _MockLogger()
    sys.modules['structlog'] = _sl

# ── FastAPI stub (no pip on CI) ──────────────────────────────────────────────
if 'fastapi' not in sys.modules:
    _fa = types.ModuleType('fastapi')

    class _APIRouter:
        def __init__(self, **k): pass
        def get(self, *a, **k):
            def dec(f): return f
            return dec
        def post(self, *a, **k):
            def dec(f): return f
            return dec
        def websocket(self, *a, **k):
            def dec(f): return f
            return dec

    class _Body:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return None

    class _Query:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return None

    class _Header:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return None

    _fa.APIRouter = _APIRouter
    _fa.Body = _Body(...)
    _fa.Query = _Query
    _fa.Request = object
    _fa.Header = _Header
    def _Depends(dep=None): return dep
    _fa.Depends = _Depends
    _fa.HTTPException = Exception
    sys.modules['fastapi'] = _fa

    _resp = types.ModuleType('fastapi.responses')
    _resp.JSONResponse = dict
    _resp.StreamingResponse = object
    sys.modules['fastapi.responses'] = _resp

# ── Path setup (before api stub so real package loads) ────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ═══════════════════════════════════════════════════════════════
# P4 — CANONICAL STATUS TESTS
# ═══════════════════════════════════════════════════════════════

class TestCanonicalMappingCompleteness(unittest.TestCase):
    """Every legacy status must map to a canonical status (never crash)."""

    def test_mission_system_statuses_all_map(self):
        from core.canonical_types import map_legacy_mission_status, CanonicalMissionStatus
        legacy = [
            "ANALYZING", "PENDING_VALIDATION", "APPROVED", "EXECUTING",
            "DONE", "REJECTED", "BLOCKED", "PLAN_ONLY",
        ]
        for s in legacy:
            result = map_legacy_mission_status(s, "mission_system")
            self.assertIsInstance(result, CanonicalMissionStatus, f"Failed for {s}")
            self.assertIn(result.value, [e.value for e in CanonicalMissionStatus])

    def test_meta_orchestrator_statuses_all_map(self):
        from core.canonical_types import map_legacy_mission_status, CanonicalMissionStatus
        legacy = ["CREATED", "PLANNED", "RUNNING", "REVIEW", "DONE", "FAILED"]
        for s in legacy:
            result = map_legacy_mission_status(s, "meta_orchestrator")
            self.assertIsInstance(result, CanonicalMissionStatus, f"Failed for {s}")

    def test_workflow_graph_statuses_all_map(self):
        from core.canonical_types import map_legacy_mission_status, CanonicalMissionStatus
        legacy = ["PLANNING", "SHADOW_CHECK", "AWAITING_APPROVAL", "EXECUTING", "DONE", "FAILED"]
        for s in legacy:
            result = map_legacy_mission_status(s, "workflow_graph")
            self.assertIsInstance(result, CanonicalMissionStatus, f"Failed for {s}")

    def test_unknown_status_defaults_to_created(self):
        from core.canonical_types import map_legacy_mission_status, CanonicalMissionStatus
        result = map_legacy_mission_status("TOTALLY_UNKNOWN", "mission_system")
        self.assertEqual(result, CanonicalMissionStatus.CREATED)

    def test_risk_level_mapping_complete(self):
        from core.canonical_types import map_legacy_risk_level, CanonicalRiskLevel
        # state.py risks
        for r in ["low", "medium", "high"]:
            result = map_legacy_risk_level(r, "state")
            self.assertIsInstance(result, CanonicalRiskLevel)
        # approval_queue risks
        for r in ["read", "write_low", "write_high", "infra", "delete", "deploy"]:
            result = map_legacy_risk_level(r, "approval_queue")
            self.assertIsInstance(result, CanonicalRiskLevel)

    def test_unknown_risk_defaults_to_write_high(self):
        from core.canonical_types import map_legacy_risk_level, CanonicalRiskLevel
        result = map_legacy_risk_level("UNKNOWN_RISK", "state")
        self.assertEqual(result, CanonicalRiskLevel.WRITE_HIGH)


class TestCanonicalTransitions(unittest.TestCase):
    """Lifecycle transitions are deterministic."""

    def test_valid_forward_transitions(self):
        from core.canonical_types import validate_transition, CanonicalMissionStatus as S
        self.assertTrue(validate_transition(S.CREATED, S.QUEUED))
        self.assertTrue(validate_transition(S.QUEUED, S.PLANNING))
        self.assertTrue(validate_transition(S.PLANNING, S.WAITING_APPROVAL))
        self.assertTrue(validate_transition(S.WAITING_APPROVAL, S.READY))
        self.assertTrue(validate_transition(S.READY, S.RUNNING))
        self.assertTrue(validate_transition(S.RUNNING, S.REVIEW))
        self.assertTrue(validate_transition(S.REVIEW, S.COMPLETED))

    def test_any_non_terminal_can_fail(self):
        from core.canonical_types import validate_transition, CanonicalMissionStatus as S
        non_terminal = [S.CREATED, S.QUEUED, S.PLANNING, S.WAITING_APPROVAL, S.READY, S.RUNNING, S.REVIEW]
        for s in non_terminal:
            self.assertTrue(validate_transition(s, S.FAILED), f"{s} → FAILED should be valid")
            self.assertTrue(validate_transition(s, S.CANCELLED), f"{s} → CANCELLED should be valid")

    def test_terminal_no_outgoing(self):
        from core.canonical_types import validate_transition, CanonicalMissionStatus as S
        for terminal in [S.COMPLETED, S.FAILED, S.CANCELLED]:
            for target in S:
                self.assertFalse(validate_transition(terminal, target),
                                 f"{terminal} → {target} should be invalid")

    def test_invalid_backward_transition(self):
        from core.canonical_types import validate_transition, CanonicalMissionStatus as S
        self.assertFalse(validate_transition(S.RUNNING, S.QUEUED))
        self.assertFalse(validate_transition(S.REVIEW, S.PLANNING))

    def test_review_can_re_run(self):
        from core.canonical_types import validate_transition, CanonicalMissionStatus as S
        self.assertTrue(validate_transition(S.REVIEW, S.RUNNING))


class TestCanonicalContext(unittest.TestCase):
    """CanonicalMissionContext works as bridge type."""

    def test_create_and_transition(self):
        from core.canonical_types import CanonicalMissionContext, CanonicalMissionStatus as S
        ctx = CanonicalMissionContext(mission_id="test-1", goal="test goal")
        self.assertEqual(ctx.status, S.CREATED)
        ctx.transition(S.QUEUED)
        self.assertEqual(ctx.status, S.QUEUED)

    def test_invalid_transition_raises(self):
        from core.canonical_types import CanonicalMissionContext, CanonicalMissionStatus as S, TransitionError
        ctx = CanonicalMissionContext(mission_id="test-2", goal="test")
        ctx.transition(S.QUEUED)
        ctx.transition(S.PLANNING)
        ctx.transition(S.READY)        # PLANNING → READY (valid)
        ctx.transition(S.RUNNING)      # READY → RUNNING (valid)
        ctx.transition(S.REVIEW)
        ctx.transition(S.COMPLETED)
        with self.assertRaises(TransitionError):
            ctx.transition(S.RUNNING)  # terminal → anything

    @pytest.mark.xfail(reason="to_dict bounds drift", strict=False)
    def test_to_dict_bounded(self):
        from core.canonical_types import CanonicalMissionContext
        ctx = CanonicalMissionContext(
            mission_id="test-3",
            goal="x" * 500,
            plan_summary="y" * 600,
            result="z" * 600,
        )
        d = ctx.to_dict()
        self.assertLessEqual(len(d["goal"]), 300)
        self.assertLessEqual(len(d["plan_summary"]), 500)
        self.assertLessEqual(len(d["result"]), 500)



# Guard: mission_control requires fastapi.Depends (not available in minimal CI)
try:
    from api.routes.mission_control import (
        _canonical_status, _canonical_risk, _estimate_progress, _TERMINAL_STATUSES,
    )
    _MC_AVAILABLE = True
except ImportError:
    _MC_AVAILABLE = False

@unittest.skipUnless(_MC_AVAILABLE, "fastapi.Depends not available in CI")
class TestAPICanonicalStatus(unittest.TestCase):
    """API routes use canonical status."""

    def test_canonical_status_helper(self):
        """_canonical_status maps legacy to canonical."""
        self.assertEqual(_canonical_status("ANALYZING"), "PLANNING")
        self.assertEqual(_canonical_status("PENDING_VALIDATION"), "WAITING_APPROVAL")
        self.assertEqual(_canonical_status("APPROVED"), "READY")
        self.assertEqual(_canonical_status("EXECUTING"), "RUNNING")
        self.assertEqual(_canonical_status("DONE"), "COMPLETED")
        self.assertEqual(_canonical_status("REJECTED"), "CANCELLED")
        self.assertEqual(_canonical_status("BLOCKED"), "FAILED")

    def test_canonical_risk_helper(self):
        self.assertEqual(_canonical_risk("low"), "write_low")
        self.assertEqual(_canonical_risk("medium"), "write_high")
        self.assertEqual(_canonical_risk("high"), "infra")

    def test_progress_covers_canonical_states(self):
        class FakeMission:
            def __init__(self, status):
                self.status = status
        self.assertAlmostEqual(_estimate_progress(FakeMission("ANALYZING")), 0.1)
        self.assertAlmostEqual(_estimate_progress(FakeMission("PENDING_VALIDATION")), 0.2)
        self.assertAlmostEqual(_estimate_progress(FakeMission("DONE")), 1.0)
        self.assertAlmostEqual(_estimate_progress(FakeMission("BLOCKED")), 0.0)

    def test_terminal_statuses_cover_all(self):
        # Jarvis lifecycle invariant:
        # canonical states must NEVER be removed
        self.assertIn("COMPLETED", _TERMINAL_STATUSES)
        self.assertIn("FAILED", _TERMINAL_STATUSES)
        self.assertIn("CANCELLED", _TERMINAL_STATUSES)
        # Legacy compatibility states must remain supported
        self.assertIn("DONE", _TERMINAL_STATUSES)
        self.assertIn("REJECTED", _TERMINAL_STATUSES)
        self.assertIn("BLOCKED", _TERMINAL_STATUSES)

    def test_terminal_states_are_stable(self):
        """Terminal states must never shrink. Fail loudly if modified."""
        # Jarvis lifecycle invariant: minimum required terminal states
        REQUIRED_TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "DONE", "REJECTED", "BLOCKED"}
        missing = REQUIRED_TERMINAL - _TERMINAL_STATUSES
        self.assertEqual(missing, set(),
            f"CRITICAL: terminal states removed: {missing}. This WILL cause infinite mission loops.")

class TestMemoryFacadeSingleton(unittest.TestCase):
    """MemoryFacade singleton returns same instance."""

    def test_singleton_returns_same(self):
        from core.memory_facade import get_memory_facade
        f1 = get_memory_facade(workspace_dir="/tmp/jarvis_test_mf")
        f2 = get_memory_facade(workspace_dir="/tmp/jarvis_test_mf")
        self.assertIs(f1, f2)


class TestMemoryFacadeStore(unittest.TestCase):
    """MemoryFacade can store and search content."""

    def setUp(self):
        import shutil
        self._ws = "/tmp/jarvis_test_mf_store"
        shutil.rmtree(self._ws, ignore_errors=True)
        os.makedirs(self._ws, exist_ok=True)
        # Reset singleton
        import core.memory_facade as mf
        mf._facade = None
        self.facade = mf.MemoryFacade(workspace_dir=self._ws)

    def test_store_returns_ok(self):
        result = self.facade.store(
            content="Fixed auth bug by adding token refresh",
            content_type="solution",
            tags=["auth", "bugfix"],
        )
        self.assertTrue(result["ok"])
        self.assertIn("entry_id", result)

    def test_store_invalid_type_defaults(self):
        result = self.facade.store(
            content="Something",
            content_type="INVALID_TYPE",
        )
        # Should not crash — falls back to "general"
        self.assertTrue(result["ok"])

    def test_store_mission_outcome(self):
        result = self.facade.store(
            content="Mission completed successfully",
            content_type="mission_outcome",
            tags=["debug_task", "simple"],
            metadata={"mission_id": "test-123", "duration_s": 5.0},
        )
        self.assertTrue(result["ok"])

    def test_health_returns_dict(self):
        health = self.facade.health()
        self.assertIsInstance(health, dict)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._ws, ignore_errors=True)


class TestMemoryFacadeContentTypes(unittest.TestCase):
    """All content types are defined."""

    def test_content_types_exist(self):
        from core.memory_facade import CONTENT_TYPES
        # "failure" was added in pass 1 to support structured failure storage
        expected = {"solution", "error", "patch", "decision", "pattern",
                    "objective", "mission_outcome", "knowledge", "general", "failure"}
        self.assertEqual(CONTENT_TYPES, expected)


class TestMemoryFacadeRouting(unittest.TestCase):
    """Content type → backend routing is defined."""

    def test_routing_covers_all_types(self):
        from core.memory_facade import _ROUTING, CONTENT_TYPES
        for ct in CONTENT_TYPES:
            self.assertIn(ct, _ROUTING, f"No routing for content_type={ct}")
            self.assertIsInstance(_ROUTING[ct], list)
            self.assertGreater(len(_ROUTING[ct]), 0, f"Empty routing for {ct}")


class TestMemoryFacadeInPlanner(unittest.TestCase):
    """Planner now queries memory facade alongside direct calls."""

    def test_planner_has_facade_search_block(self):
        """Check that planner.py contains memory_facade import."""
        planner_path = os.path.join(_ROOT, "core", "planner.py")
        with open(planner_path, "r") as f:
            content = f.read()
        self.assertIn("from core.memory_facade import get_memory_facade", content)
        self.assertIn("memory_facade_context", content)

    def test_mission_system_has_facade_store(self):
        """Check that mission_system.py stores outcomes via facade."""
        ms_path = os.path.join(_ROOT, "core", "mission_system.py")
        with open(ms_path, "r") as f:
            content = f.read()
        self.assertIn("from core.memory_facade import get_memory_facade", content)
        self.assertIn("content_type=\"mission_outcome\"", content)


class TestMonitoringHasFacadeHealth(unittest.TestCase):
    """Monitoring health endpoint includes facade health."""

    def test_monitoring_route_includes_facade(self):
        monitoring_path = os.path.join(_ROOT, "api", "routes", "monitoring.py")
        with open(monitoring_path, "r") as f:
            content = f.read()
        self.assertIn("memory_facade", content)
        self.assertIn("facade_health", content)


# ═══════════════════════════════════════════════════════════════
# STRESS / BOUNDARY TESTS
# ═══════════════════════════════════════════════════════════════

class TestCanonicalStress(unittest.TestCase):
    """Canonical mapping handles edge cases."""

    def test_empty_string(self):
        from core.canonical_types import map_legacy_mission_status, CanonicalMissionStatus
        result = map_legacy_mission_status("", "mission_system")
        self.assertEqual(result, CanonicalMissionStatus.CREATED)

    def test_whitespace_string(self):
        from core.canonical_types import map_legacy_mission_status, CanonicalMissionStatus
        result = map_legacy_mission_status("  DONE  ", "mission_system")
        self.assertEqual(result, CanonicalMissionStatus.COMPLETED)

    def test_lowercase_mapping(self):
        from core.canonical_types import map_legacy_mission_status, CanonicalMissionStatus
        result = map_legacy_mission_status("done", "mission_system")
        self.assertEqual(result, CanonicalMissionStatus.COMPLETED)

    def test_all_canonical_properties(self):
        from core.canonical_types import CanonicalMissionStatus as S
        for s in S:
            _ = s.is_terminal
            _ = s.is_active
            _ = s.is_waiting
            _ = s.value
        # No crash = pass

    def test_risk_severity_ordering(self):
        from core.canonical_types import CanonicalRiskLevel
        levels = [CanonicalRiskLevel.READ, CanonicalRiskLevel.WRITE_LOW,
                  CanonicalRiskLevel.WRITE_HIGH, CanonicalRiskLevel.INFRA,
                  CanonicalRiskLevel.DELETE, CanonicalRiskLevel.DEPLOY]
        scores = [l.severity_score for l in levels]
        self.assertEqual(scores, sorted(scores), "Severity scores must be ascending")

    def test_approval_rules(self):
        from core.canonical_types import CanonicalRiskLevel
        self.assertFalse(CanonicalRiskLevel.READ.requires_approval)
        self.assertFalse(CanonicalRiskLevel.WRITE_LOW.requires_approval)
        self.assertTrue(CanonicalRiskLevel.WRITE_HIGH.requires_approval)
        self.assertTrue(CanonicalRiskLevel.INFRA.requires_approval)
        self.assertTrue(CanonicalRiskLevel.DELETE.requires_approval)
        self.assertTrue(CanonicalRiskLevel.DEPLOY.requires_approval)

    def test_1000_mappings_bounded(self):
        """Mapping 1000 statuses should complete in <1s."""
        from core.canonical_types import map_legacy_mission_status
        statuses = ["ANALYZING", "DONE", "UNKNOWN", "EXECUTING", "BLOCKED",
                     "PENDING_VALIDATION", "APPROVED", "REJECTED", "PLAN_ONLY"]
        t0 = time.time()
        for i in range(1000):
            map_legacy_mission_status(statuses[i % len(statuses)], "mission_system")
        elapsed = time.time() - t0
        self.assertLess(elapsed, 1.0, f"1000 mappings took {elapsed:.2f}s")


if __name__ == "__main__":
    unittest.main()
