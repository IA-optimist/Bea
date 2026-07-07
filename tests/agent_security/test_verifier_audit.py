from __future__ import annotations

import json

import pytest

from agent_security.verifier.audit import VerifierAuditLog
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
        actor_id="test-actor",
        action_type=ActionType.FILESYSTEM_READ,
        target="/workspace/test.py",
        declared_scope=EffectScope.LOCAL_READONLY,
    )
    defaults.update(kwargs)
    return ActionIntent(**defaults)


def make_decision(verdict=VerifierVerdict.ALLOW, reason="test reason", **kwargs):
    return VerifierDecision(
        verdict=verdict,
        reason=reason,
        action_id="test-id",
        risk_level=RiskLevel.LOW,
        **kwargs,
    )


@pytest.fixture
def tmp_audit(tmp_path):
    return VerifierAuditLog(log_path=tmp_path / "audit.jsonl")


class TestAuditLog:
    def test_record_creates_file(self, tmp_audit, tmp_path):
        tmp_audit.record(make_intent(), make_decision())
        assert (tmp_path / "audit.jsonl").exists()

    def test_record_contains_required_fields(self, tmp_audit, tmp_path):
        tmp_audit.record(make_intent(), make_decision())
        entry = json.loads((tmp_path / "audit.jsonl").read_text().strip())
        for field in ("ts", "action_id", "actor_id", "action_type", "verdict", "reason", "risk_level"):
            assert field in entry, f"Missing field: {field}"

    def test_record_does_not_log_parameter_values(self, tmp_audit, tmp_path):
        """Parameters may contain secrets — values must never appear in audit log."""
        intent = make_intent(parameters={"password": "super_secret_123", "token": "sk-test-xyz"})
        tmp_audit.record(intent, make_decision())
        raw = (tmp_path / "audit.jsonl").read_text()
        assert "super_secret_123" not in raw
        assert "sk-test-xyz" not in raw

    def test_record_does_not_log_full_parameters_key(self, tmp_audit, tmp_path):
        """The 'parameters' dict itself must not appear serialized."""
        intent = make_intent(parameters={"api_key": "secret"})
        tmp_audit.record(intent, make_decision())
        raw = (tmp_path / "audit.jsonl").read_text()
        assert '"parameters"' not in raw

    def test_metadata_keys_only_logged(self, tmp_audit, tmp_path):
        intent = make_intent(metadata={"context": "some_value", "session": "abc"})
        tmp_audit.record(intent, make_decision())
        entry = json.loads((tmp_path / "audit.jsonl").read_text().strip())
        assert "metadata_keys" in entry
        assert "some_value" not in json.dumps(entry)

    def test_multiple_records_append(self, tmp_audit, tmp_path):
        for i in range(3):
            tmp_audit.record(make_intent(target=f"/workspace/file_{i}.py"), make_decision())
        lines = (tmp_path / "audit.jsonl").read_text().strip().split("\n")
        assert len(lines) == 3

    def test_tail_returns_last_n(self, tmp_audit):
        for i in range(5):
            tmp_audit.record(make_intent(target=f"/workspace/f{i}.py"), make_decision())
        entries = tmp_audit.tail(3)
        assert len(entries) == 3

    def test_audit_records_correct_verdict(self, tmp_audit, tmp_path):
        tmp_audit.record(make_intent(), make_decision(verdict=VerifierVerdict.DENY, reason="blocked"))
        entry = json.loads((tmp_path / "audit.jsonl").read_text().strip())
        assert entry["verdict"] == "deny"

    def test_tail_empty_log_returns_empty(self, tmp_path):
        audit = VerifierAuditLog(log_path=tmp_path / "no_file.jsonl")
        assert audit.tail() == []

    def test_record_returns_audit_ref(self, tmp_audit):
        ref = tmp_audit.record(make_intent(), make_decision())
        assert ref  # non-empty string
