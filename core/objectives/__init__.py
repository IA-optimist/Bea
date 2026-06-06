"""
Objective Engine — Point d'entrée du package.
Exporte les interfaces principales.
Fail-open : si un sous-module manque, les autres restent disponibles.
"""
from __future__ import annotations

import structlog
log = structlog.get_logger(__name__)

try:
    from core.objectives.objective_models import (
        Objective,
        SubObjective,
        ObjectiveStatus,
        SubObjectiveStatus,
    )
except ImportError as _exc:
    log.warning("swallowed_exception", action="objectives_import_1", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

try:
    from core.objectives.objective_engine import (
        ObjectiveEngine,
        get_objective_engine,
        reset_engine,
    )
except ImportError as _exc:
    log.warning("swallowed_exception", action="objectives_import_2", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

try:
    from core.objectives.objective_store import (
        ObjectiveStore,
        get_objective_store,
        reset_store,
    )
except ImportError as _exc:
    log.warning("swallowed_exception", action="objectives_import_3", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

try:
    from core.objectives.objective_cleanup import run_cleanup
except ImportError as _exc:
    log.warning("swallowed_exception", action="objectives_import_4", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

__all__ = [
    "Objective",
    "SubObjective",
    "ObjectiveStatus",
    "SubObjectiveStatus",
    "ObjectiveEngine",
    "get_objective_engine",
    "reset_engine",
    "ObjectiveStore",
    "get_objective_store",
    "reset_store",
    "run_cleanup",
]
