"""Policy gate and delegate setup for supervised mission execution.

Extracted from ExecutionMixin._execute_supervised — policy-gate phase.
Handles: delegate selection, CapabilityDispatcher wiring, confidence policy
approval preservation, kernel policy check, SecurityLayer check, kernel
working memory write, and provider/safer-model ContextVar setup.

Returns (delegate, needs_approval, provider_token, safer_token).
"""
from __future__ import annotations

import structlog

from typing import Any

log = structlog.get_logger(__name__)


def setup_policy_and_delegate(
    goal: str,
    mid: str,
    mode: str,
    ctx,
    trace,
    risk: str,
    needs_approval: bool,
    force_approved: bool,
    use_budget: bool,
    cap_dispatcher: Any,
    v2: Any,
    bea: Any,
    s: Any,
) -> tuple[Any, bool, Any, Any]:
    """Set up execution delegate and evaluate all policy gates.

    Returns:
        (delegate, needs_approval, provider_token, safer_token)
        provider_token and safer_token are ContextVar tokens — reset them
        after execution via the respective reset() calls.
    """
    delegate = v2 if use_budget else bea

    # ── Wire CapabilityDispatcher onto delegate ────────────────────────────────
    if cap_dispatcher is not None:
        try:
            delegate.capability_dispatcher = cap_dispatcher
            log.debug("meta_orchestrator.capability_dispatcher_wired",
                      mission_id=mid, delegate=type(delegate).__name__)
        except Exception as _wex:
            log.warning("meta_orchestrator.capability_dispatcher_wire_failed",
                        mission_id=mid, err=str(_wex)[:60])

    # ── Preserve confidence_policy approval before classification re-read ──────
    _cp_approval_preserved = needs_approval
    needs_approval = (
        False if force_approved
        else ctx.metadata.get("classification", {}).get("needs_approval", False)
    )
    if _cp_approval_preserved and not force_approved:
        needs_approval = True

    # ── Kernel policy check ────────────────────────────────────────────────────
    try:
        from kernel.convergence.policy_bridge import check_action_kernel
        _k_decision = check_action_kernel(
            action_type="mission_execution",
            target=goal[:120],
            risk_level=risk,
            mode=mode,
        )
        ctx.metadata["kernel_policy"] = {
            "allowed": _k_decision.allowed,
            "requires_approval": _k_decision.requires_approval,
            "risk_level": (
                _k_decision.risk_level.value
                if hasattr(_k_decision.risk_level, "value")
                else str(_k_decision.risk_level)
            ),
            "reason": getattr(_k_decision, "reason", ""),
        }
        if not _k_decision.allowed:
            log.warning("kernel_policy_blocked", mission_id=mid,
                        reason=getattr(_k_decision, "reason", ""))
            if not force_approved:
                needs_approval = True
        elif _k_decision.requires_approval and not force_approved:
            needs_approval = True
        trace.record("policy", "kernel_evaluated",
                     allowed=_k_decision.allowed,
                     requires_approval=_k_decision.requires_approval,
                     risk=risk)
    except Exception as _kpol:
        log.debug("phase_failed", phase="kernel_policy", err=str(_kpol)[:80])

    # ── SecurityLayer business governance check ────────────────────────────────
    try:
        _task_type_sl = str(
            ctx.metadata.get("classification", {}).get("task_type", "") or ""
        )
        if hasattr(_task_type_sl, "value"):
            _task_type_sl = _task_type_sl.value
        _SL_ACTION_MAP = {
            "deployment":  "deployment",
            "improvement": "self_improvement",
        }
        _sl_action = _SL_ACTION_MAP.get(_task_type_sl, "mission_execution")
        from security import get_security_layer as _get_sl
        _sl_result = _get_sl().check_action(
            action_type=_sl_action,
            mission_id=mid,
            mode=mode,
            risk_level=risk,
            action_target=goal[:200],
        )
        ctx.metadata["security_layer"] = {
            "allowed":     _sl_result.allowed,
            "escalated":   _sl_result.escalated,
            "reason":      _sl_result.reason,
            "risk_level":  _sl_result.risk_level,
            "entry_id":    _sl_result.entry_id,
            "action_type": _sl_action,
        }
        if _sl_result.escalated and not force_approved:
            needs_approval = True
            log.info("security_layer_escalated",
                     mission_id=mid,
                     action_type=_sl_action,
                     reason=_sl_result.reason,
                     entry_id=_sl_result.entry_id)
        elif not _sl_result.allowed and not force_approved:
            needs_approval = True
            log.warning("security_layer_denied",
                        mission_id=mid,
                        action_type=_sl_action,
                        reason=_sl_result.reason)
        trace.record("policy", "security_layer_checked",
                     action_type=_sl_action,
                     allowed=_sl_result.allowed,
                     escalated=_sl_result.escalated,
                     entry_id=_sl_result.entry_id)
    except Exception as _sl_err:
        log.warning("phase_failed", phase="security_layer", err=str(_sl_err)[:80])
        ctx.metadata.setdefault("security_layer", {
            "skipped": True,
            "error": str(_sl_err)[:80],
            "allowed": None,
        })

    # ── Kernel working memory write ────────────────────────────────────────────
    try:
        from kernel.runtime.boot import get_runtime as _get_kernel_rt
        _krt = _get_kernel_rt()
        _krt.memory.write_working(
            key=f"mission:{mid}",
            content={
                "mission_id":     mid,
                "goal":           goal[:200],
                "mode":           mode,
                "risk":           risk,
                "needs_approval": needs_approval,
                "classification": ctx.metadata.get("classification", {}),
            },
            mission_id=mid,
            ttl=getattr(s, "mission_timeout_s", 600) + 60,
        )
        log.debug("kernel_working_memory_written", mission_id=mid)
    except Exception as _kkmem:
        log.debug("phase_failed", phase="kernel_working_memory",
                  err=str(_kkmem)[:80])

    # ── Provider override ContextVar (Phase 0c routing) ────────────────────────
    _phase0c_provider = (
        ctx.metadata.get("routed_provider", {}).get("provider_id", "")
    )
    _provider_token = None
    if _phase0c_provider:
        try:
            from core.llm_factory import _provider_override as _pov
            _provider_token = _pov.set(_phase0c_provider)
            log.info("phase0c_routing_active",
                     mission_id=mid, provider=_phase0c_provider)
        except Exception as _exc:
            log.warning("swallowed_exception", action="phase0c_routing_log",
                        exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # ── Safer model ContextVar (Pass 43) ──────────────────────────────────────
    _safer_token = None
    _cp_meta = ctx.metadata.get("confidence_policy", {})
    if _cp_meta.get("use_safer_model") and not force_approved:
        try:
            from core.llm_factory import _safer_model_active as _sma
            _safer_token = _sma.set(True)
            log.info("safer_model_activated",
                     mission_id=mid,
                     tier=_cp_meta.get("tier", "?"),
                     confidence=_cp_meta.get("confidence", "?"))
        except Exception as _sme:
            log.debug("safer_model_activation_failed", err=str(_sme)[:60])

    return delegate, needs_approval, _provider_token, _safer_token
