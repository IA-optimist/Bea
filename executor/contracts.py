"""
executor/contracts.py — Unified execution result contract.

Every execution in BeaMax returns an ExecutionResult.
No ambiguity. No fake success. Brutally honest.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum


class ExecutionStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"
    PENDING_APPROVAL = "pending_approval"


class ErrorClass(str, Enum):
    NONE = "none"
    TOOL_NOT_AVAILABLE = "tool_not_available"
    DEPENDENCY_FAILURE = "dependency_failure"
    TIMEOUT = "timeout"
    INVALID_INPUT = "invalid_input"
    PERMISSION_DENIED = "permission_denied"
    EXECUTION_EXCEPTION = "execution_exception"
    VALIDATION_FAILED = "validation_failed"
    LLM_UNAVAILABLE = "llm_unavailable"
    EXTERNAL_SERVICE_FAILURE = "external_service_failure"
    RATE_LIMITED = "rate_limited"
    UNKNOWN = "unknown"


@dataclass
class ExecutionResult:
    """
    Canonical execution result. Every tool, action, and task execution
    MUST return this contract. No exceptions.
    """
    execution_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    task_id: str = ""
    status: ExecutionStatus = ExecutionStatus.FAILED
    success: bool = False

    # Error details
    error_class: ErrorClass = ErrorClass.NONE
    error_message: str = ""
    retryable: bool = False

    # Timing
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    duration_ms: int = 0

    # Context
    tool_used: str = ""
    risk_level: str = "low"
    confidence: float = 0.0

    # Output
    raw_output: str = ""
    normalized_output: str = ""
    validation_status: str = "unvalidated"  # validated / invalid / unvalidated

    # Retry info
    attempt: int = 1
    max_retries: int = 0

    def complete(self, success: bool, output: str = "", error: str = "") -> "ExecutionResult":
        """Finalize the result. Call this when execution is done."""
        self.finished_at = time.time()
        self.duration_ms = int((self.finished_at - self.started_at) * 1000)
        self.success = success
        self.status = ExecutionStatus.SUCCESS if success else ExecutionStatus.FAILED
        if success:
            self.raw_output = output
            self.normalized_output = output[:2000]
            self.error_class = ErrorClass.NONE
        else:
            self.error_message = error[:500]
            if not self.error_class or self.error_class == ErrorClass.NONE:
                self.error_class = classify_error(error)
            self.retryable = self.error_class in _RETRYABLE
        return self

    def to_dict(self) -> dict[str, object]:
        return {
            "execution_id": self.execution_id,
            "task_id": self.task_id,
            "status": self.status.value,
            "success": self.success,
            "error_class": self.error_class.value,
            "error_message": self.error_message[:200],
            "retryable": self.retryable,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "tool_used": self.tool_used,
            "risk_level": self.risk_level,
            "confidence": self.confidence,
            "raw_output": self.raw_output[:500],
            "normalized_output": self.normalized_output[:500],
            "validation_status": self.validation_status,
            "attempt": self.attempt,
        }


# ── Error classification ─────────────────────────────────────

_RETRYABLE = {
    ErrorClass.TIMEOUT,
    ErrorClass.EXTERNAL_SERVICE_FAILURE,
    ErrorClass.LLM_UNAVAILABLE,
    ErrorClass.RATE_LIMITED,
    ErrorClass.DEPENDENCY_FAILURE,
}


def classify_error(error: str) -> ErrorClass:
    """Classify an error string into an ErrorClass."""
    if not error:
        return ErrorClass.NONE
    e = error.lower()
    if "timeout" in e:
        return ErrorClass.TIMEOUT
    if "permission" in e or "denied" in e or "forbidden" in e:
        return ErrorClass.PERMISSION_DENIED
    if "not found" in e or "no such" in e or "does not exist" in e:
        return ErrorClass.TOOL_NOT_AVAILABLE
    if "rate" in e and "limit" in e:
        return ErrorClass.RATE_LIMITED
    if "connection" in e or "network" in e or "unreachable" in e:
        return ErrorClass.EXTERNAL_SERVICE_FAILURE
    if "llm" in e or "openai" in e or "anthropic" in e or "model" in e:
        return ErrorClass.LLM_UNAVAILABLE
    if "invalid" in e or "validation" in e or "format" in e:
        return ErrorClass.VALIDATION_FAILED
    if "depend" in e or "missing" in e or "import" in e:
        return ErrorClass.DEPENDENCY_FAILURE
    return ErrorClass.UNKNOWN


def is_retryable(error_class: ErrorClass) -> bool:
    return error_class in _RETRYABLE
