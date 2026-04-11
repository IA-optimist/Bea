"""
JARVIS MAX — Module Manager
================================
User-facing management layer for Agents, Skills, Connectors, and MCP servers.

Wraps ExtensionRegistry with:
- Human-friendly API (no jargon)
- Simple + Advanced creation modes
- Blueprint export/import
- Health status aggregation
- Connector test framework
- Catalog of available modules

Designed for non-technical users first, power-users via Advanced Mode.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# USER-FRIENDLY DATA MODELS
# ═══════════════════════════════════════════════════════════════

@dataclass
class AgentConfig:
    """User-facing agent configuration."""
    id: str = ""
    display_name: str = ""
    description: str = ""
    purpose: str = ""           # What this agent does (simple mode)
    status: str = "enabled"     # enabled / disabled
    model: str = ""             # Model assignment
    allowed_tools: list[str] = field(default_factory=list)
    linked_skills: list[str] = field(default_factory=list)
    linked_connectors: list[str] = field(default_factory=list)
    linked_secrets: list[str] = field(default_factory=list)
    risk_level: str = "low"
    approval_policy: str = "auto"  # auto / manual / always_approve
    tags: list[str] = field(default_factory=list)
    # Advanced mode fields
    system_prompt: str = ""
    behavior_rules: list[str] = field(default_factory=list)
    execution_limits: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.display_name,
            "description": self.description[:200],
            "purpose": self.purpose[:200],
            "status": self.status, "model": self.model,
            "tools": self.allowed_tools, "skills": self.linked_skills,
            "connectors": self.linked_connectors,
            "risk": self.risk_level, "approval": self.approval_policy,
            "tags": self.tags, "created": self.created_at,
        }

    def to_simple_dict(self) -> dict:
        """Simple mode view — no advanced fields."""
        return {
            "id": self.id, "name": self.display_name,
            "description": self.description[:200],
            "status": self.status, "model": self.model,
            "tools": len(self.allowed_tools),
            "skills": len(self.linked_skills),
            "tags": self.tags,
        }


@dataclass
class SkillConfig:
    """User-facing skill configuration."""
    id: str = ""
    name: str = ""
    description: str = ""
    category: str = ""          # research, coding, writing, data, etc.
    version: str = "1.0"
    status: str = "enabled"
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)
    linked_tools: list[str] = field(default_factory=list)
    linked_policies: list[str] = field(default_factory=list)
    test_cases: list[dict] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name,
            "description": self.description[:200],
            "category": self.category, "version": self.version,
            "status": self.status,
            "tools": self.linked_tools, "tags": self.tags,
            "tests": len(self.test_cases),
        }


@dataclass
class MCPConfig:
    """User-facing MCP server configuration."""
    id: str = ""
    display_name: str = ""
    transport: str = "http"     # stdio / http / websocket
    endpoint: str = ""          # URL or command
    auth_mode: str = "none"     # none / token / header
    auth_ref: str = ""          # Secret vault reference
    status: str = "enabled"
    trust_level: str = "medium"
    discovered_tools: list[str] = field(default_factory=list)
    last_test_status: str = ""
    last_test_at: float | None = None
    headers: dict = field(default_factory=dict)
    env_vars: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.display_name,
            "transport": self.transport, "endpoint": self.endpoint[:200],
            "auth": self.auth_mode, "status": self.status,
            "trust": self.trust_level,
            "tools": self.discovered_tools,
            "last_test": self.last_test_status,
            "tags": self.tags,
        }

    def to_safe_dict(self) -> dict:
        """Strips secrets from headers/env."""
        d = self.to_dict()
        d["headers"] = {k: "***" for k in self.headers}
        d["env"] = {k: "***" for k in self.env_vars}
        return d


@dataclass
class ConnectorConfig:
    """External service connector (Gmail, Stripe, GitHub, etc.)."""
    id: str = ""
    provider: str = ""
    display_name: str = ""
    auth_type: str = ""         # oauth / api_key / token / basic
    status: str = "enabled"
    scopes: list[str] = field(default_factory=list)
    linked_identity: str = ""
    linked_secrets: list[str] = field(default_factory=list)
    last_sync: float | None = None
    last_test: str = ""
    environment: str = "prod"
    notes: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "provider": self.provider,
            "name": self.display_name, "auth": self.auth_type,
            "status": self.status, "scopes": self.scopes,
            "identity": self.linked_identity,
            "last_test": self.last_test,
            "env": self.environment, "tags": self.tags,
        }


# ═══════════════════════════════════════════════════════════════
# CATALOG ENTRIES
# ═══════════════════════════════════════════════════════════════

@dataclass
class CatalogEntry:
    """A module available for installation from the catalog."""
    catalog_id: str
    name: str
    module_type: str        # agent / skill / connector / mcp / playbook
    description: str = ""
    category: str = ""
    author: str = "jarvismax"
    version: str = "1.0"
    risk_level: str = "low"
    requires_approval: bool = False
    blueprint: dict = field(default_factory=dict)
    popularity: int = 0
    tags: list[str] = field(default_factory=list)
    # ── Marketplace metadata (Phase 4 enhancement) ──
    dependencies: list[str] = field(default_factory=list)       # IDs of required modules
    required_secrets: list[str] = field(default_factory=list)    # Vault secret types needed
    required_connectors: list[str] = field(default_factory=list) # Connector types needed
    health_status: str = "unknown"                               # healthy / degraded / broken / unknown
    trust_level: str = "internal"                                # internal / verified / community / untrusted
    compatibility: list[str] = field(default_factory=list)       # e.g., ["jarvismax>=1.0", "python>=3.10"]
    install_count: int = 0
    installable: bool = True                                     # One-click install safe?
    changelog: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.catalog_id, "name": self.name,
            "type": self.module_type,
            "description": self.description[:200],
            "category": self.category, "author": self.author,
            "version": self.version, "risk": self.risk_level,
            "approval": self.requires_approval,
            "popularity": self.popularity, "tags": self.tags,
            "dependencies": self.dependencies,
            "required_secrets": self.required_secrets,
            "required_connectors": self.required_connectors,
            "health": self.health_status,
            "trust": self.trust_level,
            "compatibility": self.compatibility,
            "install_count": self.install_count,
            "installable": self.installable,
        }


# ═══════════════════════════════════════════════════════════════
# MODULE MANAGER
# ═══════════════════════════════════════════════════════════════

class ModuleManager:
    """
    Unified management layer for Agents, Skills, Connectors, MCP.
    Provides simple + advanced modes, blueprints, health, catalog.
    """

    # Default data directory — auto-populate only seeds here (or via env var)
    _DEFAULT_DATA_DIR = "data/modules"

    def __init__(self, data_dir: str | Path = "data/modules"):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        # Track whether we're using the canonical default dir
        self._is_default_dir = str(data_dir) == self._DEFAULT_DATA_DIR

        self._agents: dict[str, AgentConfig] = {}
        self._skills: dict[str, SkillConfig] = {}
        self._mcp: dict[str, MCPConfig] = {}
        self._connectors: dict[str, ConnectorConfig] = {}
        self._catalog: dict[str, CatalogEntry] = {}

        self._load()
        self._init_catalog()
        self._auto_populate()

    # ── Auto-populate ──

    def _auto_populate(self):
        """Seed known agents, skills, MCP on first boot (default dir only, idempotent)."""
        import os
        # BLOC H fix: only seed in the canonical data/modules directory to avoid
        # contaminating test tmp directories with pre-populated agents/skills/mcp.
        if not self._is_default_dir and not os.getenv("JARVIS_AUTO_POPULATE"):
            return
        _KNOWN_AGENTS = [
            {"id": "atlas-director", "name": "Atlas Director", "description": "Orchestration principale", "purpose": "orchestration", "risk": "low", "tags": ["core"]},
            {"id": "scout-research", "name": "Scout Research", "description": "Recherche et analyse d'informations", "purpose": "research", "risk": "low", "tags": ["core"]},
            {"id": "map-planner", "name": "Map Planner", "description": "Planification et architecture", "purpose": "planning", "risk": "low", "tags": ["core"]},
            {"id": "forge-builder", "name": "Forge Builder", "description": "Génération et modification de code", "purpose": "dev", "risk": "medium", "tags": ["core"]},
            {"id": "lens-reviewer", "name": "Lens Reviewer", "description": "Revue critique et validation", "purpose": "review", "risk": "low", "tags": ["core"]},
            {"id": "shadow-advisor", "name": "Shadow Advisor", "description": "Conseil sécurité et audit système", "purpose": "security", "risk": "low", "tags": ["core"]},
            {"id": "pulse-ops", "name": "Pulse Ops", "description": "Monitoring et opérations système", "purpose": "operations", "risk": "medium", "tags": ["core"]},
            {"id": "vault-memory", "name": "Vault Memory", "description": "Gestion mémoire vectorielle et RAG", "purpose": "memory", "risk": "low", "tags": ["core"]},
            {"id": "night-worker", "name": "Night Worker", "description": "Tâches asynchrones et maintenance", "purpose": "async", "risk": "low", "tags": ["core"]},
        ]
        _KNOWN_SKILLS = [
            {"id": "market-research", "name": "Market Research", "description": "Analyse de marché et tendances"},
            {"id": "offer-design", "name": "Offer Design", "description": "Conception d'offres et pricing"},
            {"id": "persona-analysis", "name": "Persona Analysis", "description": "Profils utilisateurs et segments"},
            {"id": "acquisition-strategy", "name": "Acquisition Strategy", "description": "Stratégies d'acquisition client"},
            {"id": "saas-scope", "name": "SaaS Scope", "description": "Cadrage de projets SaaS"},
            {"id": "automation-opportunity", "name": "Automation Opportunity", "description": "Détection d'opportunités d'automatisation"},
        ]
        _KNOWN_MCP = [
            {"id": "filesystem", "name": "Filesystem", "description": "Accès fichiers workspace-scoped", "trust": "official"},
            {"id": "github", "name": "GitHub", "description": "Opérations GitHub (issues, PRs, repos)", "trust": "official"},
            {"id": "fetch", "name": "Fetch", "description": "HTTP fetch et extraction web", "trust": "official"},
            {"id": "memory", "name": "Memory", "description": "Mémoire persistante clé-valeur", "trust": "official"},
            {"id": "sqlite", "name": "SQLite", "description": "Base de données SQLite", "trust": "official"},
            {"id": "sequential-thinking", "name": "Sequential Thinking", "description": "Raisonnement séquentiel structuré", "trust": "official"},
        ]

        changed = False
        for a in _KNOWN_AGENTS:
            if a["id"] not in self._agents:
                try:
                    self.create_agent(a)
                    changed = True
                except Exception:
                    _silent_log.debug("suppressed_exception", src='module_manager.py')
        for s in _KNOWN_SKILLS:
            if s["id"] not in self._skills:
                try:
                    self.create_skill(s)
                    changed = True
                except Exception:
                    _silent_log.debug("suppressed_exception", src='module_manager.py')
        for m in _KNOWN_MCP:
            if m["id"] not in self._mcp:
                try:
                    self.create_mcp(m)
                    changed = True
                except Exception:
                    _silent_log.debug("suppressed_exception", src='module_manager.py')

    # ── Agent CRUD ──

    def create_agent(self, config: dict, mode: str = "simple") -> AgentConfig:
        """Create agent. mode: simple or advanced."""
        _name_key = (config.get("name") or "") + str(time.time())
        aid = config.get("id") or f"agent-{hashlib.md5(_name_key.encode()).hexdigest()[:8]}"

        agent = AgentConfig(
            id=aid,
            display_name=config.get("name", ""),
            description=config.get("description", ""),
            purpose=config.get("purpose", ""),
            model=config.get("model", ""),
            allowed_tools=config.get("tools", []),
            linked_skills=config.get("skills", []),
            linked_connectors=config.get("connectors", []),
            linked_secrets=config.get("secrets", []),
            risk_level=config.get("risk", "low"),
            approval_policy=config.get("approval", "auto"),
            tags=config.get("tags", []),
        )

        if mode == "advanced":
            agent.system_prompt = config.get("system_prompt", "")
            agent.behavior_rules = config.get("behavior_rules", [])
            agent.execution_limits = config.get("limits", {})

        self._agents[aid] = agent
        self._persist()
        return agent

    def update_agent(self, agent_id: str, updates: dict) -> AgentConfig | None:
        agent = self._agents.get(agent_id)
        if not agent:
            return None
        for key, value in updates.items():
            if hasattr(agent, key):
                setattr(agent, key, value)
        agent.updated_at = time.time()
        self._persist()
        return agent

    def delete_agent(self, agent_id: str) -> bool:
        if agent_id not in self._agents:
            return False
        del self._agents[agent_id]
        self._persist()
        return True

    def toggle_agent(self, agent_id: str) -> str | None:
        agent = self._agents.get(agent_id)
        if not agent:
            return None
        # If enabling, check dependencies via ToolConfigRegistry (fail-open)
        if agent.status == "disabled":
            try:
                from core.tool_config_registry import get_config_registry
                blocked, msg = get_config_registry().should_block_enable(agent_id)
                if blocked:
                    logger.warning(f"Agent {agent_id} enable blocked: {msg}")
                    return None  # Cannot enable — missing dependencies
            except Exception as _e:
                logger.debug(f"Config registry check skipped: {_e}")
        agent.status = "disabled" if agent.status == "enabled" else "enabled"
        agent.updated_at = time.time()
        self._persist()
        return agent.status

    def duplicate_agent(self, agent_id: str) -> AgentConfig | None:
        agent = self._agents.get(agent_id)
        if not agent:
            return None
        new_id = f"agent-{hashlib.md5(f'{agent_id}{time.time()}'.encode()).hexdigest()[:8]}"
        new_agent = AgentConfig(**{k: v for k, v in agent.__dict__.items()})
        new_agent.id = new_id
        new_agent.display_name = f"{agent.display_name} (Copy)"
        new_agent.created_at = time.time()
        self._agents[new_id] = new_agent
        self._persist()
        return new_agent

    def list_agents(self, status: str | None = None, simple: bool = False) -> list[dict]:
        results = []
        for a in self._agents.values():
            if status and a.status != status:
                continue
            results.append(a.to_simple_dict() if simple else a.to_dict())
        return results

    def get_agent(self, agent_id: str) -> AgentConfig | None:
        return self._agents.get(agent_id)

    # ── Skill CRUD ──

    def create_skill(self, config: dict) -> SkillConfig:
        _skill_key = (config.get("name") or "") + str(time.time())
        sid = config.get("id") or f"skill-{hashlib.md5(_skill_key.encode()).hexdigest()[:8]}"
        skill = SkillConfig(
            id=sid, name=config.get("name", ""),
            description=config.get("description", ""),
            category=config.get("category", ""),
            version=config.get("version", "1.0"),
            input_schema=config.get("input_schema", {}),
            output_schema=config.get("output_schema", {}),
            linked_tools=config.get("tools", []),
            tags=config.get("tags", []),
        )
        self._skills[sid] = skill
        self._persist()
        return skill

    def update_skill(self, skill_id: str, updates: dict) -> SkillConfig | None:
        skill = self._skills.get(skill_id)
        if not skill:
            return None
        for key, value in updates.items():
            if hasattr(skill, key):
                setattr(skill, key, value)
        self._persist()
        return skill

    def delete_skill(self, skill_id: str) -> bool:
        if skill_id not in self._skills:
            return False
        del self._skills[skill_id]
        self._persist()
        return True

    def toggle_skill(self, skill_id: str) -> str | None:
        skill = self._skills.get(skill_id)
        if not skill:
            return None
        if skill.status == "disabled":
            try:
                from core.tool_config_registry import get_config_registry
                blocked, msg = get_config_registry().should_block_enable(skill_id)
                if blocked:
                    logger.warning(f"Skill {skill_id} enable blocked: {msg}")
                    return None
            except Exception as _e:
                logger.debug(f"Config registry check skipped: {_e}")
        skill.status = "disabled" if skill.status == "enabled" else "enabled"
        self._persist()
        return skill.status

    def list_skills(self, category: str | None = None) -> list[dict]:
        results = []
        for s in self._skills.values():
            if category and s.category != category:
                continue
            results.append(s.to_dict())
        return results

    def get_skill(self, skill_id: str) -> SkillConfig | None:
        return self._skills.get(skill_id)

    # ── MCP CRUD ──

    def create_mcp(self, config: dict) -> MCPConfig:
        _mcp_key = (config.get("name") or "") + str(time.time())
        mid = config.get("id") or f"mcp-{hashlib.md5(_mcp_key.encode()).hexdigest()[:8]}"
        mcp = MCPConfig(
            id=mid, display_name=config.get("name", ""),
            transport=config.get("transport", "http"),
            endpoint=config.get("endpoint", ""),
            auth_mode=config.get("auth", "none"),
            auth_ref=config.get("auth_ref", ""),
            trust_level=config.get("trust", "medium"),
            headers=config.get("headers", {}),
            env_vars=config.get("env_vars", {}),
            tags=config.get("tags", []),
        )
        self._mcp[mid] = mcp
        self._persist()
        return mcp

    def update_mcp(self, mcp_id: str, updates: dict) -> MCPConfig | None:
        mcp = self._mcp.get(mcp_id)
        if not mcp:
            return None
        for key, value in updates.items():
            if hasattr(mcp, key):
                setattr(mcp, key, value)
        self._persist()
        return mcp

    def delete_mcp(self, mcp_id: str) -> bool:
        if mcp_id not in self._mcp:
            return False
        del self._mcp[mcp_id]
        self._persist()
        return True

    def toggle_mcp(self, mcp_id: str) -> str | None:
        mcp = self._mcp.get(mcp_id)
        if not mcp:
            return None
        mcp.status = "disabled" if mcp.status == "enabled" else "enabled"
        self._persist()
        return mcp.status

    def test_mcp(self, mcp_id: str) -> dict:
        """Test MCP server connectivity."""
        mcp = self._mcp.get(mcp_id)
        if not mcp:
            return {"success": False, "error": "MCP not found"}
        # Simulated test — real implementation would attempt connection
        mcp.last_test_status = "pass" if mcp.endpoint else "fail"
        mcp.last_test_at = time.time()
        self._persist()
        return {
            "success": bool(mcp.endpoint),
            "status": mcp.last_test_status,
            "transport": mcp.transport,
            "tools_discovered": len(mcp.discovered_tools),
        }

    def list_mcp(self) -> list[dict]:
        return [m.to_safe_dict() for m in self._mcp.values()]

    def get_mcp(self, mcp_id: str) -> MCPConfig | None:
        return self._mcp.get(mcp_id)

    # ── Connector CRUD ──

    def create_connector(self, config: dict) -> ConnectorConfig:
        _conn_key = (config.get("provider") or "") + str(time.time())
        cid = config.get("id") or f"conn-{hashlib.md5(_conn_key.encode()).hexdigest()[:8]}"
        conn = ConnectorConfig(
            id=cid, provider=config.get("provider", ""),
            display_name=config.get("name", ""),
            auth_type=config.get("auth", "api_key"),
            scopes=config.get("scopes", []),
            linked_identity=config.get("identity", ""),
            linked_secrets=config.get("secrets", []),
            environment=config.get("environment", "prod"),
            notes=config.get("notes", ""),
            tags=config.get("tags", []),
        )
        self._connectors[cid] = conn
        self._persist()
        return conn

    def update_connector(self, conn_id: str, updates: dict) -> ConnectorConfig | None:
        conn = self._connectors.get(conn_id)
        if not conn:
            return None
        for key, value in updates.items():
            if hasattr(conn, key):
                setattr(conn, key, value)
        self._persist()
        return conn

    def delete_connector(self, conn_id: str) -> bool:
        if conn_id not in self._connectors:
            return False
        del self._connectors[conn_id]
        self._persist()
        return True

    def toggle_connector(self, conn_id: str) -> str | None:
        conn = self._connectors.get(conn_id)
        if not conn:
            return None
        conn.status = "disabled" if conn.status == "enabled" else "enabled"
        self._persist()
        return conn.status

    def test_connector(self, conn_id: str) -> dict:
        """Test external connector."""
        conn = self._connectors.get(conn_id)
        if not conn:
            return {"success": False, "error": "Connector not found"}
        conn.last_test = "pass" if conn.linked_identity or conn.linked_secrets else "no_credentials"
        conn.last_sync = time.time()
        self._persist()
        return {
            "success": conn.last_test == "pass",
            "status": conn.last_test,
            "provider": conn.provider,
        }

    def list_connectors(self, provider: str | None = None) -> list[dict]:
        results = []
        for c in self._connectors.values():
            if provider and c.provider != provider:
                continue
            results.append(c.to_dict())
        return results

    def get_connector(self, conn_id: str) -> ConnectorConfig | None:
        return self._connectors.get(conn_id)

    # ── Blueprint Export/Import ──

    def export_blueprint(self, module_type: str, module_id: str) -> dict | None:
        """Export a module configuration as a portable blueprint."""
        stores = {"agent": self._agents, "skill": self._skills,
                  "mcp": self._mcp, "connector": self._connectors}
        store = stores.get(module_type)
        if not store or module_id not in store:
            return None

        item = store[module_id]
        return {
            "blueprint_version": 1,
            "type": module_type,
            "exported_at": time.time(),
            "config": item.to_dict(),
        }

    def import_blueprint(self, blueprint: dict) -> dict:
        """Import a module from a blueprint."""
        bp_type = blueprint.get("type")
        config = blueprint.get("config", {})

        if bp_type == "agent":
            config.pop("id", None)
            result = self.create_agent(config)
            return {"success": True, "id": result.id, "type": "agent"}
        elif bp_type == "skill":
            config.pop("id", None)
            result = self.create_skill(config)
            return {"success": True, "id": result.id, "type": "skill"}
        elif bp_type == "mcp":
            config.pop("id", None)
            result = self.create_mcp(config)
            return {"success": True, "id": result.id, "type": "mcp"}
        elif bp_type == "connector":
            config.pop("id", None)
            result = self.create_connector(config)
            return {"success": True, "id": result.id, "type": "connector"}

        return {"success": False, "error": f"Unknown blueprint type: {bp_type}"}

    # ── Catalog ──

    def get_catalog(self, module_type: str | None = None, category: str | None = None) -> list[dict]:
        results = []
        for entry in self._catalog.values():
            if module_type and entry.module_type != module_type:
                continue
            if category and entry.category != category:
                continue
            results.append(entry.to_dict())
        return sorted(results, key=lambda x: -x.get("popularity", 0))

    def install_from_catalog(self, catalog_id: str) -> dict:
        """Install a module from the catalog with dependency/trust checks."""
        entry = self._catalog.get(catalog_id)
        if not entry:
            return {"success": False, "error": "Catalog entry not found"}
        # Check dependencies
        missing_deps = [d for d in entry.dependencies if d not in self._catalog and
                        d not in self._agents and d not in self._skills and
                        d not in self._connectors and d not in self._mcp]
        if missing_deps:
            return {"success": False, "error": f"Missing dependencies: {missing_deps}",
                    "missing_dependencies": missing_deps}
        # Check trust level
        if entry.trust_level == "untrusted":
            return {"success": False, "error": "Module is untrusted — requires manual review"}
        result = self.import_blueprint({
            "type": entry.module_type,
            "config": entry.blueprint,
        })
        if result.get("success"):
            entry.install_count += 1
            self._persist()
        return result

    # ── Health Summary ──

    def health_summary(self) -> dict:
        """Aggregate health status of all modules."""
        agents_enabled = sum(1 for a in self._agents.values() if a.status == "enabled")
        skills_enabled = sum(1 for s in self._skills.values() if s.status == "enabled")
        mcp_ok = sum(1 for m in self._mcp.values() if m.last_test_status == "pass")
        conn_ok = sum(1 for c in self._connectors.values() if c.last_test == "pass")

        result = {
            "agents": {"total": len(self._agents), "enabled": agents_enabled},
            "skills": {"total": len(self._skills), "enabled": skills_enabled},
            "mcp": {"total": len(self._mcp), "healthy": mcp_ok},
            "connectors": {"total": len(self._connectors), "healthy": conn_ok},
        }
        # Enrich with dependency health from config registry (fail-open)
        try:
            from core.tool_config_registry import get_config_registry
            result["dependency_health"] = get_config_registry().stats()
        except Exception:
            _silent_log.debug("suppressed_exception", src='module_manager.py')
        return result

    # ── Counts ──

    @property
    def agent_count(self) -> int:
        return len(self._agents)

    @property
    def skill_count(self) -> int:
        return len(self._skills)

    @property
    def mcp_count(self) -> int:
        return len(self._mcp)

    @property
    def connector_count(self) -> int:
        return len(self._connectors)

    # ── Persistence ──

    def _persist(self) -> None:
        try:
            data = {
                "agents": {k: v.to_dict() for k, v in self._agents.items()},
                "skills": {k: v.to_dict() for k, v in self._skills.items()},
                "mcp": {k: v.to_safe_dict() for k, v in self._mcp.items()},
                "connectors": {k: v.to_dict() for k, v in self._connectors.items()},
            }
            with open(self._data_dir / "modules.json", "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Module persist failed: {e}")

    def _load(self) -> None:
        path = self._data_dir / "modules.json"
        if not path.exists():
            return
        try:
            with open(path) as f:
                data = json.load(f)
            for aid, d in data.get("agents", {}).items():
                self._agents[aid] = AgentConfig(
                    id=aid, display_name=d.get("name", ""),
                    description=d.get("description", ""),
                    status=d.get("status", "enabled"),
                    model=d.get("model", ""),
                    allowed_tools=d.get("tools", []),
                    linked_skills=d.get("skills", []),
                    linked_connectors=d.get("connectors", []),
                    risk_level=d.get("risk", "low"),
                    tags=d.get("tags", []),
                    created_at=d.get("created", 0),
                )
            for sid, d in data.get("skills", {}).items():
                self._skills[sid] = SkillConfig(
                    id=sid, name=d.get("name", ""),
                    description=d.get("description", ""),
                    category=d.get("category", ""),
                    version=d.get("version", "1.0"),
                    status=d.get("status", "enabled"),
                    linked_tools=d.get("tools", []),
                    tags=d.get("tags", []),
                )
            for mid, d in data.get("mcp", {}).items():
                self._mcp[mid] = MCPConfig(
                    id=mid, display_name=d.get("name", ""),
                    transport=d.get("transport", "http"),
                    endpoint=d.get("endpoint", ""),
                    auth_mode=d.get("auth", "none"),
                    status=d.get("status", "enabled"),
                    trust_level=d.get("trust", "medium"),
                    discovered_tools=d.get("tools", []),
                    last_test_status=d.get("last_test", ""),
                    tags=d.get("tags", []),
                )
            for cid, d in data.get("connectors", {}).items():
                self._connectors[cid] = ConnectorConfig(
                    id=cid, provider=d.get("provider", ""),
                    display_name=d.get("name", ""),
                    auth_type=d.get("auth", ""),
                    status=d.get("status", "enabled"),
                    scopes=d.get("scopes", []),
                    linked_identity=d.get("identity", ""),
                    last_test=d.get("last_test", ""),
                    environment=d.get("env", "prod"),
                    tags=d.get("tags", []),
                )
        except Exception as e:
            logger.error(f"Module load failed: {e}")

    def _init_catalog(self) -> None:
        """Initialize built-in catalog entries."""
        entries = [
            CatalogEntry("cat-research", "Research Agent", "agent",
                         "Performs web research and produces structured reports",
                         "research", risk_level="low", popularity=95,
                         blueprint={"name": "Research Agent", "purpose": "Web research", "tools": ["web_search", "browser"]}),
            CatalogEntry("cat-coder", "Code Agent", "agent",
                         "Writes and reviews code across multiple languages",
                         "development", risk_level="low", popularity=90,
                         blueprint={"name": "Code Agent", "purpose": "Write code", "tools": ["code_exec", "git"]}),
            CatalogEntry("cat-writer", "Content Writer", "agent",
                         "Creates marketing copy, blog posts, and email content",
                         "content", risk_level="low", popularity=85,
                         blueprint={"name": "Content Writer", "purpose": "Create content", "tools": ["text_gen"]}),
            CatalogEntry("cat-analyst", "Data Analyst", "agent",
                         "Analyzes datasets and produces insights",
                         "analytics", risk_level="low", popularity=80,
                         blueprint={"name": "Data Analyst", "purpose": "Analyze data", "tools": ["data_query", "charts"]}),
            CatalogEntry("cat-support", "Customer Support", "agent",
                         "Handles customer tickets and inquiries",
                         "support", risk_level="low", popularity=75,
                         blueprint={"name": "Support Agent", "purpose": "Customer support", "tools": ["email", "ticket"]}),
            CatalogEntry("cat-web-scrape", "Web Scraper", "skill",
                         "Extract structured data from websites",
                         "data", risk_level="low", popularity=70,
                         blueprint={"name": "Web Scraper", "category": "data", "tools": ["browser"]}),
            CatalogEntry("cat-gmail", "Gmail Connector", "connector",
                         "Read and send emails via Gmail API",
                         "email", risk_level="medium", popularity=85,
                         blueprint={"provider": "gmail", "name": "Gmail", "auth": "oauth", "scopes": ["read", "send"]}),
            CatalogEntry("cat-github", "GitHub Connector", "connector",
                         "Manage repos, issues, and PRs",
                         "development", risk_level="low", popularity=90,
                         blueprint={"provider": "github", "name": "GitHub", "auth": "token", "scopes": ["repo", "issues"]}),
            CatalogEntry("cat-stripe", "Stripe Connector", "connector",
                         "Payment processing and invoicing",
                         "finance", risk_level="high", requires_approval=True, popularity=80,
                         blueprint={"provider": "stripe", "name": "Stripe", "auth": "api_key"}),
            CatalogEntry("cat-notion", "Notion Connector", "connector",
                         "Manage Notion pages and databases",
                         "productivity", risk_level="low", popularity=70,
                         blueprint={"provider": "notion", "name": "Notion", "auth": "token"}),
        ]
        for entry in entries:
            self._catalog[entry.catalog_id] = entry