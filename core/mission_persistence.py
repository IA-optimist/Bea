"""
Legacy import shim for mission_persistence.

DEPRECATED: This module has been moved to core/_legacy/mission_persistence.py
The canonical mission store is now api/mission_store.py (MissionStateStore)

This shim exists for backward compatibility only.
"""
import warnings
from core._legacy.mission_persistence import (
    PersistedMission,
    MissionPersistenceStore,
    get_mission_persistence,
)

warnings.warn(
    "core.mission_persistence is deprecated. Use api.mission_store.MissionStateStore instead.",
    DeprecationWarning,
    stacklevel=2
)

__all__ = ["PersistedMission", "MissionPersistenceStore", "get_mission_persistence"]
