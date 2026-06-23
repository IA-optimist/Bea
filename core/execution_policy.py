"""
ExecutionPolicy — couche de sécurité déterministe pour l'exécution des actions.
Aucune dépendance externe, logique pure, ~1 KB RAM.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# ── Constantes de décision partagées ───────────────────────────────────────
class Decision:
    AUTO_APPROVED = "AUTO_APPROVED"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
    BLOCKED = "BLOCKED"


# ── Taxonomie des types d'actions ──────────────────────────────────────────
ACTION_TYPES = {
    "read", "write", "execute", "network",
    "install", "modify_config", "restart_service",
    "self_modify", "external_api",
}

# Actions considérées comme sûres en mode SUPERVISED (risk ≤ 3)
_SAFE_ACTIONS = {"read", "write", "execute"}

# Actions bloquées en AUTO (toujours demander approbation)
_CRITICAL_ACTIONS = {"self_modify", "modify_config", "install", "network", "restart_service"}

# risk_score max autorisé en AUTO selon action_type
_AUTO_RISK_THRESHOLD: dict[str, int] = {
    "read":         9,   # jamais bloqué
    "write":        7,
    "execute":      5,
    "external_api": 4,
    "network":      0,   # toujours bloqué (dans _CRITICAL_ACTIONS)
    "install":      0,
    "modify_config":0,
    "restart_service": 0,
    "self_modify":  0,
}


@dataclass
class ActionContext:
    """Input context for an execution policy evaluation.

    Attributes:
        mission_type: Category of mission (e.g. "coding_task", "research_task").
        risk_score: Risk level 0-10 (0=safe, 10=dangerous).
        complexity: Task complexity ("low" | "medium" | "high").
        agent: Agent name requesting the action.
        action_type: One of ACTION_TYPES (read, write, execute, network, etc.).
        estimated_impact: Expected side-effect severity ("low" | "medium" | "high").
        mode: Operating mode ("MANUAL" | "SUPERVISED" | "AUTO").
    """
    mission_type: str       # ex. "coding_task"
    risk_score: int         # 0–10
    complexity: str         # "low" | "medium" | "high"
    agent: str              # ex. "forge-builder"
    action_type: str        # l'un des 9 types ci-dessus
    estimated_impact: str   # "low" | "medium" | "high"
    mode: str = "SUPERVISED"  # "MANUAL" | "SUPERVISED" | "AUTO"


@dataclass
class PolicyDecision:
    """Output of an execution policy evaluation.

    Attributes:
        approved: True if the action can proceed automatically.
        decision: One of "AUTO_APPROVED", "REQUIRES_APPROVAL", "BLOCKED".
    Use Decision constants (Decision.AUTO_APPROVED, Decision.REQUIRES_APPROVAL,
    Decision.BLOCKED) when building or comparing.
        reason: Human-readable explanation for the decision.
        risk_score: Echoed from input context.
        action_type: Echoed from input context (normalized).
    """
    approved: bool
    decision: str    # Decision.AUTO_APPROVED | Decision.REQUIRES_APPROVAL | Decision.BLOCKED
    reason: str
    risk_score: int
    action_type: str


class ExecutionPolicy:
    """
    Détermine si une action peut être exécutée automatiquement.
    Toutes les règles sont déterministes — aucun ML, aucune dépendance externe.
    """

    def evaluate(self, ctx: ActionContext) -> PolicyDecision:
        """
        Évalue le contexte d'action et retourne une PolicyDecision.
        Fail-open : en cas d'erreur interne, retourne REQUIRES_APPROVAL.
        """
        try:
            return self._evaluate(ctx)
        except Exception as e:
            logger.warning(f"[ExecutionPolicy] evaluate error (fail-open): {e}")
            return PolicyDecision(
                approved=False,
                decision=Decision.REQUIRES_APPROVAL,
                reason=f"internal_error: {e}",
                risk_score=ctx.risk_score,
                action_type=ctx.action_type,
            )

    def _evaluate(self, ctx: ActionContext) -> PolicyDecision:
        action = ctx.action_type if ctx.action_type in ACTION_TYPES else "execute"
        mode = ctx.mode.upper()

        # ── MANUAL : toujours demander ─────────────────────────────────────
        if mode == "MANUAL":
            return PolicyDecision(
                approved=False,
                decision=Decision.REQUIRES_APPROVAL,
                reason="mode_manual_always_requires_approval",
                risk_score=ctx.risk_score,
                action_type=action,
            )

        # ── SUPERVISED ────────────────────────────────────────────────────
        if mode == "SUPERVISED":
            if action in _SAFE_ACTIONS and ctx.risk_score <= 3:
                return PolicyDecision(
                    approved=True,
                    decision=Decision.AUTO_APPROVED,
                    reason=f"supervised_safe_action_low_risk (action={action}, risk={ctx.risk_score})",
                    risk_score=ctx.risk_score,
                    action_type=action,
                )
            return PolicyDecision(
                approved=False,
                decision=Decision.REQUIRES_APPROVAL,
                reason=f"supervised_requires_approval (action={action}, risk={ctx.risk_score})",
                risk_score=ctx.risk_score,
                action_type=action,
            )

        # ── AUTO ──────────────────────────────────────────────────────────
        if mode == "AUTO":
            # Actions critiques → toujours bloquées
            if action in _CRITICAL_ACTIONS:
                return PolicyDecision(
                    approved=False,
                    decision=Decision.BLOCKED,
                    reason=f"auto_critical_action_blocked (action={action})",
                    risk_score=ctx.risk_score,
                    action_type=action,
                )
            # Impact élevé → demander
            if ctx.estimated_impact == "high":
                return PolicyDecision(
                    approved=False,
                    decision=Decision.REQUIRES_APPROVAL,
                    reason=f"auto_high_impact_requires_approval (impact=high, action={action})",
                    risk_score=ctx.risk_score,
                    action_type=action,
                )
            # risk_score trop élevé pour ce type d'action
            threshold = _AUTO_RISK_THRESHOLD.get(action, 5)
            if ctx.risk_score > threshold:
                return PolicyDecision(
                    approved=False,
                    decision=Decision.REQUIRES_APPROVAL,
                    reason=f"auto_risk_exceeds_threshold (risk={ctx.risk_score} > threshold={threshold})",
                    risk_score=ctx.risk_score,
                    action_type=action,
                )
            return PolicyDecision(
                approved=True,
                decision=Decision.AUTO_APPROVED,
                reason=f"auto_approved (action={action}, risk={ctx.risk_score}, impact={ctx.estimated_impact})",
                risk_score=ctx.risk_score,
                action_type=action,
            )

        # Fallback pour mode inconnu
        return PolicyDecision(
            approved=False,
            decision=Decision.REQUIRES_APPROVAL,
            reason=f"unknown_mode_{mode}",
            risk_score=ctx.risk_score,
            action_type=action,
        )


# Singleton
_policy: Optional[ExecutionPolicy] = None

def get_execution_policy() -> ExecutionPolicy:
    """Return the singleton ExecutionPolicy instance. Thread-safe (GIL)."""
    global _policy
    if _policy is None:
        _policy = ExecutionPolicy()
    return _policy
