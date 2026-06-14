"""
core/improvement_gate.py — Per-context improvement gate override (public façade)
=================================================================================
Re-exports the ContextVar-based gate helpers defined in ``kernel.improvement.gate``
so that code outside the kernel can use a stable, core-level import path.

Why a façade?
-------------
The actual ContextVar lives in ``kernel/improvement/gate.py`` because the kernel
owns all self-improvement gating logic and must not import from ``core/``.  Code
in ``core/``, ``agents/``, ``api/`` and scripts is allowed to import from the
kernel, so this thin re-export gives them a clean import path without duplicating
the ContextVar (two separate ContextVars with the same name would be independent
objects and would not share state).

Public API
----------
``is_gate_skipped()``        — True if the gate should be skipped in the current context.
``skip_gate_for_context()``  — Activate the bypass for the current context; returns a Token.
``restore_gate(token)``      — Undo a previous ``skip_gate_for_context()`` call.

Env-var fallback
----------------
``is_gate_skipped()`` still respects the process-level ``BEA_SKIP_IMPROVEMENT_GATE``
env var so that existing test fixtures using ``os.environ`` continue to work
without any changes.

Example — async handler::

    from core.improvement_gate import skip_gate_for_context, restore_gate

    token = skip_gate_for_context(True)
    try:
        await do_improvement()
    finally:
        restore_gate(token)
"""
from __future__ import annotations

from kernel.improvement.gate import (
    is_gate_skipped,
    restore_gate,
    skip_gate_for_context,
)

__all__ = [
    "is_gate_skipped",
    "skip_gate_for_context",
    "restore_gate",
]
