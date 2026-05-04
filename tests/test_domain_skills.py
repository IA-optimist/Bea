"""
tests/test_domain_skills.py — Domain skill system tests.
"""
import os
import tempfile
import pytest


# ═══════════════════════════════════════════════════════════════
# 1 — Skill Schema
# ═══════════════════════════════════════════════════════════════

class TestSkillSchema:

    def test_DS01_skill_input_dataclass(self):
        from core.skills.domain_schema import SkillInput
        i = SkillInput(name="sector", type="string", required=True)
        assert i.name == "sector"
        assert i.required is True

    def test_DS02_domain_skill_to_dict(self):
        from core.skills.domain_schema import DomainSkill
        s = DomainSkill(id="test.basic", name="Test", domain="test")
        d = s.to_dict()
        assert d["id"] == "test.basic"
        assert "has_logic" in d

    def test_DS03_from_directory(self):
        from core.skills.domain_schema import DomainSkill
        skill_dir = os.path.join(os.path.dirname(__file__), "..", "business", "skills", "market_research")
        if os.path.isdir(skill_dir):
            skill = DomainSkill.from_directory(skill_dir)
            assert skill.id == "market_research.basic"
            assert skill.version == "1.0"
            assert len(skill.inputs) >= 1
            assert len(skill.outputs) >= 3
            assert bool(skill.logic)
            assert len(skill.examples) >= 1

    def test_DS04_build_prompt_context(self):
        from core.skills.domain_schema import DomainSkill
        skill_dir = os.path.join(os.path.dirname(__file__), "..", "business", "skills", "market_research")
        if os.path.isdir(skill_dir):
            skill = DomainSkill.from_directory(skill_dir)
            ctx = skill.build_prompt_context({"sector": "AI automation"})
            assert "Market Research" in ctx
            assert "AI automation" in ctx
            assert "Required Output Format" in ctx

    def test_DS05_missing_skill_json(self):
        from core.skills.domain_schema import DomainSkill
        with tempfile.TemporaryDirectory() as td:
            with pytest.raises(FileNotFoundError):
                DomainSkill.from_directory(td)


# ═══════════════════════════════════════════════════════════════
# 2 — Skill Loader
# ═══════════════════════════════════════════════════════════════

class TestSkillLoader:

    def test_DS06_load_all(self):
        from core.skills.domain_loader import DomainSkillRegistry
        reg = DomainSkillRegistry()
        count = reg.load_all()
        assert count >= 6

    def test_DS07_get_skill(self):
        from core.skills.domain_loader import DomainSkillRegistry
        reg = DomainSkillRegistry()
        reg.load_all()
        skill = reg.get("market_research.basic")
        assert skill is not None
        assert skill.domain == "market_research"

    def test_DS08_list_all(self):
        from core.skills.domain_loader import DomainSkillRegistry
        reg = DomainSkillRegistry()
        reg.load_all()
        skills = reg.list_all()
        assert len(skills) >= 6
        ids = {s.id for s in skills}
        assert "market_research.basic" in ids
        assert "offer_design.basic" in ids
        assert "persona.basic" in ids
        assert "acquisition.basic" in ids
        assert "saas_scope.basic" in ids
        assert "automation_opportunity.basic" in ids

    def test_DS09_list_by_domain(self):
        from core.skills.domain_loader import DomainSkillRegistry
        reg = DomainSkillRegistry()
        reg.load_all()
        mr = reg.list_by_domain("market_research")
        assert len(mr) >= 1

    def test_DS10_get_chain(self):
        from core.skills.domain_loader import DomainSkillRegistry
        reg = DomainSkillRegistry()
        reg.load_all()
        chain = reg.get_chain(["market_research.basic", "persona.basic"])
        assert len(chain) == 2

    def test_DS11_stats(self):
        from core.skills.domain_loader import DomainSkillRegistry
        reg = DomainSkillRegistry()
        reg.load_all()
        s = reg.stats()
        assert s["total"] >= 6
        assert s["loaded"] is True

    def test_DS12_singleton(self):
        from core.skills.domain_loader import get_domain_registry
        r1 = get_domain_registry()
        r2 = get_domain_registry()
        assert r1 is r2


# ═══════════════════════════════════════════════════════════════
# 3 — Skill Executor
# ═══════════════════════════════════════════════════════════════

class TestSkillExecutor:

    def test_DS13_prepare(self):
        from core.skills.domain_executor import DomainSkillExecutor
        exec_ = DomainSkillExecutor()
        result = exec_.prepare("market_research.basic", {"sector": "AI"})
        assert "prompt_context" in result
        assert "AI" in result["prompt_context"]

    def test_DS14_prepare_missing_input(self):
        from core.skills.domain_executor import DomainSkillExecutor
        exec_ = DomainSkillExecutor()
        result = exec_.prepare("market_research.basic", {})
        assert "error" in result
        assert "sector" in result["error"]

    def test_DS15_prepare_unknown_skill(self):
        from core.skills.domain_executor import DomainSkillExecutor
        exec_ = DomainSkillExecutor()
        result = exec_.prepare("nonexistent.skill", {})
        assert "error" in result

    def test_DS16_validate_complete_output(self):
        from core.skills.domain_executor import DomainSkillExecutor
        exec_ = DomainSkillExecutor()
        output = {
            "tam": {"value": "$10B"},
            "sam": {"value": "$2B"},
            "som": {"value": "$10M"},
            "problems": [{"problem": "test"}],
            "opportunities": [{"title": "test"}],
            "trends": [{"trend": "AI"}],
            "risks": [{"risk": "competition"}],
        }
        result = exec_.validate("market_research.basic", output)
        assert result.ok is True
        assert result.quality_score >= 0.7

    def test_DS17_validate_incomplete_output(self):
        from core.skills.domain_executor import DomainSkillExecutor
        exec_ = DomainSkillExecutor()
        result = exec_.validate("market_research.basic", {"tam": {"value": "$10B"}})
        assert result.quality_score < 1.0

    def test_DS18_validate_structure(self):
        from core.skills.domain_executor import DomainSkillExecutor
        exec_ = DomainSkillExecutor()
        output = {
            "value_proposition": {"problem": "test"},
            "offer_structure": {"tiers": []},
            "pricing": {"model": "monthly"},
            "differentiation": ["unique"],
            "usp": "Best product",
        }
        result = exec_.validate("offer_design.basic", output)
        assert result.ok is True

    def test_DS19_execute_chain(self):
        from core.skills.domain_executor import DomainSkillExecutor
        exec_ = DomainSkillExecutor()
        results = exec_.execute_chain(
            ["market_research.basic", "persona.basic"],
            {"sector": "AI", "target_market": "e-commerce"},
        )
        assert len(results) == 2
        assert all(r.skill_id for r in results)

    def test_DS20_result_to_dict(self):
        from core.skills.domain_executor import SkillResult
        r = SkillResult(skill_id="test", output={"a": 1}, quality_score=0.9)
        d = r.to_dict()
        assert d["skill_id"] == "test"
        assert d["quality_score"] == 0.9


# ═══════════════════════════════════════════════════════════════
# 4 — Skill Feedback
# ═══════════════════════════════════════════════════════════════

class TestSkillFeedback:

    def test_DS21_record_feedback(self):
        from core.skills.skill_feedback import SkillFeedbackStore, SkillFeedback
        with tempfile.TemporaryDirectory() as td:
            store = SkillFeedbackStore(persist_dir=td)
            store.record(SkillFeedback(
                skill_id="market_research.basic",
                signal="success",
                quality_score=0.9,
            ))
            entries = store.get_for_skill("market_research.basic")
            assert len(entries) == 1

    def test_DS22_feedback_summary(self):
        from core.skills.skill_feedback import SkillFeedbackStore, SkillFeedback
        with tempfile.TemporaryDirectory() as td:
            store = SkillFeedbackStore(persist_dir=td)
            for _ in range(3):
                store.record(SkillFeedback(skill_id="test", signal="success", quality_score=0.8))
            store.record(SkillFeedback(skill_id="test", signal="failure", quality_score=0.3))
            summary = store.get_summary("test")
            assert summary["executions"] == 4
            assert summary["successes"] == 3
            assert summary["failures"] == 1
            assert summary["success_rate"] == 0.75

    def test_DS23_no_auto_modification(self):
        """Skills are never auto-modified — only proposals stored."""
        from core.skills.skill_feedback import SkillFeedbackStore
        assert not hasattr(SkillFeedbackStore, "apply_improvement")
        assert not hasattr(SkillFeedbackStore, "auto_modify")


# ═══════════════════════════════════════════════════════════════
# 5 — Skill Chains
# ═══════════════════════════════════════════════════════════════

class TestSkillChains:

    def test_DS24_chain_registry(self):
        from core.skills.skill_chain import CHAIN_REGISTRY
        assert len(CHAIN_REGISTRY) >= 3
        assert "full_opportunity_package" in CHAIN_REGISTRY

    def test_DS25_chain_to_dict(self):
        from core.skills.skill_chain import CHAIN_REGISTRY
        chain = CHAIN_REGISTRY["full_opportunity_package"]
        d = chain.to_dict()
        assert len(d["skill_sequence"]) >= 6
        assert len(d["action_sequence"]) >= 4

    def test_DS26_list_chains(self):
        from core.skills.skill_chain import list_chains
        chains = list_chains()
        assert len(chains) >= 3

    def test_DS27_validate_idea_chain(self):
        from core.skills.skill_chain import CHAIN_REGISTRY
        chain = CHAIN_REGISTRY["validate_idea"]
        assert "market_research.basic" in chain.skill_sequence
        assert "persona.basic" in chain.skill_sequence


# ═══════════════════════════════════════════════════════════════
# 6 — API
# ═══════════════════════════════════════════════════════════════

class TestSkillAPI:

    def test_DS28_skills_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/skills" in paths

    def test_DS29_skills_stats_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/skills/stats" in paths

    def test_DS30_skills_chains_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/skills/chains" in paths

    def test_DS31_skill_detail_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/skills/{skill_id}" in paths

    def test_DS32_skill_feedback_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/skills/{skill_id}/feedback" in paths


# ═══════════════════════════════════════════════════════════════
# 7 — Agent Skill Mapping
# ═══════════════════════════════════════════════════════════════

class TestAgentSkillMapping:

    def test_DS33_action_skills_defined(self):
        from core.business_actions import ACTION_SKILLS
        assert "venture.research_workspace" in ACTION_SKILLS
        assert "market_research.basic" in ACTION_SKILLS["venture.research_workspace"]

    def test_DS34_offer_uses_skills(self):
        from core.business_actions import ACTION_SKILLS
        assert "offer_design.basic" in ACTION_SKILLS["offer.package"]
        assert "persona.basic" in ACTION_SKILLS["offer.package"]

    def test_DS35_saas_uses_skills(self):
        from core.business_actions import ACTION_SKILLS
        assert "saas_scope.basic" in ACTION_SKILLS["saas.mvp_spec"]

    def test_DS36_workflow_uses_skills(self):
        from core.business_actions import ACTION_SKILLS
        assert "automation_opportunity.basic" in ACTION_SKILLS["workflow.blueprint"]

    def test_DS37_skills_manifest_written(self):
        """Executor writes skills-used.json to project dir."""
        import inspect
        from core.business_actions import BusinessActionExecutor
        src = inspect.getsource(BusinessActionExecutor.execute)
        assert "skills-used.json" in src
        assert "skills_used" in src

    @pytest.mark.xfail(reason="skill files drift", strict=False)
    def test_DS38_all_skill_files_present(self):
        """Every skill has all 4 required files."""
        base = os.path.join(os.path.dirname(__file__), "..", "business", "skills")
        for skill_dir in os.listdir(base):
            path = os.path.join(base, skill_dir)
            if not os.path.isdir(path) or skill_dir.startswith("_"):
                continue
            for required in ["skill.json", "logic.md", "examples.json", "evaluation.md"]:
                assert os.path.isfile(os.path.join(path, required)), \
                    f"Missing {required} in {skill_dir}"
