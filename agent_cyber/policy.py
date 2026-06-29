from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

import structlog

from agent_cyber.actions import ALLOWED_ACTION_NAMES, BLOCKED_ACTION_NAMES
from agent_cyber.scope import AuthorizationStatus, CyberScopePolicy, RiskLevel

log = structlog.get_logger("bea.cyber.guard")

CYBER_CAPABILITIES: frozenset[str] = frozenset({
    "cyber.code_review",
    "cyber.dependency_audit",
    "cyber.secret_scan",
    "cyber.config_review",
    "cyber.auth_review",
    "cyber.report",
    "cyber.fix_proposal",
    "cyber.regression_tests",
    "cyber.external_target_readonly",
})

_MODIFYING_ACTIONS: frozenset[str] = frozenset({
    "propose_fix",
    "generate_regression_tests",
})

_LOCAL_TARGETS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"})


@dataclass
class CyberPolicyDecision:
    allowed: bool
    reason: str
    required_approval: bool = False
    risk_level: str = "low"
    blocked_by: Optional[str] = None
    audit_ref: str = field(default_factory=lambda: str(uuid.uuid4()))


class CyberActionGuard:
    """Central guard — ALL cyber actions pass through here. Deny-by-default."""

    APPROVAL_RISK_THRESHOLD: tuple[str, ...] = (RiskLevel.HIGH.value, RiskLevel.CRITICAL.value)

    def validate(
        self,
        action: str,
        scope: Optional[CyberScopePolicy],
        target: Optional[str] = None,
        capability: Optional[str] = None,
    ) -> CyberPolicyDecision:
        """Returns decision. Logs every decision for audit trail."""
        audit_ref = str(uuid.uuid4())

        # 1. Scope check
        if scope is None:
            decision = CyberPolicyDecision(
                allowed=False,
                reason="No scope provided — deny-by-default",
                blocked_by="missing_scope",
                audit_ref=audit_ref,
            )
            log.warning("cyber.guard.block", reason=decision.reason, action=action, audit_ref=audit_ref)
            return decision

        if scope.is_expired:
            decision = CyberPolicyDecision(
                allowed=False,
                reason=f"Scope {scope.scope_id} has expired",
                blocked_by="expired_scope",
                audit_ref=audit_ref,
            )
            log.warning("cyber.guard.block", reason=decision.reason, action=action, audit_ref=audit_ref)
            return decision

        # 2. Action check — blocked actions hard-denied
        if action in BLOCKED_ACTION_NAMES:
            decision = CyberPolicyDecision(
                allowed=False,
                reason=f"Action '{action}' is permanently blocked in v1",
                blocked_by="blocked_action",
                audit_ref=audit_ref,
            )
            log.error("cyber.guard.blocked_action", action=action, audit_ref=audit_ref)
            return decision

        if action not in ALLOWED_ACTION_NAMES:
            decision = CyberPolicyDecision(
                allowed=False,
                reason=f"Action '{action}' is not in the allowed actions list",
                blocked_by="unknown_action",
                audit_ref=audit_ref,
            )
            log.warning("cyber.guard.block", reason=decision.reason, action=action, audit_ref=audit_ref)
            return decision

        # 3. Scope-level action block
        if action in scope.blocked_actions:
            decision = CyberPolicyDecision(
                allowed=False,
                reason=f"Action '{action}' is blocked by scope policy",
                blocked_by="scope_blocked_action",
                audit_ref=audit_ref,
            )
            log.warning("cyber.guard.block", reason=decision.reason, action=action, audit_ref=audit_ref)
            return decision

        # 4. Capability check
        if capability is not None and capability not in CYBER_CAPABILITIES:
            decision = CyberPolicyDecision(
                allowed=False,
                reason=f"Capability '{capability}' is not in CYBER_CAPABILITIES",
                blocked_by="unknown_capability",
                audit_ref=audit_ref,
            )
            log.warning("cyber.guard.block", reason=decision.reason, action=action, audit_ref=audit_ref)
            return decision

        # 5. External target authorization
        if target is not None:
            is_external = target not in _LOCAL_TARGETS and not target.startswith("local:")
            if is_external and scope.authorization_status != AuthorizationStatus.EXPLICIT:
                decision = CyberPolicyDecision(
                    allowed=False,
                    reason=f"External target '{target}' requires explicit authorization (got: {scope.authorization_status.value})",
                    blocked_by="missing_authorization",
                    audit_ref=audit_ref,
                )
                log.warning("cyber.guard.block", reason=decision.reason, action=action, audit_ref=audit_ref)
                return decision

        # 6. report_only check — modifying actions blocked
        if scope.report_only and action in _MODIFYING_ACTIONS:
            decision = CyberPolicyDecision(
                allowed=False,
                reason=f"Action '{action}' modifies code and scope.report_only=True",
                blocked_by="report_only",
                audit_ref=audit_ref,
            )
            log.warning("cyber.guard.block", reason=decision.reason, action=action, audit_ref=audit_ref)
            return decision

        # 7. Approval requirement
        required_approval = scope.risk_level.value in self.APPROVAL_RISK_THRESHOLD

        decision = CyberPolicyDecision(
            allowed=True,
            reason=f"Action '{action}' allowed by scope {scope.scope_id}",
            required_approval=required_approval,
            risk_level=scope.risk_level.value,
            audit_ref=audit_ref,
        )
        log.info(
            "cyber.guard.allow",
            action=action,
            required_approval=required_approval,
            risk_level=scope.risk_level.value,
            audit_ref=audit_ref,
        )
        return decision
