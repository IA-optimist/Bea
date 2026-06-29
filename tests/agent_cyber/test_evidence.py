from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_cyber.evidence import (
    Claim,
    ClaimStatus,
    ClaimType,
    Evidence,
    EvidenceGate,
    EvidenceType,
)


def _evidence(etype: EvidenceType = EvidenceType.CODE_SNIPPET, **kwargs) -> Evidence:
    return Evidence(
        evidence_type=etype,
        source="test-source",
        content_summary="Some code snippet without secrets",
        confidence=0.9,
        **kwargs,
    )


def test_evidence_redacts_api_key_in_summary():
    e = Evidence(
        evidence_type=EvidenceType.CODE_SNIPPET,
        source="test",
        content_summary="API key is sk-abcdefghijklmnopqrstuvwxyz123456",
        confidence=0.5,
    )
    assert "sk-" not in e.content_summary or "[REDACTED" in e.content_summary


def test_evidence_redacts_bearer_token():
    e = Evidence(
        evidence_type=EvidenceType.CODE_SNIPPET,
        source="test",
        content_summary="Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc",
        confidence=0.5,
    )
    assert "REDACTED" in e.content_summary


def test_evidence_confidence_invalid_raises():
    with pytest.raises(ValidationError):
        Evidence(
            evidence_type=EvidenceType.CODE_SNIPPET,
            source="test",
            content_summary="ok",
            confidence=1.5,
        )


def test_evidence_confidence_negative_raises():
    with pytest.raises(ValidationError):
        Evidence(
            evidence_type=EvidenceType.CODE_SNIPPET,
            source="test",
            content_summary="ok",
            confidence=-0.1,
        )


def test_evidence_requires_source():
    with pytest.raises(ValidationError):
        Evidence(
            evidence_type=EvidenceType.CODE_SNIPPET,
            content_summary="ok",
            confidence=0.5,
        )


def test_claim_vuln_exists_no_evidence_unverified():
    gate = EvidenceGate()
    claim = Claim(
        claim_type=ClaimType.VULNERABILITY_EXISTS,
        content="Path traversal in download_file()",
        confidence=0.7,
    )
    result = gate.validate_claim(claim)
    assert result.status == ClaimStatus.UNVERIFIED


def test_claim_vuln_exists_with_evidence_verified():
    gate = EvidenceGate()
    ev = _evidence()
    gate.attach_evidence(ev)
    claim = Claim(
        claim_type=ClaimType.VULNERABILITY_EXISTS,
        content="SQL injection in get_user()",
        confidence=0.9,
        evidence_refs=[ev.evidence_id],
    )
    result = gate.validate_claim(claim)
    assert result.status == ClaimStatus.VERIFIED


def test_claim_test_passed_no_evidence_rejected():
    gate = EvidenceGate()
    claim = Claim(
        claim_type=ClaimType.TEST_PASSED,
        content="All tests pass",
        confidence=0.8,
    )
    result = gate.validate_claim(claim)
    assert result.status == ClaimStatus.REJECTED


def test_claim_test_passed_wrong_evidence_type_rejected():
    gate = EvidenceGate()
    ev = _evidence(etype=EvidenceType.CODE_SNIPPET)
    gate.attach_evidence(ev)
    claim = Claim(
        claim_type=ClaimType.TEST_PASSED,
        content="Tests pass",
        confidence=0.8,
        evidence_refs=[ev.evidence_id],
    )
    result = gate.validate_claim(claim)
    assert result.status == ClaimStatus.REJECTED


def test_claim_test_passed_with_test_output_verified():
    gate = EvidenceGate()
    ev = _evidence(etype=EvidenceType.TEST_OUTPUT)
    gate.attach_evidence(ev)
    claim = Claim(
        claim_type=ClaimType.TEST_PASSED,
        content="pytest 42 passed",
        confidence=0.95,
        evidence_refs=[ev.evidence_id],
    )
    result = gate.validate_claim(claim)
    assert result.status == ClaimStatus.VERIFIED


def test_claim_scope_authorized_no_evidence_rejected():
    gate = EvidenceGate()
    claim = Claim(
        claim_type=ClaimType.SCOPE_AUTHORIZED,
        content="Target is authorized",
        confidence=0.8,
    )
    result = gate.validate_claim(claim)
    assert result.status == ClaimStatus.REJECTED


def test_claim_scope_authorized_wrong_type_rejected():
    gate = EvidenceGate()
    ev = _evidence(etype=EvidenceType.CODE_SNIPPET)
    gate.attach_evidence(ev)
    claim = Claim(
        claim_type=ClaimType.SCOPE_AUTHORIZED,
        content="Authorized",
        confidence=0.9,
        evidence_refs=[ev.evidence_id],
    )
    result = gate.validate_claim(claim)
    assert result.status == ClaimStatus.REJECTED


def test_claim_scope_authorized_with_auth_evidence_verified():
    gate = EvidenceGate()
    ev = _evidence(etype=EvidenceType.USER_PROVIDED_AUTHORIZATION)
    gate.attach_evidence(ev)
    claim = Claim(
        claim_type=ClaimType.SCOPE_AUTHORIZED,
        content="Authorization confirmed",
        confidence=1.0,
        evidence_refs=[ev.evidence_id],
    )
    result = gate.validate_claim(claim)
    assert result.status == ClaimStatus.VERIFIED


def test_claim_with_nonexistent_evidence_ref_rejected():
    gate = EvidenceGate()
    claim = Claim(
        claim_type=ClaimType.VULNERABILITY_EXISTS,
        content="Something",
        confidence=0.8,
        evidence_refs=["nonexistent-uuid-1234"],
    )
    result = gate.validate_claim(claim)
    assert result.status == ClaimStatus.REJECTED


def test_claim_fix_valid_with_code_snippet_verified():
    gate = EvidenceGate()
    ev = _evidence(etype=EvidenceType.CODE_SNIPPET)
    gate.attach_evidence(ev)
    claim = Claim(
        claim_type=ClaimType.FIX_VALID,
        content="Use parameterized queries",
        confidence=0.85,
        evidence_refs=[ev.evidence_id],
    )
    result = gate.validate_claim(claim)
    assert result.status == ClaimStatus.VERIFIED


def test_claim_fix_valid_no_evidence_unverified():
    gate = EvidenceGate()
    claim = Claim(
        claim_type=ClaimType.FIX_VALID,
        content="Use parameterized queries",
        confidence=0.6,
    )
    result = gate.validate_claim(claim)
    assert result.status == ClaimStatus.UNVERIFIED
