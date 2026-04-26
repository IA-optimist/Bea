"""
core/autonomy/approval_bridge.py — ApprovalQueue ↔ MultiChoice bridge.

The existing `core.approval_queue` is binary : the operator approves
or rejects a single proposed action. For autonomy, we want to surface
*alternatives* so the operator picks the best path instead of just
gating one option.

This bridge offers a parallel API : when the daemon has multiple
strategies for a high-risk goal, it calls
`request_strategy_choice(...)` instead of `submit_for_approval(...)`.
The bridge :

1. Creates a MultiChoice decision with the alternatives + risk metadata
2. Optionally creates a parallel ApprovalQueue item so the legacy UI
   still sees the request (binary fallback : approve = first choice,
   reject = cancel)
3. Returns immediately with the decision_id ; daemon calls
   `wait_for_strategy_choice()` to block until the operator answers

Failure / timeout policy is enforced by MultiChoiceStore (default
choice + timeout). The approval_queue side is just a notification
mirror — the source of truth is MultiChoice.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

from core.autonomy.multi_choice import (
    Choice,
    Decision,
    get_multi_choice_store,
)

log = structlog.get_logger(__name__)


@dataclass
class StrategyChoice:
    """One option presented to the operator."""
    label: str
    description: str
    risk_level: str = "low"      # low | medium | high | critical
    estimated_cost_usd: float = 0.0
    estimated_duration_s: float = 0.0
    rollback_plan: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


def request_strategy_choice(
    *,
    name: str,
    question: str,
    strategies: List[StrategyChoice],
    timeout_s: float = 600.0,
    default_strategy_index: int = -1,
    mirror_to_approval_queue: bool = True,
) -> Decision:
    """Open a multi-choice decision ; returns the pending Decision.

    The decision_id comes back inside the Decision. Operator-facing UIs
    poll `MultiChoiceStore.pending()` and call `answer(decision_id, idx)`.

    `mirror_to_approval_queue` (default True) creates a parallel
    `submit_for_approval` so legacy clients still see the request.
    Approve on the legacy item maps to default_strategy_index (or 0
    if -1).
    """
    if not strategies:
        raise ValueError("strategies must be non-empty")

    choices = [
        Choice(
            index=i,
            label=s.label,
            description=s.description,
            metadata={
                "risk_level": s.risk_level,
                "estimated_cost_usd": s.estimated_cost_usd,
                "estimated_duration_s": s.estimated_duration_s,
                "rollback_plan": s.rollback_plan,
                **s.metadata,
            },
        )
        for i, s in enumerate(strategies)
    ]

    decision = get_multi_choice_store().create(
        name=name,
        question=question,
        choices=choices,
        timeout_s=timeout_s,
        default_choice=default_strategy_index,
        metadata={
            "max_risk_level": _max_risk(strategies),
            "max_cost_usd": max((s.estimated_cost_usd for s in strategies), default=0.0),
        },
    )

    if mirror_to_approval_queue:
        try:
            from core.approval_queue import submit_for_approval

            risk = _risk_to_enum(_max_risk(strategies))
            best_default = (
                default_strategy_index if default_strategy_index >= 0 else 0
            )
            apq_action = (
                f"strategy_choice : {name} (default → {strategies[best_default].label})"
            )
            apq = submit_for_approval(
                action=apq_action,
                risk_level=risk,
                reason=question[:300],
                expected_impact=", ".join(
                    f"{s.label} (risk={s.risk_level})" for s in strategies
                )[:300],
                rollback_plan="See multi_choice rollback_plan per option",
                source="autonomy_daemon",
                payload={
                    "decision_id": decision.decision_id,
                    "strategies": [
                        {
                            "label": s.label,
                            "risk_level": s.risk_level,
                            "estimated_cost_usd": s.estimated_cost_usd,
                        }
                        for s in strategies
                    ],
                },
            )
            decision.metadata["approval_queue_id"] = apq.get("item_id")
        except Exception as exc:
            log.debug("approval_bridge.mirror_failed", err=str(exc)[:120])

    return decision


def wait_for_strategy_choice(
    decision_id: str,
    *,
    max_wait_s: Optional[float] = None,
) -> Decision:
    """Block until the operator answers (or timeout fires).

    See MultiChoiceStore.wait for timeout semantics.
    """
    return get_multi_choice_store().wait(decision_id, max_wait_s=max_wait_s)


def cancel_pending_choices_older_than(seconds: float) -> int:
    """Sweep : cancel pending decisions older than `seconds`. Returns count."""
    store = get_multi_choice_store()
    cutoff = time.time() - seconds
    cancelled = 0
    for d in store.pending():
        if d.created_at < cutoff:
            if store.cancel(d.decision_id, reason="autonomy_bridge.timeout_sweep"):
                cancelled += 1
    if cancelled:
        log.info("approval_bridge.swept_stale", count=cancelled)
    return cancelled


# ── Internals ────────────────────────────────────────────────
_RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _max_risk(strategies: List[StrategyChoice]) -> str:
    return max(
        (s.risk_level for s in strategies),
        key=lambda r: _RISK_ORDER.get(r, 0),
        default="low",
    )


def _risk_to_enum(risk_str: str):
    """Translate to core.approval_queue.RiskLevel — fail-open returns WRITE_HIGH."""
    try:
        from core.approval_queue import RiskLevel

        mapping = {
            "low": RiskLevel.WRITE_LOW,
            "medium": RiskLevel.WRITE_HIGH,
            "high": RiskLevel.INFRA,
            "critical": RiskLevel.DELETE,
        }
        return mapping.get(risk_str, RiskLevel.WRITE_HIGH)
    except Exception:
        return None  # caller will catch
