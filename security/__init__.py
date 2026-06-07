"""
security/ — Native security governance layer for BeaMax (Pass 17).

Architecture:
    security/
        policies/rules.py    — configurable PolicyRules (what triggers DENY/ESCALATE)
        risk/profiles.py     — domain RiskProfiles (sensitivity, rate limits)
        audit/trail.py       — immutable AuditTrail (append-only)

SecurityLayer (this module) is the unified facade:

    from security import get_security_layer
    layer = get_security_layer()
    result = layer.check_action(action_type, mission_id, mode, risk_level)

R3:  all sensitive actions go through this layer before execution
R10: security is not decorative — every decision is audited

The SecurityLayer wraps (but never replaces) kernel.policy(). It adds:
  1. Domain-rule evaluation (PolicyRuleSet)
  2. Risk profile enrichment (RiskProfileRegistry)
  3. Immutable audit trail (AuditTrail)
"""
from __future__ import annotations

import structlog
from typing import Optional

from security.policies.rules import EnforcementAction, get_policy_ruleset
from security.risk.profiles import SensitivityLevel, get_risk_registry
from security.audit.trail import AuditDecision, make_audit_entry, get_audit_trail

log = structlog.get_logger("security")


# ══════════════════════════════════════════════════════════════════════════════
# SecurityCheckResult
# ══════════════════════════════════════════════════════════════════════════════

class SecurityCheckResult:
    """
    Result of a security layer check.

    Fields:
        allowed    — True if the action can proceed to execution
        escalated  — True if the action needs human approval first
        reason     — explanation for the decision
        risk_level — computed/enriched risk level
        entry_id   — audit trail entry ID for this decision
    """
    __slots__ = ("allowed", "escalated", "reason", "risk_level", "entry_id")

    def __init__(
        self,
        allowed: bool,
        escalated: bool = False,
        reason: str = "",
        risk_level: str = "low",
        entry_id: str = "",
    ) -> None:
        self.allowed    = allowed
        self.escalated  = escalated
        self.reason     = reason
        self.risk_level = risk_level
        self.entry_id   = entry_id

    def to_dict(self) -> dict:
        return {
            "allowed":    self.allowed,
            "escalated":  self.escalated,
            "reason":     self.reason,
            "risk_level": self.risk_level,
            "entry_id":   self.entry_id,
        }

    def __repr__(self) -> str:
        return (
            f"SecurityCheckResult(allowed={self.allowed}, escalated={self.escalated}, "
            f"risk={self.risk_level}, entry={self.entry_id[:12]}...)"
        )


# ══════════════════════════════════════════════════════════════════════════════
# SecurityLayer
# ══════════════════════════════════════════════════════════════════════════════

class SecurityLayer:
    """
    Unified security governance facade.

    Usage:
        layer = get_security_layer()
        result = layer.check_action(
            action_type="payment",
            mission_id="m-123",
            mode="auto",
            risk_level="high",
        )
        if not result.allowed:
            raise PermissionError(result.reason)
        if result.escalated:
            # route to human approval
            ...
    """

    def __init__(self) -> None:
        self._rules   = get_policy_ruleset()
        self._risk_reg = get_risk_registry()
        self._audit    = get_audit_trail()

    def check_action(
        self,
        action_type: str,
        mission_id: str = "",
        mode: str = "auto",
        risk_level: str = "low",
        action_target: str = "",
        metadata: Optional[dict] = None,
    ) -> SecurityCheckResult:
        """
        Evaluate a proposed action against the policy ruleset.

        Steps:
          1. Enrich risk_level from RiskProfile if needed
          2. Evaluate PolicyRuleSet (first-match semantics)
          3. Map EnforcementAction → SecurityCheckResult
          4. Append to AuditTrail (always, fail-open)

        Returns SecurityCheckResult (never raises).
        """
        try:
            # 1. Enrich with domain risk profile
            profile = self._risk_reg.get(action_type)
            _enriched_risk = risk_level
            if (
                profile.sensitivity in (SensitivityLevel.CONFIDENTIAL, SensitivityLevel.RESTRICTED)
                and risk_level == "low"
            ):
                _enriched_risk = "medium"  # bump low risk for sensitive action types

            # 2. Evaluate rules
            enforcement, matched_rule = self._rules.evaluate(action_type, mode, _enriched_risk)
            rule_desc = matched_rule.description if matched_rule else "no matching rule"

            # 3. Map to result
            if enforcement == EnforcementAction.DENY:
                result = SecurityCheckResult(
                    allowed=False, escalated=False,
                    reason=f"[DENY] {rule_desc}",
                    risk_level=_enriched_risk,
                )
                audit_decision = AuditDecision.DENIED

            elif enforcement == EnforcementAction.ESCALATE:
                result = SecurityCheckResult(
                    allowed=False, escalated=True,
                    reason=f"[ESCALATE] {rule_desc}",
                    risk_level=_enriched_risk,
                )
                audit_decision = AuditDecision.ESCALATED

            elif enforcement == EnforcementAction.WARN:
                log.warning(
                    "security_warn",
                    action_type=action_type,
                    mission_id=mission_id,
                    rule=matched_rule.rule_id if matched_rule else "",
                )
                result = SecurityCheckResult(
                    allowed=True, escalated=False,
                    reason=f"[WARN] {rule_desc}",
                    risk_level=_enriched_risk,
                )
                audit_decision = AuditDecision.ALLOWED

            else:  # ALLOW
                result = SecurityCheckResult(
                    allowed=True, escalated=False,
                    reason="Allowed by policy",
                    risk_level=_enriched_risk,
                )
                audit_decision = AuditDecision.ALLOWED

            # 4. Audit (fail-open)
            try:
                entry = make_audit_entry(
                    mission_id=mission_id,
                    action_type=action_type,
                    action_target=action_target or action_type,
                    risk_level=_enriched_risk,
                    decision=audit_decision,
                    reason=result.reason,
                    decided_by="security.layer",
                    metadata=metadata,
                )
                self._audit.record(entry)
                result.entry_id = entry.entry_id
            except Exception as _ae:
                log.warning("security_audit_failed", err=str(_ae)[:80])

            return result

        except Exception as e:
            # Fail-open: if security layer itself crashes, allow + log
            log.error("security_layer_error", err=str(e)[:120], action_type=action_type)
            return SecurityCheckResult(
                allowed=True, escalated=False,
                reason=f"[FAIL-OPEN] Security layer error: {str(e)[:80]}",
                risk_level=risk_level,
            )

    def audit_trail(self):
        """Expose audit trail for inspection."""
        return self._audit

    def active_rules(self) -> list:
        return self._rules.active_rules()

    def risk_profile(self, action_type: str):
        return self._risk_reg.get(action_type)


# ══════════════════════════════════════════════════════════════════════════════
# Module-level singleton
# ══════════════════════════════════════════════════════════════════════════════

_layer: Optional[SecurityLayer] = None


def get_security_layer() -> SecurityLayer:
    """Return the module-level SecurityLayer singleton."""
    global _layer
    if _layer is None:
        _layer = SecurityLayer()
    return _layer


# Public API
__all__ = [
    "SecurityLayer", "SecurityCheckResult", "get_security_layer",
]
