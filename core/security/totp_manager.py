"""
BEA MAX — TOTP Manager
============================
RFC 6238 TOTP implementation — zero external dependencies.

Stores TOTP seeds encrypted in the vault.
Generates time-based one-time passwords on demand.
Supports standard 6/8-digit codes with 30s/60s periods.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time
from dataclasses import dataclass


@dataclass
class TOTPConfig:
    """TOTP configuration for a secret."""
    digits: int = 6          # 6 or 8
    period: int = 30         # seconds
    algorithm: str = "sha1"  # sha1, sha256, sha512
    issuer: str = ""
    account: str = ""

    def to_dict(self) -> dict:
        return {
            "digits": self.digits, "period": self.period,
            "algorithm": self.algorithm,
            "issuer": self.issuer, "account": self.account,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TOTPConfig":
        return cls(
            digits=data.get("digits", 6),
            period=data.get("period", 30),
            algorithm=data.get("algorithm", "sha1"),
            issuer=data.get("issuer", ""),
            account=data.get("account", ""),
        )


def decode_seed(seed: str) -> bytes:
    """
    Decode a TOTP seed from base32 (standard format from QR codes).
    Handles padding and whitespace.
    """
    # Clean input
    clean = seed.upper().replace(" ", "").replace("-", "")
    # Add padding if needed
    padding = (8 - len(clean) % 8) % 8
    clean += "=" * padding
    return base64.b32decode(clean)


def generate_totp(
    seed_bytes: bytes,
    timestamp: float | None = None,
    digits: int = 6,
    period: int = 30,
    algorithm: str = "sha1",
) -> str:
    """
    Generate a TOTP code per RFC 6238.
    
    Args:
        seed_bytes: Decoded TOTP secret
        timestamp: Unix timestamp (defaults to now)
        digits: Number of digits (6 or 8)
        period: Time step in seconds
        algorithm: Hash algorithm (sha1, sha256, sha512)
    
    Returns:
        Zero-padded TOTP code string
    """
    if timestamp is None:
        timestamp = time.time()

    # Time counter
    counter = int(timestamp) // period

    # Counter as 8-byte big-endian
    counter_bytes = struct.pack(">Q", counter)

    # HMAC
    hash_algo = {
        "sha1": hashlib.sha1,
        "sha256": hashlib.sha256,
        "sha512": hashlib.sha512,
    }.get(algorithm, hashlib.sha1)

    mac = hmac.new(seed_bytes, counter_bytes, hash_algo).digest()

    # Dynamic truncation (RFC 4226)
    offset = mac[-1] & 0x0F
    code_int = struct.unpack(">I", mac[offset:offset + 4])[0]
    code_int &= 0x7FFFFFFF  # Clear sign bit
    code_int %= 10 ** digits

    return str(code_int).zfill(digits)


def time_remaining(period: int = 30) -> int:
    """Seconds remaining until current TOTP code expires."""
    return period - (int(time.time()) % period)


def verify_totp(
    seed_bytes: bytes,
    code: str,
    digits: int = 6,
    period: int = 30,
    algorithm: str = "sha1",
    window: int = 1,
) -> bool:
    """
    Verify a TOTP code with a time window.
    
    Args:
        window: Number of periods to check before/after current time.
                window=1 checks [-30s, now, +30s].
    """
    now = time.time()
    for offset in range(-window, window + 1):
        ts = now + (offset * period)
        expected = generate_totp(seed_bytes, ts, digits, period, algorithm)
        if hmac.compare_digest(code, expected):
            return True
    return False


def generate_seed(length: int = 20) -> tuple[str, bytes]:
    """
    Generate a new random TOTP seed.
    Returns (base32_encoded_string, raw_bytes).
    """
    import os
    raw = os.urandom(length)
    b32 = base64.b32encode(raw).decode("ascii").rstrip("=")
    return b32, raw


def build_otpauth_uri(
    seed_b32: str,
    account: str = "",
    issuer: str = "BeaMax",
    digits: int = 6,
    period: int = 30,
    algorithm: str = "sha1",
) -> str:
    """Build an otpauth:// URI for QR code generation."""
    from urllib.parse import quote
    label = f"{issuer}:{account}" if account else issuer
    params = f"secret={seed_b32}&issuer={quote(issuer)}&digits={digits}&period={period}&algorithm={algorithm.upper()}"
    return f"otpauth://totp/{quote(label)}?{params}"
