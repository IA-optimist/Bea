"""
tests/test_kernel.py — Kernel invariant tests.

Validates: contracts, events, capabilities, memory, policy, boot.
These tests must NOT depend on FastAPI, UI, or business modules.
"""
import time


# ═══════════════════════════════════════════════════════════════
# 1 — Contracts
# ═══════════════════════════════════════════════════════════════

class TestContracts:

    def test_K01_goal_validation(self):
        from kernel.contracts import Goal
        g = Goal(description="build AI chatbot", priority=3)
        assert g.validate() == []

    def test_K02_goal_empty_fails(self):
        from kernel.contracts import Goal
        g = Goal(description="")
        errors = g.validate()
        assert len(errors) >= 1
        assert "description" in errors[0].lower()

    def test_K03_goal_priority_range(self):
        from kernel.contracts import Goal
        g = Goal(description="test", priority=15)
        errors = g.validate()
        assert any("priority" in e.lower() for e in errors)

    def test_K04_mission_id_generated(self):
        from kernel.contracts import Mission
        m = Mission()
        assert m.mission_id.startswith("mission-")

    def test_K05_mission_transitions(self):
        from kernel.contracts import Mission, MissionStatus
        m = Mission()
        assert m.can_transition(MissionStatus.PLANNING)
        assert not m.can_transition(MissionStatus.COMPLETED)
        assert m.transition(MissionStatus.PLANNING)
        assert m.status == MissionStatus.PLANNING

    def test_K06_mission_terminal_no_transition(self):
        from kernel.contracts import Mission, MissionStatus
        m = Mission(status=MissionStatus.COMPLETED)
        assert not m.can_transition(MissionStatus.EXECUTING)
        assert not m.transition(MissionStatus.EXECUTING)

    def test_K07_plan_validation(self):
        from kernel.contracts import Plan, PlanStep
        p = Plan(goal="test", steps=[PlanStep(target_id="t1")])
        assert p.validate() == []

    def test_K08_plan_empty_fails(self):
        from kernel.contracts import Plan
        p = Plan(goal="")
        errors = p.validate()
        assert len(errors) >= 2  # no goal + no steps

    def test_K09_plan_step_validation(self):
        from kernel.contracts import PlanStep, StepType
        s = PlanStep(type=StepType.TOOL, target_id="n8n.workflow.trigger")
        assert s.validate() == []

    def test_K10_plan_step_no_target(self):
        from kernel.contracts import PlanStep
        s = PlanStep(target_id="")
        errors = s.validate()
        assert len(errors) >= 1

    def test_K11_decision_confidence(self):
        from kernel.contracts import Decision
        d = Decision(confidence=0.8, reason="looks good")
        assert d.validate() == []

    def test_K12_decision_bad_confidence(self):
        from kernel.contracts import Decision
        d = Decision(confidence=1.5)
        errors = d.validate()
        assert len(errors) >= 1

    def test_K13_execution_result(self):
        from kernel.contracts import ExecutionResult
        r = ExecutionResult(ok=True, output={"data": "value"}, artifacts=["/tmp/file"])
        d = r.to_dict()
        assert d["ok"] is True
        assert len(d["artifacts"]) == 1

    def test_K14_policy_decision(self):
        from kernel.contracts import PolicyDecision, RiskLevel
        pd = PolicyDecision(allowed=True, risk_level=RiskLevel.MEDIUM, requires_approval=True)
        assert pd.to_dict()["requires_approval"] is True

    def test_K15_memory_record_ttl(self):
        from kernel.contracts import MemoryRecord
        r = MemoryRecord(memory_type="working", ttl=0.01, timestamp=time.time() - 1)
        assert r.expired is True

    def test_K16_memory_record_permanent(self):
        from kernel.contracts import MemoryRecord
        r = MemoryRecord(memory_type="semantic", ttl=0)
        assert r.expired is False

    def test_K17_system_event_validation(self):
        from kernel.contracts import SystemEvent
        e = SystemEvent(event_type="mission.created", summary="New mission")
        assert e.validate() == []

    def test_K18_system_event_empty_fails(self):
        from kernel.contracts import SystemEvent
        e = SystemEvent()
        errors = e.validate()
        assert len(errors) >= 2  # event_type + summary

    def test_K19_mission_serialization(self):
        from kernel.contracts import Mission, Goal, MissionStatus
        m = Mission(goal=Goal(description="test"), status=MissionStatus.EXECUTING)
        d = m.to_dict()
        m2 = Mission.from_dict(d)
        assert m2.goal.description == "test"
        assert m2.status == MissionStatus.EXECUTING

    def test_K20_observation(self):
        from kernel.contracts import Observation
        o = Observation(source="tool", content={"data": 42})
        assert o.observation_id.startswith("obs-")
        assert o.to_dict()["confidence"] == 1.0


# ═══════════════════════════════════════════════════════════════
# 2 — Events
# ═══════════════════════════════════════════════════════════════

class TestEvents:

    def test_K21_canonical_events_defined(self):
        from kernel.events.canonical import CANONICAL_EVENTS
        assert len(CANONICAL_EVENTS) >= 25
        assert "mission.created" in CANONICAL_EVENTS
        assert "plan.generated" in CANONICAL_EVENTS
        assert "step.completed" in CANONICAL_EVENTS
        assert "tool.invoked" in CANONICAL_EVENTS
        assert "kernel.booted" in CANONICAL_EVENTS

    def test_K22_emitter_mission_created(self):
        from kernel.events.canonical import KernelEventEmitter
        emitter = KernelEventEmitter()
        result = emitter.mission_created("m-test", "build chatbot")
        # Result depends on cognitive events being available
        assert isinstance(result, bool)

    def test_K23_emitter_plan_generated(self):
        from kernel.events.canonical import KernelEventEmitter
        emitter = KernelEventEmitter()
        emitter.plan_generated("p-test", steps=5)

    def test_K24_emitter_step_failed(self):
        from kernel.events.canonical import KernelEventEmitter
        emitter = KernelEventEmitter()
        emitter.step_failed("s-test", error="timeout")

    def test_K25_emitter_invalid_event(self):
        from kernel.events.canonical import KernelEventEmitter
        from kernel.contracts import SystemEvent
        emitter = KernelEventEmitter()
        result = emitter.emit(SystemEvent())  # no event_type
        assert result is False


# ═══════════════════════════════════════════════════════════════
# 3 — Capabilities
# ═══════════════════════════════════════════════════════════════

class TestCapabilities:

    def test_K26_twelve_capabilities(self):
        from kernel.capabilities.registry import KernelCapabilityRegistry
        reg = KernelCapabilityRegistry()
        assert len(reg.list_all()) >= 12

    def test_K27_capability_categories(self):
        from kernel.capabilities.registry import KernelCapabilityRegistry
        reg = KernelCapabilityRegistry()
        categories = {c.category for c in reg.list_all()}
        assert "planning" in categories
        assert "execution" in categories
        assert "memory" in categories
        assert "policy" in categories

    def test_K28_providers_for_capability(self):
        from kernel.capabilities.registry import KernelCapabilityRegistry
        reg = KernelCapabilityRegistry()
        providers = reg.providers_for("code_generation")
        assert "engineer" in providers

    def test_K29_tool_invocation_needs_approval(self):
        from kernel.capabilities.registry import KernelCapabilityRegistry
        reg = KernelCapabilityRegistry()
        cap = reg.get("tool_invocation")
        assert cap is not None
        assert cap.requires_approval is True

    def test_K30_stats(self):
        from kernel.capabilities.registry import KernelCapabilityRegistry
        reg = KernelCapabilityRegistry()
        s = reg.stats()
        assert s["total"] >= 12


# ═══════════════════════════════════════════════════════════════
# 4 — Memory
# ═══════════════════════════════════════════════════════════════

class TestMemory:

    def test_K31_working_memory(self):
        from kernel.memory.interfaces import MemoryInterface
        mem = MemoryInterface()
        mem.write_working("test_key", {"data": "value"}, ttl=60)
        result = mem.read_working("test_key")
        assert result == {"data": "value"}

    def test_K32_working_memory_expired(self):
        from kernel.memory.interfaces import MemoryInterface
        mem = MemoryInterface()
        mem.write_working("old_key", {"data": "old"}, ttl=0.001)
        time.sleep(0.01)
        assert mem.read_working("old_key") is None

    def test_K33_clear_working_memory(self):
        from kernel.memory.interfaces import MemoryInterface
        mem = MemoryInterface()
        mem.write_working("k1", {"a": 1}, mission_id="m1")
        mem.write_working("k2", {"b": 2}, mission_id="m2")
        cleared = mem.clear_working(mission_id="m1")
        assert cleared == 1
        assert mem.read_working("k1") is None
        assert mem.read_working("k2") is not None

    def test_K34_episodic_memory(self):
        from kernel.memory.interfaces import MemoryInterface
        mem = MemoryInterface()
        record = mem.write_episodic(
            {"event": "user_spoke", "content": "build chatbot"},
            mission_id="m-test",
        )
        assert record.memory_type == "episodic"

    def test_K35_memory_stats(self):
        from kernel.memory.interfaces import MemoryInterface
        mem = MemoryInterface()
        mem.write_working("test", {"x": 1})
        s = mem.stats()
        assert s["working_memory"]["count"] >= 1
        assert "working" in s["types"]


# ═══════════════════════════════════════════════════════════════
# 5 — Policy
# ═══════════════════════════════════════════════════════════════

class TestPolicy:

    def test_K36_risk_low(self):
        from kernel.policy.engine import RiskEngine
        from kernel.contracts import Action, RiskLevel
        engine = RiskEngine()
        risk = engine.evaluate(Action(action_type="read_file"))
        assert risk == RiskLevel.LOW

    def test_K37_risk_medium(self):
        from kernel.policy.engine import RiskEngine
        from kernel.contracts import Action, RiskLevel
        engine = RiskEngine()
        risk = engine.evaluate(Action(action_type="tool_invoke"))
        assert risk == RiskLevel.MEDIUM

    def test_K38_risk_high(self):
        from kernel.policy.engine import RiskEngine
        from kernel.contracts import Action, RiskLevel
        engine = RiskEngine()
        risk = engine.evaluate(Action(action_type="payment"))
        assert risk == RiskLevel.HIGH

    def test_K39_policy_low_auto_approve(self):
        from kernel.policy.engine import evaluate_action
        from kernel.contracts import Action
        decision = evaluate_action(Action(action_type="read_file"))
        assert decision.allowed is True
        assert decision.requires_approval is False

    def test_K40_policy_critical_blocked(self):
        from kernel.policy.engine import evaluate_action
        from kernel.contracts import Action, RiskLevel
        decision = evaluate_action(Action(action_type="test", risk_level=RiskLevel.CRITICAL))
        assert decision.allowed is False

    def test_K41_approval_gate(self):
        from kernel.policy.engine import ApprovalGate
        from kernel.contracts import Action, PolicyDecision
        gate = ApprovalGate()
        action = Action(action_id="a1", action_type="webhook")
        policy = PolicyDecision(allowed=True, requires_approval=True)
        req_id = gate.request(action, policy)
        assert len(gate.get_pending()) == 1
        gate.decide(req_id, approved=True, reason="looks safe")
        assert gate.is_approved("a1")
        assert len(gate.get_pending()) == 0

    def test_K42_risk_policy_approval_separation(self):
        """Risk, policy, and approval are distinct components."""
        from kernel.policy.engine import RiskEngine, KernelPolicyEngine, ApprovalGate
        assert RiskEngine is not KernelPolicyEngine
        assert KernelPolicyEngine is not ApprovalGate
        # Risk engine only computes risk
        assert hasattr(RiskEngine, 'evaluate')
        assert not hasattr(RiskEngine, 'request')
        # Approval gate only handles approvals
        assert hasattr(ApprovalGate, 'request')
        assert not hasattr(ApprovalGate, 'evaluate')


# ═══════════════════════════════════════════════════════════════
# 6 — Kernel Boot
# ═══════════════════════════════════════════════════════════════

class TestKernelBoot:

    def test_K43_boot(self):
        from kernel.runtime.boot import boot_kernel
        runtime = boot_kernel()
        assert runtime.booted_at > 0
        assert runtime.version == "0.1.0"

    def test_K44_all_subsystems_initialized(self):
        from kernel.runtime.boot import boot_kernel
        runtime = boot_kernel()
        status = runtime.status()
        assert status["booted"] is True
        for name, ready in status["subsystems"].items():
            assert ready is True, f"Subsystem {name} not initialized"

    def test_K45_kernel_standalone(self):
        """Kernel boots without FastAPI or UI."""
        # This test itself proves it — we import kernel, not api
        from kernel.runtime.boot import boot_kernel
        runtime = boot_kernel()
        caps = runtime.capabilities.list_all()
        assert len(caps) >= 12

    def test_K46_runtime_singleton(self):
        from kernel.runtime.boot import get_runtime
        r1 = get_runtime()
        r2 = get_runtime()
        assert r1 is r2

    def test_K47_kernel_spec_exists(self):
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "docs", "kernel_spec.md")
        assert os.path.isfile(path)
        content = open(path).read()
        assert "Domain Contracts" in content
        assert "Capability Model" in content
        assert "Event Model" in content
        assert "Memory Model" in content
        assert "Policy Model" in content

    def test_K48_uptime(self):
        from kernel.runtime.boot import boot_kernel
        runtime = boot_kernel()
        assert runtime.uptime_seconds >= 0
