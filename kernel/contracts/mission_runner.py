"""MissionRunner Protocol — contrat unifié pour l'exécution de missions.

Ce Protocol capture la signature canonique de `MetaOrchestrator.run_mission`
afin que tout composant qui prétend exécuter des missions (delegates, wrappers,
tests, mocks) puisse être vérifié statiquement contre un contrat unique.

Usage:
    from kernel.contracts.mission_runner import MissionRunner

    def dispatch(runner: MissionRunner, goal: str) -> Awaitable[Any]:
        return runner.run_mission(goal=goal)

Le Protocol est intentionnellement non-runtime-checkable pour ne pas imposer
d'ABC ; les 40+ implémentations historiques restent libres d'évoluer, mais
toute nouvelle implémentation doit s'aligner sur cette signature.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

# Callback type used across the codebase (matches MetaOrchestrator.CB).
MissionCallback = Callable[[str, Any], Awaitable[None]] | Callable[[str, Any], None]


@runtime_checkable
class MissionRunner(Protocol):
    """Contrat canonique pour exécuter une mission.

    Returns le MissionContext (ou équivalent) ; laissé `Any` pour accommoder
    les variations de types entre meta_orchestrator / crews / delegates.
    """

    async def run_mission(
        self,
        goal: str,
        mode: str = "auto",
        mission_id: str | None = None,
        callback: MissionCallback | None = None,
        use_budget: bool = False,
        force_approved: bool = False,
        project_id: str | None = None,
        extra_metadata: dict | None = None,
    ) -> Any:
        ...


__all__ = ["MissionRunner", "MissionCallback"]
