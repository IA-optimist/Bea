"""core._legacy — modules historiques conservés pour compatibilité.

DEPRECATED: ces modules sont importés par leurs wrappers (core.policy_engine,
core.self_improvement_engine, core.self_improvement_loop, core.orchestrator_v2,
core.mission_persistence) mais ne doivent pas être importés directement par
du nouveau code. Ils seront supprimés dans une version ultérieure.
"""
import warnings

warnings.warn(
    "core._legacy.* est deprecated ; utilisez les façades publiques dans core/.",
    DeprecationWarning,
    stacklevel=2,
)
