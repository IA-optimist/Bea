"""
core/autonomy/stop_conditions.py — Composable stop predicates.

Stop conditions are pure functions of (context) → bool that the daemon
evaluates at every iteration. The daemon halts the current run when any
condition returns True. Conditions compose with `Any(*conds)` and
`All(*conds)` so policies are declarative.

Built-ins :

- TimeoutCondition(seconds)         — wall-clock deadline
- BudgetCondition(tracker, scope)   — wraps BudgetTracker
- ConfidenceCondition(min_value)    — current_state.confidence < min
- IterationCondition(max_iters)     — capped loop count
- ExternalSignalCondition(bus, topic) — true once a topic fires once
- AlwaysFalse / AlwaysTrue         — test fixtures

This is intentionally small and dependency-free so it can be imported
from the daemon, mission_system, supervised_executor, etc.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from core.autonomy.event_bus import EventBus


# ── Context passed to every condition ────────────────────────
@dataclass
class StopContext:
    """All the live state a condition might inspect."""
    started_at: float = field(default_factory=time.time)
    iteration: int = 0
    confidence: float = 1.0
    consecutive_failures: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def elapsed_s(self) -> float:
        return time.time() - self.started_at


StopCheck = Callable[[StopContext], bool]


# ── Concrete predicates (factories returning callables) ──────
def timeout_condition(max_seconds: float) -> StopCheck:
    def check(ctx: StopContext) -> bool:
        return ctx.elapsed_s > max_seconds
    check.__name__ = f"timeout({max_seconds}s)"  # type: ignore[attr-defined]
    return check


def confidence_condition(min_confidence: float) -> StopCheck:
    def check(ctx: StopContext) -> bool:
        return ctx.confidence < min_confidence
    check.__name__ = f"confidence<{min_confidence}"  # type: ignore[attr-defined]
    return check


def iteration_condition(max_iterations: int) -> StopCheck:
    def check(ctx: StopContext) -> bool:
        return ctx.iteration >= max_iterations
    check.__name__ = f"iter>={max_iterations}"  # type: ignore[attr-defined]
    return check


def consecutive_failures_condition(max_failures: int) -> StopCheck:
    def check(ctx: StopContext) -> bool:
        return ctx.consecutive_failures >= max_failures
    check.__name__ = f"failures>={max_failures}"  # type: ignore[attr-defined]
    return check


def external_signal_condition(bus: EventBus, topic_pattern: str) -> StopCheck:
    """Stop when a topic matching the pattern has been published."""
    seen = {"hit": False}

    def handler(_event):
        seen["hit"] = True

    bus.subscribe(topic_pattern, handler)

    def check(_ctx: StopContext) -> bool:
        return seen["hit"]
    check.__name__ = f"signal({topic_pattern})"  # type: ignore[attr-defined]
    return check


def always_false() -> StopCheck:
    def check(_ctx: StopContext) -> bool:
        return False
    check.__name__ = "never"  # type: ignore[attr-defined]
    return check


def always_true() -> StopCheck:
    def check(_ctx: StopContext) -> bool:
        return True
    check.__name__ = "always"  # type: ignore[attr-defined]
    return check


# ── Combinators ──────────────────────────────────────────────
def any_of(*conditions: StopCheck) -> StopCheck:
    """Stop when any condition returns True."""
    def check(ctx: StopContext) -> bool:
        return any(c(ctx) for c in conditions)
    check.__name__ = "any(" + ",".join(getattr(c, "__name__", "?") for c in conditions) + ")"  # type: ignore[attr-defined]
    return check


def all_of(*conditions: StopCheck) -> StopCheck:
    """Stop only when every condition returns True."""
    def check(ctx: StopContext) -> bool:
        return all(c(ctx) for c in conditions)
    check.__name__ = "all(" + ",".join(getattr(c, "__name__", "?") for c in conditions) + ")"  # type: ignore[attr-defined]
    return check


# ── Convenience : default policy for a mission ───────────────
def default_mission_policy(
    max_seconds: float = 1800,
    max_iterations: int = 50,
    min_confidence: float = 0.0,
    max_consecutive_failures: int = 3,
) -> StopCheck:
    """Reasonable default : 30 min, 50 iters, 3 consecutive failures."""
    checks: List[StopCheck] = []
    if max_seconds > 0:
        checks.append(timeout_condition(max_seconds))
    if max_iterations > 0:
        checks.append(iteration_condition(max_iterations))
    if min_confidence > 0:
        checks.append(confidence_condition(min_confidence))
    if max_consecutive_failures > 0:
        checks.append(consecutive_failures_condition(max_consecutive_failures))
    if not checks:
        return always_false()
    return any_of(*checks)


def reason(condition: StopCheck, ctx: Optional[StopContext] = None) -> str:
    """Human-readable description of why a condition triggered."""
    return getattr(condition, "__name__", str(condition))
