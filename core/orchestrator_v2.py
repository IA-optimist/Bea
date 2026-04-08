"""
Legacy import shim for orchestrator_v2.

DEPRECATED: This module has been moved to core/_legacy/orchestrator_v2.py
The canonical orchestrator is now core/meta_orchestrator.py (MetaOrchestrator)

This shim exists for backward compatibility only.
"""
import warnings
from core._legacy.orchestrator_v2 import *

warnings.warn(
    "core.orchestrator_v2 is deprecated. Use core.meta_orchestrator.MetaOrchestrator instead.",
    DeprecationWarning,
    stacklevel=2
)
