"""
kernel/adapters/policy_adapter.py — Bridge between core PolicyEngine and kernel policy pipeline.

ARCHITECTURE RULE (Kernel Rule K1):
  kernel/ NEVER imports from core/, agents/, api/, tools/.
  This adapter uses the REGISTRATION PATTERN to break the circular dependency.

  Instead of importing core.policy_engine directly, core registers a callable
  here at boot time (via register_core_policy_fn). If no callable is registered,
  the kernel-native evaluator is used — which is always sufficient.

HOW TO REGISTER (call once at app startup, after kernel boot):
  from kernel.adapters.policy_adapter import register_core_policy_fn
  from core.policy_engine import PolicyEngine
  from config.settings import get_settings
  register_core_policy_fn(PolicyEngine(get_settings()).check_action)
"""
from __future__ import annotations

from typing import Callable, Optional
from kernel.contracts.types import Action, PolicyDecision, RiskLevel

# ── Registration slot — populated by core at boot, never imported from core ──
_core_policy_fn: Optional[Callable[..., object]] = None


def register_core_policy_fn(fn: Callable[..., object]) -> None:
    """
    Register core.policy_engine.PolicyEngine.check_action (or equivalent).
    Call this at application boot AFTER the kernel is initialized.
    Kernel code never imports core directly — core registers itself here.
    """
    global _core_policy_fn
    _core_policy_fn = fn


def core_check_action_to_kernel(
    action_type: str,
    risk_level: str = "low",
    mode: str = "auto",
) -> PolicyDecision:
    """
    Produce a kernel PolicyDecision for an action.

    Priority:
      1. Registered core policy callable (set at boot, zero imports from core)
      2. Kernel-native evaluation (self-contained, always works standalone)
    """
    try:
        kernel_risk = RiskLevel(risk_level)
    except ValueError:
        kernel_risk = RiskLevel.LOW

    # 1 — registered core policy (no import from core in this file)
    if _core_policy_fn is not None:
        try:
            core_decision = _core_policy_fn(
                action_type=action_type,
                risk_level=risk_level,
                mode=mode,
            )
            return PolicyDecision(
                allowed=getattr(core_decision, "allowed", True),
                action_id=f"core-{action_type}",
                risk_level=kernel_risk,
                requires_approval=kernel_risk in (RiskLevel.HIGH, RiskLevel.CRITICAL),
                reason=getattr(core_decision, "reason", "core_policy"),
            )
        except Exception:
            import logging as _lg; _lg.getLogger(__name__).debug("swallowed_exception", exc_info=True)

    # 2 — kernel-native evaluation (self-contained, no core dependency)
    from kernel.policy.engine import evaluate_action
    action = Action(
        action_type=action_type,
        risk_level=kernel_risk,
        target=action_type,
    )
    return evaluate_action(action)


def kernel_decision_to_core_dict(decision: PolicyDecision) -> dict:
    """
    Convert kernel PolicyDecision to a dict that core code can consume.

    Shape matches core PolicyDecision usage pattern:
      {"allowed": bool, "reason": str, "suggestion": str, "metadata": dict}
    """
    return {
        "allowed": decision.allowed,
        "reason": decision.reason,
        "suggestion": "" if decision.allowed else "Escalate or modify risk level",
        "metadata": {
            "risk_level": decision.risk_level.value,
            "requires_approval": decision.requires_approval,
            "kernel_policy": True,
            "action_id": decision.action_id,
        },
    }
