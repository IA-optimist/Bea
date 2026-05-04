"""
Objective Engine — Point d'entrée du package.
Exporte les interfaces principales.
Fail-open : si un sous-module manque, les autres restent disponibles.
"""
from __future__ import annotations
_silent_log = __import__("structlog").get_logger(__name__)

try:
    from core.objectives.objective_models import (
        Objective,
        SubObjective,
        ObjectiveStatus,
        SubObjectiveStatus,
    )
except ImportError:
    _silent_log.debug("suppressed_exception", src='__init__.py')

try:
    from core.objectives.objective_engine import (
        ObjectiveEngine,
        get_objective_engine,
        reset_engine,
    )
except ImportError:
    _silent_log.debug("suppressed_exception", src='__init__.py')

try:
    from core.objectives.objective_store import (
        ObjectiveStore,
        get_objective_store,
        reset_store,
    )
except ImportError:
    _silent_log.debug("suppressed_exception", src='__init__.py')

try:
    from core.objectives.objective_cleanup import run_cleanup
except ImportError:
    _silent_log.debug("suppressed_exception", src='__init__.py')

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
