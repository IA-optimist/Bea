"""
interfaces/kernel_adapter.py — Kernel adapter for external consumers (Pass 20).

R8: The API is an adapter, never a decision-maker.

This module is the ONLY sanctioned bridge between external consumers (HTTP, CLI,
WebSocket, tests) and the kernel. It:
  - Wraps kernel.execute() with clean error surfacing
  - Exposes kernel status without coupling callers to kernel internals
  - Translates external request shapes → kernel contracts
  - Never makes routing or planning decisions itself

Usage (from api/routes/*.py):
    from interfaces.kernel_adapter import KernelAdapter, get_kernel_adapter
    adapter = get_kernel_adapter()
    result = await adapter.submit(goal=..., mode=..., mission_id=...)

Callers receive an AdapterResult — they do NOT directly hold KernelRuntime
or BeaKernel objects.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

import structlog

log = structlog.get_logger("interfaces.kernel_adapter")


# ══════════════════════════════════════════════════════════════════════════════
# AdapterResult — external-facing result type (R8: API never touches internals)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class AdapterResult:
    """
    Result returned by KernelAdapter to external consumers.

    Decouples external callers from kernel.execution.contracts.ExecutionResult.
    The API layer uses this type — it never imports ExecutionResult directly.
    """
    mission_id: str
    status: str             # "done" | "failed" | "running" | "pending"
    output: str = ""
    error: Optional[str] = None
    duration_ms: float = 0.0
    metadata: dict = field(default_factory=dict)
    source: str = "kernel"  # "kernel" | "fallback" | "error"

    @property
    def ok(self) -> bool:
        return self.status in ("done", "running")

    def to_dict(self) -> dict:
        return {
            "mission_id": self.mission_id,
            "status": self.status,
            "output": self.output[:5000] if self.output else "",
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
            "metadata": self.metadata,
            "source": self.source,
        }


# ══════════════════════════════════════════════════════════════════════════════
# KernelAdapter
# ══════════════════════════════════════════════════════════════════════════════

class KernelAdapter:
    """
    Adapter: external consumers → kernel (R8).

    Responsibilities:
      - Create ExecutionRequest from raw inputs
      - Call kernel.execute()
      - Translate ExecutionResult → AdapterResult
      - Provide kernel status without exposing internals

    NOT responsible for:
      - Classification, planning, routing (kernel's job)
      - Policy decisions (kernel's job)
      - Memory management (kernel's job)
    """

    def __init__(self) -> None:
        self._call_count = 0
        self._error_count = 0

    def _get_kernel(self):
        """Lazy kernel access — fail-open if unavailable."""
        try:
            from kernel.runtime.kernel import get_kernel
            return get_kernel()
        except Exception as _e:
            log.debug("kernel_adapter_get_kernel_failed", err=str(_e)[:80])
            return None

    async def submit(
        self,
        goal: str,
        mode: str = "auto",
        mission_id: Optional[str] = None,
        callback: Optional[Callable] = None,
        metadata: Optional[dict] = None,
    ) -> AdapterResult:
        """
        Submit a goal to the kernel for execution.

        Returns AdapterResult. Never raises — all errors are captured in result.error.
        """
        _mid = mission_id or f"adp-{uuid.uuid4().hex[:8]}"
        _t0 = time.time()
        self._call_count += 1

        _kernel = self._get_kernel()
        if _kernel is None:
            self._error_count += 1
            return AdapterResult(
                mission_id=_mid,
                status="failed",
                error="Kernel unavailable",
                duration_ms=round((time.time() - _t0) * 1000, 2),
                source="error",
            )

        try:
            from kernel.execution.contracts import ExecutionRequest
            req = ExecutionRequest(
                goal=goal,
                mission_id=_mid,
                mode=mode,
                callback=callback,
                metadata=metadata or {},
            )
            exec_result = await _kernel.execute(req)

            return AdapterResult(
                mission_id=_mid,
                status=exec_result.status.value.lower(),
                output=exec_result.result or "",
                error=exec_result.error,
                duration_ms=round((time.time() - _t0) * 1000, 2),
                metadata=exec_result.metadata,
                source="kernel",
            )
        except Exception as e:
            self._error_count += 1
            log.warning("kernel_adapter_submit_error", mid=_mid, err=str(e)[:120])
            return AdapterResult(
                mission_id=_mid,
                status="failed",
                error=str(e)[:200],
                duration_ms=round((time.time() - _t0) * 1000, 2),
                source="error",
            )

    def status(self) -> dict:
        """Return adapter health without exposing kernel internals."""
        _kernel = self._get_kernel()
        _kernel_ok = _kernel is not None
        return {
            "adapter": "KernelAdapter",
            "kernel_available": _kernel_ok,
            "calls_total": self._call_count,
            "errors_total": self._error_count,
            "error_rate": round(self._error_count / max(self._call_count, 1), 3),
        }


# ══════════════════════════════════════════════════════════════════════════════
# Module-level singleton
# ══════════════════════════════════════════════════════════════════════════════

_adapter: Optional[KernelAdapter] = None


def get_kernel_adapter() -> KernelAdapter:
    """Return the module-level KernelAdapter singleton."""
    global _adapter
    if _adapter is None:
        _adapter = KernelAdapter()
    return _adapter
