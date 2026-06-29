from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from agent_cyber.actions import CyberActionType, BlockedCyberActionType
from agent_cyber.scope import AuthorizationStatus, CyberScopePolicy, RiskLevel


def _local_scope(**kwargs) -> CyberScopePolicy:
    return CyberScopePolicy(
        mission_id="test-mission-001",
        requested_by="test-user",
        **kwargs,
    )


def test_scope_local_only_no_targets():
    scope = _local_scope()
    assert scope.is_local_only is True


def test_scope_local_only_with_localhost():
    scope = _local_scope(targets=["localhost", "127.0.0.1"])
    assert scope.is_local_only is True


def test_scope_not_local_with_external_target():
    scope = _local_scope(targets=["example.com"])
    assert scope.is_local_only is False


def test_scope_authorization_default_unknown():
    scope = _local_scope()
    assert scope.authorization_status == AuthorizationStatus.UNKNOWN


def test_scope_explicit_authorization():
    scope = _local_scope(
        authorization_status=AuthorizationStatus.EXPLICIT,
        authorization_ref="pentest-order-2026-001",
    )
    assert scope.authorization_status == AuthorizationStatus.EXPLICIT


def test_scope_not_expired_by_default():
    scope = _local_scope()
    assert scope.is_expired is False


def test_scope_not_expired_future():
    scope = _local_scope(expires_at=datetime.utcnow() + timedelta(hours=1))
    assert scope.is_expired is False


def test_scope_expired_past():
    scope = _local_scope(expires_at=datetime.utcnow() - timedelta(seconds=1))
    assert scope.is_expired is True


def test_scope_report_only_default():
    scope = _local_scope()
    assert scope.report_only is True


def test_scope_risk_level_default_low():
    scope = _local_scope()
    assert scope.risk_level == RiskLevel.LOW


def test_scope_allowed_actions_list():
    scope = _local_scope(
        allowed_actions=["code_review", "generate_report"],
        allowed_paths=["/app"],
    )
    assert "code_review" in scope.allowed_actions


def test_scope_max_requests_default_zero():
    scope = _local_scope()
    assert scope.max_requests == 0


def test_scope_missing_mission_id_raises():
    with pytest.raises(Exception):
        CyberScopePolicy(requested_by="user")


def test_scope_missing_requested_by_raises():
    with pytest.raises(Exception):
        CyberScopePolicy(mission_id="m1")
