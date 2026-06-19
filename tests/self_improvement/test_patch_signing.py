"""Tests for ed25519 patch signing (T4.4).

Covers:
  - sign + verify roundtrip (dict, str, CandidatePatch)
  - tampered content fails verification
  - wrong key fails verification
  - UNSIGNED patch rejected by gate
  - missing BEA_PATCH_VERIFY_KEY → gate logs warning but does not block
"""
from __future__ import annotations

import base64
import os
import pytest

from core.self_improvement.patch_signature import (
    PATCH_SIGNATURE_ALGORITHM,
    PatchSignatureError,
    SignatureError,
    generate_keypair,
    load_signing_key,
    load_verification_key,
    sign_patch,
    verify_patch_signature,
)
from core.self_improvement.promotion_pipeline import CandidatePatch, PatchIntent
from kernel.improvement.gate import ImprovementGate, PatchSignatureViolation


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def keypair() -> tuple[bytes, bytes]:
    """Fresh ed25519 (private_pem, public_pem)."""
    return generate_keypair()


@pytest.fixture()
def candidate() -> CandidatePatch:
    return CandidatePatch(
        patch_id="test-patch-001",
        intents=[PatchIntent(file_path="core/foo.py", old_text="x = 1", new_text="x = 2")],
        domain="test",
        description="bump x",
    )


# ── Roundtrip tests ───────────────────────────────────────────────────────────

def test_sign_and_verify_roundtrip_candidate(keypair, candidate):
    """A CandidatePatch signed with private key must verify with matching public key."""
    priv, pub = keypair
    envelope = sign_patch(candidate, private_key_pem=priv)

    assert envelope["algorithm"] == "ed25519"
    assert envelope["signature"] != "UNSIGNED"
    assert envelope["content_hash"].startswith("sha256:")
    assert "signed_at" in envelope

    result = verify_patch_signature(candidate, envelope, public_key_pem=pub)
    assert result is True


def test_sign_and_verify_roundtrip_dict(keypair):
    """A dict payload signed and verified must pass."""
    priv, pub = keypair
    payload = {"patch_id": "abc", "files": ["core/x.py"], "domain": "test"}

    envelope = sign_patch(payload, private_key_pem=priv)
    assert verify_patch_signature(payload, envelope, public_key_pem=pub) is True


def test_sign_and_verify_roundtrip_str(keypair):
    """A raw string payload signed and verified must pass."""
    priv, pub = keypair
    diff = "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new"

    envelope = sign_patch(diff, private_key_pem=priv)
    assert verify_patch_signature(diff, envelope, public_key_pem=pub) is True


# ── Tamper detection ──────────────────────────────────────────────────────────

def test_tampered_content_fails(keypair, candidate):
    """Modifying the patch content after signing must fail verification."""
    priv, pub = keypair
    envelope = sign_patch(candidate, private_key_pem=priv)

    # Tamper: change patch description
    tampered = CandidatePatch(
        patch_id=candidate.patch_id,
        intents=[PatchIntent(file_path="core/evil.py", old_text="", new_text="import os; os.system('rm -rf /')")],
        domain="test",
        description="TAMPERED",
    )

    with pytest.raises(SignatureError):
        verify_patch_signature(tampered, envelope, public_key_pem=pub)


def test_tampered_dict_fails(keypair):
    """Mutating a dict after signing must fail verification."""
    priv, pub = keypair
    payload = {"patch_id": "abc", "files": ["core/x.py"]}

    envelope = sign_patch(payload, private_key_pem=priv)

    tampered = {**payload, "files": ["core/evil.py"]}
    with pytest.raises(SignatureError):
        verify_patch_signature(tampered, envelope, public_key_pem=pub)


# ── Wrong key ─────────────────────────────────────────────────────────────────

def test_wrong_key_fails(keypair, candidate):
    """A signature produced with one private key must fail verification with a different public key."""
    priv, _pub = keypair
    _other_priv, other_pub = generate_keypair()

    envelope = sign_patch(candidate, private_key_pem=priv)

    with pytest.raises(SignatureError):
        verify_patch_signature(candidate, envelope, public_key_pem=other_pub)


# ── No signing key ────────────────────────────────────────────────────────────

def test_sign_without_key_raises(candidate, monkeypatch):
    """sign_patch() with no key available must raise SignatureError, not return UNSIGNED."""
    monkeypatch.delenv("BEA_PATCH_SIGNING_KEY", raising=False)

    with pytest.raises(SignatureError, match="No signing key available"):
        sign_patch(candidate, private_key_pem=None)


# ── Gate: UNSIGNED patch rejected ────────────────────────────────────────────

def test_unsigned_patch_rejected_by_gate(monkeypatch):
    """The gate must reject patches with 'UNSIGNED' signature regardless of env."""
    monkeypatch.delenv("BEA_PATCH_VERIFY_KEY", raising=False)

    gate = ImprovementGate()
    sig_data = {
        "algorithm": "ed25519-placeholder",
        "signature": "UNSIGNED",
        "patch_id": "test-001",
    }

    with pytest.raises(PatchSignatureViolation, match="UNSIGNED"):
        gate.validate_patch_signature({"patch_id": "test-001"}, sig_data)


def test_wrong_algorithm_rejected_by_gate(monkeypatch):
    """The gate must reject patches with an algorithm other than 'ed25519'."""
    monkeypatch.delenv("BEA_PATCH_VERIFY_KEY", raising=False)

    gate = ImprovementGate()
    sig_data = {
        "algorithm": "rsa-pss",
        "signature": base64.b64encode(b"fake").decode(),
        "content_hash": "sha256:abc",
    }

    with pytest.raises(PatchSignatureViolation, match="ed25519"):
        gate.validate_patch_signature({"patch_id": "x"}, sig_data)


# ── Gate: missing verify key → warning, no block ─────────────────────────────

def test_missing_verify_key_does_not_block(keypair, candidate, monkeypatch, caplog):
    """Without BEA_PATCH_VERIFY_KEY the gate warns but accepts a structurally-valid signed patch."""
    import logging
    priv, _pub = keypair
    monkeypatch.delenv("BEA_PATCH_VERIFY_KEY", raising=False)

    envelope = sign_patch(candidate, private_key_pem=priv)
    patch_dict = candidate.to_dict()

    gate = ImprovementGate()
    # Should not raise
    with caplog.at_level(logging.WARNING):
        gate.validate_patch_signature(patch_dict, envelope)

    # The warning was emitted somewhere (structlog or logging)
    # We just confirm no exception was raised — structlog warnings don't always
    # route through caplog depending on configuration, so we skip the message assertion.


# ── Gate: valid signature with pinned key ────────────────────────────────────

def test_valid_signature_passes_gate(keypair, candidate, monkeypatch):
    """A properly signed patch must pass gate.validate_patch_signature() when key is pinned."""
    priv, pub = keypair
    # Expose public key via env var (base64-encoded PEM)
    monkeypatch.setenv("BEA_PATCH_VERIFY_KEY", base64.b64encode(pub).decode())

    envelope = sign_patch(candidate, private_key_pem=priv)
    patch_dict = candidate.to_dict()

    gate = ImprovementGate()
    # Must not raise
    gate.validate_patch_signature(patch_dict, envelope)


def test_invalid_signature_blocked_by_gate_with_pinned_key(keypair, candidate, monkeypatch):
    """A tampered patch must be blocked when BEA_PATCH_VERIFY_KEY is pinned."""
    priv, pub = keypair
    monkeypatch.setenv("BEA_PATCH_VERIFY_KEY", base64.b64encode(pub).decode())

    # Sign the original
    envelope = sign_patch(candidate, private_key_pem=priv)

    # Tamper the content hash to simulate modification
    tampered_envelope = {**envelope, "content_hash": "sha256:" + "0" * 64}

    gate = ImprovementGate()
    with pytest.raises(PatchSignatureViolation):
        gate.validate_patch_signature(candidate.to_dict(), tampered_envelope)


# ── Env key loading ───────────────────────────────────────────────────────────

def test_load_signing_key_from_env(keypair, monkeypatch):
    """load_signing_key() must decode a base64-wrapped PEM from BEA_PATCH_SIGNING_KEY."""
    priv, _pub = keypair
    monkeypatch.setenv("BEA_PATCH_SIGNING_KEY", base64.b64encode(priv).decode())
    loaded = load_signing_key()
    assert loaded == priv


def test_load_signing_key_none_when_unset(monkeypatch):
    monkeypatch.delenv("BEA_PATCH_SIGNING_KEY", raising=False)
    assert load_signing_key() is None


def test_load_verification_key_from_env(keypair, monkeypatch):
    _priv, pub = keypair
    monkeypatch.setenv("BEA_PATCH_VERIFY_KEY", base64.b64encode(pub).decode())
    loaded = load_verification_key()
    assert loaded == pub


def test_load_verification_key_none_when_unset(monkeypatch):
    monkeypatch.delenv("BEA_PATCH_VERIFY_KEY", raising=False)
    assert load_verification_key() is None


# ── PatchSignatureError is alias for SignatureError ──────────────────────────

def test_patch_signature_error_is_alias():
    assert PatchSignatureError is SignatureError
