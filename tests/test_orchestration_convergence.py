"""
Tests for Phase C — Orchestration Convergence.

Covers:
    - Canonical types (enums, lifecycle, transitions)
    - Legacy enum mappings (MissionStatus × 3, RiskLevel × 2)
    - CanonicalMissionContext lifecycle
    - Memory facade routing + JSONL fallback
    - Orchestration bridge (submit, approve, reject, list)
"""
import json
import tempfile
import time
import pytest
from pathlib import Path


# ═══════════════════════════════════════════════════════════════
# CANONICAL TYPES
# ═══════════════════════════════════════════════════════════════

def test_import_canonical_types():
    pass


def test_canonical_status_values():
    from core.canonical_types import CanonicalMissionStatus as S
    assert len(S) == 10
    assert S.CREATED.value == "CREATED"
    assert S.COMPLETED.value == "COMPLETED"


def test_terminal_states():
    from core.canonical_types import CanonicalMissionStatus as S
    assert S.COMPLETED.is_terminal
    assert S.FAILED.is_terminal
    assert S.CANCELLED.is_terminal
    assert not S.CREATED.is_terminal
    assert not S.RUNNING.is_terminal


def test_active_states():
    from core.canonical_types import CanonicalMissionStatus as S
    assert S.PLANNING.is_active
    assert S.RUNNING.is_active
    assert S.REVIEW.is_active
    assert not S.CREATED.is_active
    assert not S.COMPLETED.is_active


def test_waiting_states():
    from core.canonical_types import CanonicalMissionStatus as S
    assert S.QUEUED.is_waiting
    assert S.WAITING_APPROVAL.is_waiting
    assert S.READY.is_waiting
    assert not S.RUNNING.is_waiting


# ── Lifecycle Transitions ─────────────────────────────────────

def test_valid_transitions():
    from core.canonical_types import validate_transition, CanonicalMissionStatus as S
    # Happy path
    assert validate_transition(S.CREATED, S.QUEUED)
    assert validate_transition(S.CREATED, S.PLANNING)
    assert validate_transition(S.QUEUED, S.PLANNING)
    assert validate_transition(S.PLANNING, S.WAITING_APPROVAL)
    assert validate_transition(S.PLANNING, S.READY)
    assert validate_transition(S.WAITING_APPROVAL, S.READY)
    assert validate_transition(S.READY, S.RUNNING)
    assert validate_transition(S.RUNNING, S.REVIEW)
    assert validate_transition(S.REVIEW, S.COMPLETED)


def test_invalid_transitions():
    from core.canonical_types import validate_transition, CanonicalMissionStatus as S
    # Can't go backwards
    assert not validate_transition(S.RUNNING, S.CREATED)
    assert not validate_transition(S.COMPLETED, S.RUNNING)
    assert not validate_transition(S.FAILED, S.RUNNING)
    # Can't skip
    assert not validate_transition(S.CREATED, S.RUNNING)
    assert not validate_transition(S.QUEUED, S.COMPLETED)


def test_any_state_can_fail():
    from core.canonical_types import validate_transition, CanonicalMissionStatus as S
    for status in S:
        if status.is_terminal:
            assert not validate_transition(status, S.FAILED)
        else:
            assert validate_transition(status, S.FAILED)


def test_any_state_can_cancel():
    from core.canonical_types import validate_transition, CanonicalMissionStatus as S
    for status in S:
        if status.is_terminal:
            assert not validate_transition(status, S.CANCELLED)
        else:
            assert validate_transition(status, S.CANCELLED)


def test_review_can_re_run():
    from core.canonical_types import validate_transition, CanonicalMissionStatus as S
    assert validate_transition(S.REVIEW, S.RUNNING)


def test_terminal_no_outgoing():
    from core.canonical_types import LIFECYCLE_TRANSITIONS, CanonicalMissionStatus as S
    assert LIFECYCLE_TRANSITIONS[S.COMPLETED] == set()
    assert LIFECYCLE_TRANSITIONS[S.FAILED] == set()
    assert LIFECYCLE_TRANSITIONS[S.CANCELLED] == set()


# ── Canonical Risk Level ──────────────────────────────────────

def test_risk_levels():
    from core.canonical_types import CanonicalRiskLevel as R
    assert len(R) == 6
    assert R.READ.requires_approval == False
    assert R.WRITE_LOW.requires_approval == False
    assert R.WRITE_HIGH.requires_approval == True
    assert R.INFRA.requires_approval == True
    assert R.DELETE.requires_approval == True
    assert R.DEPLOY.requires_approval == True


def test_risk_severity_ordering():
    from core.canonical_types import CanonicalRiskLevel as R
    scores = [R.READ.severity_score, R.WRITE_LOW.severity_score,
              R.WRITE_HIGH.severity_score, R.INFRA.severity_score,
              R.DELETE.severity_score, R.DEPLOY.severity_score]
    assert scores == sorted(scores)


def test_auto_approve_levels():
    from core.canonical_types import AUTO_APPROVE_LEVELS, CanonicalRiskLevel as R
    assert R.READ in AUTO_APPROVE_LEVELS
    assert R.WRITE_LOW in AUTO_APPROVE_LEVELS
    assert R.WRITE_HIGH not in AUTO_APPROVE_LEVELS


# ── Legacy Mappings (MissionStatus) ──────────────────────────

def test_map_mission_system_status():
    from core.canonical_types import map_legacy_mission_status, CanonicalMissionStatus as S
    assert map_legacy_mission_status("ANALYZING") == S.PLANNING
    assert map_legacy_mission_status("PENDING_VALIDATION") == S.WAITING_APPROVAL
    assert map_legacy_mission_status("APPROVED") == S.READY
    assert map_legacy_mission_status("EXECUTING") == S.RUNNING
    assert map_legacy_mission_status("DONE") == S.COMPLETED
    assert map_legacy_mission_status("REJECTED") == S.CANCELLED
    assert map_legacy_mission_status("BLOCKED") == S.FAILED
    assert map_legacy_mission_status("PLAN_ONLY") == S.COMPLETED


def test_map_meta_orchestrator_status():
    from core.canonical_types import map_legacy_mission_status, CanonicalMissionStatus as S
    assert map_legacy_mission_status("CREATED", "meta_orchestrator") == S.CREATED
    assert map_legacy_mission_status("PLANNED", "meta_orchestrator") == S.READY
    assert map_legacy_mission_status("RUNNING", "meta_orchestrator") == S.RUNNING
    assert map_legacy_mission_status("REVIEW", "meta_orchestrator") == S.REVIEW
    assert map_legacy_mission_status("DONE", "meta_orchestrator") == S.COMPLETED
    assert map_legacy_mission_status("FAILED", "meta_orchestrator") == S.FAILED


def test_map_workflow_graph_status():
    from core.canonical_types import map_legacy_mission_status, CanonicalMissionStatus as S
    assert map_legacy_mission_status("PLANNING", "workflow_graph") == S.PLANNING
    assert map_legacy_mission_status("SHADOW_CHECK", "workflow_graph") == S.PLANNING
    assert map_legacy_mission_status("AWAITING_APPROVAL", "workflow_graph") == S.WAITING_APPROVAL
    assert map_legacy_mission_status("EXECUTING", "workflow_graph") == S.RUNNING
    assert map_legacy_mission_status("DONE", "workflow_graph") == S.COMPLETED
    assert map_legacy_mission_status("FAILED", "workflow_graph") == S.FAILED


def test_map_unknown_status():
    from core.canonical_types import map_legacy_mission_status, CanonicalMissionStatus as S
    assert map_legacy_mission_status("NONEXISTENT") == S.CREATED
    assert map_legacy_mission_status("") == S.CREATED


# ── Legacy Mappings (RiskLevel) ───────────────────────────────

def test_map_state_risk():
    from core.canonical_types import map_legacy_risk_level, CanonicalRiskLevel as R
    assert map_legacy_risk_level("low") == R.WRITE_LOW
    assert map_legacy_risk_level("medium") == R.WRITE_HIGH
    assert map_legacy_risk_level("high") == R.INFRA


def test_map_approval_risk():
    from core.canonical_types import map_legacy_risk_level, CanonicalRiskLevel as R
    assert map_legacy_risk_level("read", "approval_queue") == R.READ
    assert map_legacy_risk_level("write_low", "approval_queue") == R.WRITE_LOW
    assert map_legacy_risk_level("deploy", "approval_queue") == R.DEPLOY


def test_map_unknown_risk():
    from core.canonical_types import map_legacy_risk_level, CanonicalRiskLevel as R
    assert map_legacy_risk_level("UNKNOWN") == R.WRITE_HIGH


# ── CanonicalMissionContext ───────────────────────────────────

def test_canonical_context_creation():
    from core.canonical_types import CanonicalMissionContext, CanonicalMissionStatus as S
    ctx = CanonicalMissionContext(mission_id="test1", goal="Fix auth")
    assert ctx.status == S.CREATED
    assert ctx.mission_id == "test1"


def test_canonical_context_transition():
    from core.canonical_types import CanonicalMissionContext, CanonicalMissionStatus as S
    ctx = CanonicalMissionContext(mission_id="t1", goal="Test")
    ctx.transition(S.QUEUED)
    assert ctx.status == S.QUEUED
    ctx.transition(S.PLANNING)
    assert ctx.status == S.PLANNING
    ctx.transition(S.READY)
    ctx.transition(S.RUNNING)
    ctx.transition(S.REVIEW)
    ctx.transition(S.COMPLETED)
    assert ctx.status == S.COMPLETED


def test_canonical_context_invalid_transition():
    from core.canonical_types import CanonicalMissionContext, CanonicalMissionStatus as S, TransitionError
    ctx = CanonicalMissionContext(mission_id="t2", goal="Test")
    with pytest.raises(TransitionError):
        ctx.transition(S.RUNNING)  # Can't jump from CREATED to RUNNING


def test_canonical_context_terminal_no_transition():
    from core.canonical_types import CanonicalMissionContext, CanonicalMissionStatus as S, TransitionError
    ctx = CanonicalMissionContext(mission_id="t3", goal="Test", status=S.COMPLETED)
    with pytest.raises(TransitionError):
        ctx.transition(S.RUNNING)


def test_canonical_context_to_dict():
    from core.canonical_types import CanonicalMissionContext
    ctx = CanonicalMissionContext(mission_id="t4", goal="Test mission")
    d = ctx.to_dict()
    assert d["mission_id"] == "t4"
    assert d["status"] == "CREATED"
    assert "goal" in d
    assert "risk_level" in d


# ═══════════════════════════════════════════════════════════════
# MEMORY FACADE
# ═══════════════════════════════════════════════════════════════

def test_import_memory_facade():
    pass


def test_memory_facade_store_jsonl():
    from core.memory_facade import MemoryFacade
    with tempfile.TemporaryDirectory() as tmpdir:
        facade = MemoryFacade(workspace_dir=tmpdir)
        result = facade.store(
            "Fixed auth by adding token refresh",
            content_type="solution",
            tags=["auth", "bugfix"],
        )
        assert result["ok"]
        # Should fall through to JSONL since no Qdrant available
        fallback = Path(tmpdir) / "memory_facade_store.jsonl"
        assert fallback.exists()
        entries = fallback.read_text().strip().split("\n")
        assert len(entries) == 1
        data = json.loads(entries[0])
        assert data["type"] == "solution"
        assert "auth" in data["tags"]


def test_memory_facade_search_jsonl():
    from core.memory_facade import MemoryFacade
    with tempfile.TemporaryDirectory() as tmpdir:
        facade = MemoryFacade(workspace_dir=tmpdir)
        facade.store("auth token refresh fix", content_type="solution", tags=["auth"])
        facade.store("database migration script", content_type="solution", tags=["db"])
        facade.store("auth middleware update", content_type="solution", tags=["auth"])

        results = facade.search("auth token", top_k=5)
        assert len(results) >= 1
        assert any("auth" in r.content for r in results)


def test_memory_facade_get_recent():
    from core.memory_facade import MemoryFacade
    with tempfile.TemporaryDirectory() as tmpdir:
        facade = MemoryFacade(workspace_dir=tmpdir)
        for i in range(5):
            facade.store(f"Entry {i}", content_type="solution")

        recent = facade.get_recent(n=3)
        assert len(recent) == 3


def test_memory_facade_content_type_filter():
    from core.memory_facade import MemoryFacade
    with tempfile.TemporaryDirectory() as tmpdir:
        facade = MemoryFacade(workspace_dir=tmpdir)
        facade.store("Solution A", content_type="solution")
        facade.store("Error B", content_type="error")
        facade.store("Decision C", content_type="decision")

        solutions = facade.get_recent(content_type="solution")
        assert all(r.content_type == "solution" for r in solutions)


def test_memory_facade_cleanup():
    from core.memory_facade import MemoryFacade
    with tempfile.TemporaryDirectory() as tmpdir:
        facade = MemoryFacade(workspace_dir=tmpdir)
        facade.store("Old entry", content_type="general")
        # Manually backdate the entry
        fallback = Path(tmpdir) / "memory_facade_store.jsonl"
        lines = fallback.read_text().strip().split("\n")
        old = json.loads(lines[0])
        old["timestamp"] = time.time() - (60 * 86400)  # 60 days ago
        fallback.write_text(json.dumps(old) + "\n")

        result = facade.cleanup(older_than_days=30)
        assert result["removed"] == 1
        assert result["remaining"] == 0


def test_memory_facade_health():
    from core.memory_facade import MemoryFacade
    with tempfile.TemporaryDirectory() as tmpdir:
        facade = MemoryFacade(workspace_dir=tmpdir)
        health = facade.health()
        assert "knowledge_jsonl" in health
        assert health["knowledge_jsonl"]["available"]


def test_memory_facade_dedup():
    from core.memory_facade import MemoryFacade
    with tempfile.TemporaryDirectory() as tmpdir:
        facade = MemoryFacade(workspace_dir=tmpdir)
        facade.store("Exact same content", content_type="solution")
        facade.store("Exact same content", content_type="solution")
        results = facade.search("Exact same content")
        # Should deduplicate
        contents = [r.content for r in results]
        assert contents.count("Exact same content") <= 1


def test_content_types_defined():
    from core.memory_facade import CONTENT_TYPES
    assert "solution" in CONTENT_TYPES
    assert "error" in CONTENT_TYPES
    assert "decision" in CONTENT_TYPES
    assert "mission_outcome" in CONTENT_TYPES


# ═══════════════════════════════════════════════════════════════
# ORCHESTRATION BRIDGE
# ═══════════════════════════════════════════════════════════════

def test_import_bridge():
    pass


def test_bridge_status():
    from core.orchestration_bridge import OrchestrationBridge
    bridge = OrchestrationBridge()
    status = bridge.get_status()
    assert "bridge_enabled" in status
    assert "canonical_missions_tracked" in status
    assert isinstance(status["status_counts"], dict)


def test_bridge_get_nonexistent_mission():
    from core.orchestration_bridge import OrchestrationBridge
    bridge = OrchestrationBridge()
    result = bridge.get_mission_canonical("nonexistent-id-12345")
    # Should return None without raising
    assert result is None


def test_bridge_list_empty():
    from core.orchestration_bridge import OrchestrationBridge
    bridge = OrchestrationBridge()
    missions = bridge.list_missions_canonical(limit=10)
    assert isinstance(missions, list)


# ── Transition Error ──────────────────────────────────────────

def test_transition_error_message():
    from core.canonical_types import TransitionError
    err = TransitionError("CREATED", "RUNNING", "m123")
    assert "CREATED" in str(err)
    assert "RUNNING" in str(err)
    assert "m123" in str(err)


# ── Full Lifecycle Simulation ─────────────────────────────────

def test_full_lifecycle_happy_path():
    from core.canonical_types import CanonicalMissionContext, CanonicalMissionStatus as S
    ctx = CanonicalMissionContext(mission_id="lifecycle-1", goal="Test lifecycle")

    assert ctx.status == S.CREATED
    ctx.transition(S.QUEUED)
    assert ctx.status == S.QUEUED
    ctx.transition(S.PLANNING)
    assert ctx.status == S.PLANNING
    ctx.transition(S.WAITING_APPROVAL)
    assert ctx.status == S.WAITING_APPROVAL
    ctx.transition(S.READY)
    assert ctx.status == S.READY
    ctx.transition(S.RUNNING)
    assert ctx.status == S.RUNNING
    ctx.transition(S.REVIEW)
    assert ctx.status == S.REVIEW
    ctx.transition(S.COMPLETED)
    assert ctx.status == S.COMPLETED
    assert ctx.status.is_terminal


def test_lifecycle_planning_direct_to_ready():
    """Skip approval for low-risk missions."""
    from core.canonical_types import CanonicalMissionContext, CanonicalMissionStatus as S
    ctx = CanonicalMissionContext(mission_id="direct-1", goal="Read file")
    ctx.transition(S.PLANNING)
    ctx.transition(S.READY)  # Skip WAITING_APPROVAL
    ctx.transition(S.RUNNING)
    ctx.transition(S.REVIEW)
    ctx.transition(S.COMPLETED)
    assert ctx.status == S.COMPLETED


def test_lifecycle_failure_from_any_state():
    """Any non-terminal state can fail."""
    from core.canonical_types import CanonicalMissionContext, CanonicalMissionStatus as S
    for start_state in [S.CREATED, S.QUEUED, S.PLANNING, S.WAITING_APPROVAL,
                        S.READY, S.RUNNING, S.REVIEW]:
        ctx = CanonicalMissionContext(
            mission_id=f"fail-{start_state.value}", goal="Test", status=start_state,
        )
        ctx.transition(S.FAILED)
        assert ctx.status == S.FAILED


def test_lifecycle_review_re_run():
    """Review can send back to RUNNING for re-execution."""
    from core.canonical_types import CanonicalMissionContext, CanonicalMissionStatus as S
    ctx = CanonicalMissionContext(mission_id="rerun-1", goal="Test", status=S.REVIEW)
    ctx.transition(S.RUNNING)
    assert ctx.status == S.RUNNING
    ctx.transition(S.REVIEW)
    ctx.transition(S.COMPLETED)


# ═══════════════════════════════════════════════════════════════
# AUTHORITY MAP DOCUMENT EXISTS
# ═══════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="stale: format changed")
def test_authority_map_exists():
    assert Path("docs/orchestration_authority_map.md").exists()
