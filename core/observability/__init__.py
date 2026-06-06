"""Observabilité Béa — traceur LLM partagé (coût / latence / erreurs par modèle).

`get_tracer()` renvoie un singleton `LLMTracer` persistant (SQLite dans workspace/).
Best-effort : toute erreur de traçage ne doit JAMAIS casser un appel LLM.
"""
from __future__ import annotations

import os
from pathlib import Path

from core.observability.llm_tracer import LLMTracer
from core.observability.llm_tracer import get_tracer as _llm_get_tracer


def get_tracer() -> LLMTracer:
    """Traceur LLM singleton UNIQUE et PERSISTANT (workspace/llm_traces.db).

    Délègue au singleton de `llm_tracer.get_tracer()` mais en pointant sa DB
    (`JARVIS_LLM_TRACE_DB`) sur un fichier persistant, pour que toutes les voies
    d'accès partagent le même traceur (sinon double singleton :memory:)."""
    db = os.environ.get(
        "BEA_LLM_TRACE_DB",
        str(Path(os.environ.get("JARVIS_ROOT", ".")) / "workspace" / "llm_traces.db"),
    )
    os.environ.setdefault("JARVIS_LLM_TRACE_DB", db)
    return _llm_get_tracer()
