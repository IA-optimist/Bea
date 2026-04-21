"""
kernel/routing/router.py — Kernel Capability Router (Phase 6)
=============================================================
The kernel is the single entry point for ALL capability routing decisions.

ARCHITECTURE CONTRACT
---------------------
- MetaOrchestrator Phase 0c MUST call kernel.router.route(), never core.capability_routing
  directly.
- When core router is registered: kernel passes through its RoutingDecision objects
  unchanged (transparent), but monitors/logs at the kernel level.
- When no core router (standalone mode): kernel heuristic returns minimal-compatible
  objects with the same interface as RoutingDecision.

WHY TRANSPARENT PASSTHROUGH (not conversion)
---------------------------------------------
Phase 0c reads: d.success, d.selected_provider.provider_id,
d.selected_provider.to_dict(), d.score, d.candidates_evaluated, d.fallback_used.
Converting RoutingDecision → KernelRouteDecision loses this data and breaks the pipeline.
The kernel's value here is AUTHORITY (single call point) + MONITORING, not data transformation.

KERNEL RULE: Zero imports from core/, agents/, api/, tools/.
Registration:
  from kernel.routing.router import register_core_router
  from core.capability_routing.router import route_mission
  register_core_router(route_mission)

Future (Phase 7+): kernel may intercept decisions for policy gating,
capability arbitration, or model selection override before returning.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

try:
    import structlog
    _log = structlog.get_logger("kernel.routing")
except ImportError:
    import logging
    _log = logging.getLogger("kernel.routing")


# ── Registration slot ─────────────────────────────────────────────────────────
_core_router_fn: Optional[Callable[..., Any]] = None


def register_core_router(fn: Callable[..., Any]) -> None:
    """
    Register core.capability_routing.router.route_mission.
    Called at boot — kernel never imports core directly.

    The registered fn must accept:
      fn(goal: str, classification: dict | None, mode: str)
    and return a list of RoutingDecision objects (from core.capability_routing.spec).
    """
    global _core_router_fn
    _core_router_fn = fn
    _log.debug("kernel_router_registered")


# ── Heuristic-only data types ─────────────────────────────────────────────────
# Used ONLY when no core router is available (standalone/offline mode).
# Mirrors the RoutingDecision interface that Phase 0c reads.

@dataclass
class _KernelProviderSpec:
    """
    Minimal ProviderSpec-compatible object for the heuristic path.
    Implements the interface that Phase 0c reads from RoutingDecision.selected_provider.
    """
    provider_id:      str
    capability_id:    str
    provider_type:    str    = "llm"
    requires_approval: bool  = False
    readiness:        float  = 1.0
    reliability:      float  = 0.5

    def to_dict(self) -> dict:
        return {
            "provider_id":      self.provider_id,
            "capability_id":    self.capability_id,
            "provider_type":    self.provider_type,
            "requires_approval": self.requires_approval,
            "readiness":        self.readiness,
            "reliability":      self.reliability,
            "source":           "kernel_heuristic",
        }


@dataclass
class _KernelHeuristicDecision:
    """
    RoutingDecision-compatible object for the kernel heuristic path.
    Only returned when no core router is available.
    Implements the full interface that Phase 0c reads.
    """
    capability_id:       str
    _provider:           Optional[_KernelProviderSpec]  = None
    score:               float                           = 0.4
    reason:              str                             = ""
    fallback_used:       bool                            = True
    candidates_evaluated: int                            = 0

    @property
    def success(self) -> bool:
        return self._provider is not None

    @property
    def selected_provider(self) -> Optional[_KernelProviderSpec]:
        return self._provider

    def to_dict(self) -> dict:
        return {
            "capability_id":       self.capability_id,
            "selected":            self._provider.to_dict() if self._provider else None,
            "score":               round(self.score, 3),
            "reason":              self.reason,
            "fallback_used":       self.fallback_used,
            "candidates_evaluated": self.candidates_evaluated,
            "source":              "kernel_heuristic",
        }


# ── Heuristic routing tables ──────────────────────────────────────────────────
# Used ONLY when no core router is available. Kept minimal and explicit.
_TASK_CAPABILITIES: dict[str, list[str]] = {
    "query":          ["question_answering"],
    "analysis":       ["code_analysis", "data_analysis"],
    "implementation": ["code_generation", "code_editing"],
    "debugging":      ["code_analysis", "code_generation"],
    "deployment":     ["shell_execution"],
    "research":       ["web_search", "document_analysis"],
    "system_ops":     ["shell_execution"],
    "improvement":    ["code_analysis", "code_generation"],
    "workflow":       ["orchestration"],
    "business":       ["document_generation"],
    "other":          ["general"],
}

_DEFAULT_PROVIDERS: dict[str, tuple[str, str]] = {
    # capability_id → (provider_id, provider_type)
    "code_generation":    ("llm_primary", "llm"),
    "code_analysis":      ("llm_primary", "llm"),
    "code_editing":       ("llm_primary", "llm"),
    "question_answering": ("llm_primary", "llm"),
    "data_analysis":      ("llm_primary", "llm"),
    "document_analysis":  ("llm_primary", "llm"),
    "document_generation":("llm_primary", "llm"),
    "shell_execution":    ("local_shell", "tool"),
    "web_search":         ("search_tool", "tool"),
    "orchestration":      ("meta_orchestrator", "agent"),
    "general":            ("llm_primary", "llm"),
}


def _heuristic_route(
    goal: str,
    classification: dict | None = None,
    mode: str = "auto",
) -> list[_KernelHeuristicDecision]:
    """
    Kernel heuristic routing — used only when no core router is available.
    Returns RoutingDecision-compatible objects. Always returns at least one result.
    """
    task_type = "other"
    if classification:
        raw_type = classification.get("task_type", "other")
        task_type = raw_type.value if hasattr(raw_type, "value") else str(raw_type)

    capabilities = _TASK_CAPABILITIES.get(task_type, ["general"])
    decisions = []
    for cap in capabilities:
        pid, ptype = _DEFAULT_PROVIDERS.get(cap, ("llm_primary", "llm"))
        decisions.append(_KernelHeuristicDecision(
            capability_id=cap,
            _provider=_KernelProviderSpec(
                provider_id=pid,
                capability_id=cap,
                provider_type=ptype,
            ),
            score=0.4,
            reason=f"kernel_heuristic: task_type={task_type} → {cap}",
            fallback_used=True,
            candidates_evaluated=0,
        ))
    return decisions


# ── KernelCapabilityRouter ────────────────────────────────────────────────────

class KernelCapabilityRouter:
    """
    The kernel's single authority for capability routing.

    DESIGN:
    - When core router is registered: transparent passthrough.
      Returns core's RoutingDecision objects unchanged (interface-compatible).
      Kernel gains AUTHORITY (single call point) + MONITORING.
    - When no core router: kernel heuristic.
      Returns _KernelHeuristicDecision objects (same interface, lower confidence).

    Future extensions (Phase 7+):
    - Policy gating before routing
    - Capability arbitration (kernel overrides core selection)
    - Model selection based on kernel performance history
    - Routing budget enforcement
    """

    def route(
        self,
        goal: str,
        classification: dict | None = None,
        mode: str = "auto",
    ) -> list:
        """
        Route a mission. Never raises. Returns at least one decision.

        Returns:
          - list of RoutingDecision (from core) when core router available
          - list of _KernelHeuristicDecision when heuristic
          Both implement the same interface: .success, .selected_provider,
          .capability_id, .score, .candidates_evaluated, .fallback_used, .to_dict()
        """
        # 1 — Core router (registered at boot, authoritative provider registry)
        if _core_router_fn is not None:
            try:
                decisions = _core_router_fn(
                    goal=goal,
                    classification=classification,
                    mode=mode,
                )
                if decisions:
                    _log.debug(
                        "kernel_router_core_used",
                        count=len(decisions),
                        capabilities=[getattr(d, "capability_id", "?") for d in decisions],
                    )
                    return decisions
                _log.debug("kernel_router_core_empty_fallback")
            except Exception as exc:
                _log.warning(
                    "kernel_router_core_failed",
                    err=str(exc)[:120],
                )

        # 2 — Kernel heuristic (always available, lower confidence)
        _log.debug("kernel_router_heuristic_used", task_type=(
            (classification or {}).get("task_type", "unknown")
        ))
        return _heuristic_route(goal, classification, mode)


# ── Module-level singleton ────────────────────────────────────────────────────
_router: KernelCapabilityRouter | None = None


def get_router() -> KernelCapabilityRouter:
    """Return singleton KernelCapabilityRouter."""
    global _router
    if _router is None:
        _router = KernelCapabilityRouter()
    return _router
