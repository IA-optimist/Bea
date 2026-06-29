from __future__ import annotations

import pytest

from agent_cyber.evals.runner import CyberEvalRunner
from agent_cyber.evidence import Evidence, EvidenceGate, EvidenceType
from agent_cyber.findings import FindingStatus, SecurityFinding, Severity, VulnClass
from agent_cyber.integration import (
    CYBER_MISSION_TYPES,
    CyberMissionContext,
    create_cyber_mission_context,
    finalize_cyber_mission,
)
from agent_cyber.policy import CyberActionGuard
from agent_cyber.reports import CyberReport
from agent_cyber.scope import AuthorizationStatus, CyberScopePolicy, RiskLevel


def _scope(**kwargs) -> CyberScopePolicy:
    return CyberScopePolicy(
        mission_id="integ-m-001",
        requested_by="test-user",
        **kwargs,
    )


def test_cyber_mission_types_defined():
    assert "cyber_code_review" in CYBER_MISSION_TYPES
    assert "cyber_eval" in CYBER_MISSION_TYPES
    assert len(CYBER_MISSION_TYPES) == 6


def test_create_context_requires_scope():
    scope = _scope()
    ctx = create_cyber_mission_context("m-001", scope)
    assert isinstance(ctx, CyberMissionContext)
    assert ctx.mission_id == "m-001"
    assert ctx.scope == scope
    assert isinstance(ctx.guard, CyberActionGuard)
    assert isinstance(ctx.evidence_gate, EvidenceGate)


def test_create_context_has_graph():
    scope = _scope()
    ctx = create_cyber_mission_context("m-001", scope)
    assert ctx.graph is not None
    assert ctx.graph.mission_id == "m-001"


def test_context_guard_blocks_exploit():
    scope = _scope()
    ctx = create_cyber_mission_context("m-001", scope)
    decision = ctx.guard.validate(action="exploit", scope=scope)
    assert decision.allowed is False


def test_context_guard_allows_code_review():
    scope = _scope()
    ctx = create_cyber_mission_context("m-001", scope)
    decision = ctx.guard.validate(action="code_review", scope=scope)
    assert decision.allowed is True


def test_finalize_produces_report():
    scope = _scope()
    ctx = create_cyber_mission_context("m-001", scope)
    report = finalize_cyber_mission(ctx)
    assert isinstance(report, CyberReport)
    assert report.mission_id == "m-001"
    assert report.scope_summary
    assert report.authorization_status == AuthorizationStatus.UNKNOWN.value


def test_finalize_confirmed_finding_without_evidence_downgraded():
    scope = _scope()
    ctx = create_cyber_mission_context("m-001", scope)
    finding = SecurityFinding(
        mission_id="m-001",
        title="SQL Injection",
        description="Direct string concat",
        vuln_class=VulnClass.SQL_INJECTION,
        severity=Severity.HIGH,
        confidence=0.9,
        status=FindingStatus.CONFIRMED,
        evidence_refs=["some-ref"],
    )
    # Create a finding with CONFIRMED but no evidence_refs to test downgrade
    # Note: pydantic validator requires evidence_refs for CONFIRMED,
    # so we test via mutation after creation
    bad_finding = finding.model_copy(update={"evidence_refs": []})
    # Override pydantic validation to test integration downgrade
    object.__setattr__(bad_finding, "evidence_refs", [])
    ctx.findings.append(bad_finding)
    report = finalize_cyber_mission(ctx)
    assert report.findings[0].status == FindingStatus.UNVERIFIED


def test_finalize_high_risk_scope_requires_approval():
    scope = _scope(risk_level=RiskLevel.HIGH)
    ctx = create_cyber_mission_context("m-001", scope)
    report = finalize_cyber_mission(ctx)
    assert report.approval_required is True


def test_finalize_low_risk_no_approval():
    scope = _scope(risk_level=RiskLevel.LOW)
    ctx = create_cyber_mission_context("m-001", scope)
    report = finalize_cyber_mission(ctx)
    assert report.approval_required is False


def test_finalize_evidence_count_in_summary():
    scope = _scope()
    ctx = create_cyber_mission_context("m-001", scope)
    ev = Evidence(
        evidence_type=EvidenceType.CODE_SNIPPET,
        source="test",
        content_summary="Some code",
        confidence=0.8,
    )
    ctx.evidence_gate.attach_evidence(ev)
    report = finalize_cyber_mission(ctx)
    assert "1" in report.evidence_summary


def test_cyber_eval_fixture_path_traversal_scores_100():
    runner = CyberEvalRunner()
    results = runner.run_all()
    path_traversal = next(
        (r for r in results if r[0].task_id == "eval_path_traversal_001"), None
    )
    assert path_traversal is not None
    _, output, score = path_traversal
    assert score.total_score >= 80.0


def test_high_risk_action_requires_approval():
    scope = _scope(risk_level=RiskLevel.HIGH)
    guard = CyberActionGuard()
    decision = guard.validate(action="code_review", scope=scope)
    assert decision.allowed is True
    assert decision.required_approval is True
