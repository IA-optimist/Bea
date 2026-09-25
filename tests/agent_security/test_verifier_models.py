from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_security.verifier.models import (
    ActionIntent,
    ActionType,
    EffectScope,
    RiskLevel,
    VerifierDecision,
    VerifierVerdict,
)


def make_intent(**kwargs):
    defaults = dict(
        actor_id="bea",
        action_type=ActionType.FILESYSTEM_READ,
        target="/workspace/test.py",
        declared_scope=EffectScope.LOCAL_READONLY,
    )
    defaults.update(kwargs)
    return ActionIntent(**defaults)


class TestActionIntentValidation:
    def test_valid_intent_creates(self):
        intent = make_intent()
        assert intent.actor_id == "bea"
        assert intent.action_type == ActionType.FILESYSTEM_READ

    def test_missing_actor_id_raises(self):
        with pytest.raises(ValidationError):
            ActionIntent(
                action_type=ActionType.FILESYSTEM_READ,
                target="/workspace/f.py",
                declared_scope=EffectScope.LOCAL_READONLY,
            )

    def test_empty_actor_id_raises(self):
        with pytest.raises(ValidationError):
            make_intent(actor_id="")

    def test_whitespace_actor_id_raises(self):
        with pytest.raises(ValidationError):
            make_intent(actor_id="   ")

    def test_missing_target_raises(self):
        with pytest.raises(ValidationError):
            ActionIntent(
                actor_id="bea",
                action_type=ActionType.FILESYSTEM_READ,
                declared_scope=EffectScope.LOCAL_READONLY,
            )

    def test_empty_target_raises(self):
        with pytest.raises(ValidationError):
            make_intent(target="")

    def test_intent_is_immutable(self):
        intent = make_intent()
        with pytest.raises(Exception):  # ValidationError or TypeError depending on pydantic version
            intent.actor_id = "hacker"  # type: ignore[misc]

    def test_action_id_auto_generated(self):
        intent = make_intent()
        assert intent.action_id
        assert len(intent.action_id) == 36  # UUID4

    def test_parameters_default_empty(self):
        intent = make_intent()
        assert intent.parameters == {}

    def test_metadata_default_empty(self):
        intent = make_intent()
        assert intent.metadata == {}


class TestEnums:
    def test_all_action_types_listable(self):
        types = list(ActionType)
        assert len(types) == 10
        assert ActionType.EXEC_COMMAND in types
        assert ActionType.MODIFY_SECURITY_CONFIG in types

    def test_effect_scope_values(self):
        scopes = list(EffectScope)
        assert EffectScope.LOCAL_READONLY in scopes
        assert EffectScope.SYSTEM in scopes

    def test_risk_level_values(self):
        levels = list(RiskLevel)
        assert RiskLevel.SAFE in levels
        assert RiskLevel.CRITICAL in levels

    def test_verifier_verdict_values(self):
        verdicts = list(VerifierVerdict)
        assert VerifierVerdict.ALLOW in verdicts
        assert VerifierVerdict.HALT in verdicts


class TestVerifierDecision:
    def test_decision_is_immutable(self):
        d = VerifierDecision(
            verdict=VerifierVerdict.ALLOW,
            reason="ok",
            action_id="x",
            risk_level=RiskLevel.LOW,
        )
        with pytest.raises(Exception):
            d.verdict = VerifierVerdict.DENY  # type: ignore[misc]

    def test_requires_human_approval_default_false(self):
        d = VerifierDecision(
            verdict=VerifierVerdict.DENY, reason="x", action_id="y",
        )
        assert d.requires_human_approval is False
