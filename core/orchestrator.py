"""
Legacy import shim for core.orchestrator.

DEPRECATED: This module has been moved to core/orchestrator_LEGACY_20260407.py
The canonical orchestrator is now core/meta_orchestrator.py (MetaOrchestrator)

This shim exists for backward compatibility only.
All imports of `from core.orchestrator import JarvisOrchestrator` will
continue to work, but emit a DeprecationWarning.
"""
import warnings
from core.orchestrator_LEGACY_20260407 import *  # noqa: F401,F403

warnings.warn(
    "core.orchestrator is deprecated. "
    "Use core.meta_orchestrator.MetaOrchestrator instead. "
    "This shim re-exports from core.orchestrator_LEGACY_20260407.",
    DeprecationWarning,
    stacklevel=2,
)
