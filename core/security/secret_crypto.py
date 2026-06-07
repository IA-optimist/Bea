"""
BEA MAX — Secret Crypto Layer
===================================
Authenticated encryption for individual secrets.

Uses AES-256-GCM (AEAD) via the `cryptography` library.
Each secret gets a unique random nonce. Integrity verified on decrypt.

Master key derived from master password via PBKDF2-HMAC-SHA256 (600k iterations).

Zero new dependencies — uses only `cryptography` (already in Docker image).
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── Constants ──

SALT_SIZE = 32          # 256-bit salt
NONCE_SIZE = 12         # 96-bit GCM nonce (NIST recommendation)
KEY_SIZE = 32           # 256-bit AES key
TAG_SIZE = 16           # 128-bit GCM auth tag
KDF_ITERATIONS = 600_000  # PBKDF2 iterations (OWASP 2024 recommendation)


# ── Exceptions ──

class CryptoError(Exception):
    """Base crypto error — never includes secret material in message."""
    pass


class DecryptionError(CryptoError):
    """Decryption failed — wrong key or tampered ciphertext."""
    pass


class VaultLockedError(CryptoError):
    """Vault is locked — master key not available."""
    pass


# ── Key Derivation ──

def derive_master_key(password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    """
    Derive a 256-bit master key from a password using PBKDF2-HMAC-SHA256.
    Returns (key, salt). If salt is None, generates a new random salt.
    """
    if not password:
        raise CryptoError("Master password cannot be empty")

    if salt is None:
        salt = os.urandom(SALT_SIZE)

    try:
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=KEY_SIZE,
            salt=salt,
            iterations=KDF_ITERATIONS,
        )
        key = kdf.derive(password.encode("utf-8"))
        return key, salt

    except ImportError:
        # Fallback: stdlib hashlib PBKDF2
        key = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, KDF_ITERATIONS, dklen=KEY_SIZE
        )
        return key, salt


# ── Encryption / Decryption ──

@dataclass
class EncryptedPayload:
    """Encrypted secret payload with all material needed for decryption."""
    ciphertext: bytes       # AES-256-GCM encrypted data
    nonce: bytes            # 12-byte random nonce
    tag: bytes              # 16-byte authentication tag
    salt: bytes             # 32-byte KDF salt (for master key derivation)
    version: int = 1        # Format version for future migrations

    def to_b64(self) -> str:
        """Serialize to base64 string for storage."""
        # Format: version(1) || salt(32) || nonce(12) || tag(16) || ciphertext(N)
        blob = bytes([self.version]) + self.salt + self.nonce + self.tag + self.ciphertext
        return base64.b64encode(blob).decode("ascii")

    @classmethod
    def from_b64(cls, data: str) -> "EncryptedPayload":
        """Deserialize from base64 string."""
        try:
            blob = base64.b64decode(data)
        except Exception:
            raise CryptoError("Invalid base64 payload")

        if len(blob) < 1 + SALT_SIZE + NONCE_SIZE + TAG_SIZE + 1:
            raise CryptoError("Payload too short")

        version = blob[0]
        if version != 1:
            raise CryptoError(f"Unsupported payload version: {version}")

        offset = 1
        salt = blob[offset:offset + SALT_SIZE]
        offset += SALT_SIZE
        nonce = blob[offset:offset + NONCE_SIZE]
        offset += NONCE_SIZE
        tag = blob[offset:offset + TAG_SIZE]
        offset += TAG_SIZE
        ciphertext = blob[offset:]

        return cls(ciphertext=ciphertext, nonce=nonce, tag=tag, salt=salt, version=version)


def encrypt(plaintext: str, master_key: bytes, salt: bytes) -> EncryptedPayload:
    """
    Encrypt a secret with AES-256-GCM.
    Each call uses a unique random nonce.
    """
    if not plaintext:
        raise CryptoError("Cannot encrypt empty plaintext")

    nonce = os.urandom(NONCE_SIZE)

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        aesgcm = AESGCM(master_key)
        # GCM returns ciphertext || tag appended
        ct_with_tag = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        # Split: last 16 bytes are tag
        ciphertext = ct_with_tag[:-TAG_SIZE]
        tag = ct_with_tag[-TAG_SIZE:]

    except ImportError:
        raise CryptoError("cryptography library required for AES-256-GCM")

    return EncryptedPayload(
        ciphertext=ciphertext,
        nonce=nonce,
        tag=tag,
        salt=salt,
        version=1,
    )


def decrypt(payload: EncryptedPayload, master_key: bytes) -> str:
    """
    Decrypt a secret. Verifies integrity via GCM authentication tag.
    Raises DecryptionError on wrong key or tampered data.
    """
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        aesgcm = AESGCM(master_key)
        # Reconstruct ciphertext || tag
        ct_with_tag = payload.ciphertext + payload.tag
        plaintext_bytes = aesgcm.decrypt(payload.nonce, ct_with_tag, None)
        return plaintext_bytes.decode("utf-8")

    except ImportError:
        raise CryptoError("cryptography library required for AES-256-GCM")
    except Exception:
        # Never include key material in error messages
        raise DecryptionError("Decryption failed — wrong key or corrupted data")


# ── Secure Memory Wipe Helper ──

def secure_wipe(data: bytearray) -> None:
    """Best-effort wipe of sensitive data from memory."""
    for i in range(len(data)):
        data[i] = 0


# ── Key Fingerprint ──

def key_fingerprint(key: bytes) -> str:
    """
    Generate a safe fingerprint of a key for audit logging.
    Never logs the key itself.
    """
    h = hashlib.sha256(key).hexdigest()
    return f"kf:{h[:12]}"
