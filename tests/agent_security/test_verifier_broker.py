from __future__ import annotations

import pytest

from agent_security.verifier.audit import VerifierAuditLog
from agent_security.verifier.broker import VerifierBroker
from agent_security.verifier.exceptions import (
    VerifierDenied,
    VerifierHaltTriggered,
    VerifierHoldRequired,
    VerifierUnavailable,
)
from agent_security.verifier.models import ActionIntent, ActionType, EffectScope, VerifierVerdict


def make_intent(**kwargs):
    defaults = dict(
        actor_id="bea",
        action_type=ActionType.FILESYSTEM_READ,
        target="/workspace/src.py",
        declared_scope=EffectScope.LOCAL_READONLY,
    )
    defaults.update(kwargs)
    return ActionIntent(**defaults)


@pytest.fixture
def broker(tmp_path):
    audit = VerifierAuditLog(log_path=tmp_path / "audit.jsonl")
    return VerifierBroker(audit=audit)


class TestBrokerVerdicts:
    def test_allowed_action_returns_allow_decision(self, broker):
        intent = make_intent(action_type=ActionType.FILESYSTEM_READ, target="/workspace/safe.py")
        decision = broker.execute(intent)
        assert decision.verdict == VerifierVerdict.ALLOW

    def test_denied_action_raises_verifier_denied(self, broker):
        intent = make_intent(action_type=ActionType.EXEC_COMMAND, target="ls")
        with pytest.raises(VerifierDenied):
            broker.execute(intent)

    def test_halt_action_raises_halt_triggered(self, broker):
        intent = make_intent(
            action_type=ActionType.FILESYSTEM_WRITE,
            target="agent_security/verifier/audit.py",
            declared_scope=EffectScope.LOCAL_WRITE,
        )
        with pytest.raises(VerifierHaltTriggered):
            broker.execute(intent)

    def test_hold_action_raises_hold_required(self, broker):
        intent = make_intent(action_type=ActionType.SPAWN_AGENT, target="worker")
        with pytest.raises(VerifierHoldRequired):
            broker.execute(intent)

    def test_self_modification_raises_hold(self, broker):
        intent = make_intent(action_type=ActionType.SELF_MODIFICATION, target="core/agent.py")
        with pytest.raises(VerifierHoldRequired):
            broker.execute(intent)

    def test_modify_security_config_raises_halt(self, broker):
        intent = make_intent(action_type=ActionType.MODIFY_SECURITY_CONFIG, target="config.yaml")
        with pytest.raises(VerifierHaltTriggered):
            broker.execute(intent)


class TestFailClosed:
    def test_policy_internal_failure_raises_denied(self, broker, monkeypatch):
        """policy.evaluate wraps exceptions → DENY → broker raises VerifierDenied."""
        def broken(intent):
            raise RuntimeError("policy crashed")
        monkeypatch.setattr(broker._policy, "_evaluate_inner", broken)
        intent = make_intent()
        with pytest.raises(VerifierDenied):
            broker.execute(intent)

    def test_audit_failure_raises_unavailable(self, broker, monkeypatch):
        """Audit log failure → VerifierUnavailable (fail-closed)."""
        def broken_record(*args, **kwargs):
            raise IOError("disk full")
        monkeypatch.setattr(broker._audit, "record", broken_record)
        intent = make_intent()
        with pytest.raises(VerifierUnavailable):
            broker.execute(intent)

    def test_halt_never_returns_silently(self, broker):
        """HALT must always raise — never return a decision."""
        intent = make_intent(
            action_type=ActionType.FILESYSTEM_WRITE,
            target="agent_security/verifier/policy.py",
            declared_scope=EffectScope.LOCAL_WRITE,
        )
        with pytest.raises(VerifierHaltTriggered):
            broker.execute(intent)


class TestEffectuorRegistration:
    def test_effectuor_called_on_allow(self, broker):
        called = []

        def my_handler(intent):
            called.append(intent.action_id)

        broker.register_effectuor("filesystem_read", my_handler)
        intent = make_intent()
        broker.execute(intent)
        assert len(called) == 1

    def test_unregistered_effectuor_does_not_raise_on_allow(self, broker):
        """v0: unwired effectuors warn but do not raise (ALLOW was granted)."""
        intent = make_intent()
        decision = broker.execute(intent)
        assert decision.verdict == VerifierVerdict.ALLOW

    def test_unknown_action_type_in_register_raises(self, broker):
        with pytest.raises(ValueError, match="Unknown action_type"):
            broker.register_effectuor("not_a_real_action", lambda i: None)


class TestTransparency:
    def test_integration_status_honest_about_unwired(self, broker):
        status = broker.get_integration_status()
        assert "filesystem_read" in status
        assert "INTERFACE_ONLY" in status["filesystem_read"]

    def test_integration_status_returns_copy(self, broker):
        s1 = broker.get_integration_status()
        s1["filesystem_read"] = "HACKED"
        s2 = broker.get_integration_status()
        assert "HACKED" not in s2["filesystem_read"]

    def test_exec_command_status_blocked(self, broker):
        status = broker.get_integration_status()
        assert "BLOCKED_IN_V0" in status["exec_command"]

    def test_audit_ref_in_decision(self, broker):
        intent = make_intent()
        decision = broker.execute(intent)
        assert decision.audit_ref is not None
