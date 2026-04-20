"""memory.legacy — modules historiques conservés pour compatibilité.

DEPRECATED: utilisez memory.store / memory.memory_bus pour le nouveau code.
Ces modules (failure_memory, patch_memory, project_memory, store_legacy) sont
réexportés par leurs façades dans memory/ et seront supprimés dans une
version ultérieure.
"""
import warnings

warnings.warn(
    "memory.legacy.* est deprecated ; utilisez memory.store / memory.memory_bus.",
    DeprecationWarning,
    stacklevel=2,
)
