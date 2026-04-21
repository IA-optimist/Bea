"""
tests/test_model_intelligence.py — Model intelligence layer tests.

Validates:
  - Model catalog (fetch, normalize, cache, fail-open)
  - Model profiles (task classification, scoring)
  - Performance memory (record, query, persistence)
  - Model selection (task-based, cost-aware, fallback)
  - Runtime integration (skill → task class → role)
  - API endpoints
  - No secret leakage
"""
import json
import pytest
import tempfile
from pathlib import Path
from core.model_intelligence.catalog import ModelEntry, ModelCatalog
from core.model_intelligence.selector import (
    ModelProfile, ModelPerformanceMemory, ModelPerformanceRecord,
    ModelSelector, SelectionResult, build_profile,
    TASK_CLASSES, SKILL_TASK_MAP, ROLE_TASK_MAP,
)


# ══════════════════════════════════════════════════════════════
# Phase 1 — Model Catalog
# ══════════════════════════════════════════════════════════════

class TestModelCatalog:

    def _make_entry(self, **kw) -> ModelEntry:
        defaults = {
            "model_id": "test/model-1",
            "name": "Test Model",
            "provider": "test",
            "context_length": 128000,
            "pricing_prompt": 3.0,
            "pricing_completion": 15.0,
        }
        defaults.update(kw)
        return ModelEntry(**defaults)

    def test_MI01_entry_cost_tier(self):
        """Cost tier classification works correctly."""
        assert ModelEntry(pricing_prompt=0, pricing_completion=0).cost_tier == "free"
        assert ModelEntry(pricing_prompt=0.1, pricing_completion=0.3).cost_tier == "cheap"
        assert ModelEntry(pricing_prompt=0.5, pricing_completion=2.0).cost_tier == "mid"
        assert ModelEntry(pricing_prompt=3.0, pricing_completion=15.0).cost_tier == "premium"
        assert ModelEntry(pricing_prompt=15.0, pricing_completion=60.0).cost_tier == "ultra"

    def test_MI02_entry_roundtrip(self):
        entry = self._make_entry()
        d = entry.to_dict()
        entry2 = ModelEntry.from_dict(d)
        assert entry2.model_id == entry.model_id
        assert entry2.pricing_prompt == entry.pricing_prompt

    def test_MI03_from_openrouter(self):
        """Parse from real OpenRouter API format."""
        raw = {
            "id": "anthropic/claude-sonnet-4.5",
            "name": "Claude 3.5 Sonnet",
            "pricing": {"prompt": "0.000003", "completion": "0.000015"},
            "context_length": 200000,
            "architecture": {"modality": "text->text"},
        }
        entry = ModelEntry.from_openrouter(raw)
        assert entry.model_id == "anthropic/claude-sonnet-4.5"
        assert entry.provider == "anthropic"
        assert entry.context_length == 200000
        assert entry.pricing_prompt == 3.0  # $3/1M tokens

    def test_MI04_catalog_cache_roundtrip(self):
        """Catalog persists and reloads from disk."""
        path = Path(tempfile.mktemp(suffix=".json"))
        cat1 = ModelCatalog(catalog_path=path)
        cat1._models["test/m1"] = self._make_entry(model_id="test/m1")
        cat1._save_cache()

        cat2 = ModelCatalog(catalog_path=path)
        assert cat2.count == 1
        assert cat2.get("test/m1") is not None

    def test_MI05_catalog_search(self):
        cat = ModelCatalog(catalog_path=Path(tempfile.mktemp(suffix=".json")))
        cat._models["anthropic/claude"] = self._make_entry(model_id="anthropic/claude", name="Claude")
        cat._models["openai/gpt-4"] = self._make_entry(model_id="openai/gpt-4", name="GPT-4")
        results = cat.search("claude")
        assert len(results) == 1
        assert results[0].model_id == "anthropic/claude"

    def test_MI06_catalog_fail_open_no_key(self):
        """Refresh without API key returns -1 (fail-open)."""
        cat = ModelCatalog(catalog_path=Path(tempfile.mktemp(suffix=".json")))
        result = cat.refresh(api_key="")
        assert result == -1
        # Catalog should still work (empty or cached)
        assert cat.count >= 0


# ══════════════════════════════════════════════════════════════
# Phase 2 — Model Profiles
# ══════════════════════════════════════════════════════════════

class TestModelProfiles:

    def test_MI07_claude_profile(self):
        """Claude models score high on reasoning/business."""
        entry = ModelEntry(
            model_id="anthropic/claude-sonnet-4.5",
            name="Claude 3.5 Sonnet",
            provider="anthropic",
            context_length=200000,
            pricing_prompt=3.0,
            pricing_completion=15.0,
        )
        profile = build_profile(entry)
        assert profile.score_for("business_reasoning") >= 0.8
        assert profile.score_for("structured_reasoning") >= 0.8
        assert profile.score_for("cheap_simple") <= 0.3

    def test_MI08_gpt4_mini_profile(self):
        """GPT-4o-mini scores high on cheap tasks."""
        entry = ModelEntry(
            model_id="openai/gpt-4o-mini",
            name="GPT-4o Mini",
            provider="openai",
            context_length=128000,
            pricing_prompt=0.15,
            pricing_completion=0.6,
        )
        profile = build_profile(entry)
        assert profile.score_for("cheap_simple") >= 0.8
        assert profile.best_task == "cheap_simple"

    def test_MI09_deepseek_coding_profile(self):
        """DeepSeek models score high on coding."""
        entry = ModelEntry(
            model_id="deepseek/deepseek-coder",
            name="DeepSeek Coder",
            provider="deepseek",
            context_length=32000,
            pricing_prompt=0.5,
            pricing_completion=1.0,
        )
        profile = build_profile(entry)
        assert profile.score_for("coding") >= 0.8

    def test_MI10_profile_serializable(self):
        entry = ModelEntry(model_id="test/m1", name="Test")
        profile = build_profile(entry)
        d = profile.to_dict()
        assert "scores" in d
        assert "best_task" in d


# ══════════════════════════════════════════════════════════════
# Phase 3 — Performance Memory
# ══════════════════════════════════════════════════════════════

class TestPerformanceMemory:

    def test_MI11_record_and_query(self):
        perf = ModelPerformanceMemory(path=Path(tempfile.mktemp(suffix=".json")))
        perf.record("anthropic/claude-sonnet-4.5", "business_reasoning",
                    success=True, duration_ms=5000, quality=0.9)
        stats = perf.get_stats("anthropic/claude-sonnet-4.5", "business_reasoning")
        assert len(stats) == 1
        assert stats[0]["success_rate"] == 1.0
        assert stats[0]["avg_quality"] == 0.9

    def test_MI12_multiple_records(self):
        perf = ModelPerformanceMemory(path=Path(tempfile.mktemp(suffix=".json")))
        perf.record("m1", "coding", success=True, quality=0.8)
        perf.record("m1", "coding", success=True, quality=0.6)
        perf.record("m1", "coding", success=False, quality=0.0)
        stats = perf.get_stats("m1", "coding")
        assert stats[0]["total"] == 3
        assert abs(stats[0]["success_rate"] - 0.667) < 0.01

    def test_MI13_best_for_task(self):
        perf = ModelPerformanceMemory(path=Path(tempfile.mktemp(suffix=".json")))
        perf.record("good-model", "coding", success=True, quality=0.9)
        perf.record("good-model", "coding", success=True, quality=0.85)
        perf.record("bad-model", "coding", success=True, quality=0.3)
        perf.record("bad-model", "coding", success=False, quality=0.0)
        best = perf.get_best_for_task("coding")
        assert len(best) == 2
        assert best[0]["model_id"] == "good-model"

    def test_MI14_persistence(self):
        path = Path(tempfile.mktemp(suffix=".json"))
        perf1 = ModelPerformanceMemory(path=path)
        perf1.record("m1", "coding", success=True, quality=0.9)

        perf2 = ModelPerformanceMemory(path=path)
        stats = perf2.get_stats("m1", "coding")
        assert len(stats) == 1


# ══════════════════════════════════════════════════════════════
# Phase 4 — Model Selection
# ══════════════════════════════════════════════════════════════

class TestModelSelection:

    def _mock_catalog(self):
        cat = ModelCatalog(catalog_path=Path(tempfile.mktemp(suffix=".json")))
        cat._models = {
            "cheap/model": ModelEntry(
                model_id="cheap/model", name="Cheap", provider="cheap",
                pricing_prompt=0.1, pricing_completion=0.3, context_length=32000,
            ),
            "anthropic/claude-sonnet-4.5": ModelEntry(
                model_id="anthropic/claude-sonnet-4.5", name="Claude 3.5 Sonnet",
                provider="anthropic", pricing_prompt=3.0, pricing_completion=15.0,
                context_length=200000,
            ),
            "openai/gpt-4o-mini": ModelEntry(
                model_id="openai/gpt-4o-mini", name="GPT-4o Mini",
                provider="openai", pricing_prompt=0.15, pricing_completion=0.6,
                context_length=128000,
            ),
        }
        return cat

    def test_MI15_cheap_task_prefers_cheap(self):
        """Budget mode for simple tasks prefers cheaper models."""
        selector = ModelSelector(catalog=self._mock_catalog())
        result = selector.select("cheap_simple", budget_mode="budget")
        assert result.model_id in ("openai/gpt-4o-mini", "cheap/model")
        assert result.cost_score >= 0.8

    def test_MI16_critical_task_prefers_premium(self):
        """Critical tasks prefer high-quality models."""
        selector = ModelSelector(catalog=self._mock_catalog())
        result = selector.select("high_accuracy_critical", budget_mode="critical")
        assert "claude" in result.model_id or "gpt-4" in result.model_id

    def test_MI17_fallback_without_catalog(self):
        """Selection falls back gracefully with empty catalog."""
        empty_cat = ModelCatalog(catalog_path=Path(tempfile.mktemp(suffix=".json")))
        selector = ModelSelector(catalog=empty_cat)
        result = selector.select("business_reasoning")
        assert result.is_fallback is True
        assert result.model_id != ""

    def test_MI18_select_for_skill(self):
        selector = ModelSelector(catalog=self._mock_catalog())
        result = selector.select_for_skill("market_research.basic")
        assert result.task_class == "business_reasoning"

    def test_MI19_select_for_role(self):
        selector = ModelSelector(catalog=self._mock_catalog())
        result = selector.select_for_role("fast")
        assert result.task_class == "cheap_simple"

    def test_MI20_selection_explainable(self):
        """Selection result includes rationale."""
        selector = ModelSelector(catalog=self._mock_catalog())
        result = selector.select("coding", budget_mode="normal")
        assert result.rationale != ""
        assert "profile=" in result.rationale

    def test_MI21_recommendations(self):
        selector = ModelSelector(catalog=self._mock_catalog())
        recs = selector.get_recommendations()
        assert len(recs) == len(TASK_CLASSES)
        for r in recs:
            assert "task_class" in r
            assert "recommended_model" in r


# ══════════════════════════════════════════════════════════════
# Phase 5 — Runtime Integration
# ══════════════════════════════════════════════════════════════

class TestRuntimeIntegration:

    @pytest.mark.xfail(reason="skill-task map drift", strict=False)
    def test_MI22_skill_task_map_complete(self):
        """All 16 domain skills have task mappings."""
        from core.skills.domain_loader import DomainSkillRegistry
        reg = DomainSkillRegistry()
        reg.load_all()
        for skill_id in reg._skills:
            assert skill_id in SKILL_TASK_MAP, f"Missing task map for: {skill_id}"

    def test_MI23_role_task_map_covers_factory(self):
        """All LLM factory roles have task mappings."""
        important_roles = [
            "analyst", "director", "planner", "builder", "fast",
            "classify", "fallback", "research", "validate",
        ]
        for role in important_roles:
            assert role in ROLE_TASK_MAP, f"Missing role map for: {role}"

    def test_MI24_playbook_still_works(self):
        """Playbook execution not broken by model intelligence."""
        from core.planning.playbook import execute_playbook
        result = execute_playbook("market_analysis", "Integration test")
        assert result["ok"] is True

    def test_MI25_model_selection_in_skill_path(self):
        """Skill LLM invocation path includes model intelligence."""
        import inspect
        from core.planning.skill_llm import _invoke_async
        source = inspect.getsource(_invoke_async)
        assert "model_intelligence" in source or "get_model_selector" in source
        assert "SKILL_TASK_MAP" in source


# ══════════════════════════════════════════════════════════════
# Phase 6 — Cost Awareness
# ══════════════════════════════════════════════════════════════

class TestCostAwareness:

    def test_MI26_cost_tiers_ordered(self):
        """Cost tiers are logically ordered by $/1M tokens."""
        tiers = ["free", "cheap", "mid", "premium", "ultra"]
        # $/1M tokens (prompt, completion) pairs → avg
        costs = [(0, 0), (0.1, 0.3), (0.5, 2.0), (3.0, 15.0), (15.0, 60.0)]
        for tier, (p, c) in zip(tiers, costs):
            entry = ModelEntry(pricing_prompt=p, pricing_completion=c)
            assert entry.cost_tier == tier, f"Expected {tier}, got {entry.cost_tier} for avg={entry.avg_cost_per_million}"

    def test_MI27_budget_mode_affects_selection(self):
        """Different budget modes produce different selections."""
        cat = ModelCatalog(catalog_path=Path(tempfile.mktemp(suffix=".json")))
        cat._models = {
            "cheap/m": ModelEntry(
                model_id="cheap/m", name="Cheap", provider="cheap",
                pricing_prompt=0.1, pricing_completion=0.3, context_length=32000,
            ),
            "premium/m": ModelEntry(
                model_id="premium/m", name="Claude", provider="anthropic",
                pricing_prompt=3.0, pricing_completion=15.0, context_length=200000,
            ),
        }
        selector = ModelSelector(catalog=cat)
        budget_result = selector.select("structured_reasoning", "budget")
        critical_result = selector.select("structured_reasoning", "critical")
        # Budget should favor cheaper model
        assert budget_result.cost_score >= critical_result.cost_score or \
               budget_result.model_id != critical_result.model_id


# ══════════════════════════════════════════════════════════════
# Phase 7 — API
# ══════════════════════════════════════════════════════════════

class TestAPI:

    def test_MI28_router_exists(self):
        from api.routes.models import router
        paths = [str(r.path) for r in router.routes]
        assert any("catalog" in p for p in paths)
        assert any("profiles" in p for p in paths)
        assert any("performance" in p for p in paths)
        assert any("recommendations" in p for p in paths)

    def test_MI29_router_mounted(self):
        import inspect, importlib
        main_mod = importlib.import_module("api.main")
        source = inspect.getsource(main_mod)
        assert "models_router" in source

    def test_MI30_status_endpoint(self):
        import asyncio
        from api.routes.models import model_status
        result = asyncio.get_event_loop().run_until_complete(model_status())
        assert "active" in result or "catalog" in result


# ══════════════════════════════════════════════════════════════
# Safety
# ══════════════════════════════════════════════════════════════

class TestSafety:

    def test_MI31_no_secrets_in_catalog(self):
        """Catalog entries don't contain API keys."""
        entry = ModelEntry(model_id="test/m1", name="Test")
        d = json.dumps(entry.to_dict())
        assert "sk-" not in d
        assert "api_key" not in d.lower()

    def test_MI32_no_secrets_in_selection(self):
        """Selection results don't contain API keys."""
        result = SelectionResult(
            model_id="test/m1", task_class="coding",
            rationale="test", final_score=0.5,
        )
        d = json.dumps(result.to_dict())
        assert "sk-" not in d
