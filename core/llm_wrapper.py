"""
core/llm_wrapper.py — Drop-in instrumentation for LLMFactory.

Wraps `core.llm_factory.LLMFactory.safe_invoke()` so every successful
LLM call also writes a record into the training collector. The wrap is
idempotent and additive : the original behaviour (Langfuse trace,
circuit breaker, fallback cascade) is preserved verbatim. Only one
extra fire-and-forget call is added at the end of a successful
invocation.

Activation :
    Set `JARVIS_TRAINING_COLLECT=1` in the environment of the API
    process. With the flag off the wrapper is a transparent no-op
    (no extra cost beyond a `bool` check).

Wiring :
    The intended call site is `api/main.py` at boot, ONE line :

        from core.llm_wrapper import patch_llm_factory ; patch_llm_factory()

    `patch_llm_factory()` is idempotent — calling it twice does not
    double-wrap.
"""
from __future__ import annotations

import time
from typing import Any, Optional

import structlog

log = structlog.get_logger(__name__)

# Marker attribute set on the patched method to detect re-wrap attempts.
_PATCHED_FLAG = "_jarvis_training_wrapped"


def _extract_text(messages: Any) -> str:
    """Best-effort flatten of a langchain messages list to a single string."""
    try:
        parts = []
        for m in messages or []:
            content = getattr(m, "content", None)
            if content is None and isinstance(m, dict):
                content = m.get("content", "")
            if content is None:
                continue
            role = getattr(m, "type", "") or (m.get("role", "") if isinstance(m, dict) else "")
            tag = role or "msg"
            parts.append(f"[{tag}] {content}")
        return "\n".join(parts)
    except Exception:
        return ""


def _extract_tokens(resp: Any) -> tuple[int, int]:
    """Pull (prompt_tokens, completion_tokens) from a langchain response."""
    try:
        meta = getattr(resp, "response_metadata", {}) or {}
        usage = meta.get("token_usage", {}) or meta.get("usage", {}) or {}
        return (
            int(usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0) or 0),
            int(usage.get("completion_tokens", 0) or usage.get("output_tokens", 0) or 0),
        )
    except Exception:
        return (0, 0)


def patch_llm_factory(LLMFactory: Optional[type] = None) -> bool:
    """Monkey-patch `LLMFactory.safe_invoke` to record interactions.

    Returns True on success, False if the factory module is unavailable
    or already patched. Safe to call from a try/except wrapper at boot.
    """
    if LLMFactory is None:
        try:
            from core.llm_factory import LLMFactory as _Factory
            LLMFactory = _Factory
        except Exception as exc:
            log.debug("llm_wrapper.factory_import_failed", err=str(exc)[:120])
            return False

    original = getattr(LLMFactory, "safe_invoke", None)
    if original is None:
        log.debug("llm_wrapper.no_safe_invoke_method")
        return False
    if getattr(original, _PATCHED_FLAG, False):
        return False  # already wrapped

    import functools as _functools

    # @functools.wraps preserves the original signature so
    # inspect.signature(LLMFactory.safe_invoke) still resolves the explicit
    # kwargs (task_description, budget, latency, timeout, session_id,
    # agent_name). Without it, the wrapper collapses everything into
    # (self, messages, role, **kw) and breaks the contract-introspection
    # regression tests (audit S6.F, 2026-05-19).
    @_functools.wraps(original)
    async def safe_invoke_with_capture(self, messages, role="fast", *args, **kw):
        # Transparent passthrough: the real safe_invoke accepts several extra
        # positional params (timeout, session_id, agent_name, task_description,
        # budget, latency). Capturing only (messages, role, **kw) made every
        # positional caller crash with "takes 2 to 3 positional arguments but N
        # were given". Forward *args verbatim so the wrapper is signature-neutral.
        t0 = time.monotonic()
        resp = await original(self, messages, role, *args, **kw)
        try:
            from core.training_collector import _is_enabled, record_llm_interaction

            if not _is_enabled():
                return resp

            instruction = _extract_text(messages)
            response_text = getattr(resp, "content", "") if resp is not None else ""
            t_in, t_out = _extract_tokens(resp)
            latency_ms = int((time.monotonic() - t0) * 1000)
            llm = self.get(role) if hasattr(self, "get") else None
            model = (
                getattr(llm, "model_name", None)
                or getattr(llm, "model", None)
                or "unknown"
            )
            record_llm_interaction(
                instruction=instruction,
                response=response_text,
                model=str(model),
                tokens_in=t_in,
                tokens_out=t_out,
                latency_ms=latency_ms,
                source=kw.get("agent_name", "") or role,
                context=kw.get("task_description", ""),
            )
        except Exception as exc:
            # Never let instrumentation break the LLM call
            log.debug("llm_wrapper.capture_failed", err=str(exc)[:120])
        return resp

    setattr(safe_invoke_with_capture, _PATCHED_FLAG, True)
    setattr(LLMFactory, "safe_invoke", safe_invoke_with_capture)
    log.info("llm_wrapper.patched", factory=LLMFactory.__name__)
    return True


def unpatch_llm_factory(LLMFactory: Optional[type] = None) -> bool:
    """Best-effort undo (test fixture only).

    Recovers the original by re-importing if the marker is detected.
    """
    if LLMFactory is None:
        try:
            from core.llm_factory import LLMFactory as _Factory
            LLMFactory = _Factory
        except Exception:
            return False
    method = getattr(LLMFactory, "safe_invoke", None)
    if not method or not getattr(method, _PATCHED_FLAG, False):
        return False
    # Reload the module to retrieve the unwrapped method
    import importlib

    import core.llm_factory as _mod
    importlib.reload(_mod)
    setattr(LLMFactory, "safe_invoke", _mod.LLMFactory.safe_invoke)
    return True
