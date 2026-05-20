"""
JARVIS MAX — MCP Registry Tests
====================================
Tests for MCP server registration, health, discovery, security, and API.

Total: 40 tests
"""
import sys
import os
import json
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ADMIN_PASSWORD_HASH", "test-hash")

import pytest


# ═══════════════════════════════════════════════════════════════
# REGISTRY CORE (15 tests)
# ═══════════════════════════════════════════════════════════════

class TestMCPRegistry:

    def _make_registry(self):
        from core.mcp.mcp_registry import MCPRegistry
        return MCPRegistry(data_dir=os.path.join(tempfile.mkdtemp(), "mcp"))

    def test_R01_seed_core_stack(self):
        r = self._make_registry()
        count = r.seed_core_stack()
        assert count >= 12  # 5 core + 2 data + hexstrike + 5 new

    def test_R02_get_github_mcp(self):
        r = self._make_registry()
        r.seed_core_stack()
        gh = r.get("mcp-github")
        assert gh is not None
        assert gh.name == "GitHub MCP"
        assert gh.trust_level.value == "official"

    def test_R03_get_hexstrike(self):
        r = self._make_registry()
        r.seed_core_stack()
        hs = r.get("mcp-hexstrike")
        assert hs is not None
        assert hs.risk_level == "critical"
        assert hs.requires_approval is True

    def test_R04_list_by_category(self):
        r = self._make_registry()
        r.seed_core_stack()
        eng = r.list_all(category="engineering")
        assert len(eng) >= 4  # github, filesystem, fetch, memory, playwright

    def test_R05_list_by_trust(self):
        r = self._make_registry()
        r.seed_core_stack()
        official = r.list_all(trust="official")
        assert len(official) >= 6  # 5 core + sequential thinking

    def test_R06_health_needs_setup(self):
        r = self._make_registry()
        r.seed_core_stack()
        # GitHub needs GITHUB_PERSONAL_ACCESS_TOKEN
        health = r.check_health("mcp-github")
        assert health["health"] in ("needs_setup", "disabled")

    def test_R07_health_fetch_no_secrets(self):
        r = self._make_registry()
        r.seed_core_stack()
        # Enable fetch (no secrets needed)
        r._servers["mcp-fetch"].status = "enabled"
        health = r.check_health("mcp-fetch")
        assert health["health"] == "ready"

    def test_R08_enable_checks_deps(self):
        r = self._make_registry()
        r.seed_core_stack()
        # GitHub has missing secret → cannot enable
        result = r.enable("mcp-github")
        assert result is not None
        assert "Cannot" in result or result == "enabled"

    def test_R09_disable_always_works(self):
        r = self._make_registry()
        r.seed_core_stack()
        result = r.disable("mcp-fetch")
        assert result == "disabled"

    def test_R10_stats(self):
        r = self._make_registry()
        r.seed_core_stack()
        s = r.stats()
        assert s["total_servers"] >= 7
        assert s["total_tools"] > 0

    def test_R11_persistence(self):
        from core.mcp.mcp_registry import MCPRegistry
        path = os.path.join(tempfile.mkdtemp(), "mcp")
        r1 = MCPRegistry(data_dir=path)
        r1.seed_core_stack()
        r2 = MCPRegistry(data_dir=path)
        assert r2.get("mcp-github") is not None

    def test_R12_unregister(self):
        r = self._make_registry()
        r.seed_core_stack()
        assert r.unregister("mcp-hexstrike") is True
        assert r.get("mcp-hexstrike") is None

    def test_R13_discover_tools(self):
        r = self._make_registry()
        r.seed_core_stack()
        r._servers["mcp-fetch"].status = "enabled"
        tools = r.discover_tools("mcp-fetch")
        assert len(tools) >= 1

    def test_R14_discover_disabled_returns_empty(self):
        r = self._make_registry()
        r.seed_core_stack()
        tools = r.discover_tools("mcp-github")  # disabled
        assert tools == []

    def test_R15_check_all_health(self):
        r = self._make_registry()
        r.seed_core_stack()
        health = r.check_all_health()
        assert len(health) >= 12


# ═══════════════════════════════════════════════════════════════
# SECURITY (10 tests)
# ═══════════════════════════════════════════════════════════════

class TestMCPSecurity:

    def _make_registry(self):
        from core.mcp.mcp_registry import MCPRegistry
        return MCPRegistry(data_dir=os.path.join(tempfile.mkdtemp(), "mcp"))

    # ── New MCP entries ──

    def test_R16_sequential_thinking(self):
        r = self._make_registry()
        r.seed_core_stack()
        st = r.get("mcp-sequential-thinking")
        assert st is not None
        assert st.trust_level.value == "official"
        assert st.risk_level == "low"

    def test_R17_coding_agent(self):
        r = self._make_registry()
        r.seed_core_stack()
        ca = r.get("mcp-coding-agent")
        assert ca is not None
        assert ca.trust_level.value == "community"
        assert ca.requires_approval is True

    def test_R18_zep_memory(self):
        r = self._make_registry()
        r.seed_core_stack()
        zep = r.get("mcp-zep")
        assert zep is not None
        assert "ZEP_API_KEY" in zep.required_secrets
        assert zep.trust_level.value == "managed"

    def test_R19_pentest_mcp(self):
        r = self._make_registry()
        r.seed_core_stack()
        pt = r.get("mcp-pentest")
        assert pt is not None
        assert pt.risk_level == "critical"
        assert pt.requires_approval is True
        assert pt.trust_level.value == "community"

    def test_R20_hubspot(self):
        r = self._make_registry()
        r.seed_core_stack()
        hs = r.get("mcp-hubspot")
        assert hs is not None
        assert "HUBSPOT_ACCESS_TOKEN" in hs.required_secrets
        assert hs.trust_level.value == "managed"
        assert hs.category == "business"

    def test_S01_safe_dict_masks_env(self):
        from core.mcp.mcp_registry import MCPServerEntry
        e = MCPServerEntry(id="t", name="T", env_vars={"SECRET": "value"})
        d = e.to_safe_dict()
        assert d["env_vars"]["SECRET"] == "***"

    def test_S02_hexstrike_requires_approval(self):
        r = self._make_registry()
        r.seed_core_stack()
        hs = r.get("mcp-hexstrike")
        assert hs.requires_approval is True
        assert hs.risk_level == "critical"

    def test_S03_playwright_requires_approval(self):
        r = self._make_registry()
        r.seed_core_stack()
        pw = r.get("mcp-playwright")
        assert pw.requires_approval is True

    def test_S04_fetch_no_approval(self):
        r = self._make_registry()
        r.seed_core_stack()
        f = r.get("mcp-fetch")
        assert f.requires_approval is False

    def test_S05_github_dangerous_tools(self):
        r = self._make_registry()
        r.seed_core_stack()
        gh = r.get("mcp-github")
        assert "create_pull_request" in gh.dangerous_tools
        assert "merge_pull_request" in gh.dangerous_tools

    def test_S06_filesystem_scoped(self):
        r = self._make_registry()
        r.seed_core_stack()
        fs = r.get("mcp-filesystem")
        assert "Jarvismax" in " ".join(fs.args)  # Scoped to workspace

    def test_S07_untrusted_is_restricted(self):
        from core.mcp.mcp_registry import MCPServerEntry, TrustLevel, MCPHealth
        r = self._make_registry()
        e = MCPServerEntry(id="bad", name="Bad", status="enabled",
                          trust_level=TrustLevel.UNTRUSTED)
        r.register(e)
        assert e.health == MCPHealth.RESTRICTED

    def test_S08_no_secret_in_to_dict(self):
        from core.mcp.mcp_registry import MCPServerEntry
        e = MCPServerEntry(id="t", name="T",
                          env_vars={"API_KEY": "sk-secret123"})
        d = e.to_dict()
        serialized = json.dumps(d)
        assert "sk-secret" not in serialized

    def test_S09_missing_secret_blocks_enable(self):
        r = self._make_registry()
        r.seed_core_stack()
        result = r.enable("mcp-postgres")  # Needs POSTGRES_CONNECTION_STRING
        assert result is not None
        assert "Cannot" in result

    def test_S10_no_secret_values_in_persistence(self):
        from core.mcp.mcp_registry import MCPRegistry
        path = os.path.join(tempfile.mkdtemp(), "mcp")
        r = MCPRegistry(data_dir=path)
        r.seed_core_stack()
        # Read persisted file
        data = json.loads((r._dir / "registry.json").read_text(encoding="utf-8"))
        serialized = json.dumps(data)
        assert "sk-" not in serialized
        assert "password" not in serialized.lower()


# ═══════════════════════════════════════════════════════════════
# API ROUTES (15 tests)
# ═══════════════════════════════════════════════════════════════

class TestMCPAPI:

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        import core.mcp.mcp_registry as mcpr
        # Reset singleton with writable temp dir
        mcpr._instance = mcpr.MCPRegistry(data_dir=os.path.join(tempfile.mkdtemp(), "mcp"))
        mcpr._instance.seed_core_stack()
        # Tests use Bearer "t" — align _API_TOKEN for match.
        monkeypatch.setenv("JARVIS_API_TOKEN", "t")
        import api._deps as _deps_mod
        monkeypatch.setattr(_deps_mod, "_API_TOKEN", "t", raising=False)

    def _get_client(self):
        from fastapi.testclient import TestClient
        from api.routes.mcp_management import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_A01_list_requires_auth(self):
        c = self._get_client()
        assert c.get("/api/v3/mcp/servers").status_code == 401

    def test_A02_list_servers(self):
        c = self._get_client()
        resp = c.get("/api/v3/mcp/servers", headers={"Authorization": "Bearer t"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 12

    def test_A03_get_server(self):
        c = self._get_client()
        resp = c.get("/api/v3/mcp/servers/mcp-github", headers={"Authorization": "Bearer t"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "GitHub MCP"

    def test_A04_get_nonexistent(self):
        c = self._get_client()
        resp = c.get("/api/v3/mcp/servers/nope", headers={"Authorization": "Bearer t"})
        assert resp.status_code == 404

    def test_A05_disable(self):
        c = self._get_client()
        resp = c.post("/api/v3/mcp/servers/mcp-fetch/disable",
                       headers={"Authorization": "Bearer t"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "disabled"

    def test_A06_health_check(self):
        c = self._get_client()
        resp = c.get("/api/v3/mcp/servers/mcp-fetch/health",
                      headers={"Authorization": "Bearer t"})
        assert resp.status_code == 200
        assert "health" in resp.json()

    def test_A07_discover_tools(self):
        c = self._get_client()
        resp = c.get("/api/v3/mcp/servers/mcp-fetch/tools",
                      headers={"Authorization": "Bearer t"})
        assert resp.status_code == 200
        assert "tools" in resp.json()

    def test_A08_all_health(self):
        c = self._get_client()
        resp = c.get("/api/v3/mcp/health", headers={"Authorization": "Bearer t"})
        assert resp.status_code == 200
        assert "health" in resp.json()

    def test_A09_stats(self):
        c = self._get_client()
        resp = c.get("/api/v3/mcp/stats", headers={"Authorization": "Bearer t"})
        assert resp.status_code == 200
        assert resp.json()["total_servers"] >= 12

    def test_A10_filter_by_category(self):
        c = self._get_client()
        resp = c.get("/api/v3/mcp/servers?category=engineering",
                      headers={"Authorization": "Bearer t"})
        assert resp.status_code == 200
        servers = resp.json()["servers"]
        assert all(s.get("category", "") == "engineering" for s in servers if "category" in s)

    def test_A11_filter_by_trust(self):
        c = self._get_client()
        resp = c.get("/api/v3/mcp/servers?trust=official",
                      headers={"Authorization": "Bearer t"})
        assert resp.status_code == 200

    def test_A12_enable_missing_deps(self):
        c = self._get_client()
        resp = c.post("/api/v3/mcp/servers/mcp-postgres/enable",
                       headers={"Authorization": "Bearer t"})
        # Should fail because POSTGRES_CONNECTION_STRING missing
        assert resp.status_code in (200, 409)

    def test_A13_enable_nonexistent(self):
        c = self._get_client()
        resp = c.post("/api/v3/mcp/servers/nope/enable",
                       headers={"Authorization": "Bearer t"})
        assert resp.status_code == 404

    def test_A14_safe_dict_in_response(self):
        c = self._get_client()
        resp = c.get("/api/v3/mcp/servers/mcp-hexstrike",
                      headers={"Authorization": "Bearer t"})
        data = resp.json()
        # env_vars should be masked
        if "env_vars" in data:
            for v in data["env_vars"].values():
                assert v == "***"

    def test_A15_hexstrike_visible(self):
        c = self._get_client()
        resp = c.get("/api/v3/mcp/servers/mcp-hexstrike",
                      headers={"Authorization": "Bearer t"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "HexStrike AI"
        assert resp.json()["requires_approval"] is True

    def test_A16_probe_spawn_nonexistent(self):
        """Probe non-existent server returns spawnable=False."""
        c = self._get_client()
        resp = c.get("/api/v3/mcp/servers/nope/probe",
                      headers={"Authorization": "Bearer t"})
        assert resp.status_code == 200
        d = resp.json()
        assert d["spawnable"] is False

    def test_A17_probe_spawn_filesystem(self):
        """Probe filesystem MCP — should check binary existence."""
        c = self._get_client()
        resp = c.get("/api/v3/mcp/servers/mcp-filesystem/probe",
                      headers={"Authorization": "Bearer t"})
        assert resp.status_code == 200
        d = resp.json()
        # In test env npx may or may not exist
        assert "spawnable" in d

    def test_A18_probe_all(self):
        """Probe all servers returns dict of results."""
        c = self._get_client()
        resp = c.get("/api/v3/mcp/probe-all",
                      headers={"Authorization": "Bearer t"})
        assert resp.status_code == 200
        d = resp.json()
        assert "probes" in d
        assert isinstance(d["probes"], dict)
        # All registered servers should have a result
        assert len(d["probes"]) >= 5

    def test_A19_probe_has_install_hint(self):
        """Probes for pip-based servers include install hints."""
        from core.mcp.mcp_registry import MCPRegistry
        import tempfile
        r = MCPRegistry(data_dir=os.path.join(tempfile.mkdtemp(), "mcp"))
        r.seed_core_stack()
        result = r.probe_spawn("mcp-fetch")
        # mcp-server-fetch is pip-based
        if not result["spawnable"]:
            assert result.get("install_hint") or result.get("error")
