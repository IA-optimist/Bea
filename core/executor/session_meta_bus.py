"""Session-scoped metadata bus for LLM provider/model tracking.

Records every LLM call during an async execution context so that
bea_executor can inject accurate runtime metadata into session.metadata
at the end of a run.

Two kinds of data live here:
  - initial_meta   : planned provider/mission_type set by execution_supervised_runner
                     BEFORE delegate.run() starts (from ctx.metadata routing decisions)
  - llm_calls      : actual LLM calls recorded by llm_factory on each success
                     (provider, model, fallback flag)

Both use contextvars.ContextVar so they are naturally isolated per async task.
Keys are never logged — only provider name and model name (no API keys).
"""
from __future__ import annotations

import contextvars
from typing import NamedTuple


class LLMCall(NamedTuple):
    provider: str
    model: str
    fallback: bool


# ── ContextVars ───────────────────────────────────────────────────────────────
_calls: contextvars.ContextVar[list[LLMCall]] = contextvars.ContextVar(
    "_session_llm_calls", default=[]
)
_initial: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "_session_initial_meta", default={}
)


# ── Write API (called by llm_factory and execution_supervised_runner) ─────────

def reset() -> None:
    """Reset both vars. Call at the start of each new session to avoid bleed."""
    _calls.set([])
    _initial.set({})


def record_llm_used(provider: str, model: str, *, fallback: bool = False) -> None:
    """Record a successful LLM call. Called from llm_factory after llm_call_ok/llm_fallback_ok."""
    try:
        current = list(_calls.get())
        current.append(LLMCall(provider=str(provider), model=str(model), fallback=fallback))
        _calls.set(current)
    except Exception:  # noqa: BLE001
        pass


def set_initial_meta(meta: dict) -> None:
    """Store planned routing metadata before delegate.run() is called.

    Called from execution_supervised_runner with ctx.metadata values so the
    planned provider_id, mission_type, and fallback_used reach session.metadata
    even if no LLM call lands (e.g. chat fast-path or immediate failure).
    """
    try:
        _initial.set({k: v for k, v in meta.items() if v is not None})
    except Exception:  # noqa: BLE001
        pass


# ── Read API (called by bea_executor at session end) ──────────────────────────

def get_calls() -> list[LLMCall]:
    return list(_calls.get())


def get_initial_meta() -> dict:
    return dict(_initial.get())


def get_primary_provider() -> str | None:
    """First non-fallback provider used, or first provider if all were fallbacks."""
    calls = _calls.get()
    for c in calls:
        if not c.fallback:
            return c.provider
    return calls[0].provider if calls else None


def get_primary_model() -> str | None:
    """Model name from the first non-fallback call, or first call overall."""
    calls = _calls.get()
    for c in calls:
        if not c.fallback and c.model:
            return c.model
    return calls[0].model if calls else None


def is_fallback_used() -> bool:
    """True if any Ollama/fallback call succeeded during this session."""
    return any(c.fallback for c in _calls.get())


def get_providers_used() -> list[str]:
    """Deduplicated list of providers called (in order of first use)."""
    seen: list[str] = []
    for c in _calls.get():
        if c.provider not in seen:
            seen.append(c.provider)
    return seen


def build_session_metadata_patch(session_metadata: dict) -> dict:
    """Return a dict of keys to inject into session.metadata.

    Precedence:
      1. Runtime (actual LLM calls) — most accurate.
      2. Planned (initial_meta from routing) — best-effort when no call happened.
      3. Existing session.metadata values — never overwrite.

    Never invents a value; returns None for unknown fields.
    """
    initial = get_initial_meta()
    actual_provider = get_primary_provider()
    actual_model = get_primary_model()
    fallback = is_fallback_used()

    patch: dict = {}

    # provider_used: prefer actual (what llm_factory used) over planned (routing intent)
    if "provider_used" not in session_metadata:
        patch["provider_used"] = actual_provider or initial.get("provider_used")

    # model_used: only from actual calls (routing doesn't know the model name)
    if "model_used" not in session_metadata:
        patch["model_used"] = actual_model or initial.get("model_used")

    # fallback_used: True if Ollama was the fallback, or routing said so
    if "fallback_used" not in session_metadata:
        patch["fallback_used"] = fallback or bool(initial.get("fallback_used"))

    # mission_type: from routing classification (pre-execution)
    if "mission_type" not in session_metadata:
        patch["mission_type"] = initial.get("mission_type")

    # provider_status: simple derived field
    if "provider_status" not in session_metadata and actual_provider:
        patch["provider_status"] = "fallback" if fallback else "primary"

    # agents_used: from planned routing (not overriding if already set)
    if "agents_used" not in session_metadata and initial.get("agents_used"):
        patch["agents_used"] = initial["agents_used"]

    return {k: v for k, v in patch.items() if v is not None}
