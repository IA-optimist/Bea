"""
tests/test_ai_os_foundation.py — AI OS foundation stability tests.

Validates the 6-layer architecture, agent roles, skill completeness,
tool ecosystem, planning integration, and system readiness.
"""
import os
import tempfile
import pytest
pytestmark = pytest.mark.integration



# ═══════════════════════════════════════════════════════════════
# 1 — Architecture Document
# ═══════════════════════════════════════════════════════════════

class TestArchitecture:

    def test_AO01_architecture_md_exists(self):
        path = os.path.join(os.path.dirname(__file__), "..", "ARCHITECTURE.md")
        assert os.path.isfile(path)
        content = open(path, encoding="utf-8").read()
        assert "COGNITION LAYER" in content
        assert "SKILLS LAYER" in content
        assert "PLANNING LAYER" in content
        assert "EXECUTION LAYER" in content
        assert "MEMORY LAYER" in content
        assert "CONTROL LAYER" in content


# ═══════════════════════════════════════════════════════════════
# 2 — Agent Roles
# ═══════════════════════════════════════════════════════════════

class TestAgentRoles:

    def test_AO02_six_roles_defined(self):
        from core.agents.roles import ROLE_SPECS, AgentRole
        assert len(ROLE_SPECS) == 6
        for role in AgentRole:
            assert role in ROLE_SPECS

    def test_AO03_role_spec_structure(self):
        from core.agents.roles import get_role_spec
        spec = get_role_spec("ceo")
        assert spec is not None
        assert spec.name == "CEO Agent"
        assert len(spec.responsibilities) >= 3
        assert len(spec.capabilities) >= 2

    def test_AO04_no_role_overlap(self):
        """No capability should appear in multiple roles."""
        from core.agents.roles import ROLE_SPECS
        all_caps = {}
        for role, spec in ROLE_SPECS.items():
            for cap in spec.capabilities:
                if cap in all_caps:
                    pytest.fail(f"Capability '{cap}' in both {all_caps[cap]} and {role}")
                all_caps[cap] = role

    def test_AO05_delegation_valid(self):
        """Roles can only delegate to existing roles."""
        from core.agents.roles import ROLE_SPECS, AgentRole
        for role, spec in ROLE_SPECS.items():
            for target in spec.can_delegate_to:
                assert target in AgentRole.__members__.values(), \
                    f"{role} delegates to invalid {target}"

    def test_AO06_list_roles(self):
        from core.agents.roles import list_roles
        roles = list_roles()
        assert len(roles) == 6
        assert all("role" in r and "name" in r for r in roles)

    def test_AO07_get_role_for_capability(self):
        from core.agents.roles import get_role_for_capability, AgentRole
        assert get_role_for_capability("code_generation") == AgentRole.ENGINEER
        assert get_role_for_capability("market_research") == AgentRole.ANALYST
        assert get_role_for_capability("tool_execution") == AgentRole.OPERATOR
        assert get_role_for_capability("nonexistent") is None

    def test_AO08_to_dict(self):
        from core.agents.roles import get_role_spec
        d = get_role_spec("operator").to_dict()
        assert d["risk_level"] == "high"
        assert "requires_approval_for" in d


# ═══════════════════════════════════════════════════════════════
# 3 — Skill Completeness (10 domains)
# ═══════════════════════════════════════════════════════════════

class TestSkillCompleteness:

    def test_AO09_ten_skills_loaded(self):
        from core.skills.domain_loader import DomainSkillRegistry
        reg = DomainSkillRegistry()
        count = reg.load_all()
        assert count >= 10

    def test_AO10_required_domains(self):
        from core.skills.domain_loader import DomainSkillRegistry
        reg = DomainSkillRegistry()
        reg.load_all()
        skills = reg.list_all()
        domains = {s.domain for s in skills}
        required = {
            "market_research", "offer_design", "customer_persona",
            "acquisition_strategy", "saas_scope", "automation_opportunity",
            "pricing", "competitor_analysis", "value_proposition", "funnel_design",
        }
        missing = required - domains
        assert not missing, f"Missing domains: {missing}"

    def test_AO11_all_skills_have_logic(self):
        from core.skills.domain_loader import DomainSkillRegistry
        reg = DomainSkillRegistry()
        reg.load_all()
        for skill in reg.list_all():
            assert bool(skill.logic), f"Skill {skill.id} has no logic.md"

    def test_AO12_all_skills_have_examples(self):
        from core.skills.domain_loader import DomainSkillRegistry
        reg = DomainSkillRegistry()
        reg.load_all()
        for skill in reg.list_all():
            assert len(skill.examples) >= 1, f"Skill {skill.id} has no examples"

    def test_AO13_all_skills_have_quality_checks(self):
        from core.skills.domain_loader import DomainSkillRegistry
        reg = DomainSkillRegistry()
        reg.load_all()
        for skill in reg.list_all():
            assert len(skill.quality_checks) >= 1, f"Skill {skill.id} has no quality checks"

    def test_AO14_skill_outputs_defined(self):
        from core.skills.domain_loader import DomainSkillRegistry
        reg = DomainSkillRegistry()
        reg.load_all()
        for skill in reg.list_all():
            assert len(skill.outputs) >= 2, f"Skill {skill.id} has <2 outputs"

    def test_AO15_skill_json_vs_markdown(self):
        """Each skill produces both JSON structure and markdown-compatible output."""
        from core.skills.domain_loader import DomainSkillRegistry
        reg = DomainSkillRegistry()
        reg.load_all()
        for skill in reg.list_all():
            has_json = any(o.type in ("json", "list") for o in skill.outputs)
            assert has_json, f"Skill {skill.id} has no json/list output"


# ═══════════════════════════════════════════════════════════════
# 4 — Tool Ecosystem
# ═══════════════════════════════════════════════════════════════

class TestToolEcosystem:

    def test_AO16_five_tools_registered(self):
        from core.tools_operational.tool_registry import OperationalToolRegistry
        reg = OperationalToolRegistry()
        reg.load_all()
        tools = reg.list_all()
        assert len(tools) >= 5

    def test_AO17_n8n_tool(self):
        from core.tools_operational.tool_registry import OperationalToolRegistry
        reg = OperationalToolRegistry()
        reg.load_all()
        t = reg.get("n8n.workflow.trigger")
        assert t is not None
        assert t.requires_approval is True

    def test_AO18_http_tool(self):
        from core.tools_operational.tool_registry import OperationalToolRegistry
        reg = OperationalToolRegistry()
        reg.load_all()
        t = reg.get("http.webhook.post")
        assert t is not None

    def test_AO19_file_tool(self):
        from core.tools_operational.tool_registry import OperationalToolRegistry
        reg = OperationalToolRegistry()
        reg.load_all()
        t = reg.get("file.workspace.write")
        assert t is not None
        assert t.risk_level == "low"

    def test_AO20_git_tool(self):
        from core.tools_operational.tool_registry import OperationalToolRegistry
        reg = OperationalToolRegistry()
        reg.load_all()
        t = reg.get("git.status")
        assert t is not None
        assert t.requires_approval is False

    def test_AO21_notification_tool(self):
        from core.tools_operational.tool_registry import OperationalToolRegistry
        reg = OperationalToolRegistry()
        reg.load_all()
        t = reg.get("notification.log")
        assert t is not None

    def test_AO22_file_tool_workspace_scoped(self):
        """File tool must be workspace-scoped."""
        from core.tools_operational.tool_executor import OperationalToolExecutor
        ex = OperationalToolExecutor()
        # Path traversal attempt
        r = ex.execute("file.workspace.write", {
            "path": "../../etc/passwd", "content": "hacked"
        })
        assert r.ok is False or "traversal" in r.error.lower()

    def test_AO23_all_tools_have_schema(self):
        from core.tools_operational.tool_registry import OperationalToolRegistry
        reg = OperationalToolRegistry()
        reg.load_all()
        for t in reg.list_all():
            assert t.input_schema, f"Tool {t.id} has no input_schema"

    def test_AO24_medium_high_tools_need_approval(self):
        """All medium+ risk tools require approval."""
        from core.tools_operational.tool_registry import OperationalToolRegistry
        reg = OperationalToolRegistry()
        reg.load_all()
        for t in reg.list_all():
            if t.risk_level in ("medium", "high", "critical"):
                assert t.requires_approval, f"Tool {t.id} is {t.risk_level} but no approval"


# ═══════════════════════════════════════════════════════════════
# 5 — Planning Layer
# ═══════════════════════════════════════════════════════════════

class TestPlanningLayer:

    def test_AO25_four_templates(self):
        from core.planning.workflow_templates import load_templates
        templates = load_templates()
        assert len(templates) >= 4

    def test_AO26_template_instantiation(self):
        from core.planning.workflow_templates import build_plan_from_template
        plan = build_plan_from_template("micro_saas_validation")
        assert plan is not None
        assert len(plan.steps) >= 6

    def test_AO27_plan_validation_works(self):
        from core.planning.workflow_templates import build_plan_from_template
        from core.planning.plan_validator import validate_plan
        plan = build_plan_from_template("lead_generation_system")
        v = validate_plan(plan)
        assert v["valid"] is True

    def test_AO28_plan_store_persist(self):
        from core.planning.plan_serializer import PlanStore
        from core.planning.execution_plan import ExecutionPlan, PlanStep, StepType
        with tempfile.TemporaryDirectory() as td:
            store = PlanStore(persist_dir=td)
            plan = ExecutionPlan(
                goal="test plan",
                steps=[PlanStep(type=StepType.SKILL, target_id="market_research.basic")],
            )
            store.save(plan)
            loaded = store.get(plan.plan_id)
            assert loaded.goal == "test plan"


# ═══════════════════════════════════════════════════════════════
# 6 — Memory Layer
# ═══════════════════════════════════════════════════════════════

class TestMemoryLayer:

    def test_AO29_execution_memory(self):
        from core.planning.execution_memory import ExecutionMemory, ExecutionRecord
        with tempfile.TemporaryDirectory() as td:
            mem = ExecutionMemory(persist_path=os.path.join(td, "h.json"))
            mem._loaded = True
            mem.record(ExecutionRecord(record_id="r1", goal="test", success=True))
            assert mem.stats()["total"] == 1

    def test_AO30_skill_feedback(self):
        from core.skills.skill_feedback import SkillFeedbackStore, SkillFeedback
        with tempfile.TemporaryDirectory() as td:
            store = SkillFeedbackStore(persist_dir=td)
            store.record(SkillFeedback(skill_id="test", signal="success", quality_score=0.9))
            assert store.get_summary("test")["executions"] == 1


# ═══════════════════════════════════════════════════════════════
# 7 — Control Layer
# ═══════════════════════════════════════════════════════════════

class TestControlLayer:

    def test_AO31_cognitive_journal_exists(self):
        from core.cognitive_events.store import get_journal
        j = get_journal()
        assert j is not None

    def test_AO32_approval_gate_on_tools(self):
        from core.tools_operational.tool_executor import OperationalToolExecutor
        ex = OperationalToolExecutor()
        r = ex.execute("n8n.workflow.trigger", {"payload": {}})
        assert r.ok is False  # must be blocked


# ═══════════════════════════════════════════════════════════════
# 8 — API Endpoints
# ═══════════════════════════════════════════════════════════════

class TestAPIEndpoints:

    def test_AO33_readiness_endpoint(self):
        from api.main import app
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        # readiness consolidée sous /system/readiness (refactor : plus de /api/v3/readiness)
        assert "/api/v3/system/readiness" in paths

    def test_AO34_agents_endpoint(self):
        from api.main import app
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/api/v3/agents" in paths

    def test_AO35_skills_readiness_endpoint(self):
        from api.main import app
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/api/v3/skills" in paths

    def test_AO36_tools_readiness_endpoint(self):
        from api.main import app
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/api/v3/tools/readiness" in paths


# ═══════════════════════════════════════════════════════════════
# 9 — Business Execution
# ═══════════════════════════════════════════════════════════════

class TestBusinessExecution:

    def test_AO37_five_actions_registered(self):
        from core.business_actions import ACTION_REGISTRY
        assert len(ACTION_REGISTRY) >= 5

    def test_AO38_action_to_skill_mapping(self):
        from core.business_actions import ACTION_SKILLS
        assert len(ACTION_SKILLS) >= 5
        for action_id, skills in ACTION_SKILLS.items():
            assert isinstance(skills, list)


# ═══════════════════════════════════════════════════════════════
# 10 — Dashboard
# ═══════════════════════════════════════════════════════════════

class TestDashboard:

    def test_AO39_operations_html_exists(self):
        path = os.path.join(os.path.dirname(__file__), "..", "static", "operations.html")
        assert os.path.isfile(path)

    def test_AO40_operations_has_seven_tabs(self):
        path = os.path.join(os.path.dirname(__file__), "..", "static", "operations.html")
        content = open(path, encoding="utf-8").read()
        for tab in ["Overview", "Agents", "Skills", "Tools", "Plans", "History", "Templates"]:
            assert tab in content, f"Missing tab: {tab}"


# ═══════════════════════════════════════════════════════════════
# 11 — End-to-End Validation
# ═══════════════════════════════════════════════════════════════

class TestE2EValidation:

    def test_AO41_full_flow_template_to_plan(self):
        """Template → Plan → Validate → Store → Retrieve."""
        from core.planning.workflow_templates import build_plan_from_template
        from core.planning.plan_validator import validate_plan
        from core.planning.plan_serializer import PlanStore

        with tempfile.TemporaryDirectory() as td:
            store = PlanStore(persist_dir=td)

            plan = build_plan_from_template("lead_generation_system",
                                           inputs={"product": "AI chatbot"})
            assert plan is not None

            v = validate_plan(plan)
            assert v["valid"] is True

            store.save(plan)
            loaded = store.get(plan.plan_id)
            assert loaded.goal == plan.goal
            assert len(loaded.steps) == len(plan.steps)

    def test_AO42_skill_to_validation(self):
        """Load skill → prepare prompt → validate output."""
        from core.skills.domain_executor import DomainSkillExecutor
        exec_ = DomainSkillExecutor()

        prep = exec_.prepare("pricing.strategy", {"product": "AI chatbot"})
        assert "prompt_context" in prep

        output = {
            "pricing_model": {"type": "subscription"},
            "tiers": [{"name": "Pro"}],
            "unit_economics": {"ltv": "$1000"},
            "willingness_to_pay": {"range": "$50-200"},
            "competitive_positioning": {"strategy": "market-rate"},
        }
        result = exec_.validate("pricing.strategy", output)
        assert result.ok is True
        assert result.quality_score > 0

    def test_AO43_tool_simulate(self):
        """Simulate tool execution without side effects."""
        from core.tools_operational.tool_executor import OperationalToolExecutor
        ex = OperationalToolExecutor()
        r = ex.simulate("n8n.workflow.trigger", {"payload": {"test": True}})
        assert r.ok is True
        assert r.simulated is True

    def test_AO44_new_skills_all_valid(self):
        """All 4 new skills load and have required files."""
        base = os.path.join(os.path.dirname(__file__), "..", "business", "skills")
        for skill in ["pricing_strategy", "competitor_analysis", "value_proposition", "funnel_design"]:
            path = os.path.join(base, skill)
            assert os.path.isdir(path), f"Missing: {skill}"
            for required in ["skill.json", "logic.md", "examples.json", "evaluation.md"]:
                assert os.path.isfile(os.path.join(path, required)), \
                    f"Missing {required} in {skill}"

    def test_AO45_new_tool_handlers(self):
        """File and git tools have handlers."""
        from core.tools_operational.tool_executor import OperationalToolExecutor
        ex = OperationalToolExecutor()
        assert hasattr(ex, "_exec_file_workspace_write")
        assert hasattr(ex, "_exec_git_status")
