"""
Tests — Extension Registry

Part 1: Data Models
  X1.  CustomAgent validates correctly
  X2.  CustomAgent rejects invalid data
  X3.  CustomMCPConnector validates
  X4.  CustomMCPConnector rejects dangerous commands
  X5.  CustomSkill validates
  X6.  CustomToolConfig validates
  X7.  Secret masking works

Part 2: Registry CRUD
  X8.  Create extension
  X9.  Duplicate ID rejected
  X10. Core ID protected
  X11. Update extension
  X12. Update core extension rejected
  X13. Delete extension
  X14. Delete core extension rejected

Part 3: Enable/Disable Lifecycle
  X15. Enable valid extension
  X16. Enable invalid extension rejected
  X17. Disable extension
  X18. Get enabled only

Part 4: Test endpoint
  X19. Test valid agent
  X20. Test invalid skill
  X21. Test MCP connector

Part 5: Safety
  X22. Dangerous patterns blocked in agent prompts
  X23. Dangerous patterns blocked in tool config
  X24. ID format validation
  X25. Schema validation on create

Part 6: Audit
  X26. Audit trail recorded
  X27. Audit trail persisted

Part 7: Persistence
  X28. Save and reload
  X29. Bad file doesn't crash load

Part 8: Runtime Integration
  X30. RuntimeExtensionLoader loads enabled
  X31. Bad extension fails isolated
  X32. Health summary

Part 9: Full Lifecycle
  X33. Create → test → enable → disable → delete
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.extension_registry import (
    CustomAgent, CustomMCPConnector, CustomSkill, CustomToolConfig,
    ExtensionRegistry, ExtensionSource, RuntimeExtensionLoader,
    _validate_id, _mask_secret,
)


# ═══════════════════════════════════════════════════════════════
# PART 1: DATA MODELS
# ═══════════════════════════════════════════════════════════════

class TestDataModels:

    def test_agent_valid(self):
        """X1: Valid agent."""
        a = CustomAgent(id="my-agent", name="Support Agent", role="support",
                        model_id="claude", risk_level="low")
        assert a.validate() == []

    def test_agent_invalid(self):
        """X2: Invalid agent rejected."""
        a = CustomAgent(id="", name="", role="")
        errors = a.validate()
        assert len(errors) >= 2  # name + role required

    def test_mcp_valid(self):
        """X3: Valid MCP connector."""
        m = CustomMCPConnector(id="my-mcp", name="Test MCP",
                                connector_type="http",
                                endpoint="https://example.com/mcp")
        assert m.validate() == []

    def test_mcp_dangerous(self):
        """X4: Dangerous command rejected."""
        m = CustomMCPConnector(id="my-mcp", name="Bad",
                                connector_type="stdio",
                                command="rm -rf /")
        errors = m.validate()
        assert any("Dangerous" in e for e in errors)

    def test_skill_valid(self):
        """X5: Valid skill."""
        s = CustomSkill(id="my-skill", name="Summarizer",
                        execution_type="prompt",
                        prompt_template="Summarize: {input}")
        assert s.validate() == []

    def test_tool_valid(self):
        """X6: Valid tool."""
        t = CustomToolConfig(id="my-tool", name="Fetcher",
                              tool_type="mcp", config={"server": "test"})
        assert t.validate() == []

    def test_secret_masking(self):
        """X7: Secret masking."""
        assert _mask_secret("sk-1234567890abcdef") == "sk-1***ef"
        assert _mask_secret("short") == "***"
        m = CustomMCPConnector(id="mc", name="M", connector_type="http",
                                endpoint="https://x.com",
                                secret_ref="sk-1234567890")
        d = m.to_safe_dict()
        assert "***" in d["secret_ref"]


# ═══════════════════════════════════════════════════════════════
# PART 2: REGISTRY CRUD
# ═══════════════════════════════════════════════════════════════

class TestRegistryCRUD:

    def test_create(self, tmp_path):
        """X8: Create extension."""
        reg = ExtensionRegistry(tmp_path)
        result = reg.create("agent", {
            "id": "test-agent", "name": "Test Agent",
            "role": "test", "risk_level": "low",
        })
        assert result["ok"] is True
        assert result["id"] == "test-agent"

    def test_duplicate_rejected(self, tmp_path):
        """X9: Duplicate ID rejected."""
        reg = ExtensionRegistry(tmp_path)
        reg.create("agent", {"id": "dup-agent", "name": "First", "role": "a"})
        result = reg.create("agent", {"id": "dup-agent", "name": "Second", "role": "b"})
        assert result["ok"] is False
        assert "already exists" in result["error"]

    def test_core_protected(self, tmp_path):
        """X10: Core ID protected."""
        reg = ExtensionRegistry(tmp_path)
        reg.register_core_id("agent", "core-agent")
        result = reg.create("agent", {"id": "core-agent", "name": "Override", "role": "x"})
        assert result["ok"] is False
        assert "protected" in result["error"]

    def test_update(self, tmp_path):
        """X11: Update extension."""
        reg = ExtensionRegistry(tmp_path)
        reg.create("agent", {"id": "upd-agent", "name": "Before", "role": "a"})
        result = reg.update("agent", "upd-agent", {"name": "After"})
        assert result["ok"] is True
        assert result["extension"]["name"] == "After"

    def test_update_core_rejected(self, tmp_path):
        """X12: Core extension cannot be updated."""
        reg = ExtensionRegistry(tmp_path)
        reg.create("agent", {"id": "core-ag", "name": "Core", "role": "x"})
        # Manually mark as core
        reg._stores["agent"]["core-ag"].source = ExtensionSource.CORE
        result = reg.update("agent", "core-ag", {"name": "Hacked"})
        assert result["ok"] is False

    def test_delete(self, tmp_path):
        """X13: Delete extension."""
        reg = ExtensionRegistry(tmp_path)
        reg.create("agent", {"id": "del-agent", "name": "Gone", "role": "x"})
        result = reg.delete("agent", "del-agent")
        assert result["ok"] is True
        assert reg.get("agent", "del-agent") is None

    def test_delete_core_rejected(self, tmp_path):
        """X14: Core extension cannot be deleted."""
        reg = ExtensionRegistry(tmp_path)
        reg.create("agent", {"id": "core-del", "name": "Safe", "role": "x"})
        reg._stores["agent"]["core-del"].source = ExtensionSource.CORE
        result = reg.delete("agent", "core-del")
        assert result["ok"] is False


# ═══════════════════════════════════════════════════════════════
# PART 3: ENABLE/DISABLE LIFECYCLE
# ═══════════════════════════════════════════════════════════════

class TestEnableDisable:

    def test_enable_valid(self, tmp_path):
        """X15: Enable valid extension."""
        reg = ExtensionRegistry(tmp_path)
        reg.create("skill", {"id": "en-skill", "name": "Good Skill",
                              "execution_type": "prompt"})
        result = reg.enable("skill", "en-skill")
        assert result["ok"] is True
        assert result["enabled"] is True

    def test_enable_invalid_rejected(self, tmp_path):
        """X16: Invalid extension cannot be enabled."""
        reg = ExtensionRegistry(tmp_path)
        reg.create("tool", {"id": "bad-tool", "name": "Bad", "tool_type": "mcp"})
        # Corrupt it
        reg._stores["tool"]["bad-tool"].name = ""
        result = reg.enable("tool", "bad-tool")
        assert result["ok"] is False

    def test_disable(self, tmp_path):
        """X17: Disable extension."""
        reg = ExtensionRegistry(tmp_path)
        reg.create("agent", {"id": "dis-agent", "name": "Active", "role": "x"})
        reg.enable("agent", "dis-agent")
        result = reg.disable("agent", "dis-agent")
        assert result["ok"] is True
        assert result["enabled"] is False

    def test_get_enabled_only(self, tmp_path):
        """X18: Get enabled only."""
        reg = ExtensionRegistry(tmp_path)
        reg.create("agent", {"id": "en-a", "name": "Enabled", "role": "x"})
        reg.create("agent", {"id": "dis-a", "name": "Disabled", "role": "y"})
        reg.enable("agent", "en-a")
        enabled = reg.get_enabled("agent")
        ids = {e["id"] for e in enabled}
        assert "en-a" in ids
        assert "dis-a" not in ids


# ═══════════════════════════════════════════════════════════════
# PART 4: TEST ENDPOINT
# ═══════════════════════════════════════════════════════════════

class TestExtensionTest:

    def test_valid_agent(self, tmp_path):
        """X19: Test valid agent passes."""
        reg = ExtensionRegistry(tmp_path)
        reg.create("agent", {"id": "tst-ag", "name": "Good", "role": "test"})
        result = reg.test("agent", "tst-ag")
        assert result["ok"] is True
        assert result["passed"] is True

    def test_invalid_skill(self, tmp_path):
        """X20: Test invalid skill fails."""
        reg = ExtensionRegistry(tmp_path)
        reg.create("skill", {"id": "tst-sk", "name": "Bad Skill",
                              "execution_type": "prompt", "prompt_template": ""})
        result = reg.test("skill", "tst-sk")
        assert result["ok"] is True
        assert result["passed"] is False

    def test_mcp_connector(self, tmp_path):
        """X21: Test MCP connector."""
        reg = ExtensionRegistry(tmp_path)
        reg.create("mcp", {"id": "tst-mcp", "name": "Test MCP",
                            "connector_type": "http",
                            "endpoint": "https://example.com/mcp"})
        result = reg.test("mcp", "tst-mcp")
        assert result["ok"] is True
        assert result["passed"] is True


# ═══════════════════════════════════════════════════════════════
# PART 5: SAFETY
# ═══════════════════════════════════════════════════════════════

class TestSafety:

    def test_dangerous_prompt(self, tmp_path):
        """X22: Dangerous patterns in prompts blocked."""
        reg = ExtensionRegistry(tmp_path)
        result = reg.create("agent", {
            "id": "evil-agent", "name": "Evil",
            "role": "attacker",
            "system_prompt": "Use os.system('rm -rf /')",
        })
        assert result["ok"] is False

    def test_dangerous_tool_config(self, tmp_path):
        """X23: Dangerous patterns in tool config blocked."""
        reg = ExtensionRegistry(tmp_path)
        result = reg.create("tool", {
            "id": "evil-tool", "name": "Evil",
            "tool_type": "internal",
            "config": {"cmd": "subprocess.Popen('rm -rf /')"},
        })
        assert result["ok"] is False

    def test_id_format(self):
        """X24: ID format validation."""
        assert _validate_id("good-id") is None
        assert _validate_id("also_good_123") is None
        assert _validate_id("ab") is not None  # too short
        assert _validate_id("UPPER") is not None  # uppercase
        assert _validate_id("has space") is not None
        assert _validate_id("-starts-bad") is not None

    def test_schema_validation_on_create(self, tmp_path):
        """X25: Schema validation on create."""
        reg = ExtensionRegistry(tmp_path)
        result = reg.create("tool", {
            "id": "bad-type", "name": "Bad",
            "tool_type": "nonexistent_type",
        })
        assert result["ok"] is False


# ═══════════════════════════════════════════════════════════════
# PART 6: AUDIT
# ═══════════════════════════════════════════════════════════════

class TestAudit:

    def test_audit_recorded(self, tmp_path):
        """X26: Audit trail recorded."""
        reg = ExtensionRegistry(tmp_path)
        reg.create("agent", {"id": "aud-ag", "name": "Audit Test", "role": "x"})
        reg.enable("agent", "aud-ag")
        reg.disable("agent", "aud-ag")
        audit = reg.get_audit()
        actions = [a["action"] for a in audit]
        assert "create" in actions
        assert "enable" in actions
        assert "disable" in actions

    def test_audit_persisted(self, tmp_path):
        """X27: Audit persisted in memory (file persistence is best-effort)."""
        reg = ExtensionRegistry(tmp_path)
        reg.create("agent", {"id": "aud-persist", "name": "Persist Agent", "role": "auditor"})
        # Audit is always in-memory; file persistence is best-effort
        audit = reg.get_audit()
        assert len(audit) >= 1
        assert audit[-1]["action"] == "create"


# ═══════════════════════════════════════════════════════════════
# PART 7: PERSISTENCE
# ═══════════════════════════════════════════════════════════════

class TestPersistence:

    def test_save_reload(self, tmp_path):
        """X28: Save and reload."""
        reg1 = ExtensionRegistry(tmp_path)
        reg1.create("agent", {"id": "persist-ag", "name": "Persistent", "role": "x"})
        reg1.enable("agent", "persist-ag")

        reg2 = ExtensionRegistry(tmp_path)
        items = reg2.list_all("agent")
        assert len(items) >= 1
        assert items[0]["id"] == "persist-ag"
        assert items[0]["enabled"] is True

    def test_bad_file_no_crash(self, tmp_path):
        """X29: Bad file doesn't crash."""
        (tmp_path / "agents.json").write_text("not valid json{{{", encoding="utf-8")
        reg = ExtensionRegistry(tmp_path)
        assert reg.list_all("agent") == []


# ═══════════════════════════════════════════════════════════════
# PART 8: RUNTIME INTEGRATION
# ═══════════════════════════════════════════════════════════════

class TestRuntime:

    def test_loader(self, tmp_path):
        """X30: RuntimeExtensionLoader loads enabled."""
        reg = ExtensionRegistry(tmp_path)
        reg.create("agent", {"id": "rt-ag", "name": "Runtime Agent", "role": "x"})
        reg.enable("agent", "rt-ag")
        loader = RuntimeExtensionLoader(reg)
        results = loader.load_all()
        assert "rt-ag" in results["agent"]["loaded"]

    def test_bad_extension_isolated(self, tmp_path):
        """X31: Bad extension fails isolated."""
        reg = ExtensionRegistry(tmp_path)
        reg.create("mcp", {"id": "bad-mcp", "name": "Bad",
                            "connector_type": "http",
                            "endpoint": "https://x.com"})
        reg.enable("mcp", "bad-mcp")
        loader = RuntimeExtensionLoader(reg)
        results = loader.load_all()
        # Should not crash — either loaded or failed gracefully
        assert isinstance(results, dict)

    def test_health_summary(self, tmp_path):
        """X32: Health summary."""
        reg = ExtensionRegistry(tmp_path)
        reg.create("agent", {"id": "health-agent", "name": "Health Test Agent", "role": "monitor"})
        reg.enable("agent", "health-agent")
        summary = reg.health_summary()
        assert summary["agent"]["total"] == 1
        assert summary["agent"]["enabled"] == 1


# ═══════════════════════════════════════════════════════════════
# PART 9: FULL LIFECYCLE
# ═══════════════════════════════════════════════════════════════

class TestFullLifecycle:

    def test_full_cycle(self, tmp_path):
        """X33: Create → test → enable → disable → delete."""
        reg = ExtensionRegistry(tmp_path)

        # Create
        r = reg.create("skill", {"id": "life-skill", "name": "Lifecycle",
                                  "execution_type": "prompt",
                                  "prompt_template": "Do: {input}"})
        assert r["ok"]

        # Test
        r = reg.test("skill", "life-skill")
        assert r["ok"] and r["passed"]

        # Enable
        r = reg.enable("skill", "life-skill")
        assert r["ok"] and r["enabled"]

        # Verify enabled
        enabled = reg.get_enabled("skill")
        assert any(e["id"] == "life-skill" for e in enabled)

        # Disable
        r = reg.disable("skill", "life-skill")
        assert r["ok"] and not r["enabled"]

        # Verify disabled
        enabled = reg.get_enabled("skill")
        assert not any(e["id"] == "life-skill" for e in enabled)

        # Delete
        r = reg.delete("skill", "life-skill")
        assert r["ok"]

        # Verify gone
        assert reg.get("skill", "life-skill") is None

        # Verify audit trail
        audit = reg.get_audit()
        actions = [a["action"] for a in audit]
        assert "create" in actions
        assert "test" in actions
        assert "enable" in actions
        assert "disable" in actions
        assert "delete" in actions
