"""
Tests for principal/auth binding in PolicyEngine.

Validates that `_bea_principal_id` (the trusted, auth-derived key) wins over
any client-supplied `principal_id`, and that sessions are isolated per
validated principal.
"""
from __future__ import annotations

import pytest
from core.policy_engine import PolicyEngine


@pytest.fixture
def engine():
    return PolicyEngine(None)


def test_extract_principal_id_prefers_trusted_key(engine):
    params = {
        "_bea_principal_id": "jwt:alice",
        "principal_id": "attacker",
        "user_id": "mallory",
    }
    # engine.execute_tool wrapper eventually reaches evaluate_tool which reads
    # the same _extract_principal_id helper.
    from core.policy_engine import _extract_principal_id
    assert _extract_principal_id(params) == "jwt:alice"


def test_extract_principal_id_fallback_internal_keys():
    from core.policy_engine import _extract_principal_id
    assert _extract_principal_id({"principal_id": "internal-test"}) == "internal-test"
    assert _extract_principal_id({"user_id": "legacy"}) == "legacy"
    assert _extract_principal_id({"tenant_id": "acme"}) == "acme"
    assert _extract_principal_id({"owner_id": "bob"}) == "bob"


def test_extract_principal_id_no_principal():
    from core.policy_engine import _extract_principal_id
    assert _extract_principal_id({}) is None
    assert _extract_principal_id(None) is None


def test_same_mission_different_principals_have_separate_sessions(engine):
    mid = "mission-shared"
    engine.ensure_session(mid, "auto", principal_id="jwt:alice")
    engine.ensure_session(mid, "auto", principal_id="jwt:bob")

    # The same mission_id + two different principals => two distinct keys.
    principal_keys = [f"jwt:alice:{mid}", f"jwt:bob:{mid}"]
    for key in principal_keys:
        assert key in engine._sessions


@pytest.mark.parametrize("mode", ["auto", "fast"])
def test_same_principal_same_mission_reuses_session(engine, mode):
    mid = "mission-reuse"
    engine.ensure_session(mid, mode, principal_id="access_token:tok-1")
    engine.ensure_session(mid, mode, principal_id="access_token:tok-1")
    # Should not raise or create duplicate conflicting session; the second call
    # validates compatibility but keeps the same tracker.
    key = f"access_token:tok-1:{mid}"
    assert key in engine._sessions


def test_evaluate_tool_blocks_high_risk_without_mission_id_even_with_principal():
    engine = PolicyEngine(None)
    result = engine.evaluate_tool(
        "dangerous_tool",
        "execute",
        "high",
        mission_id="",
        params={"_bea_principal_id": "jwt:alice"},
    )
    assert result.allowed is False
    # The principal must not create a bypass path for missing mission_id.


def test_evaluate_tool_blocks_empty_mission_id_with_principal():
    engine = PolicyEngine(None)
    result = engine.evaluate_tool(
        "safe_tool",
        "execute",
        "low",
        mission_id="",
        params={"_bea_principal_id": "jwt:alice"},
    )
    assert result.allowed is False


def test_evaluate_tool_uses_trusted_principal_for_session_key():
    engine = PolicyEngine(None)
    mid = "m1"
    engine.ensure_session(mid, "auto", principal_id="static:api")
    result = engine.evaluate_tool(
        "safe_tool",
        "execute",
        "low",
        mission_id=mid,
        params={"_bea_principal_id": "static:api"},
        principal_id="static:api",
    )
    assert result.allowed is True
    key = f"static:api:{mid}"
    assert key in engine._sessions
