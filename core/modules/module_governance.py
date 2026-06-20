"""
BEA MAX — Module Governance Layer
========================================
RBAC, audit, dependency validation, health checks, and wizard
for the Module Manager.

Sits between API routes and ModuleManager — enforces all governance
before any mutation reaches storage.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# RBAC
# ═══════════════════════════════════════════════════════════════

class ModuleRole:
    ADMIN = "admin"
    USER = "user"       # Paid standard user
    VIEWER = "viewer"

MODULE_PERMISSIONS = {
    "admin": {
        "agent": {"create", "update", "delete", "toggle", "duplicate", "list", "test", "export", "import"},
        "skill": {"create", "update", "delete", "toggle", "list", "test", "export", "import"},
        "mcp": {"create", "update", "delete", "toggle", "list", "test", "discover"},
        "connector": {"create", "update", "delete", "toggle", "list", "test", "rebind"},
        "catalog": {"list", "install", "preview"},
    },
    "user": {
        "agent": {"create", "update", "toggle", "list", "test"},
        "skill": {"list"},
        "mcp": {"list"},
        "connector": {"list", "test"},
        "catalog": {"list", "install", "preview"},
    },
    "viewer": {
        "agent": {"list"},
        "skill": {"list"},
        "mcp": {"list"},
        "connector": {"list"},
        "catalog": {"list", "preview"},
    },
}

# Actions that require admin approval regardless of role
HIGH_RISK_ACTIONS = {
    ("connector", "create", "payment"),      # Payment connectors
    ("connector", "create", "domain"),        # Domain connectors
    ("agent", "update", "link_payment"),      # Linking payment connector to agent
    ("mcp", "create", "untrusted"),           # Untrusted MCP server
}


def check_module_permission(role: str, module_type: str, action: str) -> bool:
    """Check if a role can perform an action on a module type."""
    perms = MODULE_PERMISSIONS.get(role, {})
    type_perms = perms.get(module_type, set())
    return action in type_perms


@dataclass
class RBACResult:
    allowed: bool
    needs_approval: bool = False
    reason: str = ""

    def to_dict(self) -> dict:
        return {"allowed": self.allowed, "approval": self.needs_approval, "reason": self.reason}


def check_rbac(
    role: str,
    module_type: str,
    action: str,
    risk_context: str = "",
) -> RBACResult:
    """Full RBAC check with high-risk detection."""
    if not check_module_permission(role, module_type, action):
        return RBACResult(False, reason=f"Role '{role}' cannot '{action}' on '{module_type}'")

    # High-risk check
    if (module_type, action, risk_context) in HIGH_RISK_ACTIONS:
        if role != "admin":
            return RBACResult(True, needs_approval=True, reason=f"High-risk: {risk_context} requires approval")

    return RBACResult(True, reason="allowed")


# ═══════════════════════════════════════════════════════════════
# MODULE AUDIT
# ═══════════════════════════════════════════════════════════════

@dataclass
class ModuleAuditEntry:
    timestamp: float
    actor: str
    role: str
    module_type: str     # agent / skill / mcp / connector
    module_id: str
    action: str          # create / update / delete / toggle / test / install
    source: str = ""     # web / mobile / api
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    result: str = "success"
    chain_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "ts": self.timestamp, "actor": self.actor, "role": self.role,
            "type": self.module_type, "id": self.module_id,
            "action": self.action, "source": self.source,
            "result": self.result,
            "before_summary": self._summarize(self.before),
            "after_summary": self._summarize(self.after),
            "chain": self.chain_hash[:16] if self.chain_hash else "",
        }

    @staticmethod
    def _summarize(d: dict) -> str:
        if not d:
            return ""
        keys = sorted(d.keys())[:5]
        return ", ".join(f"{k}={str(d[k])[:30]}" for k in keys)


class ModuleAuditLog:
    """Audit trail for all module changes."""

    def __init__(self, log_path: str | Path | None = None):
        self._entries: list[ModuleAuditEntry] = []
        self._last_hash = "MODULE_GENESIS"
        self._log_path = Path(log_path) if log_path else None

    def record(
        self,
        actor: str,
        role: str,
        module_type: str,
        module_id: str,
        action: str,
        source: str = "api",
        before: dict | None = None,
        after: dict | None = None,
        result: str = "success",
    ) -> ModuleAuditEntry:
        chain_input = f"{self._last_hash}|{time.time()}|{module_type}|{module_id}|{action}"
        chain_hash = hashlib.sha256(chain_input.encode()).hexdigest()

        entry = ModuleAuditEntry(
            timestamp=time.time(), actor=actor, role=role,
            module_type=module_type, module_id=module_id,
            action=action, source=source,
            before=before or {}, after=after or {},
            result=result, chain_hash=chain_hash,
        )
        self._entries.append(entry)
        self._last_hash = chain_hash

        if self._log_path:
            try:
                self._log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self._log_path, "a") as f:
                    f.write(json.dumps(entry.to_dict(), separators=(",", ":")) + "\n")
            except Exception as e:
                logger.error(f"Module audit persist failed: {e}")

        return entry

    def query(
        self,
        module_type: str | None = None,
        module_id: str | None = None,
        actor: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        results = []
        for e in reversed(self._entries):
            if module_type and e.module_type != module_type:
                continue
            if module_id and e.module_id != module_id:
                continue
            if actor and e.actor != actor:
                continue
            results.append(e.to_dict())
            if len(results) >= limit:
                break
        return results

    @property
    def entry_count(self) -> int:
        return len(self._entries)


# ═══════════════════════════════════════════════════════════════
# DEPENDENCY VALIDATION
# ═══════════════════════════════════════════════════════════════

@dataclass
class DependencyIssue:
    """A missing or broken dependency."""
    module_id: str
    module_type: str
    issue_type: str      # missing_secret / missing_connector / missing_skill / disabled_dep
    description: str
    fix_suggestion: str

    def to_dict(self) -> dict:
        return {
            "module": self.module_id, "type": self.module_type,
            "issue": self.issue_type, "description": self.description,
            "fix": self.fix_suggestion,
        }


class DependencyValidator:
    """Validates module dependencies are satisfied."""

    def __init__(self, module_manager=None, vault=None, identity_mgr=None):
        self._mgr = module_manager
        self._vault = vault
        self._identity_mgr = identity_mgr

    def validate_agent(self, agent_id: str) -> list[DependencyIssue]:
        """Check all dependencies for an agent."""
        issues = []
        if not self._mgr:
            return issues

        agent = self._mgr.get_agent(agent_id)
        if not agent:
            return [DependencyIssue(agent_id, "agent", "not_found", "Agent not found", "Check agent ID")]

        # Check linked connectors exist and are enabled
        for conn_id in agent.linked_connectors:
            conn = self._mgr.get_connector(conn_id)
            if not conn:
                issues.append(DependencyIssue(
                    agent_id, "agent", "missing_connector",
                    f"Connector '{conn_id}' not found",
                    f"Add connector '{conn_id}' or remove from agent config",
                ))
            elif conn.status != "enabled":
                issues.append(DependencyIssue(
                    agent_id, "agent", "disabled_dep",
                    f"Connector '{conn.display_name}' is disabled",
                    f"Enable connector '{conn_id}'",
                ))

        # Check linked skills exist and are enabled
        for skill_id in agent.linked_skills:
            skill = self._mgr.get_skill(skill_id)
            if not skill:
                issues.append(DependencyIssue(
                    agent_id, "agent", "missing_skill",
                    f"Skill '{skill_id}' not found",
                    f"Add skill '{skill_id}' or remove from agent config",
                ))
            elif skill.status != "enabled":
                issues.append(DependencyIssue(
                    agent_id, "agent", "disabled_dep",
                    f"Skill '{skill.name}' is disabled",
                    f"Enable skill '{skill_id}'",
                ))

        # Check linked secrets exist in vault
        if self._vault:
            for secret_id in agent.linked_secrets:
                meta = self._vault.get_metadata(secret_id)
                if not meta:
                    issues.append(DependencyIssue(
                        agent_id, "agent", "missing_secret",
                        f"Secret '{secret_id}' not found in vault",
                        "Add the required secret to the vault",
                    ))
                elif meta.revoked:
                    issues.append(DependencyIssue(
                        agent_id, "agent", "missing_secret",
                        f"Secret '{secret_id}' has been revoked",
                        "Replace the revoked secret with a new one",
                    ))

        return issues

    def validate_connector(self, conn_id: str) -> list[DependencyIssue]:
        """Check connector dependencies."""
        issues = []
        if not self._mgr:
            return issues

        conn = self._mgr.get_connector(conn_id)
        if not conn:
            return [DependencyIssue(conn_id, "connector", "not_found", "Connector not found", "Check ID")]

        # Check linked identity
        if conn.linked_identity and self._identity_mgr:
            identity = self._identity_mgr.get_identity(conn.linked_identity)
            if not identity:
                issues.append(DependencyIssue(
                    conn_id, "connector", "missing_identity",
                    f"Identity '{conn.linked_identity}' not found",
                    "Create the identity or update connector binding",
                ))
            elif not identity.is_active:
                issues.append(DependencyIssue(
                    conn_id, "connector", "disabled_dep",
                    f"Identity '{conn.linked_identity}' is not active",
                    "Reactivate or replace the identity",
                ))

        # Check linked secrets
        if self._vault:
            for secret_id in conn.linked_secrets:
                meta = self._vault.get_metadata(secret_id)
                if not meta:
                    issues.append(DependencyIssue(
                        conn_id, "connector", "missing_secret",
                        f"Secret '{secret_id}' not found",
                        "Add the required secret to the vault",
                    ))

        return issues

    def validate_all(self) -> dict:
        """Validate all modules and return summary."""
        if not self._mgr:
            return {"agents": [], "connectors": [], "total_issues": 0}

        agent_issues = []
        for agent in self._mgr.list_agents():
            issues = self.validate_agent(agent["id"])
            if issues:
                agent_issues.append({
                    "agent_id": agent["id"],
                    "agent_name": agent.get("name", ""),
                    "issues": [i.to_dict() for i in issues],
                })

        conn_issues = []
        for conn in self._mgr.list_connectors():
            issues = self.validate_connector(conn["id"])
            if issues:
                conn_issues.append({
                    "connector_id": conn["id"],
                    "connector_name": conn.get("name", ""),
                    "issues": [i.to_dict() for i in issues],
                })

        total = sum(len(a["issues"]) for a in agent_issues) + sum(len(c["issues"]) for c in conn_issues)

        return {
            "agents": agent_issues,
            "connectors": conn_issues,
            "total_issues": total,
        }


# ═══════════════════════════════════════════════════════════════
# CONNECTOR HEALTH ENGINE
# ═══════════════════════════════════════════════════════════════

@dataclass
class HealthStatus:
    """Human-readable health status."""
    status: str          # ready / needs_setup / disabled / error / testing / connected / missing_permissions
    label: str           # User-facing label
    details: str = ""
    last_test_at: float | None = None
    latency_ms: float | None = None

    def to_dict(self) -> dict:
        return {
            "status": self.status, "label": self.label,
            "details": self.details,
            "last_test": self.last_test_at,
            "latency_ms": self.latency_ms,
        }

# Status labels — user-friendly
STATUS_LABELS = {
    "ready": "Ready",
    "needs_setup": "Needs setup",
    "disabled": "Disabled",
    "error": "Error",
    "testing": "Testing...",
    "connected": "Connected",
    "missing_permissions": "Missing permissions",
    "no_secret": "Secret not configured",  # nosec B105  # pragma: allowlist secret
    "rate_limited": "Rate limit reached",
    "unreachable": "Service unreachable",
    "invalid_token": "Token is invalid",  # nosec B105 — error message dict value
}


class HealthEngine:
    """Computes health status for all module types."""

    def __init__(self, module_manager=None, validator: DependencyValidator | None = None):
        self._mgr = module_manager
        self._validator = validator

    def connector_health(self, conn_id: str) -> HealthStatus:
        """Compute health for a connector."""
        if not self._mgr:
            return HealthStatus("error", "System error", "Module manager not available")

        conn = self._mgr.get_connector(conn_id)
        if not conn:
            return HealthStatus("error", "Error", "Connector not found")

        if conn.status == "disabled":
            return HealthStatus("disabled", "Disabled")

        if not conn.linked_identity and not conn.linked_secrets:
            return HealthStatus("needs_setup", "Needs setup", "No credentials configured")

        if conn.last_test == "pass":
            return HealthStatus("connected", "Connected",
                                last_test_at=conn.last_sync)

        if conn.last_test == "no_credentials":
            return HealthStatus("no_secret", "Secret not configured")

        if conn.last_test == "fail":
            return HealthStatus("error", "Error", "Last test failed")

        return HealthStatus("needs_setup", "Needs setup", "Not yet tested")

    def mcp_health(self, mcp_id: str) -> HealthStatus:
        """Compute health for an MCP server."""
        if not self._mgr:
            return HealthStatus("error", "System error")

        mcp = self._mgr.get_mcp(mcp_id)
        if not mcp:
            return HealthStatus("error", "Error", "MCP not found")

        if mcp.status == "disabled":
            return HealthStatus("disabled", "Disabled")

        if not mcp.endpoint:
            return HealthStatus("needs_setup", "Needs setup", "No endpoint configured")

        if mcp.last_test_status == "pass":
            tools = len(mcp.discovered_tools)
            return HealthStatus("connected", "Connected",
                                f"{tools} tools discovered",
                                last_test_at=mcp.last_test_at)

        if mcp.last_test_status == "fail":
            return HealthStatus("error", "Error", "Connection failed")

        return HealthStatus("needs_setup", "Needs setup", "Not yet tested")

    def agent_health(self, agent_id: str) -> HealthStatus:
        """Compute health for an agent."""
        if not self._mgr:
            return HealthStatus("error", "System error")

        agent = self._mgr.get_agent(agent_id)
        if not agent:
            return HealthStatus("error", "Error", "Agent not found")

        if agent.status == "disabled":
            return HealthStatus("disabled", "Disabled")

        # Check dependencies
        if self._validator:
            issues = self._validator.validate_agent(agent_id)
            if issues:
                return HealthStatus("error", "Error",
                                    f"{len(issues)} dependency issue(s): {issues[0].description}")

        if not agent.model:
            return HealthStatus("needs_setup", "Needs setup", "No model assigned")

        return HealthStatus("ready", "Ready")

    def full_health(self) -> dict:
        """Comprehensive health overview."""
        if not self._mgr:
            return {}

        summary = {
            "connectors": {"total": 0, "connected": 0, "failing": 0, "disabled": 0},
            "mcp": {"total": 0, "connected": 0, "failing": 0, "disabled": 0, "zero_tools": 0},
            "agents": {"total": 0, "ready": 0, "broken": 0, "disabled": 0},
            "skills": {"total": 0, "enabled": 0, "orphaned": 0},
        }

        # Connectors
        for conn in self._mgr.list_connectors():
            summary["connectors"]["total"] += 1
            h = self.connector_health(conn["id"])
            if h.status == "connected":
                summary["connectors"]["connected"] += 1
            elif h.status == "disabled":
                summary["connectors"]["disabled"] += 1
            elif h.status in ("error", "no_secret", "unreachable"):
                summary["connectors"]["failing"] += 1

        # MCP
        for mcp in self._mgr.list_mcp():
            summary["mcp"]["total"] += 1
            h = self.mcp_health(mcp["id"])
            if h.status == "connected":
                summary["mcp"]["connected"] += 1
            elif h.status == "disabled":
                summary["mcp"]["disabled"] += 1
            elif h.status == "error":
                summary["mcp"]["failing"] += 1
            mcp_obj = self._mgr.get_mcp(mcp["id"])
            if mcp_obj and not mcp_obj.discovered_tools:
                summary["mcp"]["zero_tools"] += 1

        # Agents
        all_linked_skills = set()
        for agent_d in self._mgr.list_agents():
            summary["agents"]["total"] += 1
            h = self.agent_health(agent_d["id"])
            if h.status == "ready":
                summary["agents"]["ready"] += 1
            elif h.status == "disabled":
                summary["agents"]["disabled"] += 1
            elif h.status == "error":
                summary["agents"]["broken"] += 1
            agent_obj = self._mgr.get_agent(agent_d["id"])
            if agent_obj:
                all_linked_skills.update(agent_obj.linked_skills)

        # Skills
        for skill_d in self._mgr.list_skills():
            summary["skills"]["total"] += 1
            skill = self._mgr.get_skill(skill_d["id"])
            if skill and skill.status == "enabled":
                summary["skills"]["enabled"] += 1
            if skill_d["id"] not in all_linked_skills:
                summary["skills"]["orphaned"] += 1

        return summary


# ═══════════════════════════════════════════════════════════════
# AGENT CREATION WIZARD
# ═══════════════════════════════════════════════════════════════

@dataclass
class WizardStep:
    """A single step in the agent creation wizard."""
    step: int
    title: str
    description: str
    field: str
    field_type: str          # text / choice / multi_choice / radio
    options: list[dict] = field(default_factory=list)
    required: bool = True

    def to_dict(self) -> dict:
        return {
            "step": self.step, "title": self.title,
            "description": self.description,
            "field": self.field, "type": self.field_type,
            "options": self.options, "required": self.required,
        }


def get_wizard_steps() -> list[dict]:
    """Return the agent creation wizard steps."""
    return [
        WizardStep(
            1, "What should this agent do?",
            "Describe the agent's purpose in plain language.",
            "purpose", "text",
            options=[
                {"label": "Find leads", "value": "Find and qualify sales leads"},
                {"label": "Reply to customers", "value": "Handle customer support inquiries"},
                {"label": "Research competitors", "value": "Research and analyze competitors"},
                {"label": "Deploy websites", "value": "Build and deploy web applications"},
                {"label": "Manage invoices", "value": "Handle invoicing and billing"},
            ],
        ).to_dict(),
        WizardStep(
            2, "Choose intelligence level",
            "Higher levels are more capable but cost more.",
            "model_tier", "radio",
            options=[
                {"label": "Fast & cheap", "value": "fast", "description": "Quick tasks, lower quality"},
                {"label": "Balanced", "value": "balanced", "description": "Good for most tasks"},
                {"label": "Premium", "value": "premium", "description": "Best quality, higher cost"},
                {"label": "Custom", "value": "custom", "description": "Choose a specific model"},
            ],
        ).to_dict(),
        WizardStep(
            3, "Choose allowed tools",
            "What capabilities should this agent have?",
            "tools", "multi_choice",
            options=[
                {"label": "🔍 Web Search", "value": "web_search"},
                {"label": "🌐 Browser", "value": "browser"},
                {"label": "📧 Email", "value": "email"},
                {"label": "📄 Documents", "value": "docs"},
                {"label": "🐙 GitHub", "value": "github"},
                {"label": "💬 Telegram", "value": "telegram"},
                {"label": "💳 Stripe", "value": "stripe"},
                {"label": "📁 Files", "value": "files"},
            ],
        ).to_dict(),
        WizardStep(
            4, "Choose skills",
            "What specialized abilities should this agent have?",
            "skills", "multi_choice",
            options=[
                {"label": "🔬 Research", "value": "research"},
                {"label": "💬 Support", "value": "support"},
                {"label": "📈 Sales", "value": "sales"},
                {"label": "📊 Analytics", "value": "analytics"},
                {"label": "💻 Coding", "value": "coding"},
                {"label": "⚡ Automation", "value": "automation"},
            ],
            required=False,
        ).to_dict(),
        WizardStep(
            5, "Choose approval mode",
            "When should Bea ask for your permission?",
            "approval", "radio",
            options=[
                {"label": "Always ask", "value": "always_approve", "description": "Maximum control"},
                {"label": "Ask for risky actions", "value": "manual", "description": "Recommended"},
                {"label": "Auto-safe only", "value": "auto", "description": "Fully autonomous for safe actions"},
            ],
        ).to_dict(),
        WizardStep(
            6, "Review & Create",
            "Review your configuration and create the agent.",
            "confirm", "confirm",
        ).to_dict(),
    ]

# Model tier mapping
MODEL_TIER_MAP = {
    "fast": {"model": "nano", "description": "Fast responses, lower quality"},
    "balanced": {"model": "standard", "description": "Good balance of speed and quality"},
    "premium": {"model": "premium", "description": "Best quality, higher cost"},
    "custom": {"model": "", "description": "Choose model manually"},
}
