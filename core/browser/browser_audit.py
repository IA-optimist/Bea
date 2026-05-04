"""
JARVIS MAX — Browser Audit Logger
=====================================
Immutable audit trail for all browser actions.
Sensitive data (passwords, tokens) is NEVER logged.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Patterns to redact from audit entries
REDACT_PATTERNS = [
    (re.compile(r"(password|passwd|pwd|secret|token|key|auth)\s*[:=]\s*\S+", re.I), r"\1=***REDACTED***"),
    (re.compile(r"(sk-|ghp_|gho_|xoxb-|xoxp-)\S+"), "***REDACTED_TOKEN***"),
    (re.compile(r"Bearer\s+\S+"), "Bearer ***REDACTED***"),
]


def redact(text: str) -> str:
    """Remove sensitive patterns from text."""
    for pattern, replacement in REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


@dataclass
class BrowserAuditEntry:
    timestamp: float
    session_id: str
    actor: str
    action: str
    target: str = ""
    domain: str = ""
    result: str = "success"
    approval_state: str = ""     # "", "approved", "denied", "pending"
    details: str = ""
    chain_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "ts": self.timestamp, "session": self.session_id,
            "actor": self.actor, "action": self.action,
            "target": redact(self.target[:200]),
            "domain": self.domain, "result": self.result,
            "approval": self.approval_state,
            "details": redact(self.details[:300]),
            "chain": self.chain_hash[:16] if self.chain_hash else "",
        }


class BrowserAuditLog:
    """Append-only browser action audit."""

    def __init__(self, log_path: str | Path | None = None):
        self._entries: list[BrowserAuditEntry] = []
        self._last_hash = "BROWSER_GENESIS"
        self._log_path = Path(log_path) if log_path else None

    def record(
        self,
        session_id: str,
        actor: str,
        action: str,
        target: str = "",
        domain: str = "",
        result: str = "success",
        approval_state: str = "",
        details: str = "",
    ) -> BrowserAuditEntry:
        chain_input = f"{self._last_hash}|{time.time()}|{action}|{session_id}"
        chain_hash = hashlib.sha256(chain_input.encode()).hexdigest()

        entry = BrowserAuditEntry(
            timestamp=time.time(), session_id=session_id,
            actor=actor, action=action,
            target=redact(target[:200]), domain=domain,
            result=result, approval_state=approval_state,
            details=redact(details[:300]),
            chain_hash=chain_hash,
        )
        self._entries.append(entry)
        self._last_hash = chain_hash

        if self._log_path:
            self._append(entry)
        return entry

    def query(
        self,
        session_id: str | None = None,
        action: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        results = []
        for e in reversed(self._entries):
            if session_id and e.session_id != session_id:
                continue
            if action and e.action != action:
                continue
            results.append(e.to_dict())
            if len(results) >= limit:
                break
        return results

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def _append(self, entry: BrowserAuditEntry) -> None:
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "a") as f:
                f.write(json.dumps(entry.to_dict(), separators=(",", ":")) + "\n")
        except Exception as e:
            logger.error(f"Browser audit persist failed: {e}")
