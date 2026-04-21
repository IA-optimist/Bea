"""Output validator — scrub secrets from command outputs before storage.

Détecte les patterns typiques de secrets (API keys, JWT, AWS creds, SSH keys,
passwords en clair, …) et renvoie une version sanitizée avec [REDACTED].

Usage :
    from executor.output_validator import validate_output, ValidationStatus

    r = validate_output(tool_output)
    if r.status == ValidationStatus.VALID:
        store(r.sanitized_output)
    else:
        alert(r.reason)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class ValidationStatus(Enum):
    VALID = "valid"
    SANITIZED = "sanitized"       # Secrets found & redacted
    SUSPICIOUS = "suspicious"     # Potentially malicious / corrupted
    EMPTY = "empty"
    TRUNCATED = "truncated"


@dataclass
class ValidationResult:
    status: ValidationStatus
    sanitized_output: str
    reason: Optional[str] = None
    secrets_found: int = 0


# Patterns ordonnés du plus spécifique au plus général.
_SECRET_PATTERNS = [
    # OpenAI / Anthropic / Stripe / GitHub / Generic
    (r"\bsk-[A-Za-z0-9_\-]{20,}\b", "OpenAI/Stripe API key"),
    (r"\bsk-or-v1-[A-Za-z0-9_\-]{20,}\b", "OpenRouter API key"),
    (r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b", "Anthropic API key"),
    (r"\bghp_[A-Za-z0-9]{30,}\b", "GitHub PAT"),
    (r"\bghs_[A-Za-z0-9]{30,}\b", "GitHub App token"),
    (r"\bjv-[A-Za-z0-9_\-]{20,}\b", "JarvisMax access token"),
    (r"\bxox[bpsa]-[A-Za-z0-9\-]{10,}\b", "Slack token"),
    (r"\bglpat-[A-Za-z0-9\-_]{20}\b", "GitLab PAT"),
    # AWS
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS access key"),
    (r"\baws_secret_access_key\s*[:=]\s*[A-Za-z0-9/+=]{40}\b", "AWS secret"),
    # JWT (3 dot-separated base64 chunks).
    (r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b", "JWT"),
    # Password-like keywords.
    (r"(?i)(password|passwd|secret|api[_-]?key|auth[_-]?token)\s*[:=]\s*[\'\"]([^\'\"]{8,})[\'\"]",
     "password/secret keyword"),
    # Bearer tokens in http headers.
    (r"(?i)(authorization|bearer)\s*[:=]\s*[\'\"]?([A-Za-z0-9_\-\.=]{20,})[\'\"]?",
     "bearer header"),
    # SSH private keys.
    (r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
     "SSH private key"),
]


def _scrub(text: str) -> tuple[str, int]:
    """Apply all patterns; return (sanitized_text, num_matches)."""
    sanitized = text
    count = 0
    for patt, _label in _SECRET_PATTERNS:
        new = re.sub(patt, "[REDACTED]", sanitized)
        if new != sanitized:
            count += 1
            sanitized = new
    return sanitized, count


# Max output length before truncation (protect logs/memory).
_MAX_OUTPUT_BYTES = 10 * 1024 * 1024   # 10 MB


def validate_output(text: str) -> ValidationResult:
    """Valide et sanitize un output de commande.

    Returns :
        ValidationResult avec status, sanitized_output, secrets_found.
    """
    if not text:
        return ValidationResult(ValidationStatus.EMPTY, sanitized_output="")
    if not text.strip():
        return ValidationResult(ValidationStatus.EMPTY, sanitized_output=text)

    truncated = False
    if len(text) > _MAX_OUTPUT_BYTES:
        text = text[:_MAX_OUTPUT_BYTES] + "\n…[TRUNCATED]…"
        truncated = True

    sanitized, count = _scrub(text)
    if count > 0:
        return ValidationResult(
            ValidationStatus.SANITIZED,
            sanitized_output=sanitized,
            reason=f"{count} secret(s) redacted",
            secrets_found=count,
        )
    if truncated:
        return ValidationResult(
            ValidationStatus.TRUNCATED,
            sanitized_output=sanitized,
            reason=f"output exceeded {_MAX_OUTPUT_BYTES} bytes",
        )
    return ValidationResult(ValidationStatus.VALID, sanitized_output=sanitized)


__all__ = ["ValidationStatus", "ValidationResult", "validate_output"]
