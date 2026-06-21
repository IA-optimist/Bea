"""Patch signing for self-improvement promotions.

The plan calls for cryptographic signatures on auto-applied patches. This
module signs the canonical patch payload with Ed25519 and verifies it against
the configured key material.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import TYPE_CHECKING, Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

if TYPE_CHECKING:
    from core.self_improvement.promotion_pipeline import CandidatePatch


class PatchSignatureError(Exception):
    """Raised when patch signature creation or verification fails."""


PATCH_SIGNATURE_ALGORITHM = "ed25519-canonical-json"
DEFAULT_SIGNATURE_ENV = "BEA_PATCH_SIGNING_KEY"
VERIFY_SIGNATURE_ENV = "BEA_PATCH_VERIFY_KEY"


def _payload(candidate: "CandidatePatch") -> dict[str, Any]:
    intents = []
    for intent in getattr(candidate, "intents", []):
        intents.append(
            {
                "file_path": getattr(intent, "file_path", ""),
                "old_text": getattr(intent, "old_text", ""),
                "new_text": getattr(intent, "new_text", ""),
            }
        )
    return {
        "patch_id": getattr(candidate, "patch_id", ""),
        "files": list(getattr(candidate, "files", [])),
        "intents": intents,
        "domain": getattr(candidate, "domain", ""),
        "description": getattr(candidate, "description", ""),
        "issue": getattr(candidate, "issue", ""),
    }


def _canonical_json(candidate: "CandidatePatch") -> bytes:
    return json.dumps(_payload(candidate), sort_keys=True, separators=(",", ":")).encode("utf-8")


def _seed(value: str | None = None) -> bytes:
    key = (value or os.getenv(DEFAULT_SIGNATURE_ENV, "")).strip()
    if not key:
        raise PatchSignatureError(f"missing signing key: set {DEFAULT_SIGNATURE_ENV}")
    return hashlib.sha256(key.encode("utf-8")).digest()


def _verify_seed(value: str | None = None) -> bytes:
    key = (value or os.getenv(VERIFY_SIGNATURE_ENV, "")).strip()
    if not key:
        raise PatchSignatureError(f"missing verify key: set {VERIFY_SIGNATURE_ENV}")
    return hashlib.sha256(key.encode("utf-8")).digest()


def _private_key(value: str | None = None) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(_seed(value))


def _public_key(value: str | None = None) -> Ed25519PublicKey:
    return Ed25519PrivateKey.from_private_bytes(_verify_seed(value)).public_key()


def sign_patch(candidate: "CandidatePatch", private_key: str = "") -> dict[str, Any]:
    """Return a signed envelope for ``candidate``."""
    key = _private_key(private_key)
    payload = _canonical_json(candidate)
    signature = key.sign(payload)
    public_key_bytes = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return {
        "algorithm": PATCH_SIGNATURE_ALGORITHM,
        "signature": base64.urlsafe_b64encode(signature).decode("ascii"),
        "patch_id": getattr(candidate, "patch_id", ""),
        "key_id": hashlib.sha256(public_key_bytes).hexdigest()[:12],
    }


def verify_patch_signature(
    candidate: "CandidatePatch",
    signature: dict[str, Any],
    public_key: str = "",
) -> bool:
    """Verify ``signature`` against ``candidate``."""
    key = _public_key(public_key)
    payload = _canonical_json(candidate)
    actual = str(signature.get("signature", "")).strip()
    algorithm = str(signature.get("algorithm", "")).strip()
    if algorithm != PATCH_SIGNATURE_ALGORITHM:
        raise PatchSignatureError(f"unsupported signature algorithm: {algorithm or 'missing'}")
    padded = actual + "=" * (-len(actual) % 4)
    try:
        key.verify(base64.urlsafe_b64decode(padded.encode("ascii")), payload)
    except Exception:
        return False
    return True
