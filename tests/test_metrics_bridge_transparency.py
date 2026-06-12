"""Le metrics_bridge ne doit JAMAIS rétrécir les signatures qu'il patche.

Bug 2026-06-12 : instrumented_run_mission énumérait les paramètres de
run_mission tels qu'ils existaient à l'écriture du wrapper — les paramètres
ajoutés ensuite (force_approved, project_id, extra_metadata) levaient
TypeError sur toute reprise approuvée, et functools.wraps faisait mentir
inspect.signature(), rendant le bug indétectable par introspection.
"""
import inspect
import re
from pathlib import Path

import pytest


def test_patched_run_mission_accepts_any_kwargs():
    """Le wrapper installé doit avoir *args/**kwargs (CO_VARARGS/CO_VARKEYWORDS)."""
    pytest.importorskip("structlog")
    from core.metrics_bridge import _patch_meta_orchestrator
    from core.meta_orchestrator import MetaOrchestrator

    original = MetaOrchestrator.run_mission
    try:
        assert _patch_meta_orchestrator() is True
        fn = MetaOrchestrator.run_mission
        # NE PAS utiliser inspect.signature : functools.wraps la fait mentir.
        code = fn.__code__
        assert code.co_flags & inspect.CO_VARARGS, "wrapper sans *args"
        assert code.co_flags & inspect.CO_VARKEYWORDS, "wrapper sans **kwargs"
    finally:
        MetaOrchestrator.run_mission = original


def test_no_wrapper_enumerates_forwarded_call():
    """Source check : chaque appel à l'original DOIT forwarder *args/**kwargs.

    On tolère des paramètres nommés AVANT (utilisés pour les labels de
    métriques), mais l'appel forwardé doit se terminer par *args, **kwargs
    ou **kwargs (pattern transparent).
    """
    src = Path("core/metrics_bridge.py").read_text(encoding="utf-8")
    calls = re.findall(
        r"(?:await\s+)?original\w*\(self,[^)]*\)", src
    )
    assert calls, "aucun appel forwardé trouvé — le pattern a changé ?"
    for call in calls:
        assert re.search(r"\*\*\w+", call), f"appel non transparent : {call}"
