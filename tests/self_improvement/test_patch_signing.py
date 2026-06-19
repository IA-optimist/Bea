"""Patch signing tests — contract first."""
from __future__ import annotations

import pytest

from core.self_improvement.patch_signature import (
    PATCH_SIGNATURE_ALGORITHM,
    PatchSignatureError,
    sign_patch,
    verify_patch_signature,
)
from core.self_improvement.promotion_pipeline import CandidatePatch, PatchIntent


def test_sign_patch_returns_placeholder_envelope() -> None:
    candidate = CandidatePatch(
        patch_id="test-123",
        intents=[PatchIntent(file_path="core/coding_agent/repo_map.py", old_text="x", new_text="y")],
    )
    envelope = sign_patch(candidate, private_key="deadbeef")

    assert envelope["algorithm"] == PATCH_SIGNATURE_ALGORITHM
    assert envelope["signature"] == "UNSIGNED"
    assert envelope["patch_id"] == "test-123"


def test_verify_patch_signature_is_not_yet_enabled() -> None:
    candidate = CandidatePatch(patch_id="test-123")
    envelope = sign_patch(candidate)

    with pytest.raises(NotImplementedError):
        verify_patch_signature(candidate, envelope, public_key="pub")
