"""
agents/kernel_bridge.py — Kernel-registered agent adapters (Pass 27 — R7).

R7: Agents are replaceable, specialized workers operating under kernel contract.
    The kernel dispatches tasks; agents conform to KernelAgentContract.

This module provides two things:
  1. KernelStatusAgent — a lightweight monitoring agent conforming to KernelAgentContract.
     It reports system health without coupling to heavy agent dependencies.
  2. build_and_register_kernel_agents() — called at boot (main.py) to populate
     KernelAgentRegistry with real, dispatchable agents.

K1 note: this module lives in agents/ — it MAY import from kernel.contracts.
It is NOT imported by kernel/ (which would violate K1).
Boot wiring is performed in main.py using the registration pattern.
"""
from __future__ import annotations

import time
from typing import Any, Optional

import structlog

log = structlog.get_logger("agents.kernel_bridge")


# ══════════════════════════════════════════════════════════════════════════════
# KernelStatusAgent — system health monitoring, kernel-dispatchable
# ══════════════════════════════════════════════════════════════════════════════

class KernelStatusAgent:
    """
    Lightweight agent conforming to KernelAgentContract (structural typing).

    Capability: system_status — reports kernel runtime, memory, and process health.

    Design principles:
    - No BaseAgent inheritance (structural Protocol conformance only)
    - No settings dependency (uses kernel/tools APIs via fail-open calls)
    - Async execute() and health_check() as required by KernelAgentContract
    """

    # ── KernelAgentContract properties ────────────────────────────────────────

    @property
    def agent_id(self) -> str:
        return "kernel-status-agent"

    @property
    def capability_type(self) -> str:
        return "system_status"

    # ── KernelAgentContract methods ───────────────────────────────────────────

    async def execute(
        self,
        task: Any,  # KernelAgentTask — typed loosely to avoid circular import
        context: Optional[Any] = None,
    ) -> Any:  # KernelAgentResult
        """
        Execute a system_status task.

        Collects: kernel runtime status, memory stats, uptime.
        Returns KernelAgentResult(status=SUCCESS, output=...).
        Never raises — fail-open, returns FAILED result on any exception.
        """
        from kernel.contracts.agent import KernelAgentResult, KernelAgentStatus

        _t0 = time.time()
        _goal = getattr(task, "goal", "") or "system_status"
        _mid  = getattr(task, "mission_id", "") or ""

        try:
            status_parts: list[str] = []

            # Kernel runtime status
            try:
                from kernel.runtime.boot import get_runtime
                _rt = get_runtime()
                _rt_status = _rt.status()
                status_parts.append(
                    f"kernel: booted={_rt_status.get('booted', False)}, "
                    f"uptime={round(_rt_status.get('uptime_seconds', 0), 1)}s, "
                    f"security={_rt_status.get('security', False)}"
                )
            except Exception as _e:
                status_parts.append(f"kernel: unavailable ({str(_e)[:40]})")

            # Memory interface stats (fail-open)
            try:
                from kernel.memory.interfaces import get_memory_interface
                _mi = get_memory_interface()
                _mi_stats = _mi.stats()
                status_parts.append(
                    f"memory: records={_mi_stats.get('total_records', 0)}, "
                    f"facade={_mi_stats.get('facade_store_registered', False)}"
                )
            except Exception:
                status_parts.append("memory: unavailable")

            # Improvement gate status (fail-open)
            try:
                from kernel.improvement.gate import get_gate
                _gate_decision = get_gate().check(mission_id=_mid)
                status_parts.append(
                    f"improvement_gate: allowed={_gate_decision.allowed}, "
                    f"reason={_gate_decision.reason}"
                )
            except Exception:
                status_parts.append("improvement_gate: unavailable")

            _output = f"[KernelStatusAgent] System health for '{_goal}':\n" + "\n".join(
                f"  • {s}" for s in status_parts
            )

            return KernelAgentResult(
                task_id=getattr(task, "task_id", "unknown"),
                mission_id=_mid,
                agent_id=self.agent_id,
                status=KernelAgentStatus.SUCCESS,
                output=_output,
                started_at=_t0,
                finished_at=time.time(),
                metadata={"status_parts": len(status_parts)},
            )

        except Exception as e:
            log.warning("kernel_status_agent_execute_failed", err=str(e)[:100])
            from kernel.contracts.agent import KernelAgentResult, KernelAgentStatus
            return KernelAgentResult(
                task_id=getattr(task, "task_id", "unknown"),
                mission_id=_mid,
                agent_id=self.agent_id,
                status=KernelAgentStatus.FAILED,
                output="",
                error=str(e)[:200],
                started_at=_t0,
                finished_at=time.time(),
            )

    async def health_check(self) -> Any:  # AgentHealthStatus
        """
        Quick liveness check. Always returns HEALTHY (agent is stateless).
        """
        from kernel.contracts.agent import AgentHealthStatus
        return AgentHealthStatus.HEALTHY


# ══════════════════════════════════════════════════════════════════════════════
# KernelMissionAgent — kernel-registered mission execution agent (BLOC 3 — R7)
# ══════════════════════════════════════════════════════════════════════════════

class KernelMissionAgent:
    """
    Kernel-registered agent that represents the core mission execution capability.

    This agent bridges the kernel registry (R7: kernel is the authority) to the
    existing execution path (kernel.run_cognitive_cycle → MetaOrchestrator).

    capability_type = "mission_execution" — the kernel dispatches here for any
    general mission that doesn't match a more specific registered agent.

    Design: structural Protocol conformance only (no BaseAgent inheritance).
    """

    @property
    def agent_id(self) -> str:
        return "kernel-mission-agent"

    @property
    def capability_type(self) -> str:
        return "mission_execution"

    async def execute(
        self,
        task: Any,  # KernelAgentTask
        context: Optional[Any] = None,
    ) -> Any:  # KernelAgentResult
        """
        Execute a mission task through the kernel cognitive pipeline.

        Routes to kernel.run_cognitive_cycle() to leverage pre-computed context.
        Returns a KernelAgentResult wrapping the cognitive output.
        Never raises — fail-open.
        """
        from kernel.contracts.agent import KernelAgentResult, KernelAgentStatus

        _t0 = time.time()
        _goal = getattr(task, "goal", "") or ""
        _mid = getattr(task, "mission_id", "") or ""

        try:
            # Use kernel cognitive cycle as the execution backbone.
            # run_cognitive_cycle() lives on JarvisKernel (kernel/runtime/kernel.py),
            # not on KernelRuntime (kernel/runtime/boot.py).
            from kernel.runtime.kernel import get_kernel
            _rt = get_kernel()
            _kc = _rt.run_cognitive_cycle(_goal)

            _enriched = _kc.get("enriched_goal") or _goal
            _routing = _kc.get("routing", {})
            _lessons_count = len(_kc.get("kernel_lessons", []))

            _output = (
                f"[KernelMissionAgent] Cognitive cycle complete for '{_goal[:80]}'\n"
                f"  enriched_goal_len={len(_enriched)}, "
                f"routing={_routing.get('provider_id', 'none')}, "
                f"lessons_injected={_lessons_count}"
            )

            return KernelAgentResult(
                task_id=getattr(task, "task_id", "unknown"),
                mission_id=_mid,
                agent_id=self.agent_id,
                status=KernelAgentStatus.SUCCESS,
                output=_output,
                confidence=0.8,
                reasoning=f"kernel_cognitive_cycle: routing={_routing}",
                metadata={
                    "enriched_goal_len": len(_enriched),
                    "lessons_injected": _lessons_count,
                    "routing": _routing,
                },
                started_at=_t0,
                finished_at=time.time(),
            )

        except Exception as e:
            log.warning("kernel_mission_agent_execute_failed", err=str(e)[:100])
            return KernelAgentResult(
                task_id=getattr(task, "task_id", "unknown"),
                mission_id=_mid,
                agent_id=self.agent_id,
                status=KernelAgentStatus.FAILED,
                output="",
                error=str(e)[:200],
                started_at=_t0,
                finished_at=time.time(),
            )

    async def health_check(self) -> Any:  # AgentHealthStatus
        """
        Quick liveness check: verify kernel runtime is accessible.
        Returns HEALTHY if kernel is booted, DEGRADED otherwise.
        """
        from kernel.contracts.agent import AgentHealthStatus
        try:
            from kernel.runtime.boot import get_runtime
            _rt = get_runtime()
            _status = _rt.status()
            if _status.get("booted", False):
                return AgentHealthStatus.HEALTHY
            return AgentHealthStatus.DEGRADED
        except Exception:
            return AgentHealthStatus.DEGRADED


# ══════════════════════════════════════════════════════════════════════════════
# Boot registration helper
# ══════════════════════════════════════════════════════════════════════════════

def build_and_register_kernel_agents() -> list[str]:
    """
    Instantiate and register kernel-dispatchable agents.

    Called at boot (main.py) via the registration pattern.
    Returns list of successfully registered agent_ids.
    Never raises — each agent registration is fail-open.

    To add a new kernel-dispatchable agent:
        1. Create a class conforming to KernelAgentContract (structural Protocol)
        2. Instantiate it here and call registry.register(agent)
    """
    from kernel.contracts.agent import get_agent_registry

    _registry = get_agent_registry()
    _registered: list[str] = []

    # ── KernelStatusAgent ─────────────────────────────────────────────────────
    try:
        _status_agent = KernelStatusAgent()
        if _registry.register(_status_agent):
            _registered.append(_status_agent.agent_id)
            log.info("kernel_agent_registered", agent_id=_status_agent.agent_id,
                     capability=_status_agent.capability_type)
        else:
            log.warning("kernel_agent_register_failed", agent_id=_status_agent.agent_id,
                        reason="registry.register returned False (contract mismatch?)")
    except Exception as _e:
        log.warning("kernel_status_agent_boot_failed", err=str(_e)[:80])

    # ── KernelMissionAgent (BLOC 3 — R7) ─────────────────────────────────────
    # Covers capability_type="mission_execution" — kernel is the authority for
    # general mission dispatch. Bridges to kernel.run_cognitive_cycle().
    try:
        _mission_agent = KernelMissionAgent()
        if _registry.register(_mission_agent):
            _registered.append(_mission_agent.agent_id)
            log.info("kernel_agent_registered", agent_id=_mission_agent.agent_id,
                     capability=_mission_agent.capability_type)
        else:
            log.warning("kernel_agent_register_failed", agent_id=_mission_agent.agent_id,
                        reason="registry.register returned False (contract mismatch?)")
    except Exception as _e:
        log.warning("kernel_mission_agent_boot_failed", err=str(_e)[:80])

    return _registered
