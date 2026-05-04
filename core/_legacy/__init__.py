"""core._legacy — modules historiques conservés pour compatibilité.

DEPRECATED. Ces modules sont encore importés par leurs façades publiques :

- ``core.policy_engine``           → ``core._legacy.policy_engine_LEGACY_20260407``
- ``core.self_improvement_engine`` → ``core._legacy.self_improvement_engine_v2``
- ``core.self_improvement_loop``   → ``core._legacy.self_improvement_loop_v2``
- ``core.orchestrator_v2``         → ``core._legacy.orchestrator_v2``
- ``core.mission_persistence``     → ``core._legacy.mission_persistence``

Roadmap de suppression :

1. Migrer chaque façade vers une implémentation native dans ``core/`` (pas
   de ``from core._legacy import *``).
2. Retirer le ``import *`` de la façade ; garder seulement les symboles
   effectivement utilisés en externe.
3. Une fois la façade autonome, supprimer le module ``_legacy`` correspondant.

Aucun nouveau code ne doit importer directement depuis ``core._legacy``.
"""
import warnings

warnings.warn(
    "core._legacy.* est deprecated ; utilisez les façades publiques dans core/.",
    DeprecationWarning,
    stacklevel=2,
)
