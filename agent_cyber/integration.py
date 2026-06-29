"""
Thin integration layer connecting agent_cyber to Béa's mission system.
Does NOT modify existing mission routing — provides helpers callable from handlers.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agent_cyber.evidence import EvidenceGate
from agent_cyber.findings import FindingStatus, SecurityFinding
from agent_cyber.mission_graph import CyberMissionGraph
from agent_cyber.policy import CyberActionGuard
from agent_cyber.reports import CyberReport
from agent_cyber.scope import CyberScopePolicy

CYBER_MISSION_TYPES: frozenset[str] = frozenset({
    "cyber_code_review",
    "cyber_dependency_audit",
    "cyber_secret_scan",
    "cyber_config_review",
    "cyber_eval",
    "cyber_report",
})


@dataclass
class CyberMissionContext:
    """All state for one cyber mission execution."""

    mission_id: str
    scope: CyberScopePolicy
    guard: CyberActionGuard
    evidence_gate: EvidenceGate
    graph: CyberMissionGraph
    findings: list[SecurityFinding] = field(default_factory=list)


def create_cyber_mission_context(
    mission_id: str,
    scope: CyberScopePolicy,
) -> CyberMissionContext:
    """Entry point for cyber missions. REQUIRES an explicit scope."""
    guard = CyberActionGuard()
    evidence_gate = EvidenceGate()
    graph = CyberMissionGraph(mission_id=mission_id, scope=scope)
    return CyberMissionContext(
        mission_id=mission_id,
        scope=scope,
        guard=guard,
        evidence_gate=evidence_gate,
        graph=graph,
    )


def finalize_cyber_mission(
    ctx: CyberMissionContext,
    actions_performed: list[str] = None,
    actions_blocked: list[str] = None,
    risk_summary: str = "",
    remediation_plan: str = "",
    regression_tests: list[str] = None,
    limitations: list[str] = None,
) -> CyberReport:
    """Produce final report. CONFIRMED findings without evidence → downgraded to UNVERIFIED."""
    sanitized: list[SecurityFinding] = []
    for f in ctx.findings:
        if f.status == FindingStatus.CONFIRMED and not f.evidence_refs:
            f = f.model_copy(update={"status": FindingStatus.UNVERIFIED})
        sanitized.append(f)

    scope_summary = (
        f"Mission {ctx.mission_id} — targets: {ctx.scope.targets or ['local']} — "
        f"risk: {ctx.scope.risk_level.value}"
    )
    evidence_count = len(ctx.evidence_gate._evidence)

    return CyberReport(
        mission_id=ctx.mission_id,
        scope_summary=scope_summary,
        authorization_status=ctx.scope.authorization_status.value,
        actions_performed=actions_performed or [],
        actions_blocked=actions_blocked or [],
        findings=sanitized,
        evidence_summary=f"{evidence_count} evidence item(s) collected",
        risk_summary=risk_summary,
        remediation_plan=remediation_plan,
        regression_tests_recommended=regression_tests or [],
        limitations=limitations or [],
        approval_required=ctx.scope.risk_level.value in ("high", "critical"),
    )
