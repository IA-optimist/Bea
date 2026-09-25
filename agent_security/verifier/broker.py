from __future__ import annotations

"""
VerifierBroker — mandatory gateway between Béa and all real effectuors.

v0 STATUS: Interface complete. Effectuor wiring is PARTIAL — see INTEGRATION_STATUS.
Do NOT assume an action is truly executed just because ALLOW was granted;
check whether the effectuor is wired first.
"""

import logging
from typing import Any, Callable, Optional

try:
    import structlog
    _log = structlog.get_logger("bea.verifier.broker")
except ImportError:
    _log = logging.getLogger("bea.verifier.broker")  # type: ignore[assignment]

from agent_security.verifier.audit import VerifierAuditLog
from agent_security.verifier.exceptions import (
    VerifierDenied,
    VerifierHaltTriggered,
    VerifierHoldRequired,
    VerifierUnavailable,
)
from agent_security.verifier.models import ActionIntent, VerifierDecision, VerifierVerdict
from agent_security.verifier.policy import VerifierPolicy

# Transparent honesty about v0 wiring status
INTEGRATION_STATUS: dict[str, str] = {
    "filesystem_read": "INTERFACE_ONLY — effectuor not yet wired; broker enforces policy",
    "filesystem_write": "INTERFACE_ONLY — effectuor not yet wired; broker enforces policy",
    "network_request": "INTERFACE_ONLY — effectuor not yet wired; broker enforces policy",
    "api_call": "INTERFACE_ONLY — effectuor not yet wired; broker enforces policy",
    "send_message": "INTERFACE_ONLY — effectuor not yet wired; broker enforces policy",
    "exec_command": "BLOCKED_IN_V0 — always DENY",
    "self_modification": "BLOCKED_IN_V0 — always HOLD (human required)",
    "spawn_agent": "BLOCKED_IN_V0 — always HOLD (human required)",
    "modify_memory": "BLOCKED_IN_V0 — always HOLD (human required)",
    "modify_security_config": "BLOCKED_IN_V0 — always HALT",
}

EffectHandler = Callable[[ActionIntent], Any]


class VerifierBroker:
    """
    Mandatory broker for all effectful actions.

    Béa MUST use this broker — direct effectuor calls bypass all security controls.
    If the broker raises VerifierUnavailable, the action is refused (fail-closed).
    """

    def __init__(
        self,
        policy: Optional[VerifierPolicy] = None,
        audit: Optional[VerifierAuditLog] = None,
    ) -> None:
        self._policy = policy or VerifierPolicy()
        self._audit = audit or VerifierAuditLog()
        # None = not yet wired in v0
        self._effectuors: dict[str, Optional[EffectHandler]] = {
            k: None for k in INTEGRATION_STATUS
        }

    def register_effectuor(self, action_type: str, handler: EffectHandler) -> None:
        """Register a real effectuor. Only infrastructure layer should call this."""
        if action_type not in self._effectuors:
            raise ValueError(f"Unknown action_type: {action_type!r}")
        self._effectuors[action_type] = handler
        _log.info("effectuor.registered", action_type=action_type)  # type: ignore[call-arg]

    def execute(self, intent: ActionIntent) -> VerifierDecision:
        """
        Evaluate intent, audit it, then dispatch if ALLOW.

        Raises:
            VerifierDenied — action blocked
            VerifierHoldRequired — action needs human approval
            VerifierHaltTriggered — critical violation
            VerifierUnavailable — broker failure (fail-closed)
        """
        # Step 1: policy evaluation (never raises — always returns decision)
        try:
            decision = self._policy.evaluate(intent)
        except Exception as exc:
            _log.error("verifier.policy.failure", error=str(exc), action_id=intent.action_id)  # type: ignore[call-arg]
            raise VerifierUnavailable(f"policy evaluation failed: {exc}") from exc

        # Step 2: audit every decision before acting (audit failure = fail-closed)
        try:
            audit_ref = self._audit.record(intent, decision)
        except Exception as exc:
            _log.error("verifier.audit.failure", error=str(exc))  # type: ignore[call-arg]
            raise VerifierUnavailable(f"audit log failure (fail-closed): {exc}") from exc

        decision_with_ref = VerifierDecision(
            verdict=decision.verdict,
            reason=decision.reason,
            action_id=decision.action_id,
            risk_level=decision.risk_level,
            requires_human_approval=decision.requires_human_approval,
            audit_ref=audit_ref,
        )

        _log.info(  # type: ignore[call-arg]
            "verifier.decision",
            verdict=decision.verdict.value,
            action_type=intent.action_type.value,
            actor_id=intent.actor_id,
            action_id=intent.action_id,
        )

        # Step 3: dispatch
        if decision.verdict == VerifierVerdict.ALLOW:
            self._dispatch(intent, decision_with_ref)
            return decision_with_ref
        elif decision.verdict == VerifierVerdict.DENY:
            raise VerifierDenied(decision.reason, action_id=intent.action_id)
        elif decision.verdict == VerifierVerdict.HOLD:
            raise VerifierHoldRequired(decision.reason, action_id=intent.action_id)
        elif decision.verdict == VerifierVerdict.HALT:
            _log.critical(  # type: ignore[call-arg]
                "verifier.halt",
                reason=decision.reason,
                action_id=intent.action_id,
                actor_id=intent.actor_id,
            )
            raise VerifierHaltTriggered(decision.reason, action_id=intent.action_id)
        else:
            raise VerifierUnavailable(f"unknown verdict: {decision.verdict!r}")

    def _dispatch(self, intent: ActionIntent, decision: VerifierDecision) -> Any:
        handler = self._effectuors.get(intent.action_type.value)
        if handler is None:
            # v0: not wired — log warning, return None (ALLOW was already granted)
            _log.warning(  # type: ignore[call-arg]
                "verifier.effectuor.not_wired",
                action_type=intent.action_type.value,
                status=INTEGRATION_STATUS.get(intent.action_type.value, "UNKNOWN"),
                action_id=intent.action_id,
                note="TODO: wire real effectuor before this action is truly executed",
            )
            return None
        return handler(intent)

    def get_integration_status(self) -> dict[str, str]:
        """Transparency report — what is/isn't wired in v0."""
        return dict(INTEGRATION_STATUS)
