"""
JARVIS MAX — Identity Audit Logger
======================================
Audit trail for all identity operations.
Extends the same chained-hash pattern as Secret Vault audit.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


class IdentityAction:
    CREATE = "identity_created"
    UPDATE = "identity_updated"
    USE = "identity_used"
    LINK = "identity_linked"
    UNLINK = "identity_unlinked"
    ROTATE = "identity_rotated"
    REVOKE = "identity_revoked"
    DELETE = "identity_deleted"
    SESSION_START = "session_started"
    SESSION_END = "session_ended"
    DENIED = "identity_denied"


@dataclass
class IdentityAuditEntry:
    timestamp: float
    action: str
    identity_id: str
    actor: str
    target: str = ""        # Service/domain affected
    environment: str = ""
    result: str = "success"
    details: str = ""
    chain_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "ts": self.timestamp, "action": self.action,
            "identity_id": self.identity_id, "actor": self.actor,
            "target": self.target, "env": self.environment,
            "result": self.result, "details": self.details[:200],
            "chain": self.chain_hash[:16] if self.chain_hash else "",
        }


class IdentityAuditLog:
    """Append-only identity audit log with chain hashes."""

    def __init__(self, log_path: str | Path | None = None):
        self._entries: list[IdentityAuditEntry] = []
        self._last_hash = "IDENTITY_GENESIS"
        self._log_path = Path(log_path) if log_path else None

    def record(
        self,
        action: str,
        identity_id: str,
        actor: str,
        target: str = "",
        environment: str = "",
        result: str = "success",
        details: str = "",
    ) -> IdentityAuditEntry:
        chain_input = f"{self._last_hash}|{time.time()}|{action}|{identity_id}|{actor}"
        chain_hash = hashlib.sha256(chain_input.encode()).hexdigest()

        entry = IdentityAuditEntry(
            timestamp=time.time(), action=action,
            identity_id=identity_id, actor=actor,
            target=target, environment=environment,
            result=result, details=details[:200],
            chain_hash=chain_hash,
        )
        self._entries.append(entry)
        self._last_hash = chain_hash

        if self._log_path:
            self._append(entry)

        return entry

    def query(
        self,
        identity_id: str | None = None,
        action: str | None = None,
        actor: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        results = []
        for e in reversed(self._entries):
            if identity_id and e.identity_id != identity_id:
                continue
            if action and e.action != action:
                continue
            if actor and e.actor != actor:
                continue
            results.append(e.to_dict())
            if len(results) >= limit:
                break
        return results

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def _append(self, entry: IdentityAuditEntry) -> None:
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "a") as f:
                f.write(json.dumps(entry.to_dict(), separators=(",", ":")) + "\n")
        except Exception as e:
            logger.error(f"Identity audit persist failed: {e}")
