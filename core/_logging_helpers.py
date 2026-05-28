"""Logging helpers for safe exception swallowing.

Audit follow-up (M3): historically the codebase used
    try: ...
    except Exception:
        _silent_log.debug("suppressed_exception", src=__file__)

This swallows errors at DEBUG level — invisible in production. The result was
~84 blocks where bugs were silently absorbed and never reported.

The `swallow` helpers below replace that pattern with:
  - WARNING level by default (visible in prod logs)
  - exception class and message captured automatically (exc_info=True)
  - a required `action` field describing what was being attempted
  - free-form context kwargs for the surrounding state

Two usage shapes are supported:

    # Context manager (preferred for blocks):
    with swallow(log, action="emit_agent_result", agent=self.name):
        emit_agent_result(...)

    # Decorator (for whole helper functions):
    @swallowing(log, action="cleanup_session")
    def _cleanup(self): ...

Both re-raise nothing — they intentionally absorb the exception, but loudly.

Use a stricter `level="error"` if the absorbed condition is closer to a real
bug; use `level="info"` for cleanup paths that legitimately may fail.
Avoid `level="debug"` — that defeats the purpose. The helper rejects it.
"""
from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Iterator, TypeVar

# Allowed log levels. DEBUG is intentionally excluded — that's the bad
# legacy behaviour we are migrating away from.
_ALLOWED_LEVELS = {"info", "warning", "error"}

F = TypeVar("F", bound=Callable[..., Any])


@contextmanager
def swallow(
    log: Any,
    *,
    action: str,
    level: str = "warning",
    **context: Any,
) -> Iterator[None]:
    """Absorb any exception in the block and log it at `level` with `action`.

    Args:
        log: a structlog/stdlib logger.
        action: short identifier of what was being attempted (e.g. "emit_event").
        level: "info", "warning" (default), or "error". DEBUG is rejected.
        **context: extra fields included in the structured log entry.

    Re-raises nothing. KeyboardInterrupt and SystemExit pass through so the
    process can still be stopped cleanly.
    """
    if level not in _ALLOWED_LEVELS:
        raise ValueError(
            f"swallow(level={level!r}) is not allowed. "
            f"Pick one of {_ALLOWED_LEVELS}. "
            "If you need silent absorption, you almost certainly do not."
        )
    if not action or not isinstance(action, str):
        raise ValueError("swallow(action=...) is required and must be a non-empty string.")

    try:
        yield
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:  # noqa: BLE001 — that is the whole point
        emit = getattr(log, level)
        emit(
            "swallowed_exception",
            action=action,
            exc_type=type(exc).__name__,
            exc_msg=str(exc)[:200],
            **context,
        )


def swallowing(
    log: Any,
    *,
    action: str,
    level: str = "warning",
    **context: Any,
) -> Callable[[F], F]:
    """Decorator form of :func:`swallow` for whole functions.

    Example:
        @swallowing(log, action="reload_plugins")
        def _refresh(self): ...

    The wrapped callable returns None when an exception is absorbed.
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with swallow(log, action=action, level=level, **context):
                return func(*args, **kwargs)
            return None
        return wrapper  # type: ignore[return-value]
    return decorator
