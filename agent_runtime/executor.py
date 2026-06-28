"""
agent_runtime/executor.py — ACIExecutor: the central ACI enforcement point.

Every agent action goes through execute().  The executor:
1. Checks the action is registered (deny-by-default).
2. Checks agent capabilities.
3. Checks path scope for file actions.
4. Checks risk level against policy.
5. Logs everything via structlog (no secrets).
6. Delegates to the registered handler (or sandbox for dangerous actions).
"""
from __future__ import annotations

import time

import structlog

from agent_runtime.actions import ActionRequest, ActionResult, ActionType
from agent_runtime.policy import (
    CommandPolicy,
    RiskLevel,
    ACTION_RISK,
    is_sensitive_path,
)
from agent_runtime.registry import ACIActionRegistry, get_default_registry

log = structlog.get_logger("bea.aci.executor")

# Actions that touch the filesystem via payload["path"] or payload["target"]
_PATH_ACTIONS = frozenset({
    ActionType.READ_FILE,
    ActionType.APPLY_PATCH,
    ActionType.WRITE_REPORT,
})


class ACIExecutor:
    """
    Stateless ACI enforcement layer.

    Usage:
        executor = ACIExecutor(registry, agent_capabilities={"read", "write"})
        result = executor.execute(request, policy)
    """

    def __init__(
        self,
        registry: ACIActionRegistry | None = None,
        agent_capabilities: set[str] | None = None,
    ):
        self._registry = registry or get_default_registry()
        self._capabilities: set[str] = agent_capabilities or set()

    def execute(self, request: ActionRequest, policy: CommandPolicy) -> ActionResult:
        t0 = time.monotonic()
        _log = log.bind(
            action=request.action_type.value,
            mission_id=request.mission_id,
            agent_id=request.agent_id,
            realm=request.realm,
        )

        # 1. Check registered
        if not self._registry.is_registered(request.action_type):
            _log.warning("aci_action_unknown")
            return ActionResult.blocked(
                request.action_id,
                f"action '{request.action_type.value}' is not registered — deny-by-default",
            )

        # 2. Check policy allows this action
        if not policy.allows(request.action_type):
            _log.warning("aci_action_denied_by_policy")
            return ActionResult.blocked(
                request.action_id,
                f"action '{request.action_type.value}' denied by CommandPolicy",
            )

        # 3. Check agent capabilities
        allowed, reason = self._registry.check_capabilities(
            request.action_type, self._capabilities
        )
        if not allowed:
            _log.warning("aci_capability_missing", reason=reason)
            return ActionResult.blocked(request.action_id, f"capability check failed: {reason}")

        # 4. Path scope check for file-touching actions
        path = request.payload.get("path") or request.payload.get("target", "")
        if path and request.action_type in _PATH_ACTIONS:
            if is_sensitive_path(path) and not policy.path_allowed(path):
                _log.warning("aci_sensitive_path_blocked", path=path)
                return ActionResult.blocked(
                    request.action_id,
                    f"path '{path}' is in a sensitive area — explicit allow required",
                )
            if not policy.path_allowed(path) and request.action_type != ActionType.READ_FILE:
                _log.warning("aci_path_out_of_scope", path=path)
                return ActionResult.blocked(
                    request.action_id,
                    f"path '{path}' is outside allowed scope: {policy.allowed_paths}",
                )

        # 5. Risk level check
        risk = ACTION_RISK.get(request.action_type, RiskLevel.HIGH)
        if _risk_exceeds(risk, policy.require_approval_above_risk):
            _log.info("aci_approval_required", risk=risk.value)
            return ActionResult.approval_required(
                request.action_id,
                f"action risk '{risk.value}' exceeds threshold "
                f"'{policy.require_approval_above_risk.value}' — human approval required",
            )

        # 6. Execute
        reg = self._registry.get(request.action_type)
        assert reg is not None  # already checked above
        try:
            result = reg.handler(request)
        except Exception as exc:
            _log.exception("aci_handler_exception", error=str(exc)[:200])
            result = ActionResult.error_result(request.action_id, str(exc)[:200])

        duration_ms = int((time.monotonic() - t0) * 1000)
        result.duration_ms = duration_ms
        _log.info(
            "aci_action_executed",
            status=result.status,
            duration_ms=duration_ms,
            has_error=result.error is not None,
        )
        return result


_RISK_ORDER = [
    RiskLevel.SAFE,
    RiskLevel.LOW,
    RiskLevel.MEDIUM,
    RiskLevel.HIGH,
    RiskLevel.CRITICAL,
]


def _risk_exceeds(risk: RiskLevel, threshold: RiskLevel) -> bool:
    return _RISK_ORDER.index(risk) > _RISK_ORDER.index(threshold)
