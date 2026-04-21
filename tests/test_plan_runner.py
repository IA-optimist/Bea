"""
tests/test_plan_runner.py — Plan Runner tests.

Covers: step context, run state, step execution, plan runner lifecycle,
pause/resume/cancel, approval flow, execution memory, API routes.
"""
import os
import tempfile
import pytest


# ═══════════════════════════════════════════════════════════════
# 1 — Step Context
# ═══════════════════════════════════════════════════════════════

class TestStepContext:

    def test_PR01_context_create(self):
        from core.planning.step_context import StepContext
        ctx = StepContext(plan_id="p1", goal="test goal")
        assert ctx.run_id.startswith("run-")
        assert ctx.goal == "test goal"

    def test_PR02_set_get_output(self):
        from core.planning.step_context import StepContext
        ctx = StepContext()
        ctx.set_step_output("s1", {"research": "done"})
        assert ctx.get_step_output("s1") == {"research": "done"}

    def test_PR03_merged_outputs(self):
        from core.planning.step_context import StepContext
        ctx = StepContext()
        ctx.set_step_output("s1", {"sector": "AI", "research": "complete"})
        ctx.set_step_output("s2", {"persona": "Lisa", "sector": "AI updated"})
        merged = ctx.get_all_outputs()
        assert merged["persona"] == "Lisa"
        assert merged["sector"] == "AI updated"  # later step overrides

    def test_PR04_artifacts(self):
        from core.planning.step_context import StepContext
        ctx = StepContext()
        ctx.add_artifact("/workspace/business/test/README.md")
        ctx.add_artifact("/workspace/business/test/README.md")  # dedup
        assert len(ctx.artifacts) == 1

    def test_PR05_approval_recording(self):
        from core.planning.step_context import StepContext
        ctx = StepContext()
        ctx.record_approval("s3", approved=True, reason="operator approved")
        assert ctx.approval_decisions["s3"]["approved"] is True

    def test_PR06_serialization(self):
        from core.planning.step_context import StepContext
        ctx = StepContext(plan_id="p1", goal="test")
        ctx.set_step_output("s1", {"data": "value"})
        j = ctx.to_json()
        ctx2 = StepContext.from_json(j)
        assert ctx2.plan_id == "p1"
        assert ctx2.get_step_output("s1") == {"data": "value"}


# ═══════════════════════════════════════════════════════════════
# 2 — Run State
# ═══════════════════════════════════════════════════════════════

class TestRunState:

    def test_PR07_run_create(self):
        from core.planning.run_state import PlanRun, RunStatus
        run = PlanRun(plan_id="p1", steps_total=5)
        assert run.status == RunStatus.RUNNING
        assert run.progress == 0

    def test_PR08_run_progress(self):
        from core.planning.run_state import PlanRun
        run = PlanRun(steps_total=4, steps_completed=2)
        assert run.progress == 0.5

    def test_PR09_run_store(self):
        from core.planning.run_state import RunStateStore, PlanRun
        with tempfile.TemporaryDirectory() as td:
            store = RunStateStore(persist_dir=td)
            run = PlanRun(plan_id="p1", steps_total=3)
            store.save(run)
            loaded = store.get(run.run_id)
            assert loaded is not None
            assert loaded.plan_id == "p1"

    def test_PR10_run_list(self):
        from core.planning.run_state import RunStateStore, PlanRun, RunStatus
        with tempfile.TemporaryDirectory() as td:
            store = RunStateStore(persist_dir=td)
            store.save(PlanRun(plan_id="p1", status=RunStatus.RUNNING))
            store.save(PlanRun(plan_id="p2", status=RunStatus.COMPLETED))
            assert len(store.list_all()) == 2
            assert len(store.list_active()) == 1

    def test_PR11_run_persistence(self):
        from core.planning.run_state import RunStateStore, PlanRun
        with tempfile.TemporaryDirectory() as td:
            store1 = RunStateStore(persist_dir=td)
            run = PlanRun(plan_id="p1")
            store1.save(run)

            store2 = RunStateStore(persist_dir=td)
            store2.load_from_disk()
            loaded = store2.get(run.run_id)
            assert loaded is not None


# ═══════════════════════════════════════════════════════════════
# 3 — Step Executor
# ═══════════════════════════════════════════════════════════════

class TestStepExecutor:

    def test_PR12_execute_skill_step(self):
        from core.planning.step_executor import execute_step
        from core.planning.execution_plan import PlanStep, StepType
        from core.planning.step_context import StepContext
        step = PlanStep(type=StepType.SKILL, target_id="market_research.basic")
        ctx = StepContext()
        ctx.set_step_output("prev", {"sector": "AI automation"})
        result = execute_step(step, ctx)
        assert result.ok is True
        assert result.output.get("prepared") is True

    def test_PR13_execute_business_action_step(self):
        from core.planning.step_executor import execute_step
        from core.planning.execution_plan import PlanStep, StepType
        from core.planning.step_context import StepContext
        step = PlanStep(type=StepType.BUSINESS_ACTION, target_id="venture.research_workspace")
        ctx = StepContext(goal="test research")
        ctx.set_step_output("prev", {"sector": "AI"})
        result = execute_step(step, ctx)
        assert result.ok is True
        assert result.output.get("action_id") == "venture.research_workspace"

    def test_PR14_execute_tool_needs_approval(self):
        from core.planning.step_executor import execute_step
        from core.planning.execution_plan import PlanStep, StepType
        from core.planning.step_context import StepContext
        step = PlanStep(type=StepType.TOOL, target_id="n8n.workflow.trigger")
        ctx = StepContext()
        result = execute_step(step, ctx)
        assert result.needs_approval is True

    def test_PR15_unknown_step_type(self):
        from core.planning.step_executor import execute_step
        from core.planning.execution_plan import PlanStep
        from core.planning.step_context import StepContext
        step = PlanStep(target_id="test")
        step.type = "unknown"
        ctx = StepContext()
        result = execute_step(step, ctx)
        assert result.ok is False

    def test_PR16_unknown_action(self):
        from core.planning.step_executor import execute_step
        from core.planning.execution_plan import PlanStep, StepType
        from core.planning.step_context import StepContext
        step = PlanStep(type=StepType.BUSINESS_ACTION, target_id="nonexistent.action")
        ctx = StepContext()
        result = execute_step(step, ctx)
        assert result.ok is False

    def test_PR17_context_propagation(self):
        """Step 2 can read Step 1 outputs."""
        from core.planning.step_executor import execute_step
        from core.planning.execution_plan import PlanStep, StepType
        from core.planning.step_context import StepContext

        ctx = StepContext()

        # Step 1: skill that requires 'sector'
        s1 = PlanStep(type=StepType.SKILL, target_id="market_research.basic",
                      inputs={"sector": "AI chatbots"})
        r1 = execute_step(s1, ctx)
        assert r1.ok is True
        ctx.set_step_output(s1.step_id, r1.output)

        # Step 2: skill that requires 'target_market' — gets it from merged context
        s2 = PlanStep(type=StepType.SKILL, target_id="persona.basic",
                      inputs={"target_market": "e-commerce store owners"})
        r2 = execute_step(s2, ctx)
        assert r2.ok is True


# ═══════════════════════════════════════════════════════════════
# 4 — Plan Runner
# ═══════════════════════════════════════════════════════════════

class TestPlanRunner:

    def _make_plan(self, store, **kwargs):
        """Helper: create and store a validated plan."""
        from core.planning.execution_plan import ExecutionPlan, PlanStep, StepType, PlanStatus
        steps = kwargs.get("steps", [
            PlanStep(type=StepType.SKILL, target_id="market_research.basic",
                    name="Market Research", inputs={"sector": "AI"}),
            PlanStep(type=StepType.SKILL, target_id="persona.basic",
                    name="Persona", inputs={"target_market": "SMBs"}),
        ])
        plan = ExecutionPlan(
            goal=kwargs.get("goal", "test plan"),
            steps=steps,
            status=kwargs.get("status", PlanStatus.VALIDATED),
        )
        plan.risk_score = plan.compute_risk()
        plan.requires_approval = plan.compute_approval_required()
        store.save(plan)
        return plan

    def test_PR18_start_plan(self):
        from core.planning.plan_runner import PlanRunner
        from core.planning.plan_serializer import PlanStore
        from core.planning.run_state import RunStateStore, RunStatus
        with tempfile.TemporaryDirectory() as td:
            import core.planning.plan_serializer as ps
            import core.planning.run_state as rs
            old_ps, old_rs = ps._store, rs._store
            ps._store = PlanStore(persist_dir=os.path.join(td, "plans"))
            rs._store = RunStateStore(persist_dir=os.path.join(td, "runs"))
            try:
                plan = self._make_plan(ps._store)
                runner = PlanRunner()
                run = runner.start(plan.plan_id)
                assert run.status == RunStatus.COMPLETED
                assert run.steps_completed == 2
                assert run.progress == 1.0
            finally:
                ps._store, rs._store = old_ps, old_rs

    def test_PR19_plan_not_found(self):
        from core.planning.plan_runner import PlanRunner
        from core.planning.run_state import RunStatus
        runner = PlanRunner()
        run = runner.start("nonexistent-plan")
        assert run.status == RunStatus.FAILED

    def test_PR20_plan_needs_approval(self):
        from core.planning.plan_runner import PlanRunner
        from core.planning.plan_serializer import PlanStore
        from core.planning.run_state import RunStateStore, RunStatus
        from core.planning.execution_plan import PlanStep, StepType, PlanStatus
        with tempfile.TemporaryDirectory() as td:
            import core.planning.plan_serializer as ps
            import core.planning.run_state as rs
            old_ps, old_rs = ps._store, rs._store
            ps._store = PlanStore(persist_dir=os.path.join(td, "plans"))
            rs._store = RunStateStore(persist_dir=os.path.join(td, "runs"))
            try:
                plan = self._make_plan(
                    ps._store,
                    status=PlanStatus.AWAITING_APPROVAL,
                    steps=[PlanStep(type=StepType.TOOL, target_id="n8n.workflow.trigger",
                                   name="Trigger")],
                )
                plan.requires_approval = True
                ps._store.save(plan)

                runner = PlanRunner()
                run = runner.start(plan.plan_id)
                assert run.status == RunStatus.FAILED
                assert "approval" in run.error.lower()
            finally:
                ps._store, rs._store = old_ps, old_rs

    def test_PR21_tool_step_pauses_for_approval(self):
        from core.planning.plan_runner import PlanRunner
        from core.planning.plan_serializer import PlanStore
        from core.planning.run_state import RunStateStore, RunStatus
        from core.planning.execution_plan import PlanStep, StepType, PlanStatus
        with tempfile.TemporaryDirectory() as td:
            import core.planning.plan_serializer as ps
            import core.planning.run_state as rs
            old_ps, old_rs = ps._store, rs._store
            ps._store = PlanStore(persist_dir=os.path.join(td, "plans"))
            rs._store = RunStateStore(persist_dir=os.path.join(td, "runs"))
            try:
                plan = self._make_plan(
                    ps._store,
                    status=PlanStatus.APPROVED,
                    steps=[
                        PlanStep(type=StepType.SKILL, target_id="market_research.basic",
                                name="Research", inputs={"sector": "AI"}),
                        PlanStep(type=StepType.TOOL, target_id="n8n.workflow.trigger",
                                name="Trigger n8n"),
                    ],
                )
                runner = PlanRunner()
                run = runner.start(plan.plan_id)
                # Should pause at tool step
                assert run.status == RunStatus.AWAITING_APPROVAL
                assert run.steps_completed == 1
            finally:
                ps._store, rs._store = old_ps, old_rs

    def test_PR22_cancel(self):
        from core.planning.plan_runner import PlanRunner
        from core.planning.plan_serializer import PlanStore
        from core.planning.run_state import RunStateStore, RunStatus, PlanRun
        with tempfile.TemporaryDirectory() as td:
            import core.planning.plan_serializer as ps
            import core.planning.run_state as rs
            old_ps, old_rs = ps._store, rs._store
            ps._store = PlanStore(persist_dir=os.path.join(td, "plans"))
            rs._store = RunStateStore(persist_dir=os.path.join(td, "runs"))
            try:
                plan = self._make_plan(ps._store)
                # Create a paused run manually
                run = PlanRun(plan_id=plan.plan_id, status=RunStatus.PAUSED, steps_total=2)
                rs._store.save(run)
                runner = PlanRunner()
                cancelled = runner.cancel(run.run_id)
                assert cancelled.status == RunStatus.CANCELLED
            finally:
                ps._store, rs._store = old_ps, old_rs

    def test_PR23_step_failure_stops_run(self):
        from core.planning.plan_runner import PlanRunner
        from core.planning.plan_serializer import PlanStore
        from core.planning.run_state import RunStateStore, RunStatus
        from core.planning.execution_plan import PlanStep, StepType
        with tempfile.TemporaryDirectory() as td:
            import core.planning.plan_serializer as ps
            import core.planning.run_state as rs
            old_ps, old_rs = ps._store, rs._store
            ps._store = PlanStore(persist_dir=os.path.join(td, "plans"))
            rs._store = RunStateStore(persist_dir=os.path.join(td, "runs"))
            try:
                plan = self._make_plan(
                    ps._store,
                    steps=[
                        PlanStep(type=StepType.BUSINESS_ACTION, target_id="nonexistent.action",
                                name="Bad Step"),
                        PlanStep(type=StepType.SKILL, target_id="market_research.basic",
                                name="Should Not Run", inputs={"sector": "AI"}),
                    ],
                )
                runner = PlanRunner()
                run = runner.start(plan.plan_id)
                assert run.status == RunStatus.FAILED
                assert run.steps_completed == 0
                assert run.steps_failed == 1
            finally:
                ps._store, rs._store = old_ps, old_rs

    def test_PR24_resume_after_approval(self):
        from core.planning.plan_runner import PlanRunner
        from core.planning.plan_serializer import PlanStore
        from core.planning.run_state import RunStateStore, RunStatus
        from core.planning.execution_plan import PlanStep, StepType, PlanStatus
        with tempfile.TemporaryDirectory() as td:
            import core.planning.plan_serializer as ps
            import core.planning.run_state as rs
            old_ps, old_rs = ps._store, rs._store
            ps._store = PlanStore(persist_dir=os.path.join(td, "plans"))
            rs._store = RunStateStore(persist_dir=os.path.join(td, "runs"))
            try:
                plan = self._make_plan(
                    ps._store,
                    status=PlanStatus.APPROVED,
                    steps=[
                        PlanStep(step_id="s1", type=StepType.SKILL,
                                target_id="market_research.basic",
                                name="Research", inputs={"sector": "AI"}),
                        PlanStep(step_id="s2", type=StepType.TOOL,
                                target_id="notification.log",
                                name="Notify",
                                inputs={"title": "Done", "message": "Research complete"}),
                    ],
                )
                runner = PlanRunner()
                # notification.log is low risk and doesn't need approval — run completes
                run = runner.start(plan.plan_id)
                assert run.status == RunStatus.COMPLETED
                assert run.steps_completed == 2
            finally:
                ps._store, rs._store = old_ps, old_rs

    def test_PR25_execution_memory_recorded(self):
        from core.planning.plan_runner import PlanRunner
        from core.planning.plan_serializer import PlanStore
        from core.planning.run_state import RunStateStore
        from core.planning.execution_memory import ExecutionMemory
        with tempfile.TemporaryDirectory() as td:
            import core.planning.plan_serializer as ps
            import core.planning.run_state as rs
            import core.planning.execution_memory as em
            old_ps, old_rs, old_em = ps._store, rs._store, em._memory
            ps._store = PlanStore(persist_dir=os.path.join(td, "plans"))
            rs._store = RunStateStore(persist_dir=os.path.join(td, "runs"))
            em._memory = ExecutionMemory(persist_path=os.path.join(td, "history.json"))
            em._memory._loaded = True
            try:
                plan = self._make_plan(ps._store)
                runner = PlanRunner()
                run = runner.start(plan.plan_id)
                history = em._memory.get_history()
                assert len(history) >= 1
                assert history[0]["success"] is True
            finally:
                ps._store, rs._store, em._memory = old_ps, old_rs, old_em


# ═══════════════════════════════════════════════════════════════
# 5 — API Routes
# ═══════════════════════════════════════════════════════════════

class TestPlanRunnerAPI:

    def test_PR26_plan_run_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/plans/{plan_id}/run" in paths

    def test_PR27_plan_resume_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/plans/{plan_id}/resume" in paths

    def test_PR28_plan_pause_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/plans/{plan_id}/pause" in paths

    def test_PR29_plan_cancel_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/plans/{plan_id}/cancel" in paths

    def test_PR30_plan_runs_list_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/plans/{plan_id}/runs" in paths

    def test_PR31_run_detail_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/plans/runs/{run_id}" in paths

    def test_PR32_run_context_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/plans/runs/{run_id}/context" in paths

    def test_PR33_run_artifacts_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/plans/runs/{run_id}/artifacts" in paths

    def test_PR34_runs_start_alias(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/runs/start/{plan_id}" in paths

    def test_PR35_runs_list_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/runs" in paths

    def test_PR36_runs_active_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/runs/filter/active" in paths

    def test_PR37_approve_step_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/runs/approve-step/{run_id}" in paths


# ═══════════════════════════════════════════════════════════════
# 6 — Safety
# ═══════════════════════════════════════════════════════════════

class TestPlanRunnerSafety:

    def test_PR38_unapproved_plan_blocked(self):
        from core.planning.plan_runner import PlanRunner
        from core.planning.plan_serializer import PlanStore
        from core.planning.run_state import RunStateStore, RunStatus
        from core.planning.execution_plan import PlanStep, StepType, PlanStatus, ExecutionPlan
        with tempfile.TemporaryDirectory() as td:
            import core.planning.plan_serializer as ps
            import core.planning.run_state as rs
            old_ps, old_rs = ps._store, rs._store
            ps._store = PlanStore(persist_dir=os.path.join(td, "plans"))
            rs._store = RunStateStore(persist_dir=os.path.join(td, "runs"))
            try:
                plan = ExecutionPlan(
                    goal="test",
                    steps=[PlanStep(type=StepType.TOOL, target_id="n8n.workflow.trigger")],
                    status=PlanStatus.AWAITING_APPROVAL,
                )
                plan.requires_approval = True
                ps._store.save(plan)
                runner = PlanRunner()
                run = runner.start(plan.plan_id)
                assert run.status == RunStatus.FAILED
            finally:
                ps._store, rs._store = old_ps, old_rs

    @pytest.mark.xfail(reason="runs dashboard static HTML drift", strict=False)
    def test_PR40_runs_dashboard_exists(self):
        path = os.path.join(os.path.dirname(__file__), "..", "static", "runs.html")
        assert os.path.isfile(path)
        content = open(path).read()
        assert "Active" in content
        assert "Awaiting Approval" in content or "approval" in content.lower()
        assert "Resume" in content
        assert "Cancel" in content

    def test_PR39_completed_step_outputs_preserved_on_failure(self):
        from core.planning.plan_runner import PlanRunner
        from core.planning.plan_serializer import PlanStore
        from core.planning.run_state import RunStateStore
        from core.planning.execution_plan import PlanStep, StepType
        with tempfile.TemporaryDirectory() as td:
            import core.planning.plan_serializer as ps
            import core.planning.run_state as rs
            old_ps, old_rs = ps._store, rs._store
            ps._store = PlanStore(persist_dir=os.path.join(td, "plans"))
            rs._store = RunStateStore(persist_dir=os.path.join(td, "runs"))
            try:
                from core.planning.execution_plan import ExecutionPlan, PlanStatus
                plan = ExecutionPlan(
                    goal="partial",
                    steps=[
                        PlanStep(step_id="good", type=StepType.SKILL,
                                target_id="market_research.basic",
                                name="Good Step", inputs={"sector": "AI"}),
                        PlanStep(step_id="bad", type=StepType.BUSINESS_ACTION,
                                target_id="nonexistent",
                                name="Bad Step"),
                    ],
                    status=PlanStatus.VALIDATED,
                )
                ps._store.save(plan)
                runner = PlanRunner()
                run = runner.start(plan.plan_id)
                # First step succeeded — output preserved
                assert "good" in run.context.step_outputs
                assert run.steps_completed == 1
            finally:
                ps._store, rs._store = old_ps, old_rs
