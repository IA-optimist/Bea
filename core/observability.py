"""Compatibilité historique — observability store.

`core.observability` était historiquement un module .py contenant
`ObservabilityStore`, `MissionMetrics` et `get_observability_store()`.
Le namespace canonique est maintenant le package `core.observability/`.
Ce shim garde les imports existants fonctionnels pendant la migration.
"""
from __future__ import annotations

from core.observability.store import MissionMetrics, ObservabilityStore, get_observability_store

__all__ = ["MissionMetrics", "ObservabilityStore", "get_observability_store"]
