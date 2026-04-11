"""
core/tools_operational/tool_executor.py — Execute external operational tools.

Responsible for:
  - Approval gating
  - Input validation
  - Execution with timeout and retry
  - Result capture and artifact storage
  - Simulation mode
  - Cognitive event emission

Safety: all executions are logged, approval-gated tools NEVER bypass.
"""
from __future__ import annotations

import json
import os
import time
import uuid
import structlog
import urllib.request
import urllib.error
from pathlib import Path

from core.tools_operational.tool_schema import (
    OperationalTool, ToolExecutionResult, ApprovalDecision,
)
from core.tools_operational.tool_registry import get_tool_registry
from core.tools_operational.tool_readiness import check_readiness

log = structlog.get_logger("tools_operational.executor")

_WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", "workspace"))
_EXEC_DIR = _WORKSPACE / "tool_executions"


class OperationalToolExecutor:
    """Execute external tools with safety guards."""

    def __init__(self):
        self._approval_store: dict[str, ApprovalDecision] = {}

    def execute(
        self,
        tool_id: str,
        inputs: dict,
        mission_id: str = "",
        simulate: bool = False,
        approval_override: bool = False,
    ) -> ToolExecutionResult:
        """
        Execute an operational tool.

        Args:
            tool_id: Tool to execute
            inputs: Tool input payload
            mission_id: Associated mission
            simulate: If True, validate but don't execute
            approval_override: Pre-approved (bypasses approval gate)
        """
        tool = get_tool_registry().get(tool_id)
        if not tool:
            return ToolExecutionResult(
                tool_id=tool_id, ok=False, error=f"Unknown tool: {tool_id}"
            )

        # Validate inputs
        validation = self._validate_inputs(tool, inputs)
        if not validation["valid"]:
            return ToolExecutionResult(
                tool_id=tool_id, ok=False, error=validation["error"]
            )

        # Approval gate — ALWAYS checked before readiness or execution
        if tool.requires_approval and not approval_override and not simulate:
            self._emit_event(tool, mission_id, "approval_required")
            return ToolExecutionResult(
                tool_id=tool_id, ok=False, approved=False,
                error="Approval required. Use approval_override=True or approve via API."
            )

        # Simulation mode — returns early, no readiness check needed
        if simulate:
            return ToolExecutionResult(
                tool_id=tool_id, ok=True, simulated=True,
                response={"simulation": True, "tool": tool.name, "inputs_valid": True},
            )

        # Check readiness — only for actual execution
        readiness = check_readiness(tool_id)
        if not readiness.get("ready"):
            return ToolExecutionResult(
                tool_id=tool_id, ok=False,
                error=f"Tool not ready: {readiness.get('missing_secrets', [])} {readiness.get('missing_configs', [])}"
            )

        # Execute
        t0 = time.time()
        self._emit_event(tool, mission_id, "executing")

        result = self._dispatch(tool, inputs)
        result.duration_ms = round((time.time() - t0) * 1000)

        # Retry logic
        if not result.ok and tool.retry_policy.enabled:
            for attempt in range(1, tool.retry_policy.max_retries + 1):
                if result.status_code not in tool.retry_policy.retry_on_status:
                    break
                time.sleep(min(tool.retry_policy.backoff_seconds * attempt, 30))
                result = self._dispatch(tool, inputs)
                result.attempt = attempt + 1
                result.duration_ms = round((time.time() - t0) * 1000)
                if result.ok:
                    break

        # Store execution artifact
        artifact_path = self._store_artifact(tool, inputs, result, mission_id)

        # Emit completion event
        status = "completed" if result.ok else "failed"
        self._emit_event(tool, mission_id, status,
                        duration_ms=result.duration_ms, artifact=str(artifact_path))

        log.info("tool_execution", tool_id=tool_id, ok=result.ok,
                duration_ms=result.duration_ms, attempt=result.attempt)
        return result

    def simulate(self, tool_id: str, inputs: dict) -> ToolExecutionResult:
        """Simulate execution without side effects."""
        return self.execute(tool_id, inputs, simulate=True)

    def grant_approval(
        self, tool_id: str, reason: str = "", decided_by: str = "operator"
    ) -> ApprovalDecision:
        """Grant approval for a tool execution."""
        decision = ApprovalDecision(
            decision_id=f"approval-{uuid.uuid4().hex[:8]}",
            target_type="tool",
            target_id=tool_id,
            approved=True,
            reason=reason,
            decided_by=decided_by,
            timestamp=time.time(),
        )
        self._approval_store[tool_id] = decision
        return decision

    def _validate_inputs(self, tool: OperationalTool, inputs: dict) -> dict:
        """Validate inputs against tool schema."""
        schema = tool.input_schema
        if not schema:
            return {"valid": True}

        required = schema.get("required", [])
        missing = [r for r in required if r not in inputs]
        if missing:
            return {"valid": False, "error": f"Missing required inputs: {', '.join(missing)}"}

        # Type checking for known properties
        props = schema.get("properties", {})
        errors = []
        for key, spec in props.items():
            if key not in inputs:
                continue
            expected_type = spec.get("type")
            val = inputs[key]
            if expected_type == "object" and not isinstance(val, dict):
                errors.append(f"{key} must be object")
            elif expected_type == "string" and not isinstance(val, str):
                errors.append(f"{key} must be string")
            elif expected_type == "integer" and not isinstance(val, int):
                errors.append(f"{key} must be integer")

        if errors:
            return {"valid": False, "error": "; ".join(errors)}
        return {"valid": True}

    def _dispatch(self, tool: OperationalTool, inputs: dict) -> ToolExecutionResult:
        """Dispatch to tool-specific handler."""
        handler = f"_exec_{tool.id.replace('.', '_')}"
        fn = getattr(self, handler, None)
        if fn:
            return fn(tool, inputs)
        # Generic HTTP POST for webhook-type tools
        if tool.category in ("webhook", "automation"):
            return self._exec_http_post(tool, inputs)
        return ToolExecutionResult(
            tool_id=tool.id, ok=False,
            error=f"No handler for tool: {tool.id}"
        )

    # ── N8N handler ───────────────────────────────────────────

    def _exec_n8n_workflow_trigger(
        self, tool: OperationalTool, inputs: dict
    ) -> ToolExecutionResult:
        """Execute n8n webhook trigger."""
        url = inputs.get("webhook_url_override") or os.environ.get("N8N_WEBHOOK_URL", "")
        if not url:
            return ToolExecutionResult(
                tool_id=tool.id, ok=False,
                error="N8N_WEBHOOK_URL not configured"
            )

        payload = inputs.get("payload", {})
        return self._http_post(tool.id, url, payload, tool.timeout)

    # ── HTTP Webhook handler ──────────────────────────────────

    def _exec_http_webhook_post(
        self, tool: OperationalTool, inputs: dict
    ) -> ToolExecutionResult:
        """Execute generic HTTP webhook POST."""
        url = inputs.get("url", "")
        if not url:
            return ToolExecutionResult(
                tool_id=tool.id, ok=False, error="url is required"
            )
        payload = inputs.get("payload", {})
        headers = inputs.get("headers", {})
        return self._http_post(tool.id, url, payload, tool.timeout, headers)

    # ── Notification handler ──────────────────────────────────

    def _exec_notification_log(
        self, tool: OperationalTool, inputs: dict
    ) -> ToolExecutionResult:
        """Write notification to log file."""
        try:
            log_dir = _WORKSPACE / "notifications"
            log_dir.mkdir(parents=True, exist_ok=True)
            entry = {
                "title": inputs.get("title", ""),
                "message": inputs.get("message", ""),
                "level": inputs.get("level", "info"),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            path = log_dir / "notifications.jsonl"
            with open(path, "a") as f:
                f.write(json.dumps(entry) + "\n")
            return ToolExecutionResult(
                tool_id=tool.id, ok=True,
                response={"logged": True, "path": str(path)},
            )
        except Exception as e:
            return ToolExecutionResult(
                tool_id=tool.id, ok=False, error=str(e)[:200]
            )

    # ── HTTP POST helper ──────────────────────────────────────

    def _http_post(
        self, tool_id: str, url: str, payload: dict, timeout: int,
        extra_headers: dict | None = None,
    ) -> ToolExecutionResult:
        """Execute an HTTP POST request."""
        try:
            data = json.dumps(payload).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            if extra_headers:
                headers.update(extra_headers)
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")[:2000]
                return ToolExecutionResult(
                    tool_id=tool_id, ok=True,
                    status_code=resp.status,
                    response=body,
                )
        except urllib.error.HTTPError as e:
            return ToolExecutionResult(
                tool_id=tool_id, ok=False,
                status_code=e.code,
                error=f"HTTP {e.code}: {str(e)[:200]}",
            )
        except Exception as e:
            return ToolExecutionResult(
                tool_id=tool_id, ok=False,
                error=str(e)[:200],
            )

    # ── File workspace handler ─────────────────────────────────

    def _exec_file_workspace_write(
        self, tool: OperationalTool, inputs: dict
    ) -> ToolExecutionResult:
        """Write a file to the workspace directory."""
        try:
            rel_path = inputs.get("path", "")
            content = inputs.get("content", "")
            if not rel_path:
                return ToolExecutionResult(tool_id=tool.id, ok=False, error="path required")
            # Scope to workspace
            target = (_WORKSPACE / rel_path).resolve()
            if not str(target).startswith(str(_WORKSPACE.resolve())):
                return ToolExecutionResult(
                    tool_id=tool.id, ok=False, error="Path traversal blocked"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, "utf-8")
            return ToolExecutionResult(
                tool_id=tool.id, ok=True,
                response={"written": True, "path": str(target)},
            )
        except Exception as e:
            return ToolExecutionResult(tool_id=tool.id, ok=False, error=str(e)[:200])

    # ── Git status handler ────────────────────────────────────

    def _exec_git_status(
        self, tool: OperationalTool, inputs: dict
    ) -> ToolExecutionResult:
        """Run git status (read-only)."""
        import subprocess
        try:
            repo_path = inputs.get("path", ".")
            result = subprocess.run(
                ["git", "status", "--short"],
                capture_output=True, text=True, timeout=10, cwd=repo_path,
            )
            branch_result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True, text=True, timeout=5, cwd=repo_path,
            )
            return ToolExecutionResult(
                tool_id=tool.id, ok=True,
                response={
                    "status": result.stdout[:2000],
                    "branch": branch_result.stdout.strip(),
                },
            )
        except Exception as e:
            return ToolExecutionResult(tool_id=tool.id, ok=False, error=str(e)[:200])

    # ── Generic HTTP POST for webhook/automation ──────────────

    def _exec_http_post(
        self, tool: OperationalTool, inputs: dict
    ) -> ToolExecutionResult:
        """Generic POST handler for webhook/automation tools."""
        url = inputs.get("url", "")
        payload = inputs.get("payload", inputs)
        if not url:
            return ToolExecutionResult(
                tool_id=tool.id, ok=False, error="url required for generic POST"
            )
        return self._http_post(tool.id, url, payload, tool.timeout)

    # ── Artifact storage ──────────────────────────────────────

    def _store_artifact(
        self, tool: OperationalTool, inputs: dict, result: ToolExecutionResult,
        mission_id: str,
    ) -> Path:
        """Store execution result as artifact."""
        try:
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            artifact_dir = _EXEC_DIR / f"{tool.id.replace('.', '-')}-{timestamp}"
            artifact_dir.mkdir(parents=True, exist_ok=True)

            artifact = {
                "tool_id": tool.id,
                "tool_name": tool.name,
                "mission_id": mission_id,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "inputs": {k: str(v)[:500] for k, v in inputs.items()},
                "result": result.to_dict(),
                "risk_level": tool.risk_level,
                "approved": result.approved,
            }
            path = artifact_dir / "execution.json"
            path.write_text(json.dumps(artifact, indent=2, default=str), "utf-8")
            return path
        except Exception as e:
            log.debug("artifact_store_failed", err=str(e)[:80])
            return Path("")

    # ── Cognitive event emission ──────────────────────────────

    def _emit_event(self, tool: OperationalTool, mission_id: str,
                    status: str, **extra) -> None:
        """Emit cognitive event for tool execution (fail-open)."""
        try:
            from core.cognitive_events.emitter import emit
            from core.cognitive_events.types import EventType, EventSeverity
            sev = {
                "executing": EventSeverity.INFO,
                "completed": EventSeverity.INFO,
                "failed": EventSeverity.WARNING,
                "approval_required": EventSeverity.WARNING,
            }.get(status, EventSeverity.INFO)
            emit(
                EventType.TOOL_EXECUTION_COMPLETED if status == "completed"
                    else EventType.TOOL_EXECUTION_FAILED if status == "failed"
                    else EventType.TOOL_EXECUTION_REQUESTED,
                summary=f"Operational tool {tool.id}: {status}",
                source="tools_operational",
                mission_id=mission_id,
                severity=sev,
                payload={"tool_id": tool.id, "status": status,
                        "risk": tool.risk_level, **{k: str(v)[:200] for k, v in extra.items()}},
                tags=["operational_tool", tool.category],
            )
        except Exception:
            _silent_log.debug("suppressed_exception", src='tool_executor.py')


# ── Singleton ─────────────────────────────────────────────────

_executor: OperationalToolExecutor | None = None


def get_tool_executor() -> OperationalToolExecutor:
    global _executor
    if _executor is None:
        _executor = OperationalToolExecutor()
    return _executor
