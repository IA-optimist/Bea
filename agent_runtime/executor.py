"""
agent_runtime/executor.py - ACIExecutor, the central ACI enforcement point.

Every agent action goes through execute(). The executor is deny-by-default,
capability-checked, realm/path scoped, risk gated, and audited with redacted
payload summaries.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import structlog

from agent_runtime.actions import ActionRequest, ActionResult, ActionType, redact_value
from agent_runtime.policy import ACTION_RISK, CommandPolicy, RiskLevel, is_sensitive_path
from agent_runtime.registry import ACIActionRegistry, get_default_registry

log = structlog.get_logger("bea.aci.executor")

_PATH_ACTIONS = frozenset({
    ActionType.READ_FILE,
    ActionType.APPLY_PATCH,
    ActionType.WRITE_REPORT,
})


class ACIExecutor:
    """Stateless ACI enforcement layer."""

    def __init__(
        self,
        registry: ACIActionRegistry | None = None,
        agent_capabilities: set[str] | None = None,
        audit_sink: list[dict[str, Any]] | None = None,
    ) -> None:
        self._registry = registry or get_default_registry()
        self._capabilities: set[str] = agent_capabilities or set()
        self._audit_sink = audit_sink

    def execute(self, request: ActionRequest, policy: CommandPolicy) -> ActionResult:
        t0 = time.monotonic()
        risk = ACTION_RISK.get(request.action_type, RiskLevel.HIGH)
        _log = log.bind(
            action=request.action_type.value,
            mission_id=request.mission_id,
            agent_id=request.agent_id,
            realm=request.realm,
        )

        def blocked(reason: str) -> ActionResult:
            _log.warning("aci_action_blocked", reason=reason[:200])
            result = ActionResult.blocked(request.action_id, reason)
            result.audit_ref = self._audit(request, allowed=False, reason=reason, risk=risk)
            return result

        if not self._registry.is_registered(request.action_type):
            return blocked(f"action '{request.action_type.value}' is not registered - deny-by-default")

        if not policy.allows(request.action_type):
            return blocked(f"action '{request.action_type.value}' denied by CommandPolicy")

        if not policy.realm_allowed(request.realm):
            return blocked(f"realm '{request.realm}' denied by CommandPolicy")

        allowed, reason = self._registry.check_capabilities(
            request.action_type, self._capabilities
        )
        if not allowed:
            return blocked(f"capability check failed: {reason}")

        path = request.payload.get("path") or request.payload.get("target", "")
        if path and request.action_type in _PATH_ACTIONS:
            if is_sensitive_path(path) and not policy.path_allowed(path):
                return blocked(f"path '{path}' is in a sensitive area - explicit allow required")
            if not policy.path_allowed(path) and request.action_type != ActionType.READ_FILE:
                return blocked(f"path '{path}' is outside allowed scope: {policy.allowed_paths}")

        if _risk_exceeds(risk, policy.require_approval_above_risk):
            approval_reason = (
                f"action risk '{risk.value}' exceeds threshold "
                f"'{policy.require_approval_above_risk.value}' - human approval required"
            )
            result = ActionResult.approval_required(request.action_id, approval_reason)
            result.audit_ref = self._audit(request, allowed=False, reason=approval_reason, risk=risk)
            return result

        reg = self._registry.get(request.action_type)
        assert reg is not None
        try:
            result = reg.handler(request)
        except Exception as exc:
            _log.exception("aci_handler_exception", error=str(exc)[:200])
            result = ActionResult.error_result(request.action_id, str(exc)[:200])

        result.duration_ms = int((time.monotonic() - t0) * 1000)
        _log.info(
            "aci_action_executed",
            status=result.status,
            duration_ms=result.duration_ms,
            has_error=result.error is not None,
        )
        result.audit_ref = self._audit(
            request,
            allowed=result.status == "success",
            reason=result.error or result.status,
            risk=risk,
        )
        return result

    def _audit(self, request: ActionRequest, *, allowed: bool, reason: str, risk: RiskLevel) -> str | None:
        if self._audit_sink is None:
            return None
        audit_ref = f"audit:{len(self._audit_sink)}"
        self._audit_sink.append({
            "audit_ref": audit_ref,
            "who": request.agent_id,
            "what": request.action_type.value,
            "mission_id": request.mission_id,
            "action": request.action_type.value,
            "allowed": allowed,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat(timespec="seconds"),
            "risk": risk.value,
            "payload_summary": str(redact_value(request.payload))[:1000],
        })
        return audit_ref


_RISK_ORDER = [
    RiskLevel.SAFE,
    RiskLevel.LOW,
    RiskLevel.MEDIUM,
    RiskLevel.HIGH,
    RiskLevel.CRITICAL,
]


def _risk_exceeds(risk: RiskLevel, threshold: RiskLevel) -> bool:
    return _RISK_ORDER.index(risk) > _RISK_ORDER.index(threshold)
