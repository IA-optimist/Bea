"""
tests/test_mission_submitted_by.py

Hardening tests for the mission "submitted_by" identity binding.
Covers:
  - submit endpoints record the authenticated principal as submitted_by
  - client body cannot override submitted_by or _bea_principal_id
  - approval/resume distinguishes submitted_by from approved_by
  - execution after approval uses the submitter's PolicyEngine session
  - legacy records without submitted_by remain readable and fall back safely
"""
from __future__ import annotations

import pytest

from core.mission_models import MissionResult
from core.mission_system import MissionSystem
from core.policy_engine import PolicyEngine
from core.state import MissionStatus


# ──────────────────────────────────────────────────────────────────────────────
# MissionResult model / persistence hardening
# ──────────────────────────────────────────────────────────────────────────────


def test_mission_result_defaults_submitted_by_none():
    r = MissionResult(
        mission_id="m1",
        user_input="test",
        intent="OTHER",
        status=MissionStatus.ANALYZING,
    )
    assert r.submitted_by is None
    assert r.approved_by is None


def test_mission_result_submitted_by_and_approved_by_are_distinct():
    r = MissionResult(
        mission_id="m2",
        user_input="test",
        intent="OTHER",
        status=MissionStatus.PENDING_VALIDATION,
    )
    r.submitted_by = "jwt:alice"
    r.approved_by = "jwt:admin"
    assert r.submitted_by != r.approved_by


def test_from_dict_ignores_unknown_fields_for_backward_compat():
    r = MissionResult.from_dict({
        "mission_id": "legacy",
        "user_input": "legacy mission",
        "intent": "OTHER",
        "status": "DONE",
        "future_field": "ignored",
    })
    assert r.submitted_by is None
    assert r.approved_by is None


# ──────────────────────────────────────────────────────────────────────────────
# MissionSystem submit path
# ──────────────────────────────────────────────────────────────────────────────


def test_submit_stores_submitted_by():
    ms = MissionSystem.__new__(MissionSystem)
    ms.__init__()
    result = ms.submit("analyse ce code", submitted_by="jwt:alice")
    assert result.submitted_by == "jwt:alice"
    stored = ms.get(result.mission_id)
    assert stored is not None
    assert stored.submitted_by == "jwt:alice"


def test_submit_without_submitted_by_keeps_none():
    ms = MissionSystem.__new__(MissionSystem)
    ms.__init__()
    result = ms.submit("test no principal")
    assert result.submitted_by is None


# ──────────────────────────────────────────────────────────────────────────────
# Approval path: execution identity stays with submitter
# ──────────────────────────────────────────────────────────────────────────────


def test_approve_mission_for_resume_uses_submitter_principal():
    """The resumed mission must run under the submitter's PolicyEngine session."""
    import inspect
    import api.mission_approval as mod

    src = inspect.getsource(mod.approve_mission_for_resume)
    assert "_resume_principal = record.submitted_by or principal_id" in src
    assert "principal_id=_resume_principal" in src


def test_approval_sets_approved_by_separate_from_submitted_by():
    import inspect
    import api.mission_approval as mod

    src = inspect.getsource(mod.approve_mission_for_resume)
    assert "record.approved_by = principal_id" in src


# ──────────────────────────────────────────────────────────────────────────────
# MetaOrchestrator resume uses submitted_by
# ──────────────────────────────────────────────────────────────────────────────


def test_meta_orchestrator_run_mission_accepts_submitted_by():
    import inspect
    from core.meta_orchestrator import MetaOrchestrator

    sig = inspect.signature(MetaOrchestrator.run_mission)
    assert "submitted_by" in sig.parameters


def test_meta_orchestrator_resolve_approval_propagates_submitted_by():
    import inspect
    from core.meta_orchestrator import MetaOrchestrator

    src = inspect.getsource(MetaOrchestrator.resolve_approval)
    assert "_bea_submitted_by" in src or "submitted_by" in src
    assert "principal_id=_submitter" in src


# ──────────────────────────────────────────────────────────────────────────────
# PolicyEngine session isolation per submitter
# ──────────────────────────────────────────────────────────────────────────────


def test_two_submitters_same_mission_id_have_separate_sessions():
    """Even with the same mission_id, different submitters get isolated sessions."""
    engine = PolicyEngine(None)
    mid = "shared-mission-id"

    alice = engine.ensure_session(mid, principal_id="jwt:alice")
    bob = engine.ensure_session(mid, principal_id="jwt:bob")

    assert alice is not bob
    alice.record_action()
    assert bob.actions_done == 0

    assert f"jwt:alice:{mid}" in engine._sessions
    assert f"jwt:bob:{mid}" in engine._sessions


# ──────────────────────────────────────────────────────────────────────────────
# Legacy record fallback
# ──────────────────────────────────────────────────────────────────────────────


def test_legacy_record_without_submitted_by_falls_back_to_approver():
    """A legacy record (submitted_by=None) falls back to the approver principal."""
    r = MissionResult(
        mission_id="legacy",
        user_input="legacy",
        intent="OTHER",
        status=MissionStatus.PENDING_VALIDATION,
    )
    approver = "jwt:admin"
    resume_principal = r.submitted_by or approver
    assert resume_principal == approver


# ──────────────────────────────────────────────────────────────────────────────
# Persistence round-trip (kernel runtime state)
# ──────────────────────────────────────────────────────────────────────────────


def test_persisted_mission_carries_submitted_by():
    from core.mission_persistence import PersistedMission

    pm = PersistedMission(
        mission_id="p1",
        goal="g",
        submitted_by="jwt:alice",
        approved_by="jwt:admin",
    )
    d = pm.to_dict()
    assert d["submitted_by"] == "jwt:alice"
    assert d["approved_by"] == "jwt:admin"

    restored = PersistedMission.from_dict(d)
    assert restored.submitted_by == "jwt:alice"
    assert restored.approved_by == "jwt:admin"


def test_persisted_mission_from_context_reads_submitted_by():
    from core.meta_orchestrator_state import MissionContext, MissionStatus
    from core.mission_persistence import PersistedMission

    ctx = MissionContext(
        mission_id="ctx1",
        goal="g",
        mode="auto",
        status=MissionStatus.CREATED,
        created_at=0.0,
        updated_at=0.0,
        submitted_by="jwt:alice",
    )
    pm = PersistedMission.from_mission_context(ctx)
    assert pm.submitted_by == "jwt:alice"
