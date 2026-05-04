"""
core/resilience/recovery_engine.py — Structured error recovery for AI OS.

When a tool execution or mission step fails, the recovery engine:
1. Classifies the error
2. Selects a recovery strategy
3. Executes recovery (retry, switch tool, replan, ask clarification, abort)
4. Records decision in trace

Integrates into MetaOrchestrator execute phase (Phase 5) and
review phase (Phase 6).
"""
from __future__ import annotations

import structlog
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

log = structlog.get_logger("jarvis.recovery_engine")


# ── Recovery Strategies ──────────────────────────────────────────────────────

class RecoveryStrategy(str, Enum):
    RETRY = "retry"
    SWITCH_TOOL = "switch_tool"
    REPLAN = "replan"
    ASK_CLARIFICATION = "ask_clarification"
    ABORT_SAFELY = "abort_safely"
    FALLBACK_MODEL = "fallback_model"
    DEGRADE_GRACEFULLY = "degrade_gracefully"


# ── Error Classification ─────────────────────────────────────────────────────

class ErrorCategory(str, Enum):
    TRANSIENT = "TRANSIENT"       # Network, rate limit, temporary
    TIMEOUT = "TIMEOUT"           # Operation took too long
    TOOL_ERROR = "TOOL_ERROR"     # Tool logic failure
    USER_INPUT = "USER_INPUT"     # Bad input from user
    POLICY_BLOCKED = "POLICY_BLOCKED"  # Policy denied
    SYSTEM_ERROR = "SYSTEM_ERROR"      # Internal error
    LLM_ERROR = "LLM_ERROR"           # LLM failure


# Strategy matrix: error_category → ordered list of strategies to try
STRATEGY_MATRIX: dict[ErrorCategory, list[RecoveryStrategy]] = {
    ErrorCategory.TRANSIENT: [
        RecoveryStrategy.RETRY,
        RecoveryStrategy.FALLBACK_MODEL,
        RecoveryStrategy.DEGRADE_GRACEFULLY,
    ],
    ErrorCategory.TIMEOUT: [
        RecoveryStrategy.RETRY,
        RecoveryStrategy.SWITCH_TOOL,
        RecoveryStrategy.DEGRADE_GRACEFULLY,
    ],
    ErrorCategory.TOOL_ERROR: [
        RecoveryStrategy.SWITCH_TOOL,
        RecoveryStrategy.REPLAN,
        RecoveryStrategy.ABORT_SAFELY,
    ],
    ErrorCategory.USER_INPUT: [
        RecoveryStrategy.ASK_CLARIFICATION,
        RecoveryStrategy.ABORT_SAFELY,
    ],
    ErrorCategory.POLICY_BLOCKED: [
        RecoveryStrategy.ASK_CLARIFICATION,
        RecoveryStrategy.ABORT_SAFELY,
    ],
    ErrorCategory.SYSTEM_ERROR: [
        RecoveryStrategy.RETRY,
        RecoveryStrategy.DEGRADE_GRACEFULLY,
        RecoveryStrategy.ABORT_SAFELY,
    ],
    ErrorCategory.LLM_ERROR: [
        RecoveryStrategy.FALLBACK_MODEL,
        RecoveryStrategy.RETRY,
        RecoveryStrategy.DEGRADE_GRACEFULLY,
    ],
}


# ── Recovery Decision ────────────────────────────────────────────────────────

@dataclass
class RecoveryDecision:
    """Outcome of recovery engine evaluation."""
    strategy: RecoveryStrategy
    error_category: ErrorCategory
    original_error: str
    reasoning: str
    retry_count: int = 0
    max_retries: int = 2
    alternative_tool: str = ""
    wait_seconds: float = 0
    should_abort: bool = False
    trace_data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy.value,
            "error_category": self.error_category.value,
            "original_error": self.original_error[:200],
            "reasoning": self.reasoning,
            "retry_count": self.retry_count,
            "alternative_tool": self.alternative_tool,
            "wait_seconds": self.wait_seconds,
            "should_abort": self.should_abort,
        }


# ── Recovery Context ─────────────────────────────────────────────────────────

@dataclass
class RecoveryContext:
    """Tracks recovery state for a mission."""
    mission_id: str
    attempts: list[RecoveryDecision] = field(default_factory=list)
    retry_counts: dict[str, int] = field(default_factory=dict)  # tool → retries
    switched_tools: list[str] = field(default_factory=list)
    total_recovery_time: float = 0
    max_total_retries: int = 5

    @property
    def total_retries(self) -> int:
        return sum(self.retry_counts.values())

    def can_retry(self, tool_name: str, max_per_tool: int = 2) -> bool:
        """Check if we can retry this tool."""
        tool_retries = self.retry_counts.get(tool_name, 0)
        return tool_retries < max_per_tool and self.total_retries < self.max_total_retries

    def record_retry(self, tool_name: str):
        self.retry_counts[tool_name] = self.retry_counts.get(tool_name, 0) + 1

    def record_switch(self, from_tool: str, to_tool: str):
        self.switched_tools.append(f"{from_tool}→{to_tool}")


# ── Mission Recovery Tracking ────────────────────────────────────────────────

_active_contexts: dict[str, RecoveryContext] = {}


def _get_context(mission_id: str) -> RecoveryContext:
    if mission_id not in _active_contexts:
        _active_contexts[mission_id] = RecoveryContext(mission_id=mission_id)
    return _active_contexts[mission_id]


def _cleanup_context(mission_id: str):
    _active_contexts.pop(mission_id, None)


# ── Error Classifier ─────────────────────────────────────────────────────────

def classify_error(error: str | Exception) -> ErrorCategory:
    """Classify an error into a recovery category."""
    if isinstance(error, Exception):
        type(error).__name__
        msg = str(error).lower()
    else:
        msg = str(error).lower()

    # Check exception type first (subclass order matters!)
    if isinstance(error, TimeoutError):
        return ErrorCategory.TIMEOUT
    if isinstance(error, PermissionError):
        return ErrorCategory.POLICY_BLOCKED
    if isinstance(error, (ConnectionError, OSError)):
        return ErrorCategory.TRANSIENT
    if isinstance(error, (ValueError, TypeError)):
        return ErrorCategory.USER_INPUT

    # String-based classification
    if "timeout" in msg or "timed out" in msg:
        return ErrorCategory.TIMEOUT
    if any(kw in msg for kw in ("rate_limit", "429", "too many requests", "throttle")):
        return ErrorCategory.TRANSIENT
    if any(kw in msg for kw in ("connection", "network", "dns", "refused", "unreachable")):
        return ErrorCategory.TRANSIENT
    if any(kw in msg for kw in ("permission", "denied", "forbidden", "unauthorized", "policy")):
        return ErrorCategory.POLICY_BLOCKED
    if any(kw in msg for kw in ("invalid input", "missing required", "validation")):
        return ErrorCategory.USER_INPUT
    if any(kw in msg for kw in ("llm", "model", "openai", "openrouter", "anthropic", "completion")):
        return ErrorCategory.LLM_ERROR

    return ErrorCategory.TOOL_ERROR


# ── Tool Alternatives ────────────────────────────────────────────────────────

# Map tools to alternatives that can serve similar functions
TOOL_ALTERNATIVES: dict[str, list[str]] = {
    "web_search": ["web_fetch"],
    "web_fetch": ["web_search"],
    "http_get": ["web_fetch"],
    "shell_command": ["python_snippet"],
    "python_snippet": ["shell_command"],
    "file_read": ["shell_command"],
}


def _find_alternative_tool(failed_tool: str, already_tried: list[str]) -> str:
    """Find an alternative tool that hasn't been tried yet."""
    alternatives = TOOL_ALTERNATIVES.get(failed_tool, [])
    for alt in alternatives:
        if alt not in already_tried:
            return alt
    return ""


# ── Backoff Calculator ───────────────────────────────────────────────────────

def _calculate_backoff(retry_count: int, base: float = 1.0, max_wait: float = 30.0) -> float:
    """Exponential backoff with jitter."""
    import random
    wait = min(base * (2 ** retry_count), max_wait)
    jitter = wait * 0.2 * (random.random() * 2 - 1)  # ±20%
    return max(0.1, wait + jitter)


# ── Recovery Engine ──────────────────────────────────────────────────────────

class RecoveryEngine:
    """Structured error recovery for AI OS missions."""

    def evaluate(self, error: str | Exception, tool_name: str = "",
                 mission_id: str = "") -> RecoveryDecision:
        """Evaluate error and decide recovery strategy.

        This is the main entry point. Called after tool execution failure.
        """
        ctx = _get_context(mission_id)
        category = classify_error(error)
        strategies = STRATEGY_MATRIX.get(category, [RecoveryStrategy.ABORT_SAFELY])

        error_str = str(error)[:300]

        # Try each strategy in order
        for strategy in strategies:
            decision = self._evaluate_strategy(strategy, category, error_str,
                                                tool_name, ctx)
            if decision:
                ctx.attempts.append(decision)
                log.info("recovery_decided",
                         strategy=strategy.value,
                         category=category.value,
                         tool=tool_name,
                         mission=mission_id,
                         reasoning=decision.reasoning[:80])
                return decision

        # All strategies exhausted → abort
        decision = RecoveryDecision(
            strategy=RecoveryStrategy.ABORT_SAFELY,
            error_category=category,
            original_error=error_str,
            reasoning="All recovery strategies exhausted",
            should_abort=True,
        )
        ctx.attempts.append(decision)
        return decision

    def _evaluate_strategy(self, strategy: RecoveryStrategy,
                            category: ErrorCategory, error: str,
                            tool_name: str,
                            ctx: RecoveryContext) -> Optional[RecoveryDecision]:
        """Evaluate if a specific strategy is viable."""

        if strategy == RecoveryStrategy.RETRY:
            if ctx.can_retry(tool_name):
                retry_count = ctx.retry_counts.get(tool_name, 0)
                wait = _calculate_backoff(retry_count)
                ctx.record_retry(tool_name)
                return RecoveryDecision(
                    strategy=RecoveryStrategy.RETRY,
                    error_category=category,
                    original_error=error,
                    reasoning=f"Retry {tool_name} (attempt {retry_count + 1})",
                    retry_count=retry_count + 1,
                    wait_seconds=wait,
                )
            return None  # Can't retry anymore

        elif strategy == RecoveryStrategy.SWITCH_TOOL:
            alt = _find_alternative_tool(tool_name, ctx.switched_tools + [tool_name])
            if alt:
                ctx.record_switch(tool_name, alt)
                return RecoveryDecision(
                    strategy=RecoveryStrategy.SWITCH_TOOL,
                    error_category=category,
                    original_error=error,
                    reasoning=f"Switch from {tool_name} to {alt}",
                    alternative_tool=alt,
                )
            return None  # No alternative available

        elif strategy == RecoveryStrategy.FALLBACK_MODEL:
            return RecoveryDecision(
                strategy=RecoveryStrategy.FALLBACK_MODEL,
                error_category=category,
                original_error=error,
                reasoning="Switch to fallback LLM model",
            )

        elif strategy == RecoveryStrategy.REPLAN:
            return RecoveryDecision(
                strategy=RecoveryStrategy.REPLAN,
                error_category=category,
                original_error=error,
                reasoning=f"Tool {tool_name} failed — replanning mission steps",
            )

        elif strategy == RecoveryStrategy.ASK_CLARIFICATION:
            return RecoveryDecision(
                strategy=RecoveryStrategy.ASK_CLARIFICATION,
                error_category=category,
                original_error=error,
                reasoning=f"Need clarification: {error[:80]}",
            )

        elif strategy == RecoveryStrategy.DEGRADE_GRACEFULLY:
            return RecoveryDecision(
                strategy=RecoveryStrategy.DEGRADE_GRACEFULLY,
                error_category=category,
                original_error=error,
                reasoning="Degraded: returning partial result",
            )

        elif strategy == RecoveryStrategy.ABORT_SAFELY:
            return RecoveryDecision(
                strategy=RecoveryStrategy.ABORT_SAFELY,
                error_category=category,
                original_error=error,
                reasoning="Aborting mission safely",
                should_abort=True,
            )

        return None

    def execute_recovery(self, decision: RecoveryDecision,
                          tool_executor=None,
                          original_params: dict | None = None) -> dict:
        """Execute the recovery strategy and return result.

        Returns a dict compatible with ToolExecutor result format.
        """
        time.time()

        if decision.strategy == RecoveryStrategy.RETRY:
            if decision.wait_seconds > 0:
                time.sleep(min(decision.wait_seconds, 5))  # Cap wait in-process
            if tool_executor and original_params:
                result = tool_executor.execute(
                    decision.trace_data.get("tool_name", ""),
                    original_params,
                )
                result["_recovery"] = decision.to_dict()
                return result
            return {"ok": False, "error": "No executor for retry", "_recovery": decision.to_dict()}

        elif decision.strategy == RecoveryStrategy.SWITCH_TOOL:
            if tool_executor and original_params and decision.alternative_tool:
                result = tool_executor.execute(
                    decision.alternative_tool,
                    original_params,
                )
                result["_recovery"] = decision.to_dict()
                return result
            return {"ok": False, "error": "No alternative tool", "_recovery": decision.to_dict()}

        elif decision.strategy == RecoveryStrategy.ABORT_SAFELY:
            return {
                "ok": False,
                "error": f"Mission aborted: {decision.original_error[:100]}",
                "aborted": True,
                "_recovery": decision.to_dict(),
            }

        # For strategies that don't execute tools (replan, ask_clarification, etc.)
        return {
            "ok": False,
            "error": decision.reasoning,
            "needs_action": decision.strategy.value,
            "_recovery": decision.to_dict(),
        }

    def cleanup(self, mission_id: str):
        """Clean up recovery context after mission completes."""
        ctx = _active_contexts.pop(mission_id, None)
        if ctx and ctx.attempts:
            log.info("recovery_cleanup",
                     mission=mission_id,
                     total_attempts=len(ctx.attempts),
                     total_retries=ctx.total_retries,
                     switches=len(ctx.switched_tools))

    def stats(self) -> dict:
        """Recovery engine statistics."""
        return {
            "active_contexts": len(_active_contexts),
            "total_strategies": len(RecoveryStrategy),
            "strategy_matrix_rules": sum(len(v) for v in STRATEGY_MATRIX.values()),
            "tool_alternatives": len(TOOL_ALTERNATIVES),
        }


# ── Singleton ────────────────────────────────────────────────────────────────

_engine: RecoveryEngine | None = None


def get_recovery_engine() -> RecoveryEngine:
    global _engine
    if _engine is None:
        _engine = RecoveryEngine()
    return _engine
