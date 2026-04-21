"""
core/orchestration/confidence_policy.py — Confidence as Behavior Policy
=========================================================================
Phase 2 cognitive upgrade: confidence CHANGES runtime behavior, not just reports.

Current state (before this module):
  - pre_execution.py computes estimated_confidence
  - meta_orchestrator stores it in metadata
  - strategy_suggestion is NEVER checked — no behavior change

This module:
  - Takes (confidence, risk, context) → PolicyDecision
  - PolicyDecision carries mandatory behavior changes (require_approval,
    add_context_gathering, decompose, use_safer_model, abort_with_reason)
  - meta_orchestrator MUST act on PolicyDecision before execution

Thresholds (conservative — designed to be observable):
  ┌──────────────┬─────────────────────────────────────────────────────┐
  │  confidence  │  policy behavior                                    │
  ├──────────────┼─────────────────────────────────────────────────────┤
  │  ≥ 0.70      │  proceed normally                                   │
  │  0.50–0.69   │  gather more context (memory lookup, skill search)  │
  │  0.35–0.49   │  require human approval + cautious mode             │
  │  0.20–0.34   │  decompose + require approval                       │
  │  < 0.20      │  abort — confidence too low to proceed safely       │
  └──────────────┴─────────────────────────────────────────────────────┘

Risk multipliers (high/critical risk tightens thresholds by 0.10):
  - high risk:     thresholds shift up by 0.10
  - critical risk: thresholds shift up by 0.15

Status: CODE READY + WIRED (Pass 42 — Phase 2)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

log = structlog.get_logger("orchestration.confidence_policy")


# ══════════════════════════════════════════════════════════════════════════════
# Policy tiers
# ══════════════════════════════════════════════════════════════════════════════

class PolicyTier(str, Enum):
    PROCEED    = "proceed"           # Normal execution
    CONTEXT    = "gather_context"    # Retrieve more before acting
    CAUTIOUS   = "cautious"          # Require approval, safer steps
    DECOMPOSE  = "decompose"         # Break into subtasks first
    ABORT      = "abort"             # Confidence too low to proceed


# ══════════════════════════════════════════════════════════════════════════════
# Policy decision
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class PolicyDecision:
    """
    Concrete behavior changes derived from confidence + risk.

    All boolean flags are ACTION ITEMS for the orchestrator — not suggestions.
    """
    tier:                PolicyTier = PolicyTier.PROCEED
    confidence:          float = 0.5
    risk_level:          str = "low"

    # Behavior flags (orchestrator MUST act on these)
    require_approval:    bool = False   # Override needs_approval → True
    add_context:         bool = False   # Trigger extra memory/skill retrieval
    decompose_mission:   bool = False   # Break goal into sub-steps before exec
    use_safer_model:     bool = False   # Prefer cheaper/safer model (lower risk)
    abort:               bool = False   # Stop mission immediately

    abort_reason:        str = ""
    context_queries:     list[str] = field(default_factory=list)  # What to retrieve
    approval_reason:     str = ""
    prompt_additions:    list[str] = field(default_factory=list)  # Injected into goal

    # Audit
    policy_log: list[str] = field(default_factory=list)   # Human-readable reasoning

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier.value,
            "confidence": round(self.confidence, 3),
            "risk_level": self.risk_level,
            "require_approval": self.require_approval,
            "add_context": self.add_context,
            "decompose_mission": self.decompose_mission,
            "use_safer_model": self.use_safer_model,
            "abort": self.abort,
            "abort_reason": self.abort_reason,
            "approval_reason": self.approval_reason,
            "context_queries": self.context_queries,
            "prompt_additions": self.prompt_additions,
            "policy_log": self.policy_log,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Thresholds
# ══════════════════════════════════════════════════════════════════════════════

# Base thresholds (confidence floor for each tier)
_BASE_THRESHOLDS = {
    PolicyTier.PROCEED:   0.70,
    PolicyTier.CONTEXT:   0.50,
    PolicyTier.CAUTIOUS:  0.35,
    PolicyTier.DECOMPOSE: 0.20,
    PolicyTier.ABORT:     0.0,   # below DECOMPOSE threshold
}

# Risk-based shifts (added to all thresholds)
_RISK_SHIFT = {
    "none":     0.00,
    "low":      0.00,
    "medium":   0.05,
    "high":     0.10,
    "critical": 0.15,
}


# ══════════════════════════════════════════════════════════════════════════════
# Policy engine
# ══════════════════════════════════════════════════════════════════════════════

class ConfidencePolicy:
    """
    Maps (confidence, risk, context) → PolicyDecision.

    Thread-safe, no state, no LLM calls.
    """

    def decide(
        self,
        confidence: float,
        risk_level: str = "low",
        task_type: str = "",
        goal: str = "",
        strategy_suggestion: str = "",
        has_prior_failures: bool = False,
        is_destructive: bool = False,
    ) -> PolicyDecision:
        """
        Compute a PolicyDecision.

        Args:
            confidence          : 0.0–1.0 from pre_execution.py
            risk_level          : "none"|"low"|"medium"|"high"|"critical"
            task_type           : from classifier (code, deployment, research …)
            goal                : raw goal string (for context queries)
            strategy_suggestion : hint from pre_execution (cautious/decompose/…)
            has_prior_failures  : True if similar failures found in memory
            is_destructive      : True if action is irreversible (deploy, delete, …)

        Returns:
            PolicyDecision — always returns, never raises
        """
        try:
            return self._decide(
                confidence, risk_level, task_type, goal,
                strategy_suggestion, has_prior_failures, is_destructive,
            )
        except Exception as exc:
            log.warning("confidence_policy_decide_failed", err=str(exc)[:80])
            return PolicyDecision(
                tier=PolicyTier.CAUTIOUS,
                confidence=confidence,
                risk_level=risk_level,
                require_approval=True,
                approval_reason=f"policy_error:{exc}",
                policy_log=[f"policy exception — defaulting to CAUTIOUS: {exc}"],
            )

    def _decide(
        self,
        confidence: float,
        risk_level: str,
        task_type: str,
        goal: str,
        strategy_suggestion: str,
        has_prior_failures: bool,
        is_destructive: bool,
    ) -> PolicyDecision:
        policy_log = []

        # ── 1. Apply risk shift ──────────────────────────────────────────────
        shift = _RISK_SHIFT.get(risk_level, 0.0)
        adjusted = confidence - shift
        if shift > 0:
            policy_log.append(
                f"risk_shift: {risk_level} → confidence {confidence:.2f} → adjusted {adjusted:.2f}"
            )

        # ── 2. Determine tier ────────────────────────────────────────────────
        tier = self._tier_for(adjusted)
        policy_log.append(f"tier: {tier.value} (adjusted_confidence={adjusted:.2f})")

        # ── 3. Destructive action override ───────────────────────────────────
        if is_destructive and tier == PolicyTier.PROCEED:
            tier = PolicyTier.CAUTIOUS
            policy_log.append("destructive_override: PROCEED → CAUTIOUS")

        # ── 4. Prior failures override ───────────────────────────────────────
        if has_prior_failures and tier in (PolicyTier.PROCEED, PolicyTier.CONTEXT):
            tier = PolicyTier.CAUTIOUS
            policy_log.append("prior_failures_override: tier → CAUTIOUS")

        # ── 5. External strategy suggestion alignment ────────────────────────
        # pre_execution.py may suggest "decompose" or "request_approval"
        if strategy_suggestion == "decompose" and tier.value not in (
            PolicyTier.DECOMPOSE.value, PolicyTier.ABORT.value
        ):
            tier = PolicyTier.DECOMPOSE
            policy_log.append(f"strategy_hint: '{strategy_suggestion}' → DECOMPOSE")
        elif strategy_suggestion in ("cautious", "request_approval") and tier == PolicyTier.PROCEED:
            tier = PolicyTier.CAUTIOUS
            policy_log.append(f"strategy_hint: '{strategy_suggestion}' → CAUTIOUS")

        # ── 6. Build decision ────────────────────────────────────────────────
        decision = PolicyDecision(
            tier=tier,
            confidence=confidence,
            risk_level=risk_level,
            policy_log=policy_log,
        )

        # ── 7. Apply tier-specific behaviors ────────────────────────────────
        if tier == PolicyTier.PROCEED:
            pass  # No changes

        elif tier == PolicyTier.CONTEXT:
            decision.add_context = True
            decision.context_queries = self._build_context_queries(goal, task_type)
            decision.prompt_additions.append(
                "LOW_CONFIDENCE: Retrieve relevant context before acting. "
                "Do not assume — verify first."
            )
            # Critical risk at CONTEXT tier: require approval as extra safety gate
            if risk_level == "critical":
                decision.require_approval = True
                decision.approval_reason = (
                    f"critical_risk with confidence={confidence:.2f} — "
                    f"approval required regardless of tier"
                )
                policy_log.append(
                    "critical_risk_approval: CONTEXT + critical → require_approval"
                )
            policy_log.append(
                f"add_context: queries={decision.context_queries[:2]}"
            )

        elif tier == PolicyTier.CAUTIOUS:
            # Only require approval for medium+ risk when cautious.
            # Low/no risk missions should proceed even at low confidence —
            # they can't cause damage. This prevents simple info queries
            # from being blocked behind an approval gate.
            _needs_approval = risk_level in ("medium", "high", "critical")
            decision.require_approval = _needs_approval
            decision.add_context = True
            decision.context_queries = self._build_context_queries(goal, task_type)
            decision.approval_reason = (
                f"confidence={confidence:.2f} risk={risk_level} "
                f"prior_failures={has_prior_failures}"
            )
            decision.prompt_additions.append(
                "CAUTIOUS_MODE: Confidence is low. Prefer the smallest, safest "
                "next step. Avoid irreversible actions. Stop and report if uncertain."
            )
            if _needs_approval:
                policy_log.append(
                    f"require_approval: reason='{decision.approval_reason}'"
                )
            else:
                policy_log.append(
                    "cautious_no_approval: low/no risk — proceed without gate"
                )

        elif tier == PolicyTier.DECOMPOSE:
            decision.require_approval = True
            decision.decompose_mission = True
            decision.add_context = True
            decision.context_queries = self._build_context_queries(goal, task_type)
            decision.use_safer_model = True
            decision.approval_reason = (
                f"confidence={confidence:.2f} too low for direct execution; "
                f"decomposition required"
            )
            decision.prompt_additions.append(
                "DECOMPOSE_MODE: Break this goal into 3–5 independent subtasks. "
                "List them explicitly before attempting any. Do not attempt the "
                "full goal in one step."
            )
            policy_log.append("decompose_mission=True, use_safer_model=True")

        elif tier == PolicyTier.ABORT:
            decision.abort = True
            decision.abort_reason = (
                f"confidence={confidence:.2f} is below minimum threshold "
                f"(risk={risk_level}). Aborting to prevent unreliable execution."
            )
            policy_log.append(f"abort: {decision.abort_reason}")

        log.info(
            "confidence_policy_decision",
            tier=tier.value,
            confidence=confidence,
            adjusted=adjusted,
            risk_level=risk_level,
            task_type=task_type,
            require_approval=decision.require_approval,
            add_context=decision.add_context,
            decompose=decision.decompose_mission,
            abort=decision.abort,
        )

        return decision

    def _tier_for(self, adjusted_confidence: float) -> PolicyTier:
        """Map adjusted confidence to the lowest applicable tier."""
        if adjusted_confidence >= _BASE_THRESHOLDS[PolicyTier.PROCEED]:
            return PolicyTier.PROCEED
        if adjusted_confidence >= _BASE_THRESHOLDS[PolicyTier.CONTEXT]:
            return PolicyTier.CONTEXT
        if adjusted_confidence >= _BASE_THRESHOLDS[PolicyTier.CAUTIOUS]:
            return PolicyTier.CAUTIOUS
        if adjusted_confidence >= _BASE_THRESHOLDS[PolicyTier.DECOMPOSE]:
            return PolicyTier.DECOMPOSE
        return PolicyTier.ABORT

    def _build_context_queries(self, goal: str, task_type: str) -> list[str]:
        """Generate targeted memory/skill queries based on goal and task type."""
        queries = [goal[:80]]
        if task_type == "code":
            queries.append("similar code fix success pattern")
            queries.append("code failure error recovery")
        elif task_type == "deployment":
            queries.append("deployment success checklist")
            queries.append("deployment failure rollback")
        elif task_type == "research":
            queries.append("research methodology quality")
        else:
            queries.append(f"{task_type} success pattern")
        return queries[:3]


# ── Module-level singleton ────────────────────────────────────────────────────
_policy: ConfidencePolicy | None = None


def get_confidence_policy() -> ConfidencePolicy:
    """Return singleton ConfidencePolicy."""
    global _policy
    if _policy is None:
        _policy = ConfidencePolicy()
    return _policy
