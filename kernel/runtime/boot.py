"""
kernel/runtime/boot.py — Kernel boot sequence and runtime handle.

The kernel can be initialized independently of the API layer.
API becomes an adapter on top of the kernel runtime.

Boot lifecycle:
  1. Initialize contracts (validate type system)
  2. Load capabilities (register kernel capabilities)
  3. Load policy engine
  4. Initialize memory interfaces
  5. Initialize event emitter
  6. Emit kernel.booted event
  7. Return runtime handle

Usage:
  from kernel.runtime.boot import boot_kernel
  runtime = boot_kernel()
  runtime.capabilities.list_all()
  runtime.memory.write_working("key", {"data": "value"})
  runtime.events.mission_created("m-123", "build AI chatbot")
"""
from __future__ import annotations

import os
import time
import structlog
from dataclasses import dataclass

log = structlog.get_logger("kernel.boot")


@dataclass
class KernelRuntime:
    """Runtime handle — single access point for all kernel subsystems."""
    capabilities: object = None
    memory: object = None
    events: object = None
    policy: object = None
    risk: object = None
    approval: object = None
    performance: object = None
    security: object = None    # Pass 21 — native security layer (R3, R10)
    booted_at: float = 0
    version: str = "0.1.0"

    @property
    def uptime_seconds(self) -> float:
        return round(time.time() - self.booted_at, 1) if self.booted_at else 0

    def status(self) -> dict:
        return {
            "booted": self.booted_at > 0,
            "version": self.version,
            "uptime_seconds": self.uptime_seconds,
            "subsystems": {
                "capabilities": self.capabilities is not None,
                "memory": self.memory is not None,
                "events": self.events is not None,
                "policy": self.policy is not None,
                "risk": self.risk is not None,
                "approval": self.approval is not None,
                "performance": self.performance is not None,
                "security": self.security is not None,    # Pass 21
            },
        }


def boot_kernel() -> KernelRuntime:
    """
    Initialize the kernel runtime.

    Returns a KernelRuntime handle with all subsystems initialized.
    This does NOT start the API — API is an adapter on top.
    """
    log.info("kernel_boot_start")
    t0 = time.time()

    # 1. Validate contracts
    _validate_contracts()

    # 2. Load capabilities
    from kernel.capabilities.registry import get_capability_registry
    capabilities = get_capability_registry()
    log.info("kernel_capabilities_loaded", count=len(capabilities.list_all()))

    # 3. Load policy engine
    from kernel.policy.engine import KernelPolicyEngine, RiskEngine, ApprovalGate
    policy = KernelPolicyEngine()
    risk = RiskEngine()
    approval = ApprovalGate()

    # 4. Initialize memory
    from kernel.memory.interfaces import get_memory
    memory = get_memory()

    # 5. Initialize event emitter
    from kernel.events.canonical import get_kernel_emitter
    events = get_kernel_emitter()

    # 6. Initialize performance store + load persisted data
    from kernel.capabilities.performance import get_performance_store
    performance = get_performance_store()
    _load_performance(performance)

    # 7. Initialize security layer (Pass 21 — R3, R10)
    # security/ is the native governance layer — initialized at kernel boot,
    # NOT as a decorator. fail-open: if security unavailable, boot continues.
    _security = None
    try:
        from security import get_security_layer
        _security = get_security_layer()
        log.info("kernel_security_layer_initialized",
                 active_rules=len(_security.active_rules()))
    except Exception as _se:
        log.warning("kernel_security_layer_skipped", err=str(_se)[:80])

    # 8. Build runtime handle
    runtime = KernelRuntime(
        capabilities=capabilities,
        memory=memory,
        events=events,
        policy=policy,
        risk=risk,
        approval=approval,
        performance=performance,
        security=_security,
        booted_at=time.time(),
    )

    # 8. Emit boot event
    events.emit(
        __import__("kernel.contracts.types", fromlist=["SystemEvent"]).SystemEvent(
            event_type="kernel.booted",
            source="kernel",
            summary=f"Kernel booted in {round((time.time()-t0)*1000)}ms",
            payload={"version": runtime.version, "capabilities": len(capabilities.list_all())},
        )
    )

    boot_ms = round((time.time() - t0) * 1000)
    log.info("kernel_boot_complete", boot_ms=boot_ms, capabilities=len(capabilities.list_all()))

    return runtime


def _validate_contracts():
    """Validate that all contract types are importable and correct."""
    from kernel.contracts.types import (
        Mission, Goal, Plan, PlanStep, Action, Decision,
        Observation, ExecutionResult, PolicyDecision,
        MemoryRecord, SystemEvent,
    )
    # Quick smoke test — create instances
    Goal(description="test").validate()
    Mission().validate()
    PlanStep(target_id="test").validate()
    Plan(goal="test", steps=[PlanStep(target_id="t")]).validate()
    Action(action_type="test", target="test").to_dict()
    Decision().validate()
    Observation().to_dict()
    ExecutionResult(ok=True).to_dict()
    PolicyDecision(allowed=True).to_dict()
    MemoryRecord(memory_type="test").to_dict()
    SystemEvent(event_type="test", summary="test").validate()
    log.debug("kernel_contracts_validated")


# ── Performance persistence ───────────────────────────────────

_PERFORMANCE_FILE = "data/kernel_performance.json"


def _get_performance_path() -> str:
    """Resolve performance file path relative to working dir or repo root."""
    # Check if running from repo root (has kernel/ dir)
    if os.path.isdir("kernel"):
        return _PERFORMANCE_FILE
    # Try common repo locations
    for base in [os.environ.get("BEA_ROOT", ""), "/app"]:
        if base and os.path.isdir(os.path.join(base, "kernel")):
            return os.path.join(base, _PERFORMANCE_FILE)
    return _PERFORMANCE_FILE


def _load_performance(store) -> None:
    """Load persisted performance data on boot. Fail-open."""
    try:
        path = _get_performance_path()
        loaded = store.load_from_file(path)
        if loaded > 0:
            log.info("kernel_performance_restored", records=loaded, path=path)
    except Exception as e:
        log.debug("kernel_performance_restore_skip", err=str(e)[:60])


def save_performance() -> bool:
    """
    Save current performance data to disk.

    Call on shutdown or periodically to persist learning.
    Returns True on success. Fail-open: never raises.
    """
    try:
        if _runtime is None or _runtime.performance is None:
            return False
        path = _get_performance_path()
        return _runtime.performance.save_to_file(path)
    except Exception as e:
        log.debug("kernel_performance_save_failed", err=str(e)[:60])
        return False


# ── Module entry point ────────────────────────────────────────

_runtime: KernelRuntime | None = None


def get_runtime() -> KernelRuntime:
    """Get or create the kernel runtime singleton."""
    global _runtime
    if _runtime is None:
        _runtime = boot_kernel()
    return _runtime
