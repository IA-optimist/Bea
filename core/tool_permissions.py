"""
BEA MAX — Per-Tool Permission System (P1)
================================================
Declarative per-tool approval gating based on risk classification.

Design:
  - Tools declare requires_approval: bool
  - Only destructive/external/high-risk tools are gated
  - Gated tools pause execution and create an approval request
  - Approved → resume. Denied → abort with safe error.
  - All approval payloads scrub secrets before display.

Integrates with:
  - ToolExecutor (pre-execution check)
  - ApprovalNotifier (push notification)
  - CognitiveBridge (decision confidence)
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

log = structlog.get_logger()

# Patterns that indicate secrets — scrubbed from approval payloads
_SECRET_PATTERNS = [
    re.compile(r"(?i)(password|passwd|secret|token|api.?key|auth.?key|bearer)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(sk-[a-zA-Z0-9]{20,})"),
    re.compile(r"(?i)(ghp_[a-zA-Z0-9]{36,})"),
    re.compile(r"[a-fA-F0-9]{40,}"),  # Long hex strings (likely tokens)
]


@dataclass
class ToolPermission:
    """Permission declaration for a tool."""
    tool_name: str
    requires_approval: bool = False
    risk_level: str = "low"        # none | low | medium | high | critical
    approval_reason: str = ""       # Why this needs approval
    max_auto_approvals: int = 0     # Auto-approve first N (for trusted contexts)
    auto_approval_count: int = 0

    def to_dict(self) -> dict:
        return {
            "tool": self.tool_name,
            "requires_approval": self.requires_approval,
            "risk_level": self.risk_level,
            "reason": self.approval_reason,
        }


@dataclass
class ApprovalRequest:
    """A pending tool execution approval."""
    request_id: str = ""
    tool_name: str = ""
    mission_id: str = ""
    agent_id: str = ""
    risk_level: str = "medium"
    reason: str = ""
    safe_params: Dict[str, Any] = field(default_factory=dict)  # Scrubbed
    status: str = "pending"        # pending | approved | denied | expired
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0
    decided_at: float = 0
    feedback: str = ""

    def __post_init__(self):
        if not self.expires_at:
            self.expires_at = self.created_at + 300  # 5 min default

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at and self.status == "pending"

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "tool": self.tool_name,
            "mission_id": self.mission_id,
            "agent": self.agent_id,
            "risk": self.risk_level,
            "reason": self.reason,
            "params": self.safe_params,
            "status": "expired" if self.is_expired else self.status,
            "created_at": self.created_at,
            "feedback": self.feedback,
        }


def scrub_secrets(params: Dict[str, Any]) -> Dict[str, Any]:
    """Remove secrets from tool parameters for safe display."""
    scrubbed = {}
    for key, value in params.items():
        # Keys that look like secrets
        key_lower = key.lower()
        if any(s in key_lower for s in ("secret", "password", "token", "key", "auth", "bearer", "credential")):
            scrubbed[key] = "***REDACTED***"
            continue
        # String values that match secret patterns
        if isinstance(value, str):
            val = value
            for pat in _SECRET_PATTERNS:
                val = pat.sub("***REDACTED***", val)
            # Truncate long strings
            scrubbed[key] = val[:200] if len(val) > 200 else val
        elif isinstance(value, dict):
            scrubbed[key] = scrub_secrets(value)
        elif isinstance(value, list):
            scrubbed[key] = [
                scrub_secrets(v) if isinstance(v, dict) else
                (str(v)[:100] if isinstance(v, str) and len(str(v)) > 100 else v)
                for v in value[:10]
            ]
        else:
            scrubbed[key] = value
    return scrubbed


# Default permission registry — only high-risk tools gated
_DEFAULT_GATED_TOOLS: Dict[str, ToolPermission] = {
    # Shell/code execution
    "shell_command": ToolPermission("shell_command", True, "high", "Arbitrary shell execution"),
    "execute_code": ToolPermission("execute_code", True, "high", "Code execution via DockerSandbox"),
    # Destructive file ops
    "file_delete_safe": ToolPermission("file_delete_safe", True, "medium", "File deletion"),
    "replace_in_file": ToolPermission("replace_in_file", True, "medium", "File modification"),
    # Git push (external side effect)
    "git_push": ToolPermission("git_push", True, "high", "Pushes code to remote"),
    "git_commit": ToolPermission("git_commit", True, "medium", "Creates git commit"),
    # Docker lifecycle
    "docker_restart": ToolPermission("docker_restart", True, "high", "Restarts running container"),
    "docker_compose_down": ToolPermission("docker_compose_down", True, "high", "Stops all containers"),
    "docker_compose_up": ToolPermission("docker_compose_up", True, "medium", "Starts containers"),
    "docker_compose_build": ToolPermission("docker_compose_build", True, "medium", "Builds Docker images"),
}

# Non-gated tools (read-only / safe)
_SAFE_TOOLS = {
    "http_get", "read_file", "vector_search", "search_in_files",
    "list_project_structure", "count_lines", "git_status", "git_diff",
    "git_log", "git_branch", "docker_ps", "docker_logs", "docker_inspect",
}


class ToolPermissionRegistry:
    """
    Registry of per-tool permission requirements.
    
    Integrated into ToolExecutor.execute() for pre-execution gating.
    """

    def __init__(self):
        self._permissions: Dict[str, ToolPermission] = dict(_DEFAULT_GATED_TOOLS)
        self._requests: Dict[str, ApprovalRequest] = {}
        self._lock = threading.RLock()

    def register(self, perm: ToolPermission) -> None:
        """Register or override a tool permission."""
        with self._lock:
            self._permissions[perm.tool_name] = perm

    def check(self, tool_name: str, params: Dict[str, Any] = None,
              mission_id: str = "", agent_id: str = "") -> Dict[str, Any]:
        """
        Check if tool execution requires approval.
        
        Returns:
          {"allowed": True} — proceed
          {"allowed": False, "request": ApprovalRequest} — needs approval
        """
        perm = self._permissions.get(tool_name)
        if perm is None or not perm.requires_approval:
            return {"allowed": True}

        # Create approval request
        req_id = f"apr-{int(time.time())}-{len(self._requests)}"
        safe_params = scrub_secrets(params or {})
        request = ApprovalRequest(
            request_id=req_id,
            tool_name=tool_name,
            mission_id=mission_id,
            agent_id=agent_id,
            risk_level=perm.risk_level,
            reason=perm.approval_reason,
            safe_params=safe_params,
        )
        with self._lock:
            self._requests[req_id] = request
        log.info("tool_permission.approval_required",
                tool=tool_name, request_id=req_id, risk=perm.risk_level)
        return {"allowed": False, "request": request}

    def approve(self, request_id: str, feedback: str = "") -> bool:
        """Approve a pending request."""
        with self._lock:
            req = self._requests.get(request_id)
            if not req or req.status != "pending" or req.is_expired:
                return False
            req.status = "approved"
            req.decided_at = time.time()
            req.feedback = feedback
            log.info("tool_permission.approved", request_id=request_id, tool=req.tool_name)
            return True

    def deny(self, request_id: str, feedback: str = "") -> bool:
        """Deny a pending request."""
        with self._lock:
            req = self._requests.get(request_id)
            if not req or req.status != "pending" or req.is_expired:
                return False
            req.status = "denied"
            req.decided_at = time.time()
            req.feedback = feedback
            log.info("tool_permission.denied", request_id=request_id, tool=req.tool_name)
            return True

    def get_request(self, request_id: str) -> Optional[ApprovalRequest]:
        return self._requests.get(request_id)

    def get_pending(self) -> List[ApprovalRequest]:
        """Get all pending (non-expired) requests."""
        with self._lock:
            return [r for r in self._requests.values()
                    if r.status == "pending" and not r.is_expired]

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent approval decisions."""
        with self._lock:
            sorted_reqs = sorted(self._requests.values(),
                                key=lambda r: r.created_at, reverse=True)
            return [r.to_dict() for r in sorted_reqs[:limit]]

    def get_permission(self, tool_name: str) -> Optional[ToolPermission]:
        return self._permissions.get(tool_name)

    def list_all(self) -> List[Dict[str, Any]]:
        """List all tool permissions."""
        return [p.to_dict() for p in sorted(self._permissions.values(),
                                            key=lambda p: p.tool_name)]

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            pending = sum(1 for r in self._requests.values()
                         if r.status == "pending" and not r.is_expired)
            approved = sum(1 for r in self._requests.values() if r.status == "approved")
            denied = sum(1 for r in self._requests.values() if r.status == "denied")
            return {
                "gated_tools": len(self._permissions),
                "pending_approvals": pending,
                "approved": approved,
                "denied": denied,
                "total_requests": len(self._requests),
            }


# Singleton
_registry: Optional[ToolPermissionRegistry] = None
_reg_lock = threading.Lock()


def get_tool_permissions() -> ToolPermissionRegistry:
    global _registry
    if _registry is None:
        with _reg_lock:
            if _registry is None:
                _registry = ToolPermissionRegistry()
    return _registry
