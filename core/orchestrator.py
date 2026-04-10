"""
Legacy import shim for core.orchestrator.

DEPRECATED: This module has been moved to core/jarvis_executor.py
The canonical orchestrator is now core/meta_orchestrator.py (MetaOrchestrator)

This shim exists for backward compatibility only.
All imports of `from core.orchestrator import JarvisOrchestrator` will
continue to work, but emit a DeprecationWarning.
"""
import warnings
from core.jarvis_executor import *  # noqa: F401,F403

warnings.warn(
    "core.orchestrator is deprecated. "
    "Use core.meta_orchestrator.MetaOrchestrator instead. "
    "This shim re-exports from core.jarvis_executor.",
    DeprecationWarning,
    stacklevel=2,
)
