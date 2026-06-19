"""Patch signing tests — contract first."""
from __future__ import annotations

import pytest
from pytest import MonkeyPatch

from core.self_improvement.patch_signature import (
    PATCH_SIGNATURE_ALGORITHM,
    PatchSignatureError,
    sign_patch,
    verify_patch_signature,
)
from core.self_improvement.promotion_pipeline import CandidatePatch, PatchIntent


def test_sign_patch_returns_deterministic_envelope(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("BEA_PATCH_SIGNING_KEY", "test-signing-key-32-bytes-long")
    candidate = CandidatePatch(
        patch_id="test-123",
        intents=[PatchIntent(file_path="core/coding_agent/repo_map.py", old_text="x", new_text="y")],
    )
    envelope = sign_patch(candidate)

    assert envelope["algorithm"] == PATCH_SIGNATURE_ALGORITHM
    assert isinstance(envelope["signature"], str)
    assert len(envelope["signature"]) > 80
    assert envelope["patch_id"] == "test-123"
    assert envelope["key_id"]


def test_verify_patch_signature_accepts_matching_key(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("BEA_PATCH_SIGNING_KEY", "test-signing-key-32-bytes-long")
    candidate = CandidatePatch(
        patch_id="test-123",
        intents=[PatchIntent(file_path="core/coding_agent/repo_map.py", old_text="x", new_text="y")],
    )
    envelope = sign_patch(candidate)

    assert verify_patch_signature(candidate, envelope)


def test_verify_patch_signature_rejects_mismatch(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("BEA_PATCH_SIGNING_KEY", "test-signing-key-32-bytes-long")
    candidate = CandidatePatch(patch_id="test-123")
    envelope = sign_patch(candidate)

    monkeypatch.setenv("BEA_PATCH_SIGNING_KEY", "different-signing-key-32-bytes")
    assert verify_patch_signature(candidate, envelope) is False


def test_sign_patch_requires_key(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("BEA_PATCH_SIGNING_KEY", raising=False)
    with pytest.raises(PatchSignatureError):
        sign_patch(CandidatePatch(patch_id="test-123"))
