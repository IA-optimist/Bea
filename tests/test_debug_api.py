"""
tests/test_debug_api.py — Tests for debug and inspection endpoints.

DB01-DB15: Learning memory, model selection, fallback chain, pipeline health.
"""
import tempfile
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def _pinned_empty_selector():
    """Épingle le sélecteur de modèles sur un catalogue VIDE.

    La sélection devient déterministe : elle suit la fallback chain hardcodée
    (BUDGET_FALLBACKS) au lieu du cache OpenRouter de l'environnement (348 modèles,
    qui évolue → dérive des noms type gpt-4o-mini ↔ gpt-4.1-nano).
    """
    import core.model_intelligence.selector as sel_mod
    from core.model_intelligence.catalog import ModelCatalog
    from core.model_intelligence.selector import ModelSelector
    prev = sel_mod._selector
    sel_mod._selector = ModelSelector(
        catalog=ModelCatalog(catalog_path=Path(tempfile.NamedTemporaryFile(suffix=".json", delete=False).name)))
    try:
        yield
    finally:
        sel_mod._selector = prev


class TestDebugAPI:

    def test_DB01_learning_memory_stats(self):
        from api.routes.debug import get_learning_memory_stats
        r = get_learning_memory_stats()
        assert r["ok"]
        assert "stats" in r

    def test_DB02_model_selection_budget(self):
        from api.routes.debug import debug_model_selection
        with _pinned_empty_selector():
            r = debug_model_selection("business_reasoning", "budget")
        assert r["ok"]
        assert r["model_id"] == "openai/gpt-4o-mini"

    def test_DB03_model_selection_normal(self):
        from api.routes.debug import debug_model_selection
        with _pinned_empty_selector():
            r = debug_model_selection("business_reasoning", "normal")
        assert r["ok"]
        assert "claude" in r["model_id"] or "sonnet" in r["model_id"]

    def test_DB04_model_selection_critical(self):
        from api.routes.debug import debug_model_selection
        r = debug_model_selection("business_reasoning", "critical")
        assert r["ok"]

    def test_DB05_fallback_chain(self):
        from api.routes.debug import debug_fallback_chain
        r = debug_fallback_chain("coding", "normal")
        assert r["ok"]
        assert len(r["chain"]["chain"]) >= 2

    def test_DB06_execution_memory(self):
        from api.routes.debug import get_execution_memory
        r = get_execution_memory()
        assert r["ok"]
        assert "stats" in r

    def test_DB07_pipeline_health(self):
        from api.routes.debug import pipeline_health
        r = pipeline_health()
        assert "checks" in r
        assert r["total_checks"] > 0

    def test_DB08_pipeline_health_output_enforcer(self):
        from api.routes.debug import pipeline_health
        r = pipeline_health()
        assert r["checks"].get("output_enforcer", {}).get("ok") is True

    def test_DB09_pipeline_health_quality_gate(self):
        from api.routes.debug import pipeline_health
        r = pipeline_health()
        assert r["checks"].get("quality_gate", {}).get("ok") is True

    def test_DB10_pipeline_health_domain_skills(self):
        from api.routes.debug import pipeline_health
        r = pipeline_health()
        # Skills may or may not be found depending on working dir
        assert "domain_skills" in r["checks"]

    def test_DB11_pipeline_health_playbooks(self):
        from api.routes.debug import pipeline_health
        r = pipeline_health()
        # Playbooks may or may not be found depending on working dir
        assert "playbooks" in r["checks"]

    def test_DB12_strategy_lookup_empty(self):
        from api.routes.debug import strategy_lookup
        r = strategy_lookup("quantum physics simulation")
        assert r["ok"]
        # May or may not find — depends on memory state

    def test_DB13_retry_stats(self):
        from api.routes.debug import retry_stats
        r = retry_stats()
        assert r["ok"]
        assert "total_retries" in r

    def test_DB14_model_selection_unknown_task(self):
        from api.routes.debug import debug_model_selection
        r = debug_model_selection("unknown_task_class", "normal")
        assert r["ok"]
        assert r["model_id"]  # Should still return a fallback

    def test_DB15_pipeline_health_learning_memory(self):
        from api.routes.debug import pipeline_health
        r = pipeline_health()
        assert r["checks"].get("learning_memory", {}).get("ok") is True
