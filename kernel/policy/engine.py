"""
kernel/policy/engine.py — Clean separation of Risk, Policy, and Approval.

Three distinct responsibilities:
  1. RiskEngine:    computes risk score for an action
  2. PolicyEngine:  decides if an action is allowed based on risk + rules
  3. ApprovalGate:  handles human approval when policy requires it

Dependency chain:
  Action → RiskEngine → PolicyEngine → (if needed) ApprovalGate → Execute

This separation ensures:
  - Risk computation is independent of policy rules
  - Policy can change without touching risk logic
  - Approval depends on policy decision, not directly on risk score
"""
from __future__ import annotations

import time
import structlog
from dataclasses import dataclass, field

from kernel.contracts.types import (
    Action, PolicyDecision, Decision, DecisionType, RiskLevel,
)

log = structlog.get_logger("kernel.policy")


# ══════════════════════════════════════════════════════════════
# 1. Risk Engine — computes risk score
# ══════════════════════════════════════════════════════════════

class RiskEngine:
    """Compute risk level for an action based on its characteristics."""

    # Actions that are always high+ risk
    HIGH_RISK_TYPES = {"external_api", "payment", "deployment", "data_delete"}
    MEDIUM_RISK_TYPES = {"tool_invoke", "file_write", "webhook", "automation"}

    def evaluate(self, action: Action) -> RiskLevel:
        """Compute risk level for an action."""
        if action.risk_level != RiskLevel.LOW:
            return action.risk_level  # respect pre-declared risk

        if action.action_type in self.HIGH_RISK_TYPES:
            return RiskLevel.HIGH
        if action.action_type in self.MEDIUM_RISK_TYPES:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW


# ══════════════════════════════════════════════════════════════
# 2. Policy Engine — decides if action is allowed
# ══════════════════════════════════════════════════════════════

class KernelPolicyEngine:
    """
    Decide whether an action is allowed based on risk level and policy rules.

    Policy rules (default):
      - LOW risk: auto-approve
      - MEDIUM risk: require approval unless pre-approved
      - HIGH risk: always require approval
      - CRITICAL risk: block (manual override only)
    """

    def evaluate(self, action: Action, risk: RiskLevel) -> PolicyDecision:
        """Evaluate whether an action should proceed."""
        if risk == RiskLevel.CRITICAL:
            return PolicyDecision(
                allowed=False,
                action_id=action.action_id,
                risk_level=risk,
                requires_approval=False,
                reason="CRITICAL risk — blocked by default policy",
            )

        if risk == RiskLevel.HIGH:
            return PolicyDecision(
                allowed=True,
                action_id=action.action_id,
                risk_level=risk,
                requires_approval=True,
                reason="HIGH risk — requires human approval",
            )

        if risk == RiskLevel.MEDIUM:
            needs_approval = not action.requires_approval  # if already approved, don't re-ask
            return PolicyDecision(
                allowed=True,
                action_id=action.action_id,
                risk_level=risk,
                requires_approval=action.requires_approval,
                reason="MEDIUM risk — approval recommended",
            )

        return PolicyDecision(
            allowed=True,
            action_id=action.action_id,
            risk_level=risk,
            requires_approval=False,
            reason="LOW risk — auto-approved",
        )


# ══════════════════════════════════════════════════════════════
# 3. Approval Gate — handles human approval
# ══════════════════════════════════════════════════════════════

class ApprovalGate:
    """
    Manages approval requests and decisions.

    Approval gate only activates when policy says requires_approval=True.
    Does NOT make risk decisions — only processes approval flow.
    """

    def __init__(self):
        self._pending: dict[str, dict] = {}  # action_id → request data
        self._decisions: dict[str, Decision] = {}

    def request(self, action: Action, policy: PolicyDecision) -> str:
        """Create an approval request. Returns request_id."""
        request_id = f"approval-{action.action_id}"
        self._pending[request_id] = {
            "action": action.to_dict(),
            "policy": policy.to_dict(),
            "timestamp": time.time(),
        }
        # Emit event
        try:
            from kernel.events.canonical import get_kernel_emitter
            get_kernel_emitter().approval_requested(
                target_id=action.action_id,
                action=f"{action.action_type}: {action.target}",
            )
        except Exception:
            _silent_log.debug("suppressed_exception", src='engine.py')
        return request_id

    def decide(self, request_id: str, approved: bool,
               reason: str = "", decided_by: str = "operator") -> Decision:
        """Record an approval decision."""
        decision = Decision(
            decision_type=DecisionType.APPROVE if approved else DecisionType.REJECT,
            target_id=request_id,
            reason=reason,
            decided_by=decided_by,
        )
        self._decisions[request_id] = decision
        self._pending.pop(request_id, None)
        return decision

    def is_approved(self, action_id: str) -> bool:
        request_id = f"approval-{action_id}"
        decision = self._decisions.get(request_id)
        return decision is not None and decision.decision_type == DecisionType.APPROVE

    def get_pending(self) -> list[dict]:
        return [
            {"request_id": k, **v}
            for k, v in self._pending.items()
        ]


# ══════════════════════════════════════════════════════════════
# Unified Policy Pipeline
# ══════════════════════════════════════════════════════════════

def evaluate_action(action: Action) -> PolicyDecision:
    """
    Full pipeline: Risk → Policy → result.

    Usage:
        decision = evaluate_action(action)
        if decision.requires_approval:
            gate.request(action, decision)
        elif decision.allowed:
            execute(action)
        else:
            block(action)
    """
    risk_engine = RiskEngine()
    policy_engine = KernelPolicyEngine()

    risk = risk_engine.evaluate(action)
    return policy_engine.evaluate(action, risk)
