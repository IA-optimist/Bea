"""
core/__init__.py — JarvisMax Core Public API

CANONICAL EXPORTS ONLY.
This module defines the public contract of the core runtime.

Canonical execution path:
  main.py → MetaOrchestrator.run() → JarvisOrchestrator (delegate, not public)

Rules:
  - Import only from here in application code.
  - Do NOT import JarvisOrchestrator or OrchestratorV2 directly.
  - Do NOT extend core.orchestrator — it is frozen/deprecated.
"""
from __future__ import annotations

import warnings

# ── Canonical types ────────────────────────────────────────────
from core.state import MissionStatus, JarvisSession, SessionStatus

# ── Canonical orchestrator ─────────────────────────────────────
from core.meta_orchestrator import MetaOrchestrator, get_meta_orchestrator

# ── Public surface ─────────────────────────────────────────────
__all__ = [
    # State
    "MissionStatus",
    "JarvisSession",
    "SessionStatus",
    # Orchestrator
    "MetaOrchestrator",
    "get_meta_orchestrator",
    # Deprecation shim (see below)
    "JarvisOrchestrator",
]


# ── Deprecation shim ───────────────────────────────────────────
# JarvisOrchestrator is an internal implementation detail of MetaOrchestrator.
# External code must NEVER instantiate it directly.
# This shim exists only to avoid ImportError in legacy modules during migration.
# It will be removed once core/orchestrator.py is inlined into meta_orchestrator.py.

class JarvisOrchestrator:  # type: ignore[no-redef]
    """
    DEPRECATED SHIM.
    Use: get_meta_orchestrator() instead.

    This class exists only to prevent ImportError during migration.
    It will be removed in the next structural pass.
    """

    def __new__(cls, *args, **kwargs):
        warnings.warn(
            "JarvisOrchestrator is deprecated and will be removed. "
            "Use get_meta_orchestrator() from core instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        # Import and return the real internal class so behaviour is preserved
        from core.orchestrator_LEGACY_20260407 import JarvisOrchestrator as _Real
        return _Real(*args, **kwargs)
