"""
core/execution/recovery.py — Build failure classification + controlled retry layer.

Phases 1-2 of Build Recovery + Deployment.

Design:
  - 7 failure categories with retryability and recommended strategy
  - Bounded retry (max 3), each retry has an explicit reason
  - 5 retry strategies: stronger_model, critical_budget, simplify, template_variant, rewrite_only
  - All retries policy-safe, logged, traceable
  - Fail-open: retry failures never corrupt original build
"""
from __future__ import annotations

import time
import structlog
from dataclasses import dataclass, field
from enum import Enum

log = structlog.get_logger("execution.recovery")


# ── Phase 1: Build Failure Classification ─────────────────────

class FailureCategory(str, Enum):
    """Canonical build failure categories."""
    GENERATION     = "generation_failure"       # LLM produced bad/empty output
    FILE_WRITE     = "file_write_failure"       # Could not write to workspace
    VALIDATION     = "validation_failure"       # Output didn't pass quality checks
    MISSING_DEP    = "missing_dependency"       # Required tool/config unavailable
    DEPLOY_PREP    = "deploy_prep_failure"      # Deployment preparation failed
    DEPLOY_EXEC    = "deploy_execution_failure" # Deployment action failed
    VERIFICATION   = "verification_failure"     # Post-deploy verification failed


class FailureSeverity(str, Enum):
    LOW      = "low"       # Cosmetic, non-blocking
    MEDIUM   = "medium"    # Degraded output
    HIGH     = "high"      # Build unusable
    CRITICAL = "critical"  # System-level issue


class RetryStrategy(str, Enum):
    """Explicit retry strategies. Each retry must pick one."""
    STRONGER_MODEL    = "stronger_model"     # Use higher-quality model
    CRITICAL_BUDGET   = "critical_budget"    # Switch to critical budget mode
    SIMPLIFY          = "simplify"           # Reduce artifact complexity
    TEMPLATE_VARIANT  = "template_variant"   # Use alternative template
    REWRITE_ONLY      = "rewrite_only"       # Retry write/verify without regen


@dataclass
class BuildFailure:
    """Classified build failure with recovery guidance."""
    category: FailureCategory
    severity: FailureSeverity
    message: str
    retryable: bool
    recommended_strategy: RetryStrategy | None = None
    operator_relevant: bool = False  # Should this be surfaced to human?

    def to_dict(self) -> dict:
        return {
            "category": self.category.value,
            "severity": self.severity.value,
            "message": self.message[:300],
            "retryable": self.retryable,
            "recommended_strategy": self.recommended_strategy.value if self.recommended_strategy else None,
            "operator_relevant": self.operator_relevant,
        }


# ── Classification Rules ──────────────────────────────────────

_CLASSIFICATION_RULES: list[tuple[list[str], FailureCategory, FailureSeverity, bool, RetryStrategy | None, bool]] = [
    # (error patterns, category, severity, retryable, strategy, operator_relevant)
    (["empty output", "no content", "generation produced", "llm error", "model error"],
     FailureCategory.GENERATION, FailureSeverity.HIGH, True, RetryStrategy.STRONGER_MODEL, False),
    (["permission denied", "disk full", "write failed", "path invalid", "io error"],
     FailureCategory.FILE_WRITE, FailureSeverity.HIGH, True, RetryStrategy.REWRITE_ONLY, True),
    (["validation failed", "quality check", "spec validation", "required validation"],
     FailureCategory.VALIDATION, FailureSeverity.MEDIUM, True, RetryStrategy.CRITICAL_BUDGET, False),
    (["missing dependency", "not configured", "tool unavailable", "import error", "module not found"],
     FailureCategory.MISSING_DEP, FailureSeverity.CRITICAL, False, None, True),
    (["deploy prep", "deployment preparation", "target not ready", "eligibility"],
     FailureCategory.DEPLOY_PREP, FailureSeverity.MEDIUM, True, RetryStrategy.SIMPLIFY, False),
    (["deploy failed", "deployment error", "target unreachable", "deploy execution"],
     FailureCategory.DEPLOY_EXEC, FailureSeverity.HIGH, True, RetryStrategy.TEMPLATE_VARIANT, True),
    (["verification failed", "deployment verification", "not reachable", "missing entrypoint"],
     FailureCategory.VERIFICATION, FailureSeverity.MEDIUM, True, RetryStrategy.REWRITE_ONLY, False),
]


def classify_build_failure(error_msg: str, context: dict | None = None) -> BuildFailure:
    """Classify a build error into a structured failure with recovery guidance."""
    error_lower = error_msg.lower()

    for patterns, category, severity, retryable, strategy, operator in _CLASSIFICATION_RULES:
        if any(p in error_lower for p in patterns):
            return BuildFailure(
                category=category,
                severity=severity,
                message=error_msg[:300],
                retryable=retryable,
                recommended_strategy=strategy,
                operator_relevant=operator,
            )

    # Default: unclassified → not retryable, operator should see it
    return BuildFailure(
        category=FailureCategory.GENERATION,
        severity=FailureSeverity.HIGH,
        message=error_msg[:300],
        retryable=False,
        recommended_strategy=None,
        operator_relevant=True,
    )


# ── Phase 2: Controlled Build Retry Layer ─────────────────────

MAX_RETRIES = 3


@dataclass
class RetryAttempt:
    """Record of a single retry attempt."""
    attempt_number: int
    strategy: RetryStrategy
    reason: str
    success: bool = False
    duration_ms: float = 0
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "attempt": self.attempt_number,
            "strategy": self.strategy.value,
            "reason": self.reason,
            "success": self.success,
            "duration_ms": round(self.duration_ms),
            "error": self.error[:200],
        }


@dataclass
class RetryResult:
    """Result of the entire retry sequence."""
    original_error: str
    failure_class: BuildFailure
    attempts: list[RetryAttempt] = field(default_factory=list)
    recovered: bool = False
    final_build_result: object = None  # BuildResult when recovered

    def to_dict(self) -> dict:
        return {
            "original_error": self.original_error[:200],
            "failure_class": self.failure_class.to_dict(),
            "attempts": [a.to_dict() for a in self.attempts],
            "recovered": self.recovered,
            "total_attempts": len(self.attempts),
        }


# Strategy escalation path
_STRATEGY_ESCALATION: list[RetryStrategy] = [
    RetryStrategy.REWRITE_ONLY,
    RetryStrategy.CRITICAL_BUDGET,
    RetryStrategy.STRONGER_MODEL,
    RetryStrategy.SIMPLIFY,
    RetryStrategy.TEMPLATE_VARIANT,
]


def _pick_strategy(attempt: int, failure: BuildFailure, prev_strategies: list[RetryStrategy]) -> RetryStrategy:
    """Pick next retry strategy based on failure class and prior attempts."""
    # First try: use recommended strategy if available
    if failure.recommended_strategy and failure.recommended_strategy not in prev_strategies:
        return failure.recommended_strategy

    # Escalate through strategies
    for s in _STRATEGY_ESCALATION:
        if s not in prev_strategies:
            return s

    # All strategies exhausted: fallback
    return RetryStrategy.SIMPLIFY


def _apply_strategy(strategy: RetryStrategy, artifact, budget_mode: str) -> tuple:
    """Apply a retry strategy and return modified (artifact, budget_mode)."""
    if strategy == RetryStrategy.CRITICAL_BUDGET:
        return artifact, "critical"
    elif strategy == RetryStrategy.SIMPLIFY:
        # Reduce expected outcome complexity
        if artifact.expected_outcome:
            artifact.expected_outcome = (
                "Simplified version: " + artifact.expected_outcome[:200]
            )
        return artifact, budget_mode
    elif strategy == RetryStrategy.STRONGER_MODEL:
        return artifact, "critical"  # Critical budget uses best available model
    elif strategy == RetryStrategy.TEMPLATE_VARIANT:
        # Add variant marker to input context
        artifact.input_context = artifact.input_context or {}
        artifact.input_context["retry_variant"] = True
        artifact.input_context["retry_instructions"] = "Use alternative approach"
        return artifact, budget_mode
    else:  # REWRITE_ONLY
        return artifact, budget_mode


def retry_build(artifact, build_error: str, budget_mode: str = "normal") -> RetryResult:
    """
    Attempt bounded retries for a failed build.

    Returns RetryResult with all attempts and final outcome.
    Never raises — always returns structured result.
    """
    failure = classify_build_failure(build_error)
    result = RetryResult(
        original_error=build_error,
        failure_class=failure,
    )

    if not failure.retryable:
        log.info("build_not_retryable", category=failure.category.value, err=build_error[:80])
        return result

    from core.execution.build_pipeline import BuildPipeline
    pipeline = BuildPipeline()
    used_strategies: list[RetryStrategy] = []

    for attempt_num in range(1, MAX_RETRIES + 1):
        strategy = _pick_strategy(attempt_num, failure, used_strategies)
        used_strategies.append(strategy)
        reason = f"Retry {attempt_num}/{MAX_RETRIES}: {strategy.value} for {failure.category.value}"

        attempt = RetryAttempt(
            attempt_number=attempt_num,
            strategy=strategy,
            reason=reason,
        )

        t0 = time.time()
        try:
            # Apply strategy modifications
            modified_artifact, modified_budget = _apply_strategy(
                strategy, artifact, budget_mode
            )

            # Reset artifact status for retry
            from core.execution.artifacts import ArtifactStatus
            modified_artifact.status = ArtifactStatus.SPEC

            # Execute build
            build_result = pipeline.build(modified_artifact, modified_budget)
            attempt.duration_ms = (time.time() - t0) * 1000

            if build_result.success:
                attempt.success = True
                result.attempts.append(attempt)
                result.recovered = True
                result.final_build_result = build_result
                log.info("build_retry_success", attempt=attempt_num, strategy=strategy.value)
                return result
            else:
                attempt.error = build_result.error[:200]
                # Re-classify for next attempt
                failure = classify_build_failure(build_result.error)

        except Exception as e:
            attempt.duration_ms = (time.time() - t0) * 1000
            attempt.error = str(e)[:200]

        result.attempts.append(attempt)
        log.info("build_retry_failed", attempt=attempt_num, strategy=strategy.value, err=attempt.error[:60])

    return result
