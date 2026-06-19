"""Patch signing placeholders.

Task 4 Step 4 of the consolidation roadmap requires cryptographic signatures for
auto-applied patches. This module establishes the contract today; the actual
crypto backend (ed25519 or RSA-PSS) is gated behind a feature flag until keys
and key management are ready.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.self_improvement.promotion_pipeline import CandidatePatch


class PatchSignatureError(Exception):
    """Raised when patch signature creation or verification fails."""


PATCH_SIGNATURE_ALGORITHM = "ed25519-placeholder"


def sign_patch(candidate: "CandidatePatch", private_key: str = "") -> dict[str, Any]:
    """Return a placeholder signature envelope for ``candidate``.

    When the real key infrastructure is ready, this will sign a canonical digest
    of ``candidate.patch_id``, ``candidate.files``, and the unified diff.
    """
    return {
        "algorithm": PATCH_SIGNATURE_ALGORITHM,
        "signature": "UNSIGNED",
        "patch_id": getattr(candidate, "patch_id", ""),
        "key_id": private_key[-8:] if private_key else "",
    }


def verify_patch_signature(
    candidate: "CandidatePatch",
    signature: dict[str, Any],
    public_key: str = "",
) -> bool:
    """Verify ``signature`` against ``candidate``.

    Currently raises NotImplementedError because the production signing backend
    is not wired yet. Once wired, this returns True only for valid signatures.
    """
    raise NotImplementedError(
        "verify_patch_signature backend not enabled; configure SIGNING_PUBLIC_KEY"
    )
