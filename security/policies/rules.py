"""
security/policies/rules.py — Configurable policy rules (Pass 17).

A PolicyRule defines a named condition that triggers a specific enforcement
action (DENY, ESCALATE, WARN). Rules are evaluated by the SecurityLayer
before delegating to kernel.policy().

These rules are application-layer governance — not to be confused with
kernel/policy/engine.py which operates at the kernel level.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ══════════════════════════════════════════════════════════════════════════════
# Enforcement actions
# ══════════════════════════════════════════════════════════════════════════════

class EnforcementAction(str, Enum):
    ALLOW     = "allow"      # pass through to kernel.policy()
    WARN      = "warn"       # allow but log a warning
    ESCALATE  = "escalate"   # require human approval
    DENY      = "deny"       # block unconditionally


# ══════════════════════════════════════════════════════════════════════════════
# PolicyRule
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class PolicyRule:
    """
    A named, versioned policy rule.

    Fields:
        rule_id         — unique identifier (e.g. "no-external-payments-in-auto")
        description     — human-readable explanation
        action_types    — list of action_type values this rule targets (empty = all)
        modes           — execution modes this rule applies to (empty = all)
        min_risk_level  — minimum risk level to trigger this rule ("low"|"medium"|"high"|"critical")
        enforcement     — what to do when the rule matches
        enabled         — can be disabled without removing the rule
        metadata        — arbitrary annotations
    """
    rule_id:        str
    description:    str
    action_types:   list[str] = field(default_factory=list)   # empty = all
    modes:          list[str] = field(default_factory=list)   # empty = all
    min_risk_level: str = "high"   # low | medium | high | critical
    enforcement:    EnforcementAction = EnforcementAction.ESCALATE
    enabled:        bool = True
    metadata:       dict = field(default_factory=dict)

    _RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}

    def matches(self, action_type: str, mode: str, risk_level: str) -> bool:
        """Return True if this rule applies to the given context."""
        if not self.enabled:
            return False
        if self.action_types and action_type not in self.action_types:
            return False
        if self.modes and mode not in self.modes:
            return False
        # Risk level threshold
        incoming = self._RISK_ORDER.get(risk_level.lower(), 0)
        threshold = self._RISK_ORDER.get(self.min_risk_level.lower(), 2)
        return incoming >= threshold

    def to_dict(self) -> dict:
        return {
            "rule_id":        self.rule_id,
            "description":    self.description,
            "action_types":   self.action_types,
            "modes":          self.modes,
            "min_risk_level": self.min_risk_level,
            "enforcement":    self.enforcement.value,
            "enabled":        self.enabled,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Default rules
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_RULES: list[PolicyRule] = [
    PolicyRule(
        rule_id="escalate-payment-always",
        description="All payment actions require operator approval regardless of mode.",
        action_types=["payment"],
        min_risk_level="low",
        enforcement=EnforcementAction.ESCALATE,
    ),
    PolicyRule(
        rule_id="escalate-data-delete",
        description="Data deletion requires operator approval.",
        action_types=["data_delete"],
        min_risk_level="low",
        enforcement=EnforcementAction.ESCALATE,
    ),
    PolicyRule(
        rule_id="escalate-deployment",
        description="All deployments require operator approval.",
        action_types=["deployment"],
        min_risk_level="low",
        enforcement=EnforcementAction.ESCALATE,
    ),
    PolicyRule(
        rule_id="escalate-self-improvement",
        description="Self-improvement actions require operator approval (R4: kernel.improvement.gate).",
        action_types=["self_improvement"],
        min_risk_level="low",
        enforcement=EnforcementAction.ESCALATE,
    ),
    PolicyRule(
        rule_id="warn-external-api",
        description="External API calls are logged with a warning.",
        action_types=["external_api"],
        min_risk_level="low",
        enforcement=EnforcementAction.WARN,
    ),
    PolicyRule(
        rule_id="deny-critical-in-auto",
        description="CRITICAL risk actions are blocked in auto mode.",
        modes=["auto"],
        min_risk_level="critical",
        enforcement=EnforcementAction.DENY,
    ),
]


# ══════════════════════════════════════════════════════════════════════════════
# PolicyRuleSet
# ══════════════════════════════════════════════════════════════════════════════

class PolicyRuleSet:
    """Ordered collection of PolicyRules. First matching rule wins."""

    def __init__(self, rules: Optional[list[PolicyRule]] = None) -> None:
        self._rules: list[PolicyRule] = rules if rules is not None else list(DEFAULT_RULES)

    def evaluate(
        self,
        action_type: str,
        mode: str,
        risk_level: str,
    ) -> tuple[EnforcementAction, Optional[PolicyRule]]:
        """
        Evaluate rules for the given context.

        Returns (action, matching_rule). If no rule matches, returns (ALLOW, None).
        """
        for rule in self._rules:
            if rule.matches(action_type, mode, risk_level):
                return rule.enforcement, rule
        return EnforcementAction.ALLOW, None

    def add_rule(self, rule: PolicyRule) -> None:
        self._rules.insert(0, rule)  # highest priority = first

    def disable_rule(self, rule_id: str) -> bool:
        for r in self._rules:
            if r.rule_id == rule_id:
                r.enabled = False
                return True
        return False

    def active_rules(self) -> list[PolicyRule]:
        return [r for r in self._rules if r.enabled]

    def to_dict(self) -> list[dict]:
        return [r.to_dict() for r in self._rules]


# Module-level singleton
_ruleset: Optional[PolicyRuleSet] = None


def get_policy_ruleset() -> PolicyRuleSet:
    global _ruleset
    if _ruleset is None:
        _ruleset = PolicyRuleSet()
    return _ruleset
