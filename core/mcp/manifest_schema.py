"""
core/mcp/manifest_schema.py — MCP Tool Manifest Schema

Schema for signed tool manifests that declare permissions, risk levels,
and metadata for MCP tools. This enables hot-loading and trust verification.

Manifest structure:
{
  "manifest_version": "1.0",
  "tool_id": "filesystem:read",
  "name": "Filesystem Read",
  "description": "Read file contents from local filesystem",
  "version": "1.0.0",
  "author": "Bea Team",
  "permissions": {
    "filesystem": {
      "scope": "read",
      "allowed_paths": ["workspace/**", "data/**"],
      "denied_paths": ["/etc/**", "/sys/**"]
    }
  },
  "risk_level": "low",
  "signature": "sha256:...",
  "requires_secrets": [],
  "requires_network": false
}
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class RiskLevel(str, Enum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PermissionScope(str, Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    NETWORK = "network"
    ADMIN = "admin"


@dataclass
class Permission:
    resource_type: str  # filesystem, network, system, api
    scope: PermissionScope
    allowed_patterns: List[str] = field(default_factory=list)
    denied_patterns: List[str] = field(default_factory=list)
    requires_approval: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource_type": self.resource_type,
            "scope": self.scope.value,
            "allowed_patterns": self.allowed_patterns,
            "denied_patterns": self.denied_patterns,
            "requires_approval": self.requires_approval,
        }


@dataclass
class ToolManifest:
    manifest_version: str = "1.0"
    tool_id: str = ""
    name: str = ""
    description: str = ""
    version: str = "1.0.0"
    author: str = ""
    permissions: List[Permission] = field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    requires_secrets: List[str] = field(default_factory=list)
    requires_network: bool = False
    requires_approval: bool = False
    dangerous_actions: List[str] = field(default_factory=list)
    signature: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "manifest_version": self.manifest_version,
            "tool_id": self.tool_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "permissions": [p.to_dict() for p in self.permissions],
            "risk_level": self.risk_level.value,
            "requires_secrets": self.requires_secrets,
            "requires_network": self.requires_network,
            "requires_approval": self.requires_approval,
            "dangerous_actions": self.dangerous_actions,
            "signature": self.signature,
            "created_at": self.created_at,
        }

    def compute_signature(self, private_key: Optional[str] = None) -> str:
        """Compute HMAC-SHA256 signature of manifest content (signature excluded).

        Requires ``MCP_SIGNING_SECRET`` environment variable or an explicit key.
        """
        key = private_key or os.environ.get("MCP_SIGNING_SECRET", "")
        if not key:
            raise RuntimeError(
                "Manifest signing requires MCP_SIGNING_SECRET environment variable"
            )
        data = self.to_dict()
        data.pop("signature", None)
        payload = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        sig = hmac.new(key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return "hmac-sha256:" + sig

    def sign(self, private_key: Optional[str] = None) -> str:
        """Sign the manifest and set the signature field."""
        self.signature = self.compute_signature(private_key)
        return self.signature

    def verify_signature(self, public_key: Optional[str] = None) -> bool:
        """Verify the manifest HMAC signature.

        Returns False if the signature is missing, malformed, or if no key is
        configured to verify it.
        """
        if not self.signature:
            return False
        if not self.signature.startswith("hmac-sha256:"):
            return False
        key = public_key or os.environ.get("MCP_SIGNING_SECRET", "")
        if not key:
            return False
        expected = self.compute_signature(key)
        return hmac.compare_digest(self.signature, expected)

    def to_json(self) -> str:
        """Export manifest as JSON string."""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolManifest":
        """Create manifest from dictionary."""
        permissions = []
        for p_data in data.get("permissions", []):
            permissions.append(Permission(
                resource_type=p_data["resource_type"],
                scope=PermissionScope(p_data["scope"]),
                allowed_patterns=p_data.get("allowed_patterns", []),
                denied_patterns=p_data.get("denied_patterns", []),
                requires_approval=p_data.get("requires_approval", False),
            ))

        return cls(
            manifest_version=data.get("manifest_version", "1.0"),
            tool_id=data.get("tool_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            author=data.get("author", ""),
            permissions=permissions,
            risk_level=RiskLevel(data.get("risk_level", "low")),
            requires_secrets=data.get("requires_secrets", []),
            requires_network=data.get("requires_network", False),
            requires_approval=data.get("requires_approval", False),
            dangerous_actions=data.get("dangerous_actions", []),
            signature=data.get("signature", ""),
            created_at=data.get("created_at", datetime.utcnow().isoformat()),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "ToolManifest":
        """Create manifest from JSON string."""
        return cls.from_dict(json.loads(json_str))


def validate_manifest(manifest: ToolManifest) -> Dict[str, Any]:
    """Validate a tool manifest and return validation result."""
    issues = []

    if not manifest.tool_id:
        issues.append("tool_id is required")
    if not manifest.name:
        issues.append("name is required")
    if len(manifest.description) < 10:
        issues.append("description must be at least 10 characters")
    if not manifest.author:
        issues.append("author is required")
    if not manifest.permissions:
        issues.append("at least one permission is required")

    # Verify signature if present
    if manifest.signature and not manifest.verify_signature():
        issues.append("signature verification failed")

    # Check risk level consistency
    if manifest.risk_level == RiskLevel.SAFE and manifest.requires_approval:
        issues.append("SAFE tools should not require approval")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
    }


# ── Pre-signed manifests for core tools ───────────────────────────────────────

CORE_TOOL_MANIFESTS: Dict[str, ToolManifest] = {
    "filesystem:read": ToolManifest(
        tool_id="filesystem:read",
        name="Filesystem Read",
        description="Read file contents from local filesystem within allowed paths",
        version="1.0.0",
        author="Bea Team",
        permissions=[
            Permission(
                resource_type="filesystem",
                scope=PermissionScope.READ,
                allowed_patterns=["workspace/**", "data/**", "config/**"],
                denied_patterns=["/etc/**", "/sys/**", "/proc/**"],
            )
        ],
        risk_level=RiskLevel.LOW,
        requires_network=False,
    ),

    "filesystem:write": ToolManifest(
        tool_id="filesystem:write",
        name="Filesystem Write",
        description="Write or modify files within allowed paths",
        version="1.0.0",
        author="Bea Team",
        permissions=[
            Permission(
                resource_type="filesystem",
                scope=PermissionScope.WRITE,
                allowed_patterns=["workspace/**", "data/**"],
                denied_patterns=["/etc/**", "/sys/**", "/proc/**", "*.exe", "*.dll"],
                requires_approval=True,
            )
        ],
        risk_level=RiskLevel.MEDIUM,
        requires_network=False,
        dangerous_actions=["overwrite_system_file", "delete_critical_file"],
    ),

    "shell:execute": ToolManifest(
        tool_id="shell:execute",
        name="Shell Execute",
        description="Execute a small set of read-only git and test commands",
        version="1.0.0",
        author="Bea Team",
        permissions=[
            Permission(
                resource_type="system",
                scope=PermissionScope.EXECUTE,
                allowed_patterns=[
                    "git status *",
                    "git diff *",
                    "git log *",
                    "python -m pytest *",
                ],
                denied_patterns=[
                    "rm *",
                    "sudo *",
                    "chmod 777 *",
                    "eval *",
                    "exec *",
                    "curl *",
                    "wget *",
                    "bash *",
                    "sh *",
                    ">*",
                    "|*",
                ],
                requires_approval=True,
            )
        ],
        risk_level=RiskLevel.HIGH,
        requires_network=False,
        dangerous_actions=["destructive_command", "privilege_escalation"],
    ),

    "network:http": ToolManifest(
        tool_id="network:http",
        name="HTTP Request",
        description="Make HTTP requests to explicitly allowed external services",
        version="1.0.0",
        author="Bea Team",
        permissions=[
            Permission(
                resource_type="network",
                scope=PermissionScope.NETWORK,
                allowed_patterns=["https://*.bea-project.dev/**"],
                denied_patterns=[
                    "http://127.",
                    "http://localhost",
                    "http://10.",
                    "http://192.168.",
                    "http://172.16.",
                    "http://172.17.",
                    "http://172.18.",
                    "http://172.19.",
                    "http://172.20.",
                    "http://172.21.",
                    "http://172.22.",
                    "http://172.23.",
                    "http://172.24.",
                    "http://172.25.",
                    "http://172.26.",
                    "http://172.27.",
                    "http://172.28.",
                    "http://172.29.",
                    "http://172.30.",
                    "http://172.31.",
                    "http://169.254.",
                    "http://metadata",
                ],
            )
        ],
        risk_level=RiskLevel.MEDIUM,
        requires_network=True,
        requires_approval=True,
    ),

    "memory:search": ToolManifest(
        tool_id="memory:search",
        name="Memory Search",
        description="Search vector memory for relevant context",
        version="1.0.0",
        author="Bea Team",
        permissions=[
            Permission(
                resource_type="api",
                scope=PermissionScope.READ,
                allowed_patterns=["memory/**"],
            )
        ],
        risk_level=RiskLevel.LOW,
        requires_network=False,
    ),

    "mission:run": ToolManifest(
        tool_id="mission:run",
        name="Run Mission",
        description="Submit and execute a Bea mission",
        version="1.0.0",
        author="Bea Team",
        permissions=[
            Permission(
                resource_type="api",
                scope=PermissionScope.WRITE,
                allowed_patterns=["mission/**"],
                requires_approval=True,
            )
        ],
        risk_level=RiskLevel.HIGH,
        requires_network=False,
        dangerous_actions=["destructive_mission", "payment_mission"],
    ),
}
