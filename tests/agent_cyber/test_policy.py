from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from agent_cyber.actions import CyberActionType
from agent_cyber.policy import CYBER_CAPABILITIES, CyberActionGuard, CyberPolicyDecision
from agent_cyber.scope import AuthorizationStatus, CyberScopePolicy, RiskLevel


def _scope(**kwargs) -> CyberScopePolicy:
    return CyberScopePolicy(
        mission_id="test-m-001",
        requested_by="test-user",
        **kwargs,
    )


guard = CyberActionGuard()


def test_missing_scope_blocked():
    d = guard.validate(action="code_review", scope=None)
    assert d.allowed is False
    assert d.blocked_by == "missing_scope"
    assert d.reason


def test_expired_scope_blocked():
    scope = _scope(expires_at=datetime.utcnow() - timedelta(seconds=1))
    d = guard.validate(action="code_review", scope=scope)
    assert d.allowed is False
    assert d.blocked_by == "expired_scope"


def test_blocked_action_exploit():
    scope = _scope()
    d = guard.validate(action="exploit", scope=scope)
    assert d.allowed is False
    assert d.blocked_by == "blocked_action"


def test_blocked_action_brute_force():
    scope = _scope()
    d = guard.validate(action="brute_force", scope=scope)
    assert d.allowed is False
    assert d.blocked_by == "blocked_action"


def test_blocked_action_exfiltration():
    scope = _scope()
    d = guard.validate(action="exfiltration", scope=scope)
    assert d.allowed is False
    assert d.blocked_by == "blocked_action"


def test_unknown_action_blocked():
    scope = _scope()
    d = guard.validate(action="nmap_scan", scope=scope)
    assert d.allowed is False
    assert d.blocked_by == "unknown_action"


def test_unknown_capability_blocked():
    scope = _scope()
    d = guard.validate(
        action="code_review",
        scope=scope,
        capability="cyber.offensive_scan",
    )
    assert d.allowed is False
    assert d.blocked_by == "unknown_capability"


def test_external_target_no_auth_blocked():
    scope = _scope(
        targets=["evil.com"],
        authorization_status=AuthorizationStatus.MISSING,
    )
    d = guard.validate(action="code_review", scope=scope, target="evil.com")
    assert d.allowed is False
    assert d.blocked_by == "missing_authorization"


def test_external_target_unknown_auth_blocked():
    scope = _scope(targets=["evil.com"])
    d = guard.validate(action="code_review", scope=scope, target="evil.com")
    assert d.allowed is False
    assert d.blocked_by == "missing_authorization"


def test_external_target_explicit_auth_allowed():
    scope = _scope(
        targets=["target.example.com"],
        authorization_status=AuthorizationStatus.EXPLICIT,
        authorization_ref="contract-001",
    )
    d = guard.validate(
        action="code_review",
        scope=scope,
        target="target.example.com",
        capability="cyber.code_review",
    )
    assert d.allowed is True


def test_local_code_review_allowed():
    scope = _scope(targets=["localhost"])
    d = guard.validate(action="code_review", scope=scope, capability="cyber.code_review")
    assert d.allowed is True
    assert d.required_approval is False


def test_high_risk_requires_approval():
    scope = _scope(risk_level=RiskLevel.HIGH)
    d = guard.validate(action="code_review", scope=scope)
    assert d.allowed is True
    assert d.required_approval is True


def test_critical_risk_requires_approval():
    scope = _scope(risk_level=RiskLevel.CRITICAL)
    d = guard.validate(action="code_review", scope=scope)
    assert d.allowed is True
    assert d.required_approval is True


def test_low_risk_no_approval_required():
    scope = _scope(risk_level=RiskLevel.LOW)
    d = guard.validate(action="code_review", scope=scope)
    assert d.allowed is True
    assert d.required_approval is False


def test_audit_ref_always_present():
    scope = _scope()
    d = guard.validate(action="code_review", scope=scope)
    assert d.audit_ref is not None and len(d.audit_ref) > 0


def test_audit_ref_present_on_block():
    d = guard.validate(action="exploit", scope=None)
    assert d.audit_ref is not None


def test_report_only_blocks_propose_fix():
    scope = _scope(report_only=True)
    d = guard.validate(action="propose_fix", scope=scope)
    assert d.allowed is False
    assert d.blocked_by == "report_only"


def test_scope_level_blocked_action():
    scope = _scope(blocked_actions=["code_review"])
    d = guard.validate(action="code_review", scope=scope)
    assert d.allowed is False
    assert d.blocked_by == "scope_blocked_action"


def test_generate_report_allowed():
    scope = _scope()
    d = guard.validate(action="generate_report", scope=scope)
    assert d.allowed is True


def test_secret_scan_allowed():
    scope = _scope()
    d = guard.validate(action="secret_scan", scope=scope)
    assert d.allowed is True


def test_localhost_no_auth_needed():
    scope = _scope(authorization_status=AuthorizationStatus.MISSING)
    d = guard.validate(action="code_review", scope=scope, target="127.0.0.1")
    assert d.allowed is True
