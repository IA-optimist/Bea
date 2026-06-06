"""Observabilité Béa — traceur LLM partagé (coût / latence / erreurs par modèle).

`get_tracer()` renvoie un singleton `LLMTracer` persistant (SQLite dans workspace/).
Best-effort : toute erreur de traçage ne doit JAMAIS casser un appel LLM.
"""
from __future__ import annotations

import os
from pathlib import Path

from core.observability.llm_tracer import LLMTracer

_tracer: LLMTracer | None = None


def get_tracer() -> LLMTracer:
    """Traceur LLM singleton (DB SQLite dans workspace/, override via BEA_LLM_TRACE_DB)."""
    global _tracer
    if _tracer is None:
        db = os.environ.get(
            "BEA_LLM_TRACE_DB",
            str(Path(os.environ.get("JARVIS_ROOT", ".")) / "workspace" / "llm_traces.db"),
        )
        _tracer = LLMTracer(db)
    return _tracer
