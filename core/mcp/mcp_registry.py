"""
JARVIS MAX — MCP Registry
=============================
Centralized registry of MCP server integrations.

NOT a second registry — extends the existing ModuleManager MCP layer
with structured metadata, health checking, tool discovery, and secret deps.

Each MCP server entry tracks:
  - source, trust level, transport
  - required secrets/configs
  - discovered tools
  - health status
  - approval requirements
  - RBAC: admin-only install, user can enable/test
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

log = structlog.get_logger()


class TrustLevel(str, Enum):
    OFFICIAL = "official"           # modelcontextprotocol/servers
    VENDOR = "vendor"               # Official vendor (GitHub, Qdrant, etc.)
    MANAGED = "managed"             # Composio / Smithery
    COMMUNITY = "community"         # Reviewed community
    UNTRUSTED = "untrusted"         # Not reviewed


class MCPHealth(str, Enum):
    READY = "ready"
    NEEDS_SETUP = "needs_setup"
    DISABLED = "disabled"
    ERROR = "error"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


@dataclass
class MCPServerEntry:
    """A registered MCP server with full metadata."""
    id: str = ""
    name: str = ""
    description: str = ""
    # Source
    source: str = ""                    # e.g., "modelcontextprotocol/servers"
    source_url: str = ""                # GitHub URL
    trust_level: TrustLevel = TrustLevel.COMMUNITY
    # Transport
    transport: str = "stdio"            # stdio | http | sse
    command: str = ""                   # For stdio: python3, npx, etc.
    args: List[str] = field(default_factory=list)
    endpoint: str = ""                  # For http: URL
    env_vars: Dict[str, str] = field(default_factory=dict)  # Non-secret env
    # Dependencies
    required_secrets: List[str] = field(default_factory=list)
    required_configs: List[str] = field(default_factory=list)
    install_command: str = ""           # pip install / npm install
    # Runtime
    status: str = "disabled"            # enabled | disabled
    health: MCPHealth = MCPHealth.UNKNOWN
    health_message: str = ""
    discovered_tools: List[Dict[str, Any]] = field(default_factory=list)
    last_test_at: float = 0
    last_test_status: str = ""
    # Safety
    risk_level: str = "medium"          # low | medium | high | critical
    requires_approval: bool = False     # All tool calls need approval?
    dangerous_tools: List[str] = field(default_factory=list)  # Specific tools needing approval
    # Metadata
    tags: List[str] = field(default_factory=list)
    version: str = ""
    category: str = ""                  # engineering | data | infra | security | managed
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "description": self.description[:200],
            "source": self.source, "source_url": self.source_url,
            "trust": self.trust_level.value if isinstance(self.trust_level, TrustLevel) else self.trust_level,
            "transport": self.transport,
            "status": self.status, "health": self.health.value if isinstance(self.health, MCPHealth) else self.health,
            "health_message": self.health_message,
            "tools_count": len(self.discovered_tools),
            "discovered_tools": [t.get("name", "") for t in self.discovered_tools[:20]],
            "required_secrets": self.required_secrets,
            "required_configs": self.required_configs,
            "risk": self.risk_level,
            "requires_approval": self.requires_approval,
            "dangerous_tools": self.dangerous_tools,
            "tags": self.tags, "category": self.category,
            "last_test": self.last_test_status,
            "last_test_at": self.last_test_at,
        }

    def to_safe_dict(self) -> dict:
        """Never expose env vars or secrets."""
        d = self.to_dict()
        d["env_vars"] = {k: "***" for k in self.env_vars}
        return d


class MCPRegistry:
    """
    Central MCP server registry.

    Extends (not replaces) ModuleManager's MCP layer with:
      - Structured metadata per server
      - Health checking with secret validation
      - Tool discovery
      - Trust level enforcement
    """

    def __init__(self, data_dir: str = "data/mcp"):
        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._servers: Dict[str, MCPServerEntry] = {}
        self._lock = threading.RLock()
        self._load()

    # ── Registration ──

    def register(self, entry: MCPServerEntry) -> MCPServerEntry:
        """Register or update an MCP server."""
        with self._lock:
            # Compute health based on dependencies
            entry.health = self._compute_health(entry)
            self._servers[entry.id] = entry
            self._persist()
        return entry

    def unregister(self, mcp_id: str) -> bool:
        with self._lock:
            if mcp_id in self._servers:
                del self._servers[mcp_id]
                self._persist()
                return True
        return False

    def get(self, mcp_id: str) -> Optional[MCPServerEntry]:
        return self._servers.get(mcp_id)

    def list_all(self, category: str = "", trust: str = "") -> List[MCPServerEntry]:
        results = []
        for s in self._servers.values():
            if category and s.category != category:
                continue
            trust_val = s.trust_level.value if isinstance(s.trust_level, TrustLevel) else s.trust_level
            if trust and trust_val != trust:
                continue
            results.append(s)
        return sorted(results, key=lambda s: s.name)

    # ── Health ──

    def check_health(self, mcp_id: str) -> Dict[str, Any]:
        """Check health of a specific MCP server."""
        entry = self._servers.get(mcp_id)
        if not entry:
            return {"health": "not_found"}
        entry.health = self._compute_health(entry)
        entry.last_test_at = time.time()
        missing_secrets = self._check_secrets(entry)
        missing_configs = self._check_configs(entry)
        result = {
            "id": mcp_id,
            "health": entry.health.value if isinstance(entry.health, MCPHealth) else entry.health,
            "message": entry.health_message,
            "missing_secrets": missing_secrets,
            "missing_configs": missing_configs,
        }
        self._persist()
        return result

    def check_all_health(self) -> Dict[str, Dict[str, Any]]:
        return {mid: self.check_health(mid) for mid in self._servers}

    def _compute_health(self, entry: MCPServerEntry) -> MCPHealth:
        if entry.status == "disabled":
            entry.health_message = "Disabled by user"
            return MCPHealth.DISABLED
        missing_s = self._check_secrets(entry)
        missing_c = self._check_configs(entry)
        if missing_s or missing_c:
            parts = []
            if missing_s:
                parts.append(f"Missing secrets: {', '.join(missing_s)}")
            if missing_c:
                parts.append(f"Missing configs: {', '.join(missing_c)}")
            entry.health_message = ". ".join(parts)
            return MCPHealth.NEEDS_SETUP
        if entry.trust_level == TrustLevel.UNTRUSTED:
            entry.health_message = "Untrusted source — requires review"
            return MCPHealth.RESTRICTED
        entry.health_message = "All dependencies satisfied"
        return MCPHealth.READY

    def _check_secrets(self, entry: MCPServerEntry) -> List[str]:
        missing = []
        for secret in entry.required_secrets:
            env_key = secret.upper().replace("-", "_").replace(".", "_")
            if not os.environ.get(env_key):
                # Check vault
                try:
                    from core.tool_config_registry import get_config_registry
                    if not get_config_registry()._secret_exists(secret):
                        missing.append(secret)
                except Exception:
                    missing.append(secret)
        return missing

    def _check_configs(self, entry: MCPServerEntry) -> List[str]:
        missing = []
        for config in entry.required_configs:
            env_key = config.upper().replace("-", "_").replace(".", "_")
            if not os.environ.get(env_key):
                missing.append(config)
        return missing

    # ── Spawn Probe ──

    def probe_spawn(self, mcp_id: str) -> Dict[str, Any]:
        """Test if a server's binary can actually start (spawn + kill).

        Returns dict with spawnable=True/False and details.
        Does NOT enable the server.
        """
        entry = self._servers.get(mcp_id)
        if not entry:
            return {"spawnable": False, "error": "Server not found"}
        if not entry.command:
            return {"spawnable": False, "error": "No command configured"}

        import shutil
        cmd = entry.command
        # Check if binary exists
        if not shutil.which(cmd):
            return {
                "spawnable": False,
                "error": f"Binary '{cmd}' not found in PATH",
                "install_hint": entry.install_command or None,
            }
        # Try to start the process and immediately kill it
        try:
            full_cmd = [cmd] + entry.args
            proc = subprocess.Popen(
                full_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, **entry.env_vars},
            )
            # Wait briefly to see if it crashes immediately
            import time as _time
            _time.sleep(0.5)
            if proc.poll() is not None:
                stderr = proc.stderr.read().decode("utf-8", errors="replace")[:500]
                return {"spawnable": False, "error": f"Process exited immediately: {stderr}"}
            # Still running = spawnable
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
            return {"spawnable": True, "command": " ".join(full_cmd)}
        except FileNotFoundError:
            return {"spawnable": False, "error": f"Binary '{cmd}' not found"}
        except Exception as e:
            return {"spawnable": False, "error": str(e)}

    def probe_all_spawnable(self) -> Dict[str, Dict[str, Any]]:
        """Probe all registered servers for spawn capability."""
        results = {}
        for mid in self._servers:
            results[mid] = self.probe_spawn(mid)
        return results

    # ── Enable / Disable ──

    def enable(self, mcp_id: str) -> Optional[str]:
        entry = self._servers.get(mcp_id)
        if not entry:
            return None
        # Check deps before enabling
        health = self._compute_health(MCPServerEntry(**{
            **entry.__dict__, "status": "enabled"
        }))
        if health == MCPHealth.NEEDS_SETUP:
            return f"Cannot enable: {entry.health_message}"
        entry.status = "enabled"
        entry.health = MCPHealth.READY
        entry.health_message = "Enabled and ready"
        self._persist()
        return "enabled"

    def disable(self, mcp_id: str) -> Optional[str]:
        entry = self._servers.get(mcp_id)
        if not entry:
            return None
        entry.status = "disabled"
        entry.health = MCPHealth.DISABLED
        entry.health_message = "Disabled by user"
        self._persist()
        return "disabled"

    # ── Tool Discovery ──

    def discover_tools(self, mcp_id: str) -> List[Dict[str, Any]]:
        """Attempt tool discovery for an MCP server. Returns discovered tools."""
        entry = self._servers.get(mcp_id)
        if not entry or entry.status != "enabled":
            return []
        # For now, return statically declared tools
        # Real discovery would involve connecting to the MCP server
        entry.last_test_at = time.time()
        entry.last_test_status = "discovery_ok" if entry.discovered_tools else "no_tools"
        self._persist()
        return entry.discovered_tools

    # ── Stats ──

    def stats(self) -> Dict[str, Any]:
        by_trust: Dict[str, int] = {}
        by_health: Dict[str, int] = {}
        by_category: Dict[str, int] = {}
        total_tools = 0
        for s in self._servers.values():
            t = s.trust_level.value if isinstance(s.trust_level, TrustLevel) else s.trust_level
            h = s.health.value if isinstance(s.health, MCPHealth) else s.health
            by_trust[t] = by_trust.get(t, 0) + 1
            by_health[h] = by_health.get(h, 0) + 1
            by_category[s.category] = by_category.get(s.category, 0) + 1
            total_tools += len(s.discovered_tools)
        return {
            "total_servers": len(self._servers),
            "total_tools": total_tools,
            "by_trust": by_trust,
            "by_health": by_health,
            "by_category": by_category,
        }

    # ── Persistence ──

    def _persist(self) -> None:
        try:
            data = {}
            for mid, entry in self._servers.items():
                d = entry.__dict__.copy()
                d["trust_level"] = entry.trust_level.value if isinstance(entry.trust_level, TrustLevel) else entry.trust_level
                d["health"] = entry.health.value if isinstance(entry.health, MCPHealth) else entry.health
                data[mid] = d
            (self._dir / "registry.json").write_text(json.dumps(data, indent=2, default=str))
        except Exception as e:
            log.warning("mcp_registry_persist_failed", err=str(e))

    def _load(self) -> None:
        path = self._dir / "registry.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            for mid, d in data.items():
                tl = d.pop("trust_level", "community")
                try:
                    tl = TrustLevel(tl)
                except ValueError:
                    tl = TrustLevel.COMMUNITY
                h = d.pop("health", "unknown")
                try:
                    h = MCPHealth(h)
                except ValueError:
                    h = MCPHealth.UNKNOWN
                entry = MCPServerEntry(**{k: v for k, v in d.items()
                                         if k in MCPServerEntry.__dataclass_fields__})
                entry.trust_level = tl
                entry.health = h
                self._servers[mid] = entry
        except Exception as e:
            log.warning("mcp_registry_load_failed", err=str(e))

    # ── Seed defaults ──

    def seed_core_stack(self) -> int:
        """Seed the curated MCP stack. Returns count of new entries."""
        count = 0
        for entry in _CORE_MCP_STACK:
            if entry.id not in self._servers:
                self.register(entry)
                count += 1
        return count


# ═══════════════════════════════════════════════════════════════
# CURATED MCP STACK
# ═══════════════════════════════════════════════════════════════

_CORE_MCP_STACK: List[MCPServerEntry] = [
    # ── LAYER A: Core Engineering MCPs ──
    MCPServerEntry(
        id="mcp-github", name="GitHub MCP",
        description="Official GitHub MCP server — repos, issues, PRs, workflows, code search",
        source="modelcontextprotocol/servers", source_url="https://github.com/modelcontextprotocol/servers/tree/main/src/github",
        trust_level=TrustLevel.OFFICIAL,
        transport="stdio", command="npx", args=["-y", "@modelcontextprotocol/server-github"],
        required_secrets=["GITHUB_PERSONAL_ACCESS_TOKEN"],
        risk_level="medium", category="engineering",
        tags=["github", "code", "issues", "pr", "ci"],
        dangerous_tools=["create_or_update_file", "push_files", "create_pull_request", "merge_pull_request", "delete_branch"],
        discovered_tools=[
            {"name": "search_repositories"}, {"name": "get_file_contents"},
            {"name": "list_issues"}, {"name": "create_issue"},
            {"name": "create_pull_request"}, {"name": "list_commits"},
            {"name": "search_code"}, {"name": "get_pull_request"},
        ],
    ),
    MCPServerEntry(
        id="mcp-filesystem", name="Filesystem MCP",
        description="Official filesystem MCP — scoped file read/write/search",
        source="modelcontextprotocol/servers", source_url="https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem",
        trust_level=TrustLevel.OFFICIAL,
        transport="stdio", command="npx", args=["-y", "@modelcontextprotocol/server-filesystem", "/root/.openclaw/workspace/Jarvismax"],
        risk_level="medium", category="engineering",
        tags=["filesystem", "files", "read", "write"],
        dangerous_tools=["write_file", "move_file", "create_directory"],
        discovered_tools=[
            {"name": "read_file"}, {"name": "write_file"},
            {"name": "list_directory"}, {"name": "search_files"},
            {"name": "get_file_info"}, {"name": "move_file"},
        ],
    ),
    MCPServerEntry(
        id="mcp-fetch", name="Fetch MCP",
        description="Official web fetch MCP — retrieve and extract web content safely",
        source="modelcontextprotocol/servers", source_url="https://github.com/modelcontextprotocol/servers/tree/main/src/fetch",
        trust_level=TrustLevel.OFFICIAL,
        transport="stdio", command="mcp-server-fetch", args=[],
        install_command="pip install mcp-server-fetch",
        risk_level="low", category="engineering",
        tags=["web", "fetch", "http", "research"],
        discovered_tools=[
            {"name": "fetch"}, {"name": "fetch_html"},
        ],
    ),
    MCPServerEntry(
        id="mcp-memory", name="Memory MCP",
        description="Official knowledge graph memory MCP — persistent entity/relation storage",
        source="modelcontextprotocol/servers", source_url="https://github.com/modelcontextprotocol/servers/tree/main/src/memory",
        trust_level=TrustLevel.OFFICIAL,
        transport="stdio", command="npx", args=["-y", "@modelcontextprotocol/server-memory"],
        risk_level="low", category="engineering",
        tags=["memory", "knowledge", "graph", "entities"],
        discovered_tools=[
            {"name": "create_entities"}, {"name": "create_relations"},
            {"name": "search_nodes"}, {"name": "open_nodes"},
            {"name": "read_graph"}, {"name": "delete_entities"},
        ],
    ),
    MCPServerEntry(
        id="mcp-playwright", name="Playwright MCP",
        description="Browser automation MCP via Playwright — navigate, click, screenshot, extract",
        source="modelcontextprotocol/servers", source_url="https://github.com/modelcontextprotocol/servers/tree/main/src/playwright",
        trust_level=TrustLevel.OFFICIAL,
        transport="stdio", command="npx", args=["-y", "@modelcontextprotocol/server-playwright"],
        risk_level="high", category="engineering",
        requires_approval=True,
        tags=["browser", "web", "automation", "screenshot"],
        dangerous_tools=["playwright_click", "playwright_fill", "playwright_navigate"],
        discovered_tools=[
            {"name": "playwright_navigate"}, {"name": "playwright_screenshot"},
            {"name": "playwright_click"}, {"name": "playwright_fill"},
            {"name": "playwright_evaluate"}, {"name": "playwright_get_visible_text"},
        ],
    ),
    # ── LAYER B: Data / Infra MCPs ──
    MCPServerEntry(
        id="mcp-postgres", name="PostgreSQL MCP",
        description="Official PostgreSQL MCP — read-only queries on operational data",
        source="modelcontextprotocol/servers", source_url="https://github.com/modelcontextprotocol/servers/tree/main/src/postgres",
        trust_level=TrustLevel.OFFICIAL,
        transport="stdio", command="mcp-server-postgres", args=[],
        install_command="pip install mcp-server-postgres",
        required_secrets=["POSTGRES_CONNECTION_STRING"],
        risk_level="medium", category="data",
        tags=["database", "postgres", "sql", "query"],
        dangerous_tools=["query"],  # Write queries gated
        discovered_tools=[
            {"name": "query"}, {"name": "list_tables"}, {"name": "describe_table"},
        ],
    ),
    MCPServerEntry(
        id="mcp-sqlite", name="SQLite MCP",
        description="Official SQLite MCP — local database for lightweight data ops",
        source="modelcontextprotocol/servers", source_url="https://github.com/modelcontextprotocol/servers/tree/main/src/sqlite",
        trust_level=TrustLevel.OFFICIAL,
        transport="stdio", command="mcp-server-sqlite", args=[],
        install_command="pip install mcp-server-sqlite",
        required_configs=["SQLITE_DB_PATH"],
        risk_level="low", category="data",
        tags=["database", "sqlite", "local"],
        discovered_tools=[
            {"name": "read_query"}, {"name": "write_query"},
            {"name": "list_tables"}, {"name": "describe_table"},
            {"name": "create_table"},
        ],
    ),
    # ── LAYER C: HexStrike (user-requested) ──
    MCPServerEntry(
        id="mcp-hexstrike", name="HexStrike AI",
        description="Cybersecurity MCP — 150+ pentesting tools, vulnerability scanning, bug bounty",
        source="0x4m4/hexstrike-ai", source_url="https://github.com/0x4m4/hexstrike-ai",
        trust_level=TrustLevel.COMMUNITY,
        transport="http", endpoint="http://localhost:8888",
        install_command="pip install -r mcp/hexstrike-ai/requirements.txt",
        risk_level="critical", category="security",
        requires_approval=True,
        tags=["security", "pentest", "vulnerability", "bugbounty"],
        dangerous_tools=["*"],  # All tools require approval
        discovered_tools=[
            {"name": "nmap_scan"}, {"name": "nuclei_scan"},
            {"name": "subdomain_enum"}, {"name": "web_scan"},
            {"name": "port_scan"}, {"name": "vulnerability_scan"},
        ],
    ),
    # ── Sequential Thinking (official) ──
    MCPServerEntry(
        id="mcp-sequential-thinking", name="Sequential Thinking MCP",
        description="Official structured thinking MCP — break down complex problems into steps with revision and branching",
        source="modelcontextprotocol/servers", source_url="https://github.com/modelcontextprotocol/servers/tree/main/src/sequentialthinking",
        trust_level=TrustLevel.OFFICIAL,
        transport="stdio", command="npx", args=["-y", "@modelcontextprotocol/server-sequential-thinking"],
        risk_level="low", category="engineering",
        tags=["thinking", "reasoning", "planning", "analysis"],
        discovered_tools=[
            {"name": "sequentialthinking", "description": "Break down complex problems into manageable steps with revision and branching"},
        ],
    ),
    # ── Coding Agent MCP (community) ──
    MCPServerEntry(
        id="mcp-coding-agent", name="Coding Agent MCP",
        description="Coding agent capabilities — file ops, terminal commands, search, and utility operations",
        source="Sukarth/coding-agent-mcp", source_url="https://github.com/Sukarth/coding-agent-mcp",
        trust_level=TrustLevel.COMMUNITY,
        transport="stdio", command="npx", args=["-y", "coding-agent-mcp"],
        risk_level="high", category="engineering",
        requires_approval=True,
        tags=["coding", "agent", "files", "terminal", "search"],
        dangerous_tools=["terminal_command", "write_file", "delete_file"],
        discovered_tools=[
            {"name": "read_file"}, {"name": "write_file"}, {"name": "delete_file"},
            {"name": "terminal_command"}, {"name": "search_files"}, {"name": "list_directory"},
        ],
    ),
    # ── Zep Memory MCP (via Composio) ──
    MCPServerEntry(
        id="mcp-zep", name="Zep Memory MCP",
        description="Zep knowledge graph memory — session memory, user graphs, fact triples, threaded conversations",
        source="composio/zep", source_url="https://composio.dev/toolkits/zep",
        trust_level=TrustLevel.MANAGED,
        transport="stdio", command="npx", args=["-y", "composio-mcp-zep"],
        required_secrets=["ZEP_API_KEY"],
        risk_level="medium", category="data",
        tags=["memory", "knowledge-graph", "sessions", "zep", "composio"],
        dangerous_tools=["delete_graph", "delete_user", "delete_session_memory"],
        discovered_tools=[
            {"name": "add_session_memory"}, {"name": "get_session_memory"},
            {"name": "create_user"}, {"name": "search_graph"},
            {"name": "add_fact_triple"}, {"name": "create_thread"},
            {"name": "get_thread_user_context"}, {"name": "create_graph"},
        ],
    ),
    # ── Context7 (documentation lookup) ──
    MCPServerEntry(
        id="mcp-context7", name="Context7 MCP",
        description="Up-to-date documentation and code examples for libraries and frameworks via Context7",
        source="upstash/context7", source_url="https://github.com/upstash/context7",
        trust_level=TrustLevel.COMMUNITY,
        transport="stdio", command="npx", args=["-y", "@upstash/context7-mcp@latest"],
        risk_level="low", category="engineering",
        tags=["documentation", "context", "libraries", "code_examples"],
        discovered_tools=[
            {"name": "resolve-library-id"}, {"name": "get-library-docs"},
        ],
    ),
    # ── PentestMCP (community security) ──
    MCPServerEntry(
        id="mcp-pentest", name="PentestMCP",
        description="AI-powered pentesting — Nmap, Nuclei, ZAP, SQLMap, 20+ security tools via Docker",
        source="RamKansal/pentestMCP", source_url="https://github.com/RamKansal/pentestMCP",
        trust_level=TrustLevel.COMMUNITY,
        transport="stdio", command="docker",
        args=["run", "--rm", "-i", "pentestmcp:latest"],
        install_command="docker pull ghcr.io/ramkansal/pentestmcp:latest",
        risk_level="critical", category="security",
        requires_approval=True,
        tags=["security", "pentest", "nmap", "nuclei", "zap", "sqlmap"],
        dangerous_tools=["*"],
        discovered_tools=[
            {"name": "nmap_scan"}, {"name": "nuclei_scan"},
            {"name": "zap_scan"}, {"name": "sqlmap_scan"},
            {"name": "gobuster_scan"}, {"name": "nikto_scan"},
            {"name": "whois_lookup"}, {"name": "subdomain_enum"},
        ],
    ),
    # ── HubSpot MCP (via Smithery) ──
    MCPServerEntry(
        id="mcp-hubspot", name="HubSpot CRM MCP",
        description="HubSpot CRM integration — contacts, deals, companies, tickets, engagement tracking",
        source="smithery/hubspot", source_url="https://smithery.ai/servers/hubspot",
        trust_level=TrustLevel.MANAGED,
        transport="stdio", command="npx", args=["-y", "@smithery/mcp-hubspot"],
        required_secrets=["HUBSPOT_ACCESS_TOKEN"],
        risk_level="medium", category="business",
        tags=["crm", "hubspot", "contacts", "deals", "sales", "smithery"],
        dangerous_tools=["create_deal", "update_contact", "delete_contact", "create_ticket"],
        discovered_tools=[
            {"name": "search_contacts"}, {"name": "get_contact"},
            {"name": "create_contact"}, {"name": "search_deals"},
            {"name": "create_deal"}, {"name": "list_companies"},
            {"name": "create_ticket"}, {"name": "get_engagement"},
        ],
    ),
]


# Singleton
_instance: Optional[MCPRegistry] = None
_lock = threading.Lock()


def get_mcp_registry() -> MCPRegistry:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = MCPRegistry()
                _instance.seed_core_stack()
    return _instance
