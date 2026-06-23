"""Observabilite Bea -- traceur LLM partage + redacteur privacy-safe.

`get_tracer()` retourne un singleton `LLMTracer` persistant (SQLite workspace/).
`redact()` / `redact_dict()` : suppression secrets des logs structures.
`MissionEvent` : evenement leger mission (provider/model/duration/error).
Best-effort : toute erreur de tracage ne doit JAMAIS casser un appel LLM.
"""
from __future__ import annotations

import os
from pathlib import Path

from core.observability.llm_tracer import LLMTracer
from core.observability.llm_tracer import get_tracer as _llm_get_tracer
from core.observability.redactor import redact, redact_dict
from core.observability.mission_event import MissionEvent

__all__ = ["get_tracer", "LLMTracer", "redact", "redact_dict", "MissionEvent"]


def get_tracer() -> LLMTracer:
    """Traceur LLM singleton UNIQUE et PERSISTANT (workspace/llm_traces.db).

    Délègue au singleton de `llm_tracer.get_tracer()` mais en pointant sa DB
    (`BEA_LLM_TRACE_DB`) sur un fichier persistant, pour que toutes les voies
    d'accès partagent le même traceur (sinon double singleton :memory:)."""
    db = os.environ.get(
        "BEA_LLM_TRACE_DB",
        str(Path(os.environ.get("BEA_ROOT", ".")) / "workspace" / "llm_traces.db"),
    )
    os.environ.setdefault("BEA_LLM_TRACE_DB", db)
    return _llm_get_tracer()
