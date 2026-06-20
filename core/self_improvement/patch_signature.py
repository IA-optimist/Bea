"""Patch signing — ed25519 implementation.

Signs and verifies candidate patches using ed25519 asymmetric cryptography.
Keys are loaded from environment variables (never from source control):
  BEA_PATCH_SIGNING_KEY — PEM-encoded private key, base64-wrapped (for env compat)
  BEA_PATCH_VERIFY_KEY  — PEM-encoded public key, base64-wrapped

If BEA_PATCH_SIGNING_KEY is not set, sign_patch() raises SignatureError.
If BEA_PATCH_VERIFY_KEY is not set, verify_patch_signature() logs a warning and
returns True (dev/CI mode — no key pinned yet).  When the env var IS set,
verification is strict: any tamper or wrong-key raises SignatureError.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import json
import os
from typing import TYPE_CHECKING, Any

try:
    import structlog
    _log = structlog.get_logger("core.self_improvement.patch_signature")
except Exception:
    import logging
    _log = logging.getLogger("core.self_improvement.patch_signature")  # type: ignore[assignment]

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
    load_pem_public_key,
)

if TYPE_CHECKING:
    from core.self_improvement.promotion_pipeline import CandidatePatch

# ── Public API names kept for backward compat (old alias) ────────────────────
PATCH_SIGNATURE_ALGORITHM = "ed25519"


class SignatureError(Exception):
    """Raised when patch signature creation or verification fails."""


# Backward-compat alias used by existing code
PatchSignatureError = SignatureError


# ── Key generation ────────────────────────────────────────────────────────────

def generate_keypair() -> tuple[bytes, bytes]:
    """Generate a fresh ed25519 keypair.

    Returns:
        (private_pem, public_pem) — both as PEM-encoded bytes.
    """
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=Encoding.PEM,
        format=PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


# ── Key loading from environment ──────────────────────────────────────────────

def load_signing_key() -> bytes | None:
    """Load the private signing key from BEA_PATCH_SIGNING_KEY.

    The env var must hold the PEM bytes encoded as base64 (makes it safe to
    store in .env files without quoting issues).  Returns None if not set.
    """
    raw = os.getenv("BEA_PATCH_SIGNING_KEY")
    if not raw:
        return None
    try:
        return base64.b64decode(raw.strip())
    except Exception as exc:
        raise SignatureError(
            f"BEA_PATCH_SIGNING_KEY is set but not valid base64: {exc}"
        ) from exc


def load_verification_key() -> bytes | None:
    """Load the public verification key from BEA_PATCH_VERIFY_KEY.

    The env var must hold the PEM bytes encoded as base64.  Returns None if
    not set (dev mode — verification is skipped with a warning).
    """
    raw = os.getenv("BEA_PATCH_VERIFY_KEY")
    if not raw:
        return None
    try:
        return base64.b64decode(raw.strip())
    except Exception as exc:
        raise SignatureError(
            f"BEA_PATCH_VERIFY_KEY is set but not valid base64: {exc}"
        ) from exc


# ── Content canonicalisation ──────────────────────────────────────────────────

def _canonical_bytes(content: "str | dict | CandidatePatch") -> bytes:
    """Produce a stable byte representation for signing.

    - dict  → JSON with sorted keys, no whitespace
    - str   → UTF-8 encoded
    - CandidatePatch → to_dict() then JSON
    """
    if isinstance(content, str):
        return content.encode("utf-8")
    if isinstance(content, dict):
        return json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
    # CandidatePatch or any object with to_dict()
    try:
        d = content.to_dict()
    except AttributeError:
        d = {"patch_id": getattr(content, "patch_id", ""), "files": getattr(content, "files", [])}
    return json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_hex(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


# ── Core sign / verify ────────────────────────────────────────────────────────

def sign_patch(
    candidate: "str | dict | CandidatePatch",
    private_key_pem: bytes | None = None,
) -> dict[str, Any]:
    """Sign a patch and return a signature envelope.

    Args:
        candidate: The patch content — a CandidatePatch, a dict, or a str.
        private_key_pem: PEM-encoded ed25519 private key bytes.  If omitted,
            falls back to BEA_PATCH_SIGNING_KEY env var.

    Returns:
        dict with keys: algorithm, signature (base64), content_hash, signed_at.

    Raises:
        SignatureError: if no key is available or signing fails.
    """
    if private_key_pem is None:
        private_key_pem = load_signing_key()
    if not private_key_pem:
        raise SignatureError(
            "No signing key available — set BEA_PATCH_SIGNING_KEY (base64-encoded PEM) "
            "or pass private_key_pem explicitly."
        )

    try:
        private_key: Ed25519PrivateKey = load_pem_private_key(private_key_pem, password=None)  # type: ignore[assignment]
    except Exception as exc:
        raise SignatureError(f"Failed to load private key: {exc}") from exc

    content_bytes = _canonical_bytes(candidate)
    content_hash = _sha256_hex(content_bytes)

    try:
        raw_sig = private_key.sign(content_bytes)
    except Exception as exc:
        raise SignatureError(f"ed25519 signing failed: {exc}") from exc

    return {
        "algorithm": PATCH_SIGNATURE_ALGORITHM,
        "signature": base64.b64encode(raw_sig).decode("ascii"),
        "content_hash": content_hash,
        "signed_at": datetime.datetime.utcnow().isoformat() + "Z",
    }


def verify_patch_signature(
    candidate: "str | dict | CandidatePatch",
    signature_data: dict[str, Any],
    public_key_pem: bytes | None = None,
) -> bool:
    """Verify an ed25519 signature against a patch.

    Args:
        candidate: The patch content to verify.
        signature_data: The envelope returned by sign_patch().
        public_key_pem: PEM-encoded ed25519 public key bytes.  If omitted,
            falls back to BEA_PATCH_VERIFY_KEY env var.

    Returns:
        True if the signature is valid.

    Raises:
        SignatureError: if the signature is missing, malformed, or invalid.
    """
    if public_key_pem is None:
        public_key_pem = load_verification_key()
    if not public_key_pem:
        _log.warning(
            "patch_signature_no_verify_key",
            msg="BEA_PATCH_VERIFY_KEY not set — skipping signature verification (dev mode)",
        )
        return True

    algorithm = signature_data.get("algorithm", "")
    if algorithm != PATCH_SIGNATURE_ALGORITHM:
        raise SignatureError(
            f"Unsupported signature algorithm: {algorithm!r} (expected 'ed25519')"
        )

    sig_b64 = signature_data.get("signature", "")
    if not sig_b64 or sig_b64 == "UNSIGNED":
        raise SignatureError("Patch has no valid signature (UNSIGNED or missing)")

    try:
        raw_sig = base64.b64decode(sig_b64)
    except Exception as exc:
        raise SignatureError(f"Malformed signature base64: {exc}") from exc

    try:
        public_key: Ed25519PublicKey = load_pem_public_key(public_key_pem)  # type: ignore[assignment]
    except Exception as exc:
        raise SignatureError(f"Failed to load public key: {exc}") from exc

    content_bytes = _canonical_bytes(candidate)

    # Verify content hash if present (extra integrity check)
    claimed_hash = signature_data.get("content_hash", "")
    if claimed_hash:
        actual_hash = _sha256_hex(content_bytes)
        if actual_hash != claimed_hash:
            raise SignatureError(
                f"Content hash mismatch: expected {claimed_hash!r}, got {actual_hash!r}"
            )

    try:
        public_key.verify(raw_sig, content_bytes)
    except Exception as exc:
        raise SignatureError(f"Signature verification failed: {exc}") from exc

    return True
