from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from agent_security.verifier.models import ActionIntent, VerifierDecision

_DEFAULT_AUDIT_PATH = Path("logs/verifier_audit.jsonl")
_lock = threading.Lock()


class VerifierAuditLog:
    """
    Append-only audit log for all Verifier decisions.

    CRITICAL: Agents must never write to this file directly.
    It is protected at the policy level (HALT on writes targeting audit log).
    Parameters are NEVER logged — they may contain secrets.
    """

    def __init__(self, log_path: Optional[Path] = None) -> None:
        self._path = log_path or _DEFAULT_AUDIT_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        intent: ActionIntent,
        decision: VerifierDecision,
        *,
        extra: Optional[dict] = None,
    ) -> str:
        """Append one audit entry. Returns audit_ref (file byte offset as string)."""
        entry = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "action_id": intent.action_id,
            "actor_id": intent.actor_id,
            "action_type": intent.action_type.value,
            "target": intent.target,
            "declared_scope": intent.declared_scope.value,
            "verdict": decision.verdict.value,
            "reason": decision.reason,
            "risk_level": decision.risk_level.value,
            "requires_human_approval": decision.requires_human_approval,
            # Only log parameter keys, never values (may contain secrets)
            "metadata_keys": list(intent.metadata.keys()) if intent.metadata else [],
        }

        with _lock:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            audit_ref = str(self._path.stat().st_size)

        return audit_ref

    def tail(self, n: int = 20) -> list[dict]:
        """Return last N log entries. Does not expose parameters."""
        if not self._path.exists():
            return []
        lines = self._path.read_text(encoding="utf-8").strip().split("\n")
        return [json.loads(line) for line in lines[-n:] if line]
