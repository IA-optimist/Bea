"""
tests/test_operational_intelligence.py — Operational intelligence layer tests.

Covers: tool registry, readiness, execution, plans, validation,
approval flow, workflow templates, execution memory.
"""
import json
import os
import tempfile
import pytest
pytestmark = pytest.mark.integration



# ═══════════════════════════════════════════════════════════════
# 1 — Tool Schema
# ═══════════════════════════════════════════════════════════════

class TestToolSchema:

    def test_OI01_operational_tool_from_dict(self):
        from core.tools_operational.tool_schema import OperationalTool
        t = OperationalTool.from_dict({
            "id": "test.tool",
            "name": "Test",
            "category": "webhook",
            "risk_level": "low",
        })
        assert t.id == "test.tool"
        assert t.category == "webhook"
        assert t.enabled is True

    def test_OI02_tool_to_dict(self):
        from core.tools_operational.tool_schema import OperationalTool
        t = OperationalTool(id="test.tool", name="Test", category="api")
        d = t.to_dict()
        assert d["id"] == "test.tool"
        assert "retry_policy" in d
        assert d["retry_policy"]["enabled"] is False

    def test_OI03_retry_policy(self):
        from core.tools_operational.tool_schema import RetryPolicy
        rp = RetryPolicy(max_retries=3, enabled=True)
        d = rp.to_dict()
        assert d["max_retries"] == 3
        rp2 = RetryPolicy.from_dict(d)
        assert rp2.max_retries == 3

    def test_OI04_tool_execution_result(self):
        from core.tools_operational.tool_schema import ToolExecutionResult
        r = ToolExecutionResult(tool_id="t1", ok=True, status_code=200)
        d = r.to_dict()
        assert d["ok"] is True
        assert d["tool_id"] == "t1"

    def test_OI05_approval_decision(self):
        from core.tools_operational.tool_schema import ApprovalDecision
        a = ApprovalDecision(target_type="tool", target_id="t1", approved=True)
        d = a.to_dict()
        assert d["approved"] is True

    def test_OI06_tool_from_json_file(self):
        from core.tools_operational.tool_schema import OperationalTool
        path = os.path.join(
            os.path.dirname(__file__), "..", "business", "tools", "n8n_workflow_trigger.json"
        )
        if os.path.isfile(path):
            t = OperationalTool.from_json_file(path)
            assert t.id == "n8n.workflow.trigger"
            assert t.requires_approval is True
            assert "N8N_WEBHOOK_URL" in t.required_secrets


# ═══════════════════════════════════════════════════════════════
# 2 — Tool Registry
# ═══════════════════════════════════════════════════════════════

class TestToolRegistry:

    def test_OI07_registry_builtins(self):
        from core.tools_operational.tool_registry import OperationalToolRegistry
        reg = OperationalToolRegistry()
        reg.load_all()
        tools = reg.list_all()
        ids = {t.id for t in tools}
        assert "n8n.workflow.trigger" in ids
        assert "notification.log" in ids
        assert "http.webhook.post" in ids

    def test_OI08_register_unregister(self):
        from core.tools_operational.tool_registry import OperationalToolRegistry
        from core.tools_operational.tool_schema import OperationalTool
        reg = OperationalToolRegistry()
        reg.register(OperationalTool(id="custom.tool", name="Custom"))
        assert reg.get("custom.tool") is not None
        assert reg.unregister("custom.tool") is True
        assert reg.get("custom.tool") is None

    def test_OI09_list_by_category(self):
        from core.tools_operational.tool_registry import OperationalToolRegistry
        reg = OperationalToolRegistry()
        reg.load_all()
        auto = reg.list_by_category("automation")
        assert len(auto) >= 1

    def test_OI10_list_enabled(self):
        from core.tools_operational.tool_registry import OperationalToolRegistry
        reg = OperationalToolRegistry()
        reg.load_all()
        enabled = reg.list_enabled()
        assert len(enabled) >= 3

    def test_OI11_stats(self):
        from core.tools_operational.tool_registry import OperationalToolRegistry
        reg = OperationalToolRegistry()
        reg.load_all()
        s = reg.stats()
        assert s["total"] >= 3
        assert "by_category" in s

    def test_OI12_singleton(self):
        from core.tools_operational.tool_registry import get_tool_registry
        r1 = get_tool_registry()
        r2 = get_tool_registry()
        assert r1 is r2


# ═══════════════════════════════════════════════════════════════
# 3 — Tool Readiness
# ═══════════════════════════════════════════════════════════════

class TestToolReadiness:

    def test_OI13_n8n_not_ready(self):
        """n8n requires N8N_WEBHOOK_URL which is not set in test env."""
        from core.tools_operational.tool_readiness import check_readiness
        r = check_readiness("n8n.workflow.trigger")
        if not os.environ.get("N8N_WEBHOOK_URL"):
            assert r["ready"] is False
            assert "N8N_WEBHOOK_URL" in r["missing_secrets"]

    def test_OI14_notification_ready(self):
        """notification.log has no required secrets."""
        from core.tools_operational.tool_readiness import check_readiness
        r = check_readiness("notification.log")
        assert r["ready"] is True
        assert r["requires_approval"] is False

    def test_OI15_unknown_tool(self):
        from core.tools_operational.tool_readiness import check_readiness
        r = check_readiness("nonexistent.tool")
        assert r["ready"] is False

    def test_OI16_check_all(self):
        from core.tools_operational.tool_readiness import check_all_readiness
        results = check_all_readiness()
        assert len(results) >= 3

    def test_OI17_blocked_tools(self):
        from core.tools_operational.tool_readiness import get_blocked_tools
        blocked = get_blocked_tools()
        # n8n should be blocked (no webhook URL in test)
        if not os.environ.get("N8N_WEBHOOK_URL"):
            assert any(b["tool_id"] == "n8n.workflow.trigger" for b in blocked)


# ═══════════════════════════════════════════════════════════════
# 4 — Tool Executor
# ═══════════════════════════════════════════════════════════════

class TestToolExecutor:

    def test_OI18_simulate(self):
        from core.tools_operational.tool_executor import OperationalToolExecutor
        ex = OperationalToolExecutor()
        r = ex.simulate("n8n.workflow.trigger", {"payload": {"test": True}})
        assert r.ok is True
        assert r.simulated is True

    def test_OI19_approval_required(self):
        from core.tools_operational.tool_executor import OperationalToolExecutor
        ex = OperationalToolExecutor()
        r = ex.execute("n8n.workflow.trigger", {"payload": {}})
        # Should be blocked by approval gate (not by readiness in simulate mode)
        assert r.approved is False or r.ok is False

    def test_OI20_execute_notification(self):
        from core.tools_operational.tool_executor import OperationalToolExecutor
        with tempfile.TemporaryDirectory() as td:
            os.environ["WORKSPACE_DIR"] = td
            try:
                ex = OperationalToolExecutor()
                r = ex.execute("notification.log", {
                    "title": "Test", "message": "Hello"
                })
                assert r.ok is True
            finally:
                os.environ.pop("WORKSPACE_DIR", None)

    def test_OI21_unknown_tool(self):
        from core.tools_operational.tool_executor import OperationalToolExecutor
        ex = OperationalToolExecutor()
        r = ex.execute("nonexistent.tool", {})
        assert r.ok is False

    def test_OI22_input_validation(self):
        from core.tools_operational.tool_executor import OperationalToolExecutor
        ex = OperationalToolExecutor()
        # http.webhook.post requires url and payload
        ex.simulate("http.webhook.post", {})
        # Simulate skips validation... let's test execute
        r2 = ex.execute("http.webhook.post", {}, approval_override=True)
        # Should fail — missing url or dispatch fails
        assert r2.ok is False or r2.simulated

    def test_OI23_grant_approval(self):
        from core.tools_operational.tool_executor import OperationalToolExecutor
        ex = OperationalToolExecutor()
        decision = ex.grant_approval("n8n.workflow.trigger", reason="test")
        assert decision.approved is True
        assert decision.target_id == "n8n.workflow.trigger"


# ═══════════════════════════════════════════════════════════════
# 5 — Execution Plans
# ═══════════════════════════════════════════════════════════════

class TestExecutionPlan:

    def test_OI24_plan_create(self):
        from core.planning.execution_plan import ExecutionPlan, PlanStep, StepType
        plan = ExecutionPlan(
            goal="test goal",
            steps=[
                PlanStep(type=StepType.BUSINESS_ACTION, target_id="venture.research_workspace"),
                PlanStep(type=StepType.TOOL, target_id="n8n.workflow.trigger"),
            ],
        )
        assert plan.plan_id.startswith("plan-")
        assert len(plan.steps) == 2

    def test_OI25_plan_risk(self):
        from core.planning.execution_plan import ExecutionPlan, PlanStep, StepType
        plan = ExecutionPlan(steps=[
            PlanStep(type=StepType.TOOL, target_id="n8n.workflow.trigger"),
        ])
        assert plan.compute_risk() == "medium"

    def test_OI26_plan_approval(self):
        from core.planning.execution_plan import ExecutionPlan, PlanStep, StepType
        plan = ExecutionPlan(steps=[
            PlanStep(type=StepType.TOOL, target_id="n8n.workflow.trigger"),
        ])
        assert plan.compute_approval_required() is True

    def test_OI27_plan_no_approval(self):
        from core.planning.execution_plan import ExecutionPlan, PlanStep, StepType
        plan = ExecutionPlan(steps=[
            PlanStep(type=StepType.BUSINESS_ACTION, target_id="venture.research_workspace"),
        ])
        assert plan.compute_approval_required() is False

    def test_OI28_plan_serialization(self):
        from core.planning.execution_plan import ExecutionPlan, PlanStep, StepType
        plan = ExecutionPlan(
            goal="test",
            steps=[PlanStep(type=StepType.SKILL, target_id="market_research.basic")],
        )
        j = plan.to_json()
        plan2 = ExecutionPlan.from_json(j)
        assert plan2.goal == "test"
        assert len(plan2.steps) == 1

    def test_OI29_plan_progress(self):
        from core.planning.execution_plan import ExecutionPlan, PlanStep, StepType
        plan = ExecutionPlan(steps=[
            PlanStep(type=StepType.BUSINESS_ACTION, target_id="t1", status="completed"),
            PlanStep(type=StepType.BUSINESS_ACTION, target_id="t2", status="pending"),
        ])
        assert plan.progress == 0.5


# ═══════════════════════════════════════════════════════════════
# 6 — Plan Validation
# ═══════════════════════════════════════════════════════════════

class TestPlanValidator:

    def test_OI30_valid_plan(self):
        from core.planning.execution_plan import ExecutionPlan, PlanStep, StepType
        from core.planning.plan_validator import validate_plan
        plan = ExecutionPlan(
            goal="research AI market",
            steps=[
                PlanStep(type=StepType.BUSINESS_ACTION, target_id="venture.research_workspace"),
            ],
        )
        v = validate_plan(plan)
        assert v["valid"] is True

    def test_OI31_empty_plan(self):
        from core.planning.execution_plan import ExecutionPlan
        from core.planning.plan_validator import validate_plan
        plan = ExecutionPlan(goal="")
        v = validate_plan(plan)
        assert v["valid"] is False
        assert any("goal" in e for e in v["errors"])

    def test_OI32_unknown_target(self):
        from core.planning.execution_plan import ExecutionPlan, PlanStep, StepType
        from core.planning.plan_validator import validate_plan
        plan = ExecutionPlan(
            goal="test",
            steps=[PlanStep(type=StepType.BUSINESS_ACTION, target_id="nonexistent.action")],
        )
        v = validate_plan(plan)
        assert v["valid"] is False

    def test_OI33_cycle_detection(self):
        from core.planning.execution_plan import ExecutionPlan, PlanStep, StepType
        from core.planning.plan_validator import validate_plan
        s1 = PlanStep(step_id="s1", type=StepType.BUSINESS_ACTION,
                      target_id="venture.research_workspace", depends_on=["s2"])
        s2 = PlanStep(step_id="s2", type=StepType.BUSINESS_ACTION,
                      target_id="offer.package", depends_on=["s1"])
        plan = ExecutionPlan(goal="test", steps=[s1, s2])
        v = validate_plan(plan)
        assert v["valid"] is False
        assert any("circular" in e.lower() for e in v["errors"])

    def test_OI34_tool_readiness_warning(self):
        from core.planning.execution_plan import ExecutionPlan, PlanStep, StepType
        from core.planning.plan_validator import validate_plan
        plan = ExecutionPlan(
            goal="test",
            steps=[PlanStep(type=StepType.TOOL, target_id="n8n.workflow.trigger")],
        )
        v = validate_plan(plan)
        if not os.environ.get("N8N_WEBHOOK_URL"):
            assert len(v["warnings"]) >= 1


# ═══════════════════════════════════════════════════════════════
# 7 — Plan Store
# ═══════════════════════════════════════════════════════════════

class TestPlanStore:

    def test_OI35_save_load(self):
        from core.planning.plan_serializer import PlanStore
        from core.planning.execution_plan import ExecutionPlan, PlanStep, StepType
        with tempfile.TemporaryDirectory() as td:
            store = PlanStore(persist_dir=td)
            plan = ExecutionPlan(goal="test", steps=[
                PlanStep(type=StepType.BUSINESS_ACTION, target_id="venture.research_workspace"),
            ])
            store.save(plan)
            loaded = store.get(plan.plan_id)
            assert loaded is not None
            assert loaded.goal == "test"

    def test_OI36_cancel(self):
        from core.planning.plan_serializer import PlanStore
        from core.planning.execution_plan import ExecutionPlan, PlanStatus
        with tempfile.TemporaryDirectory() as td:
            store = PlanStore(persist_dir=td)
            plan = ExecutionPlan(goal="cancel me", status=PlanStatus.VALIDATED)
            store.save(plan)
            assert store.cancel(plan.plan_id) is True
            assert store.get(plan.plan_id).status == PlanStatus.CANCELLED

    def test_OI37_approve(self):
        from core.planning.plan_serializer import PlanStore
        from core.planning.execution_plan import ExecutionPlan, PlanStatus
        with tempfile.TemporaryDirectory() as td:
            store = PlanStore(persist_dir=td)
            plan = ExecutionPlan(goal="approve me", status=PlanStatus.AWAITING_APPROVAL)
            store.save(plan)
            assert store.approve(plan.plan_id) is True
            assert store.get(plan.plan_id).status == PlanStatus.APPROVED


# ═══════════════════════════════════════════════════════════════
# 8 — Workflow Templates
# ═══════════════════════════════════════════════════════════════

class TestWorkflowTemplates:

    def test_OI38_load_templates(self):
        from core.planning.workflow_templates import load_templates
        templates = load_templates()
        assert len(templates) >= 4
        ids = {t["template_id"] for t in templates}
        assert "micro_saas_validation" in ids
        assert "lead_generation_system" in ids
        assert "competitor_monitoring" in ids
        assert "content_engine_setup" in ids

    def test_OI39_get_template(self):
        from core.planning.workflow_templates import get_template
        t = get_template("micro_saas_validation")
        assert t is not None
        assert len(t["steps"]) >= 6

    def test_OI40_build_plan(self):
        from core.planning.workflow_templates import build_plan_from_template
        plan = build_plan_from_template("micro_saas_validation", inputs={"sector": "AI"})
        assert plan is not None
        assert plan.template_id == "micro_saas_validation"
        assert len(plan.steps) >= 6
        assert plan.requires_approval is True  # contains n8n tool

    def test_OI41_build_plan_low_risk(self):
        from core.planning.workflow_templates import build_plan_from_template
        plan = build_plan_from_template("competitor_monitoring")
        assert plan is not None
        assert plan.risk_score == "low"

    def test_OI42_template_not_found(self):
        from core.planning.workflow_templates import build_plan_from_template
        plan = build_plan_from_template("nonexistent_template")
        assert plan is None


# ═══════════════════════════════════════════════════════════════
# 9 — Execution Memory
# ═══════════════════════════════════════════════════════════════

class TestExecutionMemory:

    def test_OI43_record_and_retrieve(self):
        from core.planning.execution_memory import ExecutionMemory, ExecutionRecord
        with tempfile.TemporaryDirectory() as td:
            mem = ExecutionMemory(persist_path=os.path.join(td, "history.json"))
            mem._loaded = True  # prevent loading stale data
            mem.record(ExecutionRecord(
                record_id="r1", goal="test", success=True,
                tools_used=["n8n.workflow.trigger"],
                template_id="micro_saas_validation",
            ))
            history = mem.get_history()
            assert len(history) == 1
            assert history[0]["success"] is True

    def test_OI44_stats(self):
        from core.planning.execution_memory import ExecutionMemory, ExecutionRecord
        with tempfile.TemporaryDirectory() as td:
            mem = ExecutionMemory(persist_path=os.path.join(td, "h.json"))
            mem._loaded = True
            mem.record(ExecutionRecord(record_id="r1", success=True))
            mem.record(ExecutionRecord(record_id="r2", success=False))
            s = mem.stats()
            assert s["total"] == 2
            assert s["successes"] == 1
            assert s["success_rate"] == 0.5

    def test_OI45_patterns(self):
        from core.planning.execution_memory import ExecutionMemory, ExecutionRecord
        with tempfile.TemporaryDirectory() as td:
            mem = ExecutionMemory(persist_path=os.path.join(td, "h.json"))
            mem._loaded = True
            for i in range(3):
                mem.record(ExecutionRecord(
                    record_id=f"r{i}", success=True,
                    template_id="micro_saas_validation",
                    tools_used=["n8n.workflow.trigger"],
                ))
            patterns = mem.get_successful_patterns()
            assert len(patterns) >= 1
            assert patterns[0]["count"] == 3

    def test_OI46_persistence(self):
        from core.planning.execution_memory import ExecutionMemory, ExecutionRecord
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "h.json")
            mem1 = ExecutionMemory(persist_path=path)
            mem1.record(ExecutionRecord(record_id="r1", goal="persisted", success=True))

            mem2 = ExecutionMemory(persist_path=path)
            history = mem2.get_history()
            assert len(history) == 1
            assert history[0]["goal"] == "persisted"


# ═══════════════════════════════════════════════════════════════
# 10 — API Routes
# ═══════════════════════════════════════════════════════════════

class TestOperationalAPI:

    def test_OI47_tools_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/tools" in paths

    def test_OI48_tools_readiness_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/tools/readiness" in paths

    def test_OI49_tools_execute_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/tools/{tool_id}/execute" in paths

    def test_OI50_plans_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/plans" in paths

    def test_OI51_plans_approve_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/plans/{plan_id}/approve" in paths

    def test_OI52_templates_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/templates" in paths

    def test_OI53_templates_instantiate_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/templates/{template_id}/instantiate" in paths

    def test_OI54_execution_history_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/execution-history" in paths

    def test_OI55_execution_patterns_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/execution-history/patterns" in paths


# ═══════════════════════════════════════════════════════════════
# 11 — Safety / No Bypass
# ═══════════════════════════════════════════════════════════════

class TestSafety:

    def test_OI56_no_auto_execute_approval_tool(self):
        """Approval-gated tools MUST NOT execute without approval_override."""
        from core.tools_operational.tool_executor import OperationalToolExecutor
        ex = OperationalToolExecutor()
        r = ex.execute("n8n.workflow.trigger", {"payload": {"x": 1}})
        # Must be blocked — either by approval gate or readiness
        assert r.ok is False
        assert r.approved is False or "not ready" in r.error.lower()

    def test_OI57_no_hidden_execution(self):
        """Tool executor always logs via cognitive events."""
        import inspect
        from core.tools_operational.tool_executor import OperationalToolExecutor
        src = inspect.getsource(OperationalToolExecutor.execute)
        assert "_emit_event" in src

    def test_OI58_plan_requires_approval_propagates(self):
        """If any step requires approval, the plan does too."""
        from core.planning.execution_plan import ExecutionPlan, PlanStep, StepType
        plan = ExecutionPlan(
            goal="mixed",
            steps=[
                PlanStep(type=StepType.BUSINESS_ACTION, target_id="venture.research_workspace"),
                PlanStep(type=StepType.TOOL, target_id="n8n.workflow.trigger"),
            ],
        )
        assert plan.compute_approval_required() is True

    def test_OI59_all_tool_files_valid_json(self):
        """All tool definition files must be valid JSON."""
        tools_dir = os.path.join(os.path.dirname(__file__), "..", "business", "tools")
        if os.path.isdir(tools_dir):
            for f in os.listdir(tools_dir):
                if f.endswith(".json"):
                    path = os.path.join(tools_dir, f)
                    with open(path) as fh:
                        data = json.load(fh)
                    assert "id" in data, f"Missing id in {f}"

    def test_OI60_all_workflow_templates_valid(self):
        """All workflow templates must be valid JSON with required fields."""
        wf_dir = os.path.join(os.path.dirname(__file__), "..", "business", "workflows")
        if os.path.isdir(wf_dir):
            for f in os.listdir(wf_dir):
                if f.endswith(".json"):
                    path = os.path.join(wf_dir, f)
                    with open(path) as fh:
                        data = json.load(fh)
                    assert "template_id" in data, f"Missing template_id in {f}"
                    assert "steps" in data, f"Missing steps in {f}"
                    assert len(data["steps"]) >= 1, f"Empty steps in {f}"
