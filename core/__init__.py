"""
core/__init__.py — BeaMax Core Public API

CANONICAL EXPORTS ONLY.
This module defines the public contract of the core runtime.

Canonical execution path:
  main.py → MetaOrchestrator.run() → BeaOrchestrator (delegate, not public)

Rules:
  - Import only from here in application code.
  - Do NOT import BeaOrchestrator or OrchestratorV2 directly.
  - Do NOT extend core.orchestrator — it is frozen/deprecated.
"""
from __future__ import annotations

import warnings

# ── Canonical types ────────────────────────────────────────────
from core.state import MissionStatus, BeaSession, SessionStatus

# ── Canonical orchestrator ─────────────────────────────────────
from core.meta_orchestrator import MetaOrchestrator, get_meta_orchestrator

# ── Public surface ─────────────────────────────────────────────
__all__ = [
    # State
    "MissionStatus",
    "BeaSession",
    "SessionStatus",
    # Orchestrator
    "MetaOrchestrator",
    "get_meta_orchestrator",
    # Deprecation shim (see below)
    "BeaOrchestrator",
]


# ── Deprecation shim ───────────────────────────────────────────
# BeaOrchestrator is an internal implementation detail of MetaOrchestrator.
# External code must NEVER instantiate it directly.
# This shim exists only to avoid ImportError in legacy modules during migration.
# It will be removed once core/orchestrator.py is inlined into meta_orchestrator.py.

class BeaOrchestrator:  # type: ignore[no-redef]
    """
    DEPRECATED SHIM.
    Use: get_meta_orchestrator() instead.

    This class exists only to prevent ImportError during migration.
    It will be removed in the next structural pass.
    """

    def __new__(cls, *args, **kwargs):
        warnings.warn(
            "BeaOrchestrator is deprecated and will be removed. "
            "Use get_meta_orchestrator() from core instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        # Import and return the real internal class so behaviour is preserved
        from core.bea_executor import BeaOrchestrator as _Real
        return _Real(*args, **kwargs)
