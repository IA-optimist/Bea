"""
Tests — Module Manager (45 tests)

Agent CRUD
  MM1.  Create agent simple mode
  MM2.  Create agent advanced mode
  MM3.  Update agent
  MM4.  Delete agent
  MM5.  Toggle agent enabled/disabled
  MM6.  Duplicate agent
  MM7.  List agents
  MM8.  List agents filtered by status
  MM9.  Simple dict hides advanced fields

Skill CRUD
  MM10. Create skill
  MM11. Update skill
  MM12. Delete skill
  MM13. Toggle skill
  MM14. List skills
  MM15. List skills by category

MCP CRUD
  MM16. Create MCP
  MM17. Update MCP
  MM18. Delete MCP
  MM19. Toggle MCP
  MM20. Test MCP (endpoint present)
  MM21. Test MCP (no endpoint)
  MM22. List MCP (secrets masked)

Connector CRUD
  MM23. Create connector
  MM24. Update connector
  MM25. Delete connector
  MM26. Toggle connector
  MM27. Test connector (with identity)
  MM28. Test connector (no credentials)
  MM29. List connectors
  MM30. List connectors by provider

Blueprint Export/Import
  MM31. Export agent blueprint
  MM32. Import agent blueprint
  MM33. Export skill blueprint
  MM34. Import creates new ID
  MM35. Export nonexistent → None

Catalog
  MM36. Catalog has built-in entries
  MM37. Filter catalog by type
  MM38. Install from catalog
  MM39. Catalog sorted by popularity

Health
  MM40. Health summary structure

Persistence
  MM41. Agents persist to disk
  MM42. Skills persist to disk
  MM43. MCP persist to disk
  MM44. Connectors persist to disk
  MM45. Load from persisted data
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.modules.module_manager import (
    ModuleManager,
)


class TestAgentCRUD:

    def _mgr(self, tmp_path):
        return ModuleManager(data_dir=tmp_path / "modules")

    def test_create_simple(self, tmp_path):
        """MM1."""
        mgr = self._mgr(tmp_path)
        agent = mgr.create_agent({"name": "Test Agent", "purpose": "Testing", "model": "gpt-4"})
        assert agent.id.startswith("agent-")
        assert agent.display_name == "Test Agent"
        assert agent.status == "enabled"

    def test_create_advanced(self, tmp_path):
        """MM2."""
        mgr = self._mgr(tmp_path)
        agent = mgr.create_agent({
            "name": "Advanced Agent",
            "system_prompt": "You are a specialized analyst.",
            "behavior_rules": ["Always cite sources"],
            "limits": {"max_tokens": 4000},
        }, mode="advanced")
        assert agent.system_prompt == "You are a specialized analyst."

    def test_update(self, tmp_path):
        """MM3."""
        mgr = self._mgr(tmp_path)
        agent = mgr.create_agent({"name": "Updatable"})
        updated = mgr.update_agent(agent.id, {"display_name": "Updated Name"})
        assert updated.display_name == "Updated Name"

    def test_delete(self, tmp_path):
        """MM4."""
        mgr = self._mgr(tmp_path)
        agent = mgr.create_agent({"name": "Delete Me"})
        assert mgr.delete_agent(agent.id)
        assert mgr.agent_count == 0

    def test_toggle(self, tmp_path):
        """MM5."""
        mgr = self._mgr(tmp_path)
        agent = mgr.create_agent({"name": "Toggle"})
        assert agent.status == "enabled"
        new_status = mgr.toggle_agent(agent.id)
        assert new_status == "disabled"
        new_status = mgr.toggle_agent(agent.id)
        assert new_status == "enabled"

    def test_duplicate(self, tmp_path):
        """MM6."""
        mgr = self._mgr(tmp_path)
        agent = mgr.create_agent({"name": "Original", "model": "gpt-4"})
        copy = mgr.duplicate_agent(agent.id)
        assert copy.id != agent.id
        assert "(Copy)" in copy.display_name
        assert copy.model == agent.model

    def test_list(self, tmp_path):
        """MM7."""
        mgr = self._mgr(tmp_path)
        mgr.create_agent({"name": "A1"})
        mgr.create_agent({"name": "A2"})
        assert len(mgr.list_agents()) == 2

    def test_list_filtered(self, tmp_path):
        """MM8."""
        mgr = self._mgr(tmp_path)
        a1 = mgr.create_agent({"name": "Active"})
        a2 = mgr.create_agent({"name": "Inactive"})
        mgr.toggle_agent(a2.id)
        enabled = mgr.list_agents(status="enabled")
        assert len(enabled) == 1

    def test_simple_dict(self, tmp_path):
        """MM9."""
        mgr = self._mgr(tmp_path)
        agent = mgr.create_agent({"name": "Simple"})
        d = agent.to_simple_dict()
        assert "name" in d
        assert "system_prompt" not in d


class TestSkillCRUD:

    def _mgr(self, tmp_path):
        return ModuleManager(data_dir=tmp_path / "modules")

    def test_create(self, tmp_path):
        """MM10."""
        mgr = self._mgr(tmp_path)
        skill = mgr.create_skill({"name": "Web Search", "category": "research"})
        assert skill.id.startswith("skill-")

    def test_update(self, tmp_path):
        """MM11."""
        mgr = self._mgr(tmp_path)
        skill = mgr.create_skill({"name": "Skill1"})
        updated = mgr.update_skill(skill.id, {"name": "Updated Skill"})
        assert updated.name == "Updated Skill"

    def test_delete(self, tmp_path):
        """MM12."""
        mgr = self._mgr(tmp_path)
        skill = mgr.create_skill({"name": "Temp"})
        assert mgr.delete_skill(skill.id)
        assert mgr.skill_count == 0

    def test_toggle(self, tmp_path):
        """MM13."""
        mgr = self._mgr(tmp_path)
        skill = mgr.create_skill({"name": "Toggle"})
        assert mgr.toggle_skill(skill.id) == "disabled"

    def test_list(self, tmp_path):
        """MM14."""
        mgr = self._mgr(tmp_path)
        mgr.create_skill({"name": "S1"})
        mgr.create_skill({"name": "S2"})
        assert len(mgr.list_skills()) == 2

    def test_list_by_category(self, tmp_path):
        """MM15."""
        mgr = self._mgr(tmp_path)
        mgr.create_skill({"name": "S1", "category": "research"})
        mgr.create_skill({"name": "S2", "category": "coding"})
        assert len(mgr.list_skills(category="research")) == 1


class TestMCPCRUD:

    def _mgr(self, tmp_path):
        return ModuleManager(data_dir=tmp_path / "modules")

    def test_create(self, tmp_path):
        """MM16."""
        mgr = self._mgr(tmp_path)
        mcp = mgr.create_mcp({"name": "Local MCP", "endpoint": "http://localhost:3000"})
        assert mcp.id.startswith("mcp-")

    def test_update(self, tmp_path):
        """MM17."""
        mgr = self._mgr(tmp_path)
        mcp = mgr.create_mcp({"name": "MCP1"})
        updated = mgr.update_mcp(mcp.id, {"display_name": "Updated MCP"})
        assert updated.display_name == "Updated MCP"

    def test_delete(self, tmp_path):
        """MM18."""
        mgr = self._mgr(tmp_path)
        mcp = mgr.create_mcp({"name": "Temp"})
        assert mgr.delete_mcp(mcp.id)

    def test_toggle(self, tmp_path):
        """MM19."""
        mgr = self._mgr(tmp_path)
        mcp = mgr.create_mcp({"name": "Toggle"})
        assert mgr.toggle_mcp(mcp.id) == "disabled"

    def test_test_with_endpoint(self, tmp_path):
        """MM20."""
        mgr = self._mgr(tmp_path)
        mcp = mgr.create_mcp({"name": "MCP", "endpoint": "http://localhost:3000"})
        result = mgr.test_mcp(mcp.id)
        assert result["success"]
        assert result["status"] == "pass"

    def test_test_no_endpoint(self, tmp_path):
        """MM21."""
        mgr = self._mgr(tmp_path)
        mcp = mgr.create_mcp({"name": "Empty MCP"})
        result = mgr.test_mcp(mcp.id)
        assert not result["success"]

    def test_list_masked(self, tmp_path):
        """MM22."""
        mgr = self._mgr(tmp_path)
        mgr.create_mcp({"name": "MCP", "headers": {"Authorization": "Bearer secret123"}})
        listing = mgr.list_mcp()
        assert len(listing) == 1
        assert "secret123" not in str(listing)


class TestConnectorCRUD:

    def _mgr(self, tmp_path):
        return ModuleManager(data_dir=tmp_path / "modules")

    def test_create(self, tmp_path):
        """MM23."""
        mgr = self._mgr(tmp_path)
        conn = mgr.create_connector({"provider": "gmail", "name": "Gmail"})
        assert conn.id.startswith("conn-")

    def test_update(self, tmp_path):
        """MM24."""
        mgr = self._mgr(tmp_path)
        conn = mgr.create_connector({"provider": "github"})
        updated = mgr.update_connector(conn.id, {"display_name": "My GitHub"})
        assert updated.display_name == "My GitHub"

    def test_delete(self, tmp_path):
        """MM25."""
        mgr = self._mgr(tmp_path)
        conn = mgr.create_connector({"provider": "temp"})
        assert mgr.delete_connector(conn.id)

    def test_toggle(self, tmp_path):
        """MM26."""
        mgr = self._mgr(tmp_path)
        conn = mgr.create_connector({"provider": "slack"})
        assert mgr.toggle_connector(conn.id) == "disabled"

    def test_test_with_identity(self, tmp_path):
        """MM27."""
        mgr = self._mgr(tmp_path)
        conn = mgr.create_connector({"provider": "github", "identity": "id-gh"})
        result = mgr.test_connector(conn.id)
        assert result["success"]

    def test_test_no_creds(self, tmp_path):
        """MM28."""
        mgr = self._mgr(tmp_path)
        conn = mgr.create_connector({"provider": "empty"})
        result = mgr.test_connector(conn.id)
        assert not result["success"]

    def test_list(self, tmp_path):
        """MM29."""
        mgr = self._mgr(tmp_path)
        mgr.create_connector({"provider": "gmail"})
        mgr.create_connector({"provider": "github"})
        assert len(mgr.list_connectors()) == 2

    def test_list_by_provider(self, tmp_path):
        """MM30."""
        mgr = self._mgr(tmp_path)
        mgr.create_connector({"provider": "gmail"})
        mgr.create_connector({"provider": "github"})
        assert len(mgr.list_connectors(provider="gmail")) == 1


class TestBlueprint:

    def _mgr(self, tmp_path):
        return ModuleManager(data_dir=tmp_path / "modules")

    def test_export_agent(self, tmp_path):
        """MM31."""
        mgr = self._mgr(tmp_path)
        agent = mgr.create_agent({"name": "Export Me"})
        bp = mgr.export_blueprint("agent", agent.id)
        assert bp["type"] == "agent"
        assert bp["config"]["name"] == "Export Me"

    def test_import_agent(self, tmp_path):
        """MM32."""
        mgr = self._mgr(tmp_path)
        bp = {"type": "agent", "config": {"name": "Imported Agent", "model": "gpt-4"}}
        result = mgr.import_blueprint(bp)
        assert result["success"]
        assert mgr.agent_count == 1

    def test_export_skill(self, tmp_path):
        """MM33."""
        mgr = self._mgr(tmp_path)
        skill = mgr.create_skill({"name": "Export Skill"})
        bp = mgr.export_blueprint("skill", skill.id)
        assert bp["type"] == "skill"

    def test_import_new_id(self, tmp_path):
        """MM34."""
        mgr = self._mgr(tmp_path)
        agent = mgr.create_agent({"name": "Original"})
        bp = mgr.export_blueprint("agent", agent.id)
        result = mgr.import_blueprint(bp)
        assert result["id"] != agent.id
        assert mgr.agent_count == 2

    def test_export_nonexistent(self, tmp_path):
        """MM35."""
        mgr = self._mgr(tmp_path)
        assert mgr.export_blueprint("agent", "nonexistent") is None


class TestCatalog:

    def _mgr(self, tmp_path):
        return ModuleManager(data_dir=tmp_path / "modules")

    def test_catalog_populated(self, tmp_path):
        """MM36."""
        mgr = self._mgr(tmp_path)
        catalog = mgr.get_catalog()
        assert len(catalog) >= 10

    def test_catalog_filter_type(self, tmp_path):
        """MM37."""
        mgr = self._mgr(tmp_path)
        agents = mgr.get_catalog(module_type="agent")
        assert all(e["type"] == "agent" for e in agents)
        assert len(agents) >= 5

    def test_install_from_catalog(self, tmp_path):
        """MM38."""
        mgr = self._mgr(tmp_path)
        result = mgr.install_from_catalog("cat-research")
        assert result["success"]
        assert mgr.agent_count == 1

    def test_catalog_sorted(self, tmp_path):
        """MM39."""
        mgr = self._mgr(tmp_path)
        catalog = mgr.get_catalog()
        pops = [e["popularity"] for e in catalog]
        assert pops == sorted(pops, reverse=True)


class TestHealth:

    def test_summary(self, tmp_path):
        """MM40."""
        mgr = ModuleManager(data_dir=tmp_path / "modules")
        mgr.create_agent({"name": "A"})
        mgr.create_skill({"name": "S"})
        health = mgr.health_summary()
        assert health["agents"]["total"] == 1
        assert health["skills"]["total"] == 1


class TestPersistence:

    def test_agents_persist(self, tmp_path):
        """MM41."""
        mgr = ModuleManager(data_dir=tmp_path / "modules")
        mgr.create_agent({"name": "Persistent"})
        mgr2 = ModuleManager(data_dir=tmp_path / "modules")
        assert mgr2.agent_count == 1

    def test_skills_persist(self, tmp_path):
        """MM42."""
        mgr = ModuleManager(data_dir=tmp_path / "modules")
        mgr.create_skill({"name": "Persistent"})
        mgr2 = ModuleManager(data_dir=tmp_path / "modules")
        assert mgr2.skill_count == 1

    def test_mcp_persist(self, tmp_path):
        """MM43."""
        mgr = ModuleManager(data_dir=tmp_path / "modules")
        mgr.create_mcp({"name": "Persistent"})
        mgr2 = ModuleManager(data_dir=tmp_path / "modules")
        assert mgr2.mcp_count == 1

    def test_connectors_persist(self, tmp_path):
        """MM44."""
        mgr = ModuleManager(data_dir=tmp_path / "modules")
        mgr.create_connector({"provider": "github"})
        mgr2 = ModuleManager(data_dir=tmp_path / "modules")
        assert mgr2.connector_count == 1

    def test_load_full(self, tmp_path):
        """MM45."""
        mgr = ModuleManager(data_dir=tmp_path / "modules")
        mgr.create_agent({"name": "A"})
        mgr.create_skill({"name": "S"})
        mgr.create_mcp({"name": "M"})
        mgr.create_connector({"provider": "p"})
        mgr2 = ModuleManager(data_dir=tmp_path / "modules")
        assert mgr2.agent_count == 1
        assert mgr2.skill_count == 1
        assert mgr2.mcp_count == 1
        assert mgr2.connector_count == 1
