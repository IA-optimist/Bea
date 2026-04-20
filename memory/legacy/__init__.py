"""memory.legacy — modules historiques conservés pour compatibilité.

DEPRECATED. Le nouveau code doit utiliser ``memory.store`` / ``memory.memory_bus``.

Modules encore référencés :

- ``memory.legacy.store_legacy``     → ré-exporté par ``memory.store``
- ``memory.legacy.failure_memory``   → utilisé uniquement par ``tests/test_memory.py``
- ``memory.legacy.patch_memory``     → utilisé uniquement par ``tests/test_memory.py``
- ``memory.legacy.project_memory``   → wrapper DB dépassé (PostgreSQL via env)

Roadmap de suppression :

1. Faire de ``memory.store`` une implémentation native (drop du ``import *``).
2. Migrer ``test_memory.py`` vers l'API canonique de ``memory.store``.
3. Supprimer ``project_memory`` (remplacé par la couche modèles moderne).
4. Supprimer ``failure_memory`` et ``patch_memory`` (remplacés par
   ``core.improvement_memory`` / kernel memory).

Aucun nouveau code ne doit importer directement depuis ``memory.legacy``.
"""
import warnings

warnings.warn(
    "memory.legacy.* est deprecated ; utilisez memory.store / memory.memory_bus.",
    DeprecationWarning,
    stacklevel=2,
)
