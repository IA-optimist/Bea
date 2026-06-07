"""
core/resilience.py — Reliability guards for Bea v1.

Provides:
- Standardized error envelopes
- Circuit breaker for tool execution
- Context size guard
- Timeout guards
- Graceful degradation helpers
- Idempotency key generation

Does NOT modify MetaOrchestrator, CanonicalAction, or FinalOutput schemas.
Acts as defensive middleware.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Literal, Optional

log = logging.getLogger("bea.resilience")


# ── Standardized Error Envelope ───────────────────────────────────────────────

@dataclass
class BeaError:
    """Standardized error across all Bea components."""
    code: str                    # machine-readable: TOOL_TIMEOUT, POLICY_BLOCKED, etc.
    message: str                 # human-readable
    component: str               # orchestrator, executor, policy, tool, memory, api
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    retryable: bool = False
    trace_id: str = ""
    mission_id: str = ""
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_exception(cls, exc: Exception, component: str = "unknown",
                       trace_id: str = "", mission_id: str = "") -> "BeaError":
        """Build error from an exception."""
        code = _classify_exception(exc)
        return cls(
            code=code,
            message=str(exc)[:500],
            component=component,
            severity=_severity_for_code(code),
            retryable=code in _RETRYABLE_CODES,
            trace_id=trace_id,
            mission_id=mission_id,
        )


# Error classification
_RETRYABLE_CODES = {"TOOL_TIMEOUT", "TOOL_TRANSIENT", "LLM_TIMEOUT", "LLM_RATE_LIMIT"}

def _classify_exception(exc: Exception) -> str:
    # Check exception type first
    if isinstance(exc, (TimeoutError,)):
        return "TOOL_TIMEOUT"
    msg = str(exc).lower()
    if "timeout" in msg: return "TOOL_TIMEOUT"
    if "rate_limit" in msg or "429" in msg: return "LLM_RATE_LIMIT"
    if "connection" in msg: return "TOOL_TRANSIENT"
    if "permission" in msg or "denied" in msg: return "PERMISSION_DENIED"
    if "json" in msg or "parse" in msg: return "PARSE_ERROR"
    if "memory" in msg: return "MEMORY_ERROR"
    return "INTERNAL_ERROR"

def _severity_for_code(code: str) -> str:
    if code in ("PERMISSION_DENIED", "INTERNAL_ERROR"): return "HIGH"
    if code in ("TOOL_TIMEOUT", "LLM_RATE_LIMIT"): return "MEDIUM"
    if code in ("TOOL_TRANSIENT", "PARSE_ERROR"): return "LOW"
    return "MEDIUM"


# ── Circuit Breaker ───────────────────────────────────────────────────────────



# ── Structured Error Types ────────────────────────────────────────────────

class BeaExecutionError(Exception):
    """Structured execution error with canonical taxonomy.
    
    Standalone class (not inheriting BeaError dataclass) to avoid
    dataclass __init__ conflicts.
    """
    
    def __init__(self, message: str = "", *, tool: str = "", stage: str = "execution",
                 cause: str = "", severity: str = "MEDIUM", retryable: bool = False,
                 error_type: str = "TOOL_ERROR"):
        super().__init__(message or cause or "Unknown execution error")
        self.tool = tool
        self.stage = stage
        self.cause = cause
        self.severity = severity
        self.retryable = retryable
        self.error_type = error_type
    
    def to_dict(self) -> dict:
        return {
            "type": self.error_type,
            "retryable": self.retryable,
            "message": str(self),
            "tool": self.tool,
            "stage": self.stage,
            "severity": self.severity,
            "cause": self.cause,
        }

    @classmethod
    def from_exception(cls, exc: Exception, tool: str = "", stage: str = "execution"):
        """Classify any exception into a structured BeaExecutionError."""
        exc_name = type(exc).__name__
        
        # Classification map — order matters (specific before general)
        if isinstance(exc, TimeoutError) or "timeout" in str(exc).lower():
            return cls(str(exc), tool=tool, stage=stage, cause=exc_name,
                      severity="MEDIUM", retryable=True, error_type="TIMEOUT")
        elif isinstance(exc, PermissionError) or "blocked" in str(exc).lower():
            return cls(str(exc), tool=tool, stage=stage, cause=exc_name,
                      severity="HIGH", retryable=False, error_type="POLICY_BLOCKED")
        elif isinstance(exc, (FileNotFoundError, ModuleNotFoundError, ImportError)):
            # Must come BEFORE OSError (FileNotFoundError is a subclass)
            return cls(str(exc), tool=tool, stage=stage, cause=exc_name,
                      severity="MEDIUM", retryable=False, error_type="SYSTEM_ERROR")
        elif isinstance(exc, (ConnectionError, OSError)):
            return cls(str(exc), tool=tool, stage=stage, cause=exc_name,
                      severity="MEDIUM", retryable=True, error_type="TRANSIENT")
        elif isinstance(exc, (ValueError, TypeError, KeyError)):
            return cls(str(exc), tool=tool, stage=stage, cause=exc_name,
                      severity="LOW", retryable=False, error_type="USER_INPUT")
        else:
            return cls(str(exc), tool=tool, stage=stage, cause=exc_name,
                      severity="MEDIUM", retryable=False, error_type="TOOL_ERROR")


# Error type constants
ERROR_TYPES = ("TRANSIENT", "USER_INPUT", "TOOL_ERROR", "POLICY_BLOCKED", "TIMEOUT", "SYSTEM_ERROR")


class CircuitBreaker:
    """
    Circuit breaker for tool execution.

    States: CLOSED (normal) → OPEN (blocking) → HALF_OPEN (testing)

    After `failure_threshold` consecutive failures, circuit opens.
    After `recovery_timeout` seconds, allows a single test call (HALF_OPEN).
    If test succeeds, circuit closes. If test fails, circuit re-opens.
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self._lock = threading.Lock()
        self._tools: dict[str, dict] = {}
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

    def can_execute(self, tool_name: str) -> bool:
        """Check if tool is allowed to execute."""
        with self._lock:
            state = self._tools.get(tool_name)
            if state is None:
                return True
            if state["circuit"] == "CLOSED":
                return True
            if state["circuit"] == "OPEN":
                if time.time() - state["opened_at"] > self.recovery_timeout:
                    state["circuit"] = "HALF_OPEN"
                    return True
                return False
            if state["circuit"] == "HALF_OPEN":
                return True  # Allow test call
            return True

    def record_success(self, tool_name: str) -> None:
        with self._lock:
            state = self._tools.get(tool_name, {})
            state["consecutive_failures"] = 0
            state["circuit"] = "CLOSED"
            self._tools[tool_name] = state

    def record_failure(self, tool_name: str) -> None:
        with self._lock:
            if tool_name not in self._tools:
                self._tools[tool_name] = {
                    "consecutive_failures": 0,
                    "circuit": "CLOSED",
                    "opened_at": 0,
                }
            state = self._tools[tool_name]
            state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1

            if state["circuit"] == "HALF_OPEN":
                state["circuit"] = "OPEN"
                state["opened_at"] = time.time()
            elif state["consecutive_failures"] >= self.failure_threshold:
                state["circuit"] = "OPEN"
                state["opened_at"] = time.time()
                log.warning("circuit_opened: tool=%s failures=%s", tool_name,
                           state["consecutive_failures"])

    def get_status(self, tool_name: str) -> str:
        with self._lock:
            state = self._tools.get(tool_name)
            return state["circuit"] if state else "CLOSED"

    def stats(self) -> dict:
        with self._lock:
            return {
                tool: {"circuit": s["circuit"], "failures": s.get("consecutive_failures", 0)}
                for tool, s in self._tools.items()
            }


# ── Context Size Guard ────────────────────────────────────────────────────────

MAX_CONTEXT_TOKENS = 8000  # Safe limit for mistral:7b
MAX_CONTEXT_CHARS = MAX_CONTEXT_TOKENS * 4  # ~4 chars per token

def guard_context(text: str, max_chars: int = MAX_CONTEXT_CHARS, label: str = "") -> str:
    """Truncate context if it exceeds safe limits. Preserves start and end."""
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    truncated = text[:half] + f"\n\n[... truncated {len(text) - max_chars} chars ...]\n\n" + text[-half:]
    log.info("context_truncated: label=%s orig=%d trunc=%d", label, len(text), len(truncated))
    return truncated


def estimate_tokens(text: str) -> int:
    """Rough token count estimate (~4 chars per token)."""
    return len(text) // 4


# ── Timeout Guard ─────────────────────────────────────────────────────────────

def timeout_guard(max_seconds: float = 120.0, start_time: float = 0.0) -> Optional[str]:
    """Check if execution has exceeded timeout. Returns error string or None."""
    if start_time <= 0:
        return None
    elapsed = time.time() - start_time
    if elapsed > max_seconds:
        return f"execution_timeout: {elapsed:.1f}s > {max_seconds}s"
    return None


# ── Idempotency ───────────────────────────────────────────────────────────────

def idempotency_key(tool_name: str, params: dict) -> str:
    """Generate a deterministic key for deduplication of tool calls."""
    import json
    raw = f"{tool_name}:{json.dumps(params, sort_keys=True, default=str)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ── Graceful Degradation ─────────────────────────────────────────────────────

def degrade_gracefully(operation: str, fallback_value: Any = None,
                       log_error: bool = True):
    """Decorator for graceful degradation — returns fallback on exception."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                if log_error:
                    log.warning("graceful_degradation: op=%s err=%s",
                              operation,
                              str(exc)[:200])
                return fallback_value
        wrapper.__name__ = func.__name__
        return wrapper
    return decorator


# ── Singleton ─────────────────────────────────────────────────────────────────

_breaker: CircuitBreaker | None = None

def get_circuit_breaker() -> CircuitBreaker:
    global _breaker
    if _breaker is None:
        _breaker = CircuitBreaker()
    return _breaker
