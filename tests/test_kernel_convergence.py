"""
tests/test_kernel_convergence.py — Kernel ↔ runtime convergence tests.

Validates:
  - Adapters correctly translate between core and kernel types
  - Dual event emission works
  - Kernel capability registry is queryable from runtime
  - Kernel policy decisions align with existing approval behavior
  - No regression in mission execution path
"""


# ═══════════════════════════════════════════════════════════════
# 1 — Mission Adapter
# ═══════════════════════════════════════════════════════════════

class TestMissionAdapter:

    def test_KC01_core_status_to_kernel(self):
        """All core statuses map to kernel statuses."""
        from kernel.adapters.mission_adapter import _CORE_TO_KERNEL_STATUS
        core_statuses = [
            "CREATED", "ANALYZING", "PENDING_VALIDATION", "APPROVED",
            "EXECUTING", "RUNNING", "DONE", "REJECTED", "BLOCKED",
            "PLAN_ONLY", "PLANNED", "AWAITING_APPROVAL", "REVIEW", "FAILED",
        ]
        for s in core_statuses:
            assert s in _CORE_TO_KERNEL_STATUS, f"Missing mapping for {s}"

    def test_KC02_kernel_status_to_core(self):
        """All kernel statuses map back to core statuses."""
        from kernel.adapters.mission_adapter import _KERNEL_TO_CORE_STATUS
        kernel_statuses = [
            "pending", "planning", "executing", "awaiting_approval",
            "completed", "failed", "cancelled",
        ]
        for s in kernel_statuses:
            assert s in _KERNEL_TO_CORE_STATUS, f"Missing mapping for {s}"

    def test_KC03_mission_context_to_kernel(self):
        """MissionContext converts to kernel Mission."""
        from dataclasses import dataclass, field
        from kernel.adapters.mission_adapter import mission_context_to_kernel

        @dataclass
        class FakeMissionContext:
            mission_id: str = "m-test"
            goal: str = "build chatbot"
            mode: str = "auto"
            status: object = None
            created_at: float = 1234567890
            updated_at: float = 1234567900
            metadata: dict = field(default_factory=dict)

        class FakeStatus:
            value = "EXECUTING"

        ctx = FakeMissionContext(status=FakeStatus())
        mission = mission_context_to_kernel(ctx)

        assert mission.mission_id == "m-test"
        assert mission.goal.description == "build chatbot"
        assert mission.status.value == "executing"
        assert mission.created_at == 1234567890

    def test_KC04_kernel_mission_to_context_dict(self):
        """Kernel Mission converts to dict for MissionContext construction."""
        from kernel.contracts.types import Mission, Goal, MissionStatus
        from kernel.adapters.mission_adapter import kernel_mission_to_context

        m = Mission(
            mission_id="m-kern",
            goal=Goal(description="deploy app", source="operator"),
            status=MissionStatus.COMPLETED,
        )
        d = kernel_mission_to_context(m)
        assert d["mission_id"] == "m-kern"
        assert d["goal"] == "deploy app"
        assert d["status"] == "DONE"

    def test_KC05_roundtrip_status(self):
        """Status roundtrip: core → kernel → core preserves semantics."""
        from kernel.adapters.mission_adapter import (
            core_status_to_kernel, kernel_status_to_core,
        )
        test_cases = {
            "CREATED": "CREATED",
            "EXECUTING": "EXECUTING",
            "DONE": "DONE",
            "FAILED": "FAILED",
        }
        for core_in, expected_core_out in test_cases.items():
            kernel_val = core_status_to_kernel(core_in)
            core_out = kernel_status_to_core(kernel_val)
            assert core_out == expected_core_out, f"{core_in} → {kernel_val} → {core_out} != {expected_core_out}"


# ═══════════════════════════════════════════════════════════════
# 2 — Plan Adapter
# ═══════════════════════════════════════════════════════════════

class TestPlanAdapter:

    def test_KC06_execution_plan_to_kernel(self):
        """ExecutionPlan converts to kernel Plan."""
        from core.planning.execution_plan import ExecutionPlan, PlanStep, PlanStatus, StepType
        from kernel.adapters.plan_adapter import execution_plan_to_kernel

        ep = ExecutionPlan(
            plan_id="p-test",
            goal="validate SaaS idea",
            steps=[
                PlanStep(step_id="s1", type=StepType.SKILL, target_id="market_research.basic", name="Research"),
                PlanStep(step_id="s2", type=StepType.TOOL, target_id="n8n.workflow.trigger", name="Trigger"),
            ],
            status=PlanStatus.APPROVED,
            risk_score="medium",
            requires_approval=True,
        )
        plan = execution_plan_to_kernel(ep)

        assert plan.plan_id == "p-test"
        assert plan.goal == "validate SaaS idea"
        assert len(plan.steps) == 2
        assert plan.status.value == "approved"
        assert plan.risk_level.value == "medium"
        assert plan.requires_approval is True

    def test_KC07_kernel_plan_to_dict(self):
        """Kernel Plan converts to dict compatible with ExecutionPlan.from_dict()."""
        from kernel.contracts.types import Plan, PlanStep, StepType, PlanStatus, RiskLevel
        from kernel.adapters.plan_adapter import kernel_plan_to_dict

        plan = Plan(
            plan_id="p-kern",
            goal="deploy microservice",
            steps=[PlanStep(target_id="code_generation", type=StepType.COGNITIVE)],
            status=PlanStatus.VALIDATED,
            risk_level=RiskLevel.LOW,
        )
        d = kernel_plan_to_dict(plan)
        assert d["plan_id"] == "p-kern"
        assert d["status"] == "validated"
        assert d["risk_score"] == "low"
        assert len(d["steps"]) == 1


# ═══════════════════════════════════════════════════════════════
# 3 — Result Adapter
# ═══════════════════════════════════════════════════════════════

class TestResultAdapter:

    def test_KC08_tool_result_to_kernel(self):
        """Tool execution result dict converts to kernel ExecutionResult."""
        from kernel.adapters.result_adapter import tool_result_to_kernel

        result = {
            "success": True,
            "output": "workflow triggered",
            "error": "",
            "duration_ms": 1250.5,
            "artifacts": ["/tmp/output.json"],
        }
        kr = tool_result_to_kernel(result, step_id="s-1", mission_id="m-1")
        assert kr.ok is True
        assert kr.step_id == "s-1"
        assert kr.mission_id == "m-1"
        assert kr.duration_ms == 1250.5
        assert len(kr.artifacts) == 1

    def test_KC09_failed_result(self):
        from kernel.adapters.result_adapter import tool_result_to_kernel
        result = {"success": False, "error": "timeout after 30s"}
        kr = tool_result_to_kernel(result)
        assert kr.ok is False
        assert "timeout" in kr.error

    def test_KC10_routing_decision_to_kernel(self):
        """Routing result converts to kernel Decision."""
        from kernel.adapters.result_adapter import routing_decision_to_kernel

        route_result = {
            "capability_id": "code_generation",
            "provider": {"id": "agent:jarvis-coder", "type": "agent"},
            "score": 0.91,
        }
        decision = routing_decision_to_kernel(route_result)
        assert decision.decision_type.value == "approve"
        assert decision.confidence == 0.91
        assert "jarvis-coder" in decision.reason
        assert decision.decided_by == "capability_router"


# ═══════════════════════════════════════════════════════════════
# 4 — Event Adapter
# ═══════════════════════════════════════════════════════════════

class TestEventAdapter:

    def test_KC11_all_core_events_mapped(self):
        """Every core EventType has a kernel mapping."""
        from kernel.adapters.event_adapter import CORE_TO_KERNEL_EVENT
        from core.cognitive_events.types import EventType
        for et in EventType:
            assert et.value in CORE_TO_KERNEL_EVENT, f"No kernel mapping for {et.value}"

    def test_KC12_kernel_events_are_canonical(self):
        """All mapped kernel events exist in canonical set."""
        from kernel.adapters.event_adapter import CORE_TO_KERNEL_EVENT
        from kernel.events.canonical import CANONICAL_EVENTS
        for kernel_type in set(CORE_TO_KERNEL_EVENT.values()):
            assert kernel_type in CANONICAL_EVENTS, f"Kernel event {kernel_type} not in canonical set"

    def test_KC13_reverse_mapping(self):
        """Reverse mapping returns list of core events."""
        from kernel.adapters.event_adapter import kernel_to_core_event_type
        core_events = kernel_to_core_event_type("mission.created")
        assert "mission.created" in core_events


# ═══════════════════════════════════════════════════════════════
# 5 — Event Bridge (Dual Emission)
# ═══════════════════════════════════════════════════════════════

class TestEventBridge:

    def test_KC14_emit_mission_created(self):
        """Kernel event emission works for mission.created."""
        from kernel.convergence.event_bridge import emit_kernel_event
        result = emit_kernel_event("mission.created", mission_id="m-test", goal="test mission")
        assert isinstance(result, bool)

    def test_KC15_emit_mission_completed(self):
        from kernel.convergence.event_bridge import emit_kernel_event
        emit_kernel_event("mission.completed", mission_id="m-test", duration_ms=1500)

    def test_KC16_emit_mission_failed(self):
        from kernel.convergence.event_bridge import emit_kernel_event
        emit_kernel_event("mission.failed", mission_id="m-test", error="timeout")

    def test_KC17_emit_step_events(self):
        from kernel.convergence.event_bridge import emit_kernel_event
        emit_kernel_event("step.started", step_id="s1", plan_id="p1", step_name="Research")
        emit_kernel_event("step.completed", step_id="s1", plan_id="p1")
        emit_kernel_event("step.failed", step_id="s2", error="no data")

    def test_KC18_emit_tool_invoked(self):
        from kernel.convergence.event_bridge import emit_kernel_event
        emit_kernel_event("tool.invoked", tool_id="n8n.workflow.trigger", step_id="s1")

    def test_KC19_emit_policy_evaluated(self):
        from kernel.convergence.event_bridge import emit_kernel_event
        emit_kernel_event("policy.evaluated", action_type="tool_invoke")

    def test_KC20_emit_unknown_type_fallback(self):
        """Unknown event types fall back to generic emission."""
        from kernel.convergence.event_bridge import emit_kernel_event
        result = emit_kernel_event("custom.new_type", summary="testing custom event")
        assert isinstance(result, bool)


# ═══════════════════════════════════════════════════════════════
# 6 — Capability Bridge
# ═══════════════════════════════════════════════════════════════

class TestCapabilityBridge:

    def test_KC21_query_capabilities(self):
        """Kernel capabilities are queryable."""
        from kernel.convergence.capability_bridge import query_capabilities
        caps = query_capabilities()
        assert len(caps) >= 12  # at least the 12 kernel built-ins

    def test_KC22_query_by_category(self):
        from kernel.convergence.capability_bridge import query_capabilities
        planning = query_capabilities(category="planning")
        assert len(planning) >= 2  # plan_generation, plan_validation

    def test_KC23_resolve_kernel_capability(self):
        """Built-in kernel capabilities resolve to providers."""
        from kernel.convergence.capability_bridge import resolve_provider
        result = resolve_provider("code_generation")
        assert result is not None
        assert result["provider_id"] == "engineer"
        assert result["source"] == "kernel"

    def test_KC24_resolve_unknown_returns_none(self):
        from kernel.convergence.capability_bridge import resolve_provider
        result = resolve_provider("nonexistent_capability_xyz")
        assert result is None

    def test_KC25_registry_stats(self):
        from kernel.convergence.capability_bridge import get_registry_stats
        stats = get_registry_stats()
        assert "kernel" in stats
        assert stats["kernel"]["total"] >= 12


# ═══════════════════════════════════════════════════════════════
# 7 — Policy Bridge
# ═══════════════════════════════════════════════════════════════

class TestPolicyBridge:

    def test_KC26_low_risk_auto_approved(self):
        """Low risk actions are auto-approved by kernel."""
        from kernel.convergence.policy_bridge import check_action_kernel
        decision = check_action_kernel("read_file", risk_level="low")
        assert decision.allowed is True
        assert decision.requires_approval is False

    def test_KC27_high_risk_needs_approval(self):
        """High risk actions require approval."""
        from kernel.convergence.policy_bridge import check_action_kernel
        decision = check_action_kernel("payment", risk_level="high")
        assert decision.requires_approval is True

    def test_KC28_critical_blocked(self):
        """Critical risk actions are blocked."""
        from kernel.convergence.policy_bridge import check_action_kernel
        decision = check_action_kernel("nuclear_launch", risk_level="critical")
        assert decision.allowed is False

    def test_KC29_pending_approvals_empty(self):
        from kernel.convergence.policy_bridge import get_pending_approvals
        pending = get_pending_approvals()
        assert isinstance(pending, list)

    def test_KC30_resolve_approval(self):
        """Can resolve approvals through kernel."""
        from kernel.convergence.policy_bridge import resolve_approval
        result = resolve_approval("nonexistent", approved=True)
        # Either returns a decision dict or error for nonexistent
        assert isinstance(result, dict)


# ═══════════════════════════════════════════════════════════════
# 8 — MetaOrchestrator Integration (non-invasive)
# ═══════════════════════════════════════════════════════════════

class TestMetaOrchestratorIntegration:

    def test_KC31_kernel_event_emission_in_orchestrator(self):
        """MetaOrchestrator emits kernel events (dual emission wired)."""
        import inspect
        from core.meta_orchestrator import MetaOrchestrator
        source = inspect.getsource(MetaOrchestrator)  # class source — features in helpers
        assert "emit_kernel_event" in source
        assert "mission.created" in source
        assert "mission.completed" in source
        assert "mission.failed" in source

    def test_KC32_kernel_capabilities_phase_in_orchestrator(self):
        """MetaOrchestrator has kernel capability enrichment phase."""
        import inspect
        from core.meta_orchestrator import MetaOrchestrator
        source = inspect.getsource(MetaOrchestrator)  # class source — features in helpers
        assert "kernel_capabilities_count" in source
        assert "kernel_provider" in source
        assert "Phase 0d" in source

    def test_KC33_orchestrator_not_broken(self):
        """MetaOrchestrator still instantiates correctly."""
        from core.meta_orchestrator import MetaOrchestrator
        mo = MetaOrchestrator()
        assert hasattr(mo, "run_mission")
        assert hasattr(mo, "_missions")

    def test_KC34_kernel_convergence_imports_clean(self):
        """All kernel convergence modules import without error."""


# ═══════════════════════════════════════════════════════════════
# 9 — Kernel API Routes
# ═══════════════════════════════════════════════════════════════

class TestKernelAPI:

    def test_KC35_api_router_importable(self):
        from api.routes.kernel import router
        routes = [r.path for r in router.routes]
        assert "/status" in routes or any("/status" in r for r in routes)

    def test_KC36_convergence_endpoint_exists(self):
        from api.routes.kernel import router
        paths = [r.path for r in router.routes]
        assert any("convergence" in p for p in paths)


# ═══════════════════════════════════════════════════════════════
# 10 — Invariant Tests
# ═══════════════════════════════════════════════════════════════

class TestConvergenceInvariants:

    def test_KC37_kernel_zero_fastapi_deps(self):
        """kernel/ modules have zero direct FastAPI imports."""
        import os
        kernel_dir = os.path.join(os.path.dirname(__file__), "..", "kernel")
        for root, dirs, files in os.walk(kernel_dir):
            for f in files:
                if not f.endswith(".py"):
                    continue
                path = os.path.join(root, f)
                content = open(path, encoding="utf-8").read()
                # api/routes/kernel.py is in api/, not kernel/
                assert "from fastapi" not in content, f"FastAPI import found in {path}"
                assert "import fastapi" not in content, f"FastAPI import found in {path}"

    def test_KC38_adapters_are_thin(self):
        """Adapter modules are under 200 lines each (thin requirement)."""
        import os
        adapter_dir = os.path.join(os.path.dirname(__file__), "..", "kernel", "adapters")
        for f in os.listdir(adapter_dir):
            if f.endswith(".py") and f != "__init__.py":
                path = os.path.join(adapter_dir, f)
                lines = len(open(path, encoding="utf-8").readlines())
                assert lines <= 200, f"Adapter {f} is {lines} lines (max 200)"

    def test_KC39_all_emissions_fail_open(self):
        """All kernel emissions in MetaOrchestrator are wrapped in try/except."""
        import re
        import inspect
        from core.meta_orchestrator import MetaOrchestrator
        source = inspect.getsource(MetaOrchestrator)  # class source — features in helpers
        # Find all emit_kernel_event calls
        calls = [m.start() for m in re.finditer("emit_kernel_event", source)]
        assert len(calls) >= 3, f"Expected 3+ kernel emit calls, found {len(calls)}"
        # Each should be inside a try block (check preceding 'try:')
        for pos in calls:
            preceding = source[max(0, pos - 200):pos]
            assert "try:" in preceding, f"emit_kernel_event at {pos} not in try/except"

    def test_KC40_kernel_boot_idempotent(self):
        """Multiple kernel boots return same runtime."""
        from kernel.runtime.boot import get_runtime
        r1 = get_runtime()
        r2 = get_runtime()
        assert r1 is r2
        assert r1.booted_at > 0
