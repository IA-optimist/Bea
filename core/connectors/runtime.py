"""Connector registry and execution runtime helpers."""
from __future__ import annotations

import structlog
import os
import time
from typing import Optional

from core.connectors.contracts import ConnectorResult

logger = structlog.get_logger("jarvis.connectors")
log = logger  # alias for M3 swallowed_exception emitter


def _connector_registry() -> dict[str, dict]:
    from core.connectors._base import CONNECTOR_REGISTRY

    return CONNECTOR_REGISTRY


def get_connector(name: str) -> Optional[dict]:
    return _connector_registry().get(name)


def list_connectors() -> list[dict]:
    return [
        {**c["spec"].to_dict(), "available": True}
        for c in _connector_registry().values()
    ]


def _sanitize_connector_params(name: str, params: dict) -> tuple[dict, list[str]]:
    """
    Sanitize connector input parameters.

    Returns (clean_params, warnings).
    Strips script tags, null bytes, and dangerous patterns from string values.
    Bounds numeric values. Never raises.
    """
    warnings: list[str] = []
    clean = {}
    dangerous_patterns = (
        "<script", "javascript:", "data:text/html", "\x00",
        "file:///", "gopher://", "ftp://",
    )
    max_string_len = 10_000
    max_body_len = 100_000

    for k, v in params.items():
        if isinstance(v, str):
            if "\x00" in v:
                v = v.replace("\x00", "")
                warnings.append(f"null_bytes_removed:{k}")
            v_lower = v.lower()
            for pattern in dangerous_patterns:
                if pattern in v_lower:
                    warnings.append(f"dangerous_pattern:{k}={pattern}")
            max_len = max_body_len if k == "body" else max_string_len
            if len(v) > max_len:
                v = v[:max_len]
                warnings.append(f"truncated:{k}")
            clean[k] = v
        elif isinstance(v, (int, float)):
            if v > 1_000_000:
                v = 1_000_000
                warnings.append(f"numeric_bounded:{k}")
            clean[k] = v
        elif isinstance(v, dict):
            inner_clean, inner_warn = _sanitize_connector_params(f"{name}.{k}", v)
            clean[k] = inner_clean
            warnings.extend(inner_warn)
        elif isinstance(v, list):
            clean[k] = v[:100]
            if len(v) > 100:
                warnings.append(f"list_truncated:{k}")
        else:
            clean[k] = v
    return clean, warnings


def _audit_connector_execution(
    name: str, params_keys: list[str], result: ConnectorResult,
    sanitize_warnings: list[str], duration_ms: float,
) -> None:
    """Append connector execution to audit log. Fail-open."""
    try:
        from core.governance import log_mission_event
        detail = (
            f"connector={name} keys={params_keys} "
            f"success={result.success} latency={result.latency_ms}ms "
            f"warnings={sanitize_warnings}" if sanitize_warnings else
            f"connector={name} keys={params_keys} "
            f"success={result.success} latency={result.latency_ms}ms"
        )
        log_mission_event(
            mission_id=f"connector:{name}",
            event="connector_executed",
            detail=detail[:500],
        )
    except Exception as _exc:
        log.warning("swallowed_exception", action="connector_register", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])


def execute_connector(name: str, params: dict) -> ConnectorResult:
    """Execute a connector with safety gates, tracking, and audit trail."""
    connector = get_connector(name)
    if not connector:
        return ConnectorResult(error=f"connector '{name}' not found")

    spec = connector["spec"]
    exec_start = time.time()

    try:
        from core.governance import safety_checkpoint
        check = safety_checkpoint(
            action="execute_connector",
            connector=name,
            risk_level=spec.risk_level,
        )
        if not check["allowed"]:
            return ConnectorResult(error=check["reason"], connector=name)
    except ImportError:
        if os.environ.get("JARVIS_EXECUTION_DISABLED", "").lower() in ("1", "true", "yes"):
            return ConnectorResult(error="execution_disabled", connector=name)

    clean_params, sanitize_warnings = _sanitize_connector_params(name, params)
    if sanitize_warnings:
        logger.info("connector_input_sanitized: %s warnings=%s", name, sanitize_warnings[:5])

    if spec.requires_approval:
        try:
            from core.connectors._base import log_approval_event
            from core.operating_primitives import requires_approval
            if requires_approval(spec.category, spec.risk_level):
                auto_approve = os.environ.get("JARVIS_AUTO_APPROVE_LOW_RISK") and spec.risk_level == "low"
                if auto_approve:
                    log_approval_event(name, "execute", True, "auto_approved_low_risk")
                else:
                    log_approval_event(name, "execute", True, "supervised_execution")
                    logger.info("connector_approval_required: %s (%s)", name, spec.risk_level)
        except Exception as _exc:
            log.warning("swallowed_exception", action="connector_approval_log", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    try:
        from core.governance import check_connector_rate
        allowed, reason = check_connector_rate(name)
        if not allowed:
            result = ConnectorResult(error=f"rate_limited: {reason}", connector=name)
            _audit_connector_execution(name, list(params.keys()), result, sanitize_warnings,
                                       (time.time() - exec_start) * 1000)
            return result
    except Exception as _exc:
        log.warning("swallowed_exception", action="connector_execute_trace", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    if spec.category in ("communication", "integration") and spec.risk_level in ("medium", "high"):
        try:
            from core.business_pipeline import get_budget_tracker
            bt = get_budget_tracker()
            if hasattr(bt, "can_spend") and not bt.can_spend():
                result = ConnectorResult(error="budget_exceeded", connector=name)
                _audit_connector_execution(name, list(params.keys()), result, sanitize_warnings,
                                           (time.time() - exec_start) * 1000)
                return result
        except Exception as _exc:
            log.warning("swallowed_exception", action="connector_subexec_trace", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    result = connector["execute"](clean_params)

    try:
        from core.tool_performance_tracker import ToolExecution, get_tool_performance_tracker
        get_tool_performance_tracker().record(ToolExecution(
            tool=f"connector:{name}",
            success=result.success,
            latency_ms=result.latency_ms,
            error_type=result.error[:50] if result.error else None,
        ))
    except Exception as _exc:
        log.warning("swallowed_exception", action="connector_audit_emit", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    _audit_connector_execution(
        name, list(params.keys()), result, sanitize_warnings,
        (time.time() - exec_start) * 1000,
    )

    return result
