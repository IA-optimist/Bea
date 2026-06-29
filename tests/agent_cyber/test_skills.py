from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_cyber.actions import BlockedCyberActionType
from agent_cyber.scope import RiskLevel
from agent_cyber.skills import DEFENSIVE_SKILLS_V1, SKILL_REGISTRY, CyberSkill


def test_skill_with_exploit_action_raises():
    with pytest.raises(ValueError, match="blocked action"):
        CyberSkill(
            skill_id="bad_skill",
            name="Bad Skill",
            description="Attempts exploitation",
            allowed_actions=["exploit"],
            risk_level=RiskLevel.CRITICAL,
        )


def test_skill_with_brute_force_raises():
    with pytest.raises(ValueError):
        CyberSkill(
            skill_id="bad",
            name="Bad",
            description="Brute forces",
            allowed_actions=["brute_force"],
            risk_level=RiskLevel.CRITICAL,
        )


def test_skill_without_allowed_actions_raises():
    with pytest.raises(ValueError, match="at least one allowed_action"):
        CyberSkill(
            skill_id="empty",
            name="Empty",
            description="No actions",
            allowed_actions=[],
            risk_level=RiskLevel.LOW,
        )


def test_skill_without_risk_level_raises():
    with pytest.raises(ValidationError):
        CyberSkill(
            skill_id="nolevel",
            name="No Level",
            description="Missing risk",
            allowed_actions=["code_review"],
        )


def test_valid_skill_code_review():
    skill = CyberSkill(
        skill_id="test_code_review",
        name="Code Review",
        description="Reviews code",
        allowed_actions=["code_review", "generate_report"],
        risk_level=RiskLevel.LOW,
        evidence_required=True,
        tests_required=False,
    )
    assert skill.skill_id == "test_code_review"
    assert skill.evidence_required is True


def test_all_11_defensive_skills_valid():
    assert len(DEFENSIVE_SKILLS_V1) == 11
    for skill in DEFENSIVE_SKILLS_V1:
        assert skill.allowed_actions
        assert skill.risk_level is not None
        assert skill.skill_id


def test_no_blocked_actions_in_defensive_skills():
    blocked = {a.value for a in BlockedCyberActionType}
    for skill in DEFENSIVE_SKILLS_V1:
        for action in skill.allowed_actions:
            assert action not in blocked, (
                f"Skill '{skill.skill_id}' includes blocked action '{action}'"
            )


def test_skill_registry_populated():
    assert len(SKILL_REGISTRY) == 11
    assert "auth_flow_review" in SKILL_REGISTRY
    assert "secrets_scan_review" in SKILL_REGISTRY
    assert "dependency_vulnerability_review" in SKILL_REGISTRY


def test_ai_agent_security_review_high_risk():
    skill = SKILL_REGISTRY["ai_agent_security_review"]
    assert skill.risk_level == RiskLevel.HIGH
    assert skill.evidence_required is True
    assert skill.tests_required is True


def test_regression_test_planner_safe():
    skill = SKILL_REGISTRY["regression_test_planner"]
    assert skill.risk_level == RiskLevel.SAFE


def test_remediation_planner_report_only_actions():
    skill = SKILL_REGISTRY["remediation_planner"]
    assert "propose_fix" in skill.allowed_actions
    assert "generate_report" in skill.allowed_actions


def test_evidence_required_on_all_skills():
    for skill in DEFENSIVE_SKILLS_V1:
        assert skill.evidence_required is True, (
            f"Skill '{skill.skill_id}' has evidence_required=False"
        )
