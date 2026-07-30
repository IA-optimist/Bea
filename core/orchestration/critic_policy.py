"""Canonical critic decision policy.

The kernel remains the single evaluation authority. This module only decides
whether a structured KernelScore may be accepted, rerun, or must block mission
completion. Resource pressure is a permission gate, never a rerun trigger.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math

from core.resource_guard import SystemStatus
from kernel.evaluation.scorer import KernelScore, PASS_THRESHOLD


class CriticAction(str, Enum):
    ACCEPT = "accept"
    NATURAL_RERUN = "natural_rerun"
    FORCED_RERUN = "forced_rerun"
    BLOCKED = "blocked"
    ERROR = "error"


@dataclass(frozen=True)
class CriticDecision:
    """Minimal, persistence-safe decision metadata."""

    action: CriticAction
    score: float
    reason: str
    resource_status: str
    forced: bool = False

    @property
    def should_rerun(self) -> bool:
        return self.action in {
            CriticAction.NATURAL_RERUN,
            CriticAction.FORCED_RERUN,
        }

    @property
    def quality_sufficient(self) -> bool:
        return self.action in {
            CriticAction.ACCEPT,
            CriticAction.FORCED_RERUN,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action.value,
            "score": round(self.score, 3) if math.isfinite(self.score) else None,
            "reason": self.reason,
            "resource_status": self.resource_status,
            "forced": self.forced,
        }


class CriticPipelineError(RuntimeError):
    """Base error for a critic verdict that cannot safely complete a mission."""


class CriticEvaluationError(CriticPipelineError):
    """The critic could not produce a valid structured verdict."""


class CriticResourceBlocked(CriticPipelineError):
    """A required natural rerun was denied by ResourceGuard."""


class CriticQualityRejected(CriticPipelineError):
    """The best bounded attempt still failed the canonical critic."""


class CriticRerunFailed(CriticPipelineError):
    """A required natural rerun failed before producing a valid candidate."""


def _status_value(resource_status: SystemStatus | str) -> tuple[SystemStatus | None, str]:
    if isinstance(resource_status, SystemStatus):
        return resource_status, resource_status.value
    try:
        status = SystemStatus(str(resource_status))
    except (TypeError, ValueError):
        return None, str(resource_status)
    return status, status.value


def decide_critic_action(
    kernel_score: KernelScore,
    resource_status: SystemStatus | str,
    *,
    forced_enabled: bool = False,
    already_reran: bool = False,
    execution_retries: int = 0,
    goal_length: int = 0,
) -> CriticDecision:
    """Return a deterministic action for one mission-scoped critic cycle."""
    status, status_text = _status_value(resource_status)
    try:
        score = float(kernel_score.score)
    except (TypeError, ValueError):
        score = math.nan
    try:
        confidence = float(kernel_score.confidence)
    except (TypeError, ValueError):
        confidence = math.nan

    if (
        not math.isfinite(score)
        or not 0.0 <= score <= 1.0
        or not math.isfinite(confidence)
        or not 0.0 <= confidence <= 1.0
        or not isinstance(kernel_score.passed, bool)
        or not isinstance(kernel_score.retry_recommended, bool)
        or kernel_score.failure_class in {
            "critic_invalid_score",
            "critic_evaluation_error",
        }
    ):
        return CriticDecision(
            action=CriticAction.ERROR,
            score=score,
            reason="invalid_critic_score",
            resource_status=status_text,
        )
    if status is None:
        return CriticDecision(
            action=CriticAction.ERROR,
            score=score,
            reason="invalid_resource_status",
            resource_status=status_text,
        )

    natural_failure = (
        score < PASS_THRESHOLD
        or not kernel_score.passed
        or kernel_score.retry_recommended
    )
    if natural_failure:
        if already_reran:
            return CriticDecision(
                action=CriticAction.BLOCKED,
                score=score,
                reason="critic_rerun_limit_reached",
                resource_status=status_text,
            )
        if execution_retries > 0:
            return CriticDecision(
                action=CriticAction.BLOCKED,
                score=score,
                reason="execution_retry_budget_exhausted",
                resource_status=status_text,
            )
        if status not in {SystemStatus.NORMAL, SystemStatus.SOFT_WARN}:
            return CriticDecision(
                action=CriticAction.BLOCKED,
                score=score,
                reason="resource_guard_unavailable",
                resource_status=status_text,
            )
        return CriticDecision(
            action=CriticAction.NATURAL_RERUN,
            score=score,
            reason="critic_quality_below_threshold",
            resource_status=status_text,
        )

    explicit_quality_signal = bool(kernel_score.weaknesses) or (
        kernel_score.verdict == "low_confidence"
    )
    forced_conditions_met = (
        forced_enabled
        and explicit_quality_signal
        and goal_length > 80
        and not already_reran
        and execution_retries == 0
    )
    if forced_conditions_met and status is SystemStatus.NORMAL:
        return CriticDecision(
            action=CriticAction.FORCED_RERUN,
            score=score,
            reason="server_forced_quality_review",
            resource_status=status_text,
            forced=True,
        )

    reason = (
        "forced_rerun_suppressed"
        if forced_conditions_met
        else "critic_quality_passed"
    )
    return CriticDecision(
        action=CriticAction.ACCEPT,
        score=score,
        reason=reason,
        resource_status=status_text,
    )
