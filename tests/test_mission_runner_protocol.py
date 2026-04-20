"""Gate test — conformance des implémentations au Protocol MissionRunner.

Le Protocol ``kernel.contracts.mission_runner.MissionRunner`` fige la
signature canonique de ``run_mission``. Ce test vérifie qu'au moins
``MetaOrchestrator`` (implémentation de référence) est conforme et que
la signature publique n'a pas dérivé.

Ajoute ici toute classe qui doit satisfaire le contrat.
"""
from __future__ import annotations

import inspect

import pytest

from kernel.contracts.mission_runner import MissionRunner

# Signature canonique attendue (doit rester synchrone avec MissionRunner).
_EXPECTED_PARAMS = {
    "goal",
    "mode",
    "mission_id",
    "callback",
    "use_budget",
    "force_approved",
    "project_id",
    "extra_metadata",
}


def _get_run_mission_params(cls: type) -> set[str]:
    sig = inspect.signature(cls.run_mission)
    # `self` exclu.
    return {p.name for p in sig.parameters.values() if p.name != "self"}


def test_meta_orchestrator_conforms_to_mission_runner():
    from core.meta_orchestrator import MetaOrchestrator

    instance = MetaOrchestrator.__new__(MetaOrchestrator)
    assert isinstance(instance, MissionRunner), (
        "MetaOrchestrator doit satisfaire le Protocol MissionRunner "
        "(@runtime_checkable vérifie la présence de run_mission)."
    )


def test_meta_orchestrator_signature_unchanged():
    from core.meta_orchestrator import MetaOrchestrator

    params = _get_run_mission_params(MetaOrchestrator)
    assert params == _EXPECTED_PARAMS, (
        f"La signature publique de MetaOrchestrator.run_mission a dérivé. "
        f"Attendue: {sorted(_EXPECTED_PARAMS)} ; observée: {sorted(params)}. "
        f"Synchronise kernel/contracts/mission_runner.py si le changement "
        f"est volontaire, ou corrige la signature."
    )


def test_mission_runner_is_async():
    from core.meta_orchestrator import MetaOrchestrator

    assert inspect.iscoroutinefunction(MetaOrchestrator.run_mission), (
        "run_mission doit rester une coroutine (async def)."
    )
