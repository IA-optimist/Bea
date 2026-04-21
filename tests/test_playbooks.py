"""
tests/test_playbooks.py — Strategic playbook system tests.

Validates:
  - Playbook loading and registry
  - Playbook structure (steps, skills, metadata)
  - Plan generation from playbooks
  - End-to-end execution via PlanRunner
  - Performance tracking
  - API endpoints
  - Extensibility (save/version)
"""
import pytest
pytestmark = pytest.mark.integration

from core.planning.playbook import (
    Playbook, PlaybookStep, PlaybookRegistry,
    PlaybookPerformanceTracker, execute_playbook,
)


class TestPlaybookLoading:

    def test_PB01_6_playbooks_loaded(self):
        """All 6 playbooks load from disk."""
        reg = PlaybookRegistry()
        count = reg.load_all()
        assert count == 6, f"Expected 6, got {count}"

    def test_PB02_market_analysis_exists(self):
        reg = PlaybookRegistry()
        reg.load_all()
        pb = reg.get("market_analysis")
        assert pb is not None
        assert pb.name == "Market Analysis"

    def test_PB03_product_creation_exists(self):
        reg = PlaybookRegistry()
        reg.load_all()
        pb = reg.get("product_creation")
        assert pb is not None
        assert len(pb.steps) == 6

    def test_PB04_all_playbook_ids(self):
        reg = PlaybookRegistry()
        reg.load_all()
        ids = {pb["playbook_id"] for pb in reg.list_all()}
        expected = {"market_analysis", "product_creation", "offer_design",
                    "landing_page", "growth_experiment", "content_strategy"}
        assert ids == expected

    def test_PB05_list_by_tier(self):
        reg = PlaybookRegistry()
        reg.load_all()
        growth = reg.list_by_tier("growth")
        assert len(growth) >= 2  # landing_page, growth_experiment, content_strategy


class TestPlaybookStructure:

    def _get(self, pid):
        reg = PlaybookRegistry()
        reg.load_all()
        return reg.get(pid)

    def test_PB06_steps_have_skill_ids(self):
        """Every playbook step references a real skill."""
        from core.skills.domain_loader import DomainSkillRegistry
        skill_reg = DomainSkillRegistry()
        skill_reg.load_all()
        skill_ids = set(skill_reg._skills.keys())

        reg = PlaybookRegistry()
        reg.load_all()
        for pb_dict in reg.list_all():
            pb = reg.get(pb_dict["playbook_id"])
            for step in pb.steps:
                assert step.skill_id in skill_ids, \
                    f"Playbook {pb.playbook_id} step references unknown skill: {step.skill_id}"

    def test_PB07_has_success_criteria(self):
        """Every playbook has at least 3 success criteria."""
        reg = PlaybookRegistry()
        reg.load_all()
        for pb_dict in reg.list_all():
            pb = reg.get(pb_dict["playbook_id"])
            assert len(pb.success_criteria) >= 3, \
                f"{pb.playbook_id} has only {len(pb.success_criteria)} criteria"

    def test_PB08_has_goal_template(self):
        """Every playbook has a goal template."""
        reg = PlaybookRegistry()
        reg.load_all()
        for pb_dict in reg.list_all():
            pb = reg.get(pb_dict["playbook_id"])
            assert len(pb.goal_template) > 10, f"{pb.playbook_id} missing goal_template"

    def test_PB09_to_dict_complete(self):
        pb = self._get("market_analysis")
        d = pb.to_dict()
        assert "playbook_id" in d
        assert "steps" in d
        assert "step_count" in d
        assert "skills_used" in d
        assert d["step_count"] == len(d["steps"])


class TestPlanGeneration:

    def test_PB10_build_plan_from_playbook(self):
        """Playbook generates valid ExecutionPlan."""
        reg = PlaybookRegistry()
        reg.load_all()
        pb = reg.get("market_analysis")
        plan = pb.build_plan("Analyze the AI chatbot market")

        assert plan.goal == "Analyze the AI chatbot market"
        assert len(plan.steps) == 4
        assert plan.status.value == "approved"
        assert plan.template_id == "market_analysis"

    def test_PB11_steps_are_skill_type(self):
        """All generated plan steps are StepType.SKILL."""
        from core.planning.execution_plan import StepType
        reg = PlaybookRegistry()
        reg.load_all()
        pb = reg.get("product_creation")
        plan = pb.build_plan("Create a product")
        for step in plan.steps:
            assert step.type == StepType.SKILL

    def test_PB12_step_ids_prefixed(self):
        """Plan step IDs include playbook prefix."""
        reg = PlaybookRegistry()
        reg.load_all()
        pb = reg.get("landing_page")
        plan = pb.build_plan("Design landing page")
        for step in plan.steps:
            assert step.step_id.startswith("pb-landing_page-")

    def test_PB13_dependencies_chain(self):
        """Plan steps have sequential dependencies."""
        reg = PlaybookRegistry()
        reg.load_all()
        pb = reg.get("growth_experiment")
        plan = pb.build_plan("Plan growth")
        # Step 2 should depend on step 1
        assert plan.steps[1].depends_on == ["pb-growth_experiment-s1"]


class TestPlaybookExecution:

    def test_PB14_market_analysis_executes(self):
        """Market analysis playbook executes all 4 steps."""
        result = execute_playbook("market_analysis", "Analyze AI chatbot market")
        assert result["ok"] is True
        assert result["run"]["steps_completed"] == 4
        assert result["run"]["status"] == "completed"

    def test_PB15_product_creation_executes(self):
        """Product creation playbook executes all 6 steps."""
        result = execute_playbook("product_creation", "Create AI chatbot product")
        assert result["ok"] is True
        assert result["run"]["steps_completed"] == 6

    def test_PB16_landing_page_executes(self):
        """Landing page playbook executes all 4 steps."""
        result = execute_playbook("landing_page", "Design landing page for AI tool")
        assert result["ok"] is True
        assert result["run"]["steps_completed"] == 4

    def test_PB17_nonexistent_playbook_fails(self):
        """Unknown playbook returns error."""
        result = execute_playbook("nonexistent_playbook", "goal")
        assert result["ok"] is False
        assert "not found" in result["error"]

    def test_PB18_execution_returns_playbook_info(self):
        """Execution result includes playbook metadata."""
        result = execute_playbook("offer_design", "Design offer for SaaS")
        assert "playbook" in result
        assert result["playbook"]["playbook_id"] == "offer_design"
        assert result["playbook"]["step_count"] == 5


class TestPerformanceTracking:

    def test_PB19_tracker_records_execution(self):
        tracker = PlaybookPerformanceTracker()
        tracker.record_start("test_pb", "run-1", 3)
        tracker.record_complete("run-1", "completed", 3)

        stats = tracker.get_stats("test_pb")
        assert stats["executions"] == 1
        assert stats["completed"] == 1
        assert stats["success_rate"] == 1.0

    def test_PB20_tracker_failure_rate(self):
        tracker = PlaybookPerformanceTracker()
        tracker.record_start("mix", "r1", 3)
        tracker.record_complete("r1", "completed", 3)
        tracker.record_start("mix", "r2", 3)
        tracker.record_complete("r2", "failed", 1)

        stats = tracker.get_stats("mix")
        assert stats["executions"] == 2
        assert stats["completed"] == 1
        assert stats["failed"] == 1
        assert stats["success_rate"] == 0.5

    def test_PB21_execution_updates_tracker(self):
        """execute_playbook records stats."""
        execute_playbook("market_analysis", "Test tracking")
        from core.planning.playbook import get_performance_tracker
        stats = get_performance_tracker().get_stats("market_analysis")
        assert stats["executions"] >= 1

    def test_PB22_all_stats(self):
        tracker = PlaybookPerformanceTracker()
        tracker.record_start("a", "r1", 2)
        tracker.record_complete("r1", "completed", 2)
        tracker.record_start("b", "r2", 3)
        tracker.record_complete("r2", "failed", 1)

        all_stats = tracker.get_all_stats()
        assert len(all_stats) == 2
        ids = {s["playbook_id"] for s in all_stats}
        assert ids == {"a", "b"}


class TestExtensibility:

    def test_PB23_save_and_reload(self):
        """Custom playbook can be saved and reloaded."""
        import tempfile
        import os
        from pathlib import Path
        import core.planning.playbook as _mod

        old_dir = _mod._PLAYBOOKS_DIR
        tmpdir = Path(tempfile.mkdtemp())
        _mod._PLAYBOOKS_DIR = tmpdir

        try:
            reg = PlaybookRegistry()
            custom = Playbook(
                playbook_id="custom_test",
                name="Custom Test",
                description="Test playbook",
                goal_template="Test {product}",
                steps=[
                    PlaybookStep(skill_id="market_research.basic", name="Research"),
                    PlaybookStep(skill_id="persona.basic", name="Persona"),
                ],
                success_criteria=["Test passes"],
            )
            ok = reg.save(custom)
            assert ok is True

            # Verify file exists
            path = os.path.join(tmpdir, "custom_test.json")
            assert os.path.exists(path)

            # Reload
            reg2 = PlaybookRegistry()
            _mod._PLAYBOOKS_DIR = tmpdir  # still points to tmp
            count = reg2.load_all()
            assert count == 1
            pb = reg2.get("custom_test")
            assert pb is not None
            assert len(pb.steps) == 2
        finally:
            _mod._PLAYBOOKS_DIR = old_dir
            import shutil
            shutil.rmtree(tmpdir)

    def test_PB24_from_dict_roundtrip(self):
        """Playbook survives to_dict → from_dict roundtrip."""
        reg = PlaybookRegistry()
        reg.load_all()
        original = reg.get("market_analysis")
        d = original.to_dict()

        # Remove computed fields
        d.pop("step_count", None)
        d.pop("skills_used", None)

        restored = Playbook.from_dict(d)
        assert restored.playbook_id == original.playbook_id
        assert len(restored.steps) == len(original.steps)
        assert restored.version == original.version


class TestAPIEndpoints:

    def test_PB25_list_endpoint(self):
        """Playbooks list endpoint exists."""
        from api.routes.playbooks import router
        paths = [r.path for r in router.routes]
        assert any("playbooks" in str(p) and "run" not in str(p)
                    and "stats" not in str(p) for p in paths)

    def test_PB26_run_endpoint(self):
        """Playbook run endpoint exists."""
        from api.routes.playbooks import router
        paths = [r.path for r in router.routes]
        assert any("run" in str(p) for p in paths)

    def test_PB27_stats_endpoint(self):
        """Playbook stats endpoint exists."""
        from api.routes.playbooks import router
        paths = [r.path for r in router.routes]
        assert any("stats" in str(p) for p in paths)

    def test_PB28_router_mounted(self):
        """Playbooks router is mounted in main app."""
        import inspect
        import importlib
        main_mod = importlib.import_module("api.main")
        source = inspect.getsource(main_mod)
        assert "playbooks_router" in source
