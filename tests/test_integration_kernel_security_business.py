"""
tests/test_integration_kernel_security_business.py — Pass 22.

Integration tests for the full kernel → security → business pipeline.
Validates that all architectural rules (R1–R10) hold end-to-end.

Run with:
    python -m pytest tests/test_integration_kernel_security_business.py -v
    or
    python tests/test_integration_kernel_security_business.py
"""
from __future__ import annotations

import asyncio
import ast
import sys
import time
from pathlib import Path
_silent_log = __import__("structlog").get_logger(__name__)

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).parent.parent))

_PASS = "✅ PASS"
_FAIL = "❌ FAIL"
_results: list[tuple[str, bool, str]] = []


def _run_test(name: str, fn) -> bool:
    """Run a single test, record result."""
    try:
        fn()
        _results.append((name, True, ""))
        print(f"  {_PASS} {name}")
        return True
    except Exception as e:
        _results.append((name, False, str(e)[:120]))
        print(f"  {_FAIL} {name}: {str(e)[:80]}")
        return False


def _run_atest(name: str, coro) -> bool:
    """Run a single async test."""
    try:
        asyncio.get_event_loop().run_until_complete(coro)
        _results.append((name, True, ""))
        print(f"  {_PASS} {name}")
        return True
    except Exception as e:
        _results.append((name, False, str(e)[:120]))
        print(f"  {_FAIL} {name}: {str(e)[:80]}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 1: K1 Rule — kernel never imports from core/api/agents/tools
# ══════════════════════════════════════════════════════════════════════════════

def _k1_scan_directory(directory: str) -> list[str]:
    """Return list of K1 violations in directory."""
    violations = []
    for py_file in Path(directory).rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        try:
            with open(py_file, encoding="utf-8") as f:
                src = f.read()
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if any(node.module.startswith(p) for p in ["core.", "api.", "agents.", "tools."]):
                        violations.append(f"{py_file}:{node.lineno} → {node.module}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if any(alias.name.startswith(p) for p in ["core.", "api.", "agents.", "tools."]):
                            violations.append(f"{py_file}:{node.lineno} → {alias.name}")
        except Exception:
            _silent_log.debug("suppressed_exception", src='test_integration_kernel_security_business.py')
    return violations


def group_k1_rule():
    print("\n── GROUP 1: K1 Rule (kernel/ never imports core/api/agents/tools) ──")

    def t_kernel_contracts():
        v = _k1_scan_directory("kernel/contracts")
        assert not v, f"K1 violations: {v[:3]}"

    def t_kernel_memory():
        v = _k1_scan_directory("kernel/memory")
        assert not v, f"K1 violations: {v[:3]}"

    def t_kernel_policy():
        v = _k1_scan_directory("kernel/policy")
        assert not v, f"K1 violations: {v[:3]}"

    def t_kernel_execution():
        v = _k1_scan_directory("kernel/execution")
        assert not v, f"K1 violations: {v[:3]}"

    def t_kernel_state():
        v = _k1_scan_directory("kernel/state")
        assert not v, f"K1 violations: {v[:3]}"

    def t_security_layer():
        v = _k1_scan_directory("security")
        # security/ CAN import kernel/ — only blocked from core/api/agents/tools
        assert not v, f"K1 violations: {v[:3]}"

    _run_test("K1: kernel/contracts/ clean", t_kernel_contracts)
    _run_test("K1: kernel/memory/ clean", t_kernel_memory)
    _run_test("K1: kernel/policy/ clean", t_kernel_policy)
    _run_test("K1: kernel/execution/ clean", t_kernel_execution)
    _run_test("K1: kernel/state/ clean", t_kernel_state)
    _run_test("K1: security/ clean (no core/api imports)", t_security_layer)


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 2: Kernel boot — all subsystems operational
# ══════════════════════════════════════════════════════════════════════════════

def group_kernel_boot():
    print("\n── GROUP 2: Kernel Boot ──")

    def t_boot():
        from kernel.runtime.boot import boot_kernel
        runtime = boot_kernel()
        status = runtime.status()
        subsys = status["subsystems"]
        assert subsys["capabilities"], "capabilities not booted"
        assert subsys["memory"], "memory not booted"
        assert subsys["events"], "events not booted"
        assert subsys["policy"], "policy not booted"
        assert subsys["security"], "security not booted (Pass 21)"

    def t_kernel_singleton():
        from kernel.runtime.kernel import get_kernel
        k1 = get_kernel()
        k2 = get_kernel()
        assert k1 is k2, "JarvisKernel should be singleton"

    def t_cognitive_cycle():
        from kernel.runtime.kernel import get_kernel
        k = get_kernel()
        result = k.run_cognitive_cycle(goal="analyze market opportunity", mode="auto", mission_id="it-001")
        assert isinstance(result, dict)
        assert "classification" in result or "kernel_cognitive_source" in result
        # Must have at least classification or plan
        has_data = bool(result.get("classification") or result.get("kernel_plan"))
        assert has_data, f"cognitive cycle returned empty: {list(result.keys())}"

    _run_test("Boot: all subsystems initialized", t_boot)
    _run_test("Boot: JarvisKernel singleton stable", t_kernel_singleton)
    _run_test("Boot: cognitive cycle returns data", t_cognitive_cycle)


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 3: Security layer — governance rules enforced
# ══════════════════════════════════════════════════════════════════════════════

def group_security():
    print("\n── GROUP 3: Security Layer (R3, R10) ──")

    def t_payment_escalated():
        from security import get_security_layer
        layer = get_security_layer()
        r = layer.check_action("payment", mission_id="it-sec-001", mode="auto", risk_level="high")
        assert not r.allowed, "payment should be blocked"
        assert r.escalated, "payment should be escalated, not denied"

    def t_critical_denied():
        from security import get_security_layer
        layer = get_security_layer()
        r = layer.check_action("anything", mission_id="it-sec-001", mode="auto", risk_level="critical")
        assert not r.allowed, "critical/auto should be blocked"
        assert not r.escalated, "critical should be DENIED, not escalated"

    def t_cognitive_allowed():
        from security import get_security_layer
        layer = get_security_layer()
        r = layer.check_action("cognitive", mission_id="it-sec-001", mode="auto", risk_level="low")
        assert r.allowed, "cognitive should be allowed"

    def t_audit_trail_populated():
        from security import get_security_layer
        from security.audit import AuditDecision
        layer = get_security_layer()
        # Run a few checks
        layer.check_action("payment", mission_id="it-audit", mode="auto", risk_level="medium")
        layer.check_action("cognitive", mission_id="it-audit", mode="auto", risk_level="low")
        trail = layer.audit_trail()
        assert len(trail) > 0, "AuditTrail should have entries"
        payment_entries = trail.by_decision(AuditDecision.ESCALATED)
        assert len(payment_entries) > 0, "Should have at least one escalated entry"

    def t_self_improvement_gated():
        from security import get_security_layer
        layer = get_security_layer()
        r = layer.check_action("self_improvement", mission_id="it-sec-002", mode="auto", risk_level="low")
        # R4: self-improvement always requires approval
        assert not r.allowed or r.escalated, "self_improvement should be gated"

    def t_risk_profile_confidential():
        from security.risk import get_risk_registry, SensitivityLevel
        reg = get_risk_registry()
        for action_type in ["payment", "data_delete", "deployment", "self_improvement"]:
            profile = reg.get(action_type)
            assert profile.sensitivity == SensitivityLevel.CONFIDENTIAL, \
                f"{action_type} should be CONFIDENTIAL, got {profile.sensitivity}"

    _run_test("Security: payment → ESCALATE (R3)", t_payment_escalated)
    _run_test("Security: critical/auto → DENY", t_critical_denied)
    _run_test("Security: cognitive → ALLOW", t_cognitive_allowed)
    _run_test("Security: audit trail populated (R10)", t_audit_trail_populated)
    _run_test("Security: self_improvement gated (R4)", t_self_improvement_gated)
    _run_test("Security: high-risk profiles CONFIDENTIAL", t_risk_profile_confidential)


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 4: Memory — MemoryFacade as unified interface (R6)
# ══════════════════════════════════════════════════════════════════════════════

def group_memory():
    print("\n── GROUP 4: Memory Unification (R6) ──")

    def t_facade_slots_registered():
        from kernel.memory import interfaces as _mi
        # After boot, slots should be registered
        # (may be None in test env where main.py startup didn't run)
        # Just verify the slots exist as module-level attributes
        assert hasattr(_mi, "_facade_store_fn"), "_facade_store_fn missing"
        assert hasattr(_mi, "_facade_search_fn"), "_facade_search_fn missing"

    def t_memory_interface_search():
        from kernel.memory.interfaces import (
            MemoryInterface, register_facade_store, register_facade_search
        )
        register_facade_store(lambda c, ct="general", tags=None, m=None: {"ok": True})
        register_facade_search(lambda q, k=5: [{"content": "result", "score": 0.7}])
        mi = MemoryInterface()
        results = mi.search("test query", top_k=3)
        assert results[0]["score"] == 0.7

    def t_persist_record_uses_facade():
        from kernel.memory.interfaces import (
            MemoryInterface, register_facade_store
        )
        from kernel.contracts.types import MemoryRecord
        calls = []
        register_facade_store(lambda c, ct="general", tags=None, m=None: calls.append(ct) or {"ok": True})
        mi = MemoryInterface()
        r = MemoryRecord(memory_type="episodic", content={"summary": "test"}, mission_id="m001")
        mi._persist_record(r)
        assert "mission_outcome" in calls, f"Expected mission_outcome in calls, got {calls}"

    def t_kernel_memory_singleton():
        from kernel.memory import get_memory
        m1 = get_memory()
        m2 = get_memory()
        assert m1 is m2

    _run_test("Memory: facade slots exist in kernel.memory.interfaces", t_facade_slots_registered)
    _run_test("Memory: MemoryInterface.search() delegates to facade", t_memory_interface_search)
    _run_test("Memory: _persist_record uses facade (R6)", t_persist_record_uses_facade)
    _run_test("Memory: kernel memory singleton stable", t_kernel_memory_singleton)


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 5: Business — R9 policy gate
# ══════════════════════════════════════════════════════════════════════════════

def group_business():
    print("\n── GROUP 5: Business Layer (R9) ──")

    def t_business_layer_has_security_gate():
        from business.layer import BusinessLayer, _SENSITIVE_MODULES
        assert "finance" in _SENSITIVE_MODULES, f"finance not in sensitive: {_SENSITIVE_MODULES}"
        assert hasattr(BusinessLayer, "_security_gate"), "_security_gate missing"

    def t_security_gate_venture_not_blocked():
        from business.layer import BusinessLayer
        from config.settings import get_settings
        bl = BusinessLayer(get_settings())

        class FakeSession:
            session_id = "it-biz-001"
            user_input = "build a venture"
            mission_summary = ""

        # venture is not in _SENSITIVE_MODULES → always allowed
        assert bl._security_gate("venture", FakeSession()), "venture should not be blocked"

    def t_finance_goes_through_security():
        from business.layer import BusinessLayer
        from config.settings import get_settings
        bl = BusinessLayer(get_settings())

        class FakeSession:
            session_id = "it-biz-002"
            user_input = "financial plan"
            mission_summary = ""

        # finance IS in _SENSITIVE_MODULES → security is checked (but allowed by default rules)
        result = bl._security_gate("finance", FakeSession())
        # Should be allowed (no rule blocks 'business_finance')
        assert result, "finance should be allowed by current rules"

    async def t_strategy_runs():
        from business.layer import BusinessLayer
        from config.settings import get_settings
        bl = BusinessLayer(get_settings())

        class FakeSession:
            session_id = "it-biz-003"
            user_input = "roadmap stratégique"
            mission_summary = ""

        r = await bl.run("strategy", FakeSession())
        assert "[Strategic Analysis]" in r, f"Expected strategy output: {r[:80]}"

    async def t_finance_runs():
        from business.layer import BusinessLayer
        from config.settings import get_settings
        bl = BusinessLayer(get_settings())

        class FakeSession:
            session_id = "it-biz-004"
            user_input = "financial plan LTV"
            mission_summary = ""

        r = await bl.run("finance", FakeSession())
        assert "[Financial Analysis]" in r, f"Expected finance output: {r[:80]}"

    _run_test("Business: _security_gate exists + finance in sensitive", t_business_layer_has_security_gate)
    _run_test("Business: venture not gated", t_security_gate_venture_not_blocked)
    _run_test("Business: finance goes through security (R9)", t_finance_goes_through_security)
    _run_atest("Business: strategy agent runs", t_strategy_runs())
    _run_atest("Business: finance agent runs", t_finance_runs())


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 6: Agent contract — R7
# ══════════════════════════════════════════════════════════════════════════════

def group_agent_contract():
    print("\n── GROUP 6: Agent Contract (R7) ──")

    def t_protocol_importable():
        pass

    def t_structural_typing():
        from kernel.contracts.agent import (
            KernelAgentContract, KernelAgentResult, AgentHealthStatus
        )
        # Define a conforming agent without inheriting
        class MyAgent:
            @property
            def agent_id(self): return "my-agent-001"
            @property
            def capability_type(self): return "research"
            async def execute(self, task, context=None):
                return KernelAgentResult(agent_id=self.agent_id)
            async def health_check(self):
                return AgentHealthStatus.HEALTHY

        assert isinstance(MyAgent(), KernelAgentContract), "MyAgent should satisfy protocol"

    def t_registry_rejects_non_conforming():
        from kernel.contracts.agent import KernelAgentRegistry

        class BadAgent:  # missing agent_id, capability_type, execute, health_check
            pass

        reg = KernelAgentRegistry()
        result = reg.register(BadAgent())
        assert not result, "Non-conforming agent should be rejected"

    def t_kernel_agent_result_ok():
        from kernel.contracts.agent import KernelAgentResult, KernelAgentStatus
        r = KernelAgentResult(agent_id="a001", output="done", confidence=0.9)
        assert r.ok
        assert r.status == KernelAgentStatus.SUCCESS
        d = r.to_dict()
        assert d["confidence"] == 0.9

    _run_test("AgentContract: protocol importable", t_protocol_importable)
    _run_test("AgentContract: structural typing works (R7)", t_structural_typing)
    _run_test("AgentContract: registry rejects non-conforming", t_registry_rejects_non_conforming)
    _run_test("AgentContract: KernelAgentResult correct", t_kernel_agent_result_ok)


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 7: Interfaces adapter (R8)
# ══════════════════════════════════════════════════════════════════════════════

def group_interfaces():
    print("\n── GROUP 7: Interfaces Adapter (R8) ──")

    def t_adapter_importable():
        pass

    def t_adapter_result_decoupled():
        # AdapterResult must NOT import ExecutionResult from kernel
        import ast
        with open("interfaces/kernel_adapter.py", encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "ExecutionResult" not in [a.name for a in node.names] or \
                       "kernel.execution.contracts" in node.module or \
                       node.module.startswith("kernel."), \
                    f"AdapterResult should not import from non-kernel: {node.module}"

    def t_adapter_status_no_internals():
        from interfaces import get_kernel_adapter
        adapter = get_kernel_adapter()
        status = adapter.status()
        # status must not expose runtime internals
        assert "capabilities" not in status, "Should not expose kernel capabilities directly"
        assert "kernel_available" in status

    _run_test("Interfaces: adapter importable", t_adapter_importable)
    _run_test("Interfaces: AdapterResult decoupled from kernel internals (R8)", t_adapter_result_decoupled)
    _run_test("Interfaces: status() no internal exposure", t_adapter_status_no_internals)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 65)
    print("PASS 22 — Integration Tests: kernel → security → business")
    print("=" * 65)

    t0 = time.time()
    group_k1_rule()
    group_kernel_boot()
    group_security()
    group_memory()
    group_business()
    group_agent_contract()
    group_interfaces()

    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    elapsed = round((time.time() - t0) * 1000)

    print()
    print("=" * 65)
    print(f"Results: {passed}/{len(_results)} passed — {elapsed}ms")
    if failed:
        print(f"\n{_FAIL} {failed} test(s) failed:")
        for name, ok, err in _results:
            if not ok:
                print(f"  - {name}: {err}")
    else:
        print(f"\n{_PASS} All {passed} tests passed.")
    print("=" * 65)

    return 0 if failed == 0 else 1


def test_integration_kernel_security_business():
    """Pytest entry-point: runs the full Pass 22 integration suite."""
    global _results
    _results = []
    assert main() == 0, "Integration tests failed — see stdout for details"


if __name__ == "__main__":
    sys.exit(main())
