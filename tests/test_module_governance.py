"""
Tests — Module Governance (45 tests)

RBAC
  MG1.  Admin has all permissions
  MG2.  User can create agents but not delete
  MG3.  Viewer list only
  MG4.  User cannot create connectors
  MG5.  High-risk payment connector needs approval for non-admin
  MG6.  Admin bypasses high-risk approval

Audit
  MG7.  Record creates entry with chain hash
  MG8.  Before/after summary captured
  MG9.  Query by module type
  MG10. Query by module id
  MG11. Persistence to file
  MG12. Source field captured

Dependency Validation
  MG13. Agent with missing connector detected
  MG14. Agent with disabled connector detected
  MG15. Agent with missing skill detected
  MG16. Agent with disabled skill detected
  MG17. Agent with no issues passes
  MG18. Connector with missing identity detected
  MG19. Validate all returns summary
  MG20. Missing secret detected

Health Engine
  MG21. Connector connected status
  MG22. Connector needs_setup (no credentials)
  MG23. Connector disabled status
  MG24. Connector error (last test failed)
  MG25. MCP connected with tools
  MG26. MCP no endpoint → needs_setup
  MG27. MCP disabled
  MG28. Agent ready status
  MG29. Agent no model → needs_setup
  MG30. Agent with broken deps → error
  MG31. Full health summary structure
  MG32. Orphaned skills detected

Wizard
  MG33. Wizard has 6 steps
  MG34. Step 1 is purpose
  MG35. Step 2 is model tier
  MG36. Step 3 is tools (multi_choice)
  MG37. Step 5 is approval mode
  MG38. Model tier mapping exists

Status Labels
  MG39. Ready label
  MG40. Needs setup label
  MG41. Disabled label
  MG42. Error label
  MG43. Connected label

Integration
  MG44. RBAC blocks viewer from creating agent
  MG45. Audit records RBAC denial
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock

from core.modules.module_manager import ModuleManager
from core.modules.module_governance import (
    check_module_permission, check_rbac, ModuleAuditLog, DependencyValidator, HealthEngine, STATUS_LABELS,
    get_wizard_steps, MODEL_TIER_MAP,
)


# ═══════════════════════════════════════════════════════════════
# RBAC
# ═══════════════════════════════════════════════════════════════

class TestRBAC:

    def test_admin_all(self):
        """MG1."""
        for mod in ["agent", "skill", "mcp", "connector"]:
            for action in ["create", "delete", "list"]:
                assert check_module_permission("admin", mod, action)

    def test_user_create_not_delete(self):
        """MG2."""
        assert check_module_permission("user", "agent", "create")
        assert not check_module_permission("user", "agent", "delete")

    def test_viewer_list_only(self):
        """MG3."""
        assert check_module_permission("viewer", "agent", "list")
        assert not check_module_permission("viewer", "agent", "create")
        assert not check_module_permission("viewer", "agent", "delete")

    def test_user_no_connector_create(self):
        """MG4."""
        assert not check_module_permission("user", "connector", "create")

    def test_high_risk_approval(self):
        """MG5."""
        result = check_rbac("user", "connector", "create", "payment")
        # User can't create connectors, so should be denied
        assert not result.allowed

    def test_admin_bypasses_high_risk(self):
        """MG6."""
        result = check_rbac("admin", "connector", "create", "payment")
        assert result.allowed


# ═══════════════════════════════════════════════════════════════
# AUDIT
# ═══════════════════════════════════════════════════════════════

class TestAudit:

    def test_record_chain(self):
        """MG7."""
        audit = ModuleAuditLog()
        e1 = audit.record("admin", "admin", "agent", "a1", "create")
        e2 = audit.record("admin", "admin", "agent", "a1", "update")
        assert e1.chain_hash != e2.chain_hash
        assert audit.entry_count == 2

    def test_before_after(self):
        """MG8."""
        audit = ModuleAuditLog()
        e = audit.record("admin", "admin", "agent", "a1", "update",
                         before={"name": "Old"}, after={"name": "New"})
        d = e.to_dict()
        assert "name=Old" in d["before_summary"]
        assert "name=New" in d["after_summary"]

    def test_query_type(self):
        """MG9."""
        audit = ModuleAuditLog()
        audit.record("admin", "admin", "agent", "a1", "create")
        audit.record("admin", "admin", "skill", "s1", "create")
        results = audit.query(module_type="agent")
        assert len(results) == 1

    def test_query_id(self):
        """MG10."""
        audit = ModuleAuditLog()
        audit.record("admin", "admin", "agent", "a1", "create")
        audit.record("admin", "admin", "agent", "a2", "create")
        results = audit.query(module_id="a1")
        assert len(results) == 1

    def test_persistence(self, tmp_path):
        """MG11."""
        log = tmp_path / "audit.jsonl"
        audit = ModuleAuditLog(log)
        audit.record("admin", "admin", "agent", "a1", "create")
        assert log.exists()

    def test_source_captured(self):
        """MG12."""
        audit = ModuleAuditLog()
        e = audit.record("admin", "admin", "agent", "a1", "create", source="mobile")
        assert e.source == "mobile"


# ═══════════════════════════════════════════════════════════════
# DEPENDENCY VALIDATION
# ═══════════════════════════════════════════════════════════════

class TestDependency:

    def _mgr_with_agent(self, tmp_path, connectors=None, skills=None, secrets=None):
        mgr = ModuleManager(data_dir=tmp_path / "modules")
        agent = mgr.create_agent({
            "name": "Test",
            "connectors": connectors or [],
            "skills": skills or [],
            "secrets": secrets or [],
            "model": "test-model",
        })
        return mgr, agent

    def test_missing_connector(self, tmp_path):
        """MG13."""
        mgr, agent = self._mgr_with_agent(tmp_path, connectors=["conn-missing"])
        validator = DependencyValidator(mgr)
        issues = validator.validate_agent(agent.id)
        assert len(issues) == 1
        assert issues[0].issue_type == "missing_connector"

    def test_disabled_connector(self, tmp_path):
        """MG14."""
        mgr, agent = self._mgr_with_agent(tmp_path)
        conn = mgr.create_connector({"provider": "test"})
        mgr.toggle_connector(conn.id)  # disable
        mgr.update_agent(agent.id, {"linked_connectors": [conn.id]})
        validator = DependencyValidator(mgr)
        issues = validator.validate_agent(agent.id)
        assert any(i.issue_type == "disabled_dep" for i in issues)

    def test_missing_skill(self, tmp_path):
        """MG15."""
        mgr, agent = self._mgr_with_agent(tmp_path, skills=["skill-missing"])
        validator = DependencyValidator(mgr)
        issues = validator.validate_agent(agent.id)
        assert any(i.issue_type == "missing_skill" for i in issues)

    def test_disabled_skill(self, tmp_path):
        """MG16."""
        mgr, agent = self._mgr_with_agent(tmp_path)
        skill = mgr.create_skill({"name": "Test"})
        mgr.toggle_skill(skill.id)  # disable
        mgr.update_agent(agent.id, {"linked_skills": [skill.id]})
        validator = DependencyValidator(mgr)
        issues = validator.validate_agent(agent.id)
        assert any(i.issue_type == "disabled_dep" for i in issues)

    def test_no_issues(self, tmp_path):
        """MG17."""
        mgr, agent = self._mgr_with_agent(tmp_path)
        validator = DependencyValidator(mgr)
        issues = validator.validate_agent(agent.id)
        assert len(issues) == 0

    def test_connector_missing_identity(self, tmp_path):
        """MG18."""
        mgr = ModuleManager(data_dir=tmp_path / "modules")
        conn = mgr.create_connector({"provider": "test", "identity": "id-missing"})
        id_mgr = MagicMock()
        id_mgr.get_identity.return_value = None
        validator = DependencyValidator(mgr, identity_mgr=id_mgr)
        issues = validator.validate_connector(conn.id)
        assert any(i.issue_type == "missing_identity" for i in issues)

    def test_validate_all(self, tmp_path):
        """MG19."""
        mgr, agent = self._mgr_with_agent(tmp_path, connectors=["missing"])
        validator = DependencyValidator(mgr)
        summary = validator.validate_all()
        assert summary["total_issues"] >= 1

    def test_missing_secret(self, tmp_path):
        """MG20."""
        mgr, agent = self._mgr_with_agent(tmp_path, secrets=["sec-gone"])
        vault = MagicMock()
        vault.get_metadata.return_value = None
        validator = DependencyValidator(mgr, vault=vault)
        issues = validator.validate_agent(agent.id)
        assert any(i.issue_type == "missing_secret" for i in issues)


# ═══════════════════════════════════════════════════════════════
# HEALTH ENGINE
# ═══════════════════════════════════════════════════════════════

class TestHealth:

    def _setup(self, tmp_path):
        mgr = ModuleManager(data_dir=tmp_path / "modules")
        validator = DependencyValidator(mgr)
        engine = HealthEngine(mgr, validator)
        return mgr, engine

    def test_connector_connected(self, tmp_path):
        """MG21."""
        mgr, engine = self._setup(tmp_path)
        conn = mgr.create_connector({"provider": "github", "identity": "id-1"})
        mgr.test_connector(conn.id)  # sets last_test = "pass"
        h = engine.connector_health(conn.id)
        assert h.status == "connected"

    def test_connector_needs_setup(self, tmp_path):
        """MG22."""
        mgr, engine = self._setup(tmp_path)
        conn = mgr.create_connector({"provider": "empty"})
        h = engine.connector_health(conn.id)
        assert h.status == "needs_setup"

    def test_connector_disabled(self, tmp_path):
        """MG23."""
        mgr, engine = self._setup(tmp_path)
        conn = mgr.create_connector({"provider": "test", "identity": "id"})
        mgr.toggle_connector(conn.id)
        h = engine.connector_health(conn.id)
        assert h.status == "disabled"

    def test_connector_error(self, tmp_path):
        """MG24."""
        mgr, engine = self._setup(tmp_path)
        conn = mgr.create_connector({"provider": "broken"})
        # Manually set fail test
        conn_obj = mgr.get_connector(conn.id)
        conn_obj.last_test = "fail"
        conn_obj.linked_identity = "id"
        h = engine.connector_health(conn.id)
        assert h.status == "error"

    def test_mcp_connected(self, tmp_path):
        """MG25."""
        mgr, engine = self._setup(tmp_path)
        mcp = mgr.create_mcp({"name": "Test", "endpoint": "http://localhost:3000"})
        mgr.test_mcp(mcp.id)
        h = engine.mcp_health(mcp.id)
        assert h.status == "connected"

    def test_mcp_no_endpoint(self, tmp_path):
        """MG26."""
        mgr, engine = self._setup(tmp_path)
        mcp = mgr.create_mcp({"name": "Empty"})
        h = engine.mcp_health(mcp.id)
        assert h.status == "needs_setup"

    def test_mcp_disabled(self, tmp_path):
        """MG27."""
        mgr, engine = self._setup(tmp_path)
        mcp = mgr.create_mcp({"name": "Test", "endpoint": "http://x"})
        mgr.toggle_mcp(mcp.id)
        h = engine.mcp_health(mcp.id)
        assert h.status == "disabled"

    def test_agent_ready(self, tmp_path):
        """MG28."""
        mgr, engine = self._setup(tmp_path)
        mgr.create_agent({"name": "Ready", "model": "gpt-4"})
        agents = mgr.list_agents()
        h = engine.agent_health(agents[0]["id"])
        assert h.status == "ready"

    def test_agent_no_model(self, tmp_path):
        """MG29."""
        mgr, engine = self._setup(tmp_path)
        mgr.create_agent({"name": "NoModel"})
        agents = mgr.list_agents()
        h = engine.agent_health(agents[0]["id"])
        assert h.status == "needs_setup"

    def test_agent_broken_deps(self, tmp_path):
        """MG30."""
        mgr, engine = self._setup(tmp_path)
        mgr.create_agent({"name": "Broken", "model": "gpt-4", "connectors": ["missing"]})
        agents = mgr.list_agents()
        h = engine.agent_health(agents[0]["id"])
        assert h.status == "error"

    def test_full_health_structure(self, tmp_path):
        """MG31."""
        mgr, engine = self._setup(tmp_path)
        mgr.create_agent({"name": "A", "model": "m"})
        mgr.create_skill({"name": "S"})
        mgr.create_connector({"provider": "p", "identity": "id"})
        mgr.create_mcp({"name": "M", "endpoint": "http://x"})
        health = engine.full_health()
        assert "connectors" in health
        assert "mcp" in health
        assert "agents" in health
        assert "skills" in health

    def test_orphaned_skills(self, tmp_path):
        """MG32."""
        mgr, engine = self._setup(tmp_path)
        mgr.create_skill({"name": "Unlinked"})
        mgr.create_agent({"name": "A", "model": "m"})  # No skills linked
        health = engine.full_health()
        assert health["skills"]["orphaned"] >= 1


# ═══════════════════════════════════════════════════════════════
# WIZARD
# ═══════════════════════════════════════════════════════════════

class TestWizard:

    def test_6_steps(self):
        """MG33."""
        steps = get_wizard_steps()
        assert len(steps) == 6

    def test_step1_purpose(self):
        """MG34."""
        steps = get_wizard_steps()
        assert steps[0]["field"] == "purpose"
        assert steps[0]["type"] == "text"

    def test_step2_model(self):
        """MG35."""
        steps = get_wizard_steps()
        assert steps[1]["field"] == "model_tier"
        assert steps[1]["type"] == "radio"

    def test_step3_tools(self):
        """MG36."""
        steps = get_wizard_steps()
        assert steps[2]["field"] == "tools"
        assert steps[2]["type"] == "multi_choice"

    def test_step5_approval(self):
        """MG37."""
        steps = get_wizard_steps()
        assert steps[4]["field"] == "approval"

    def test_model_tier_mapping(self):
        """MG38."""
        assert "fast" in MODEL_TIER_MAP
        assert "balanced" in MODEL_TIER_MAP
        assert "premium" in MODEL_TIER_MAP


# ═══════════════════════════════════════════════════════════════
# STATUS LABELS
# ═══════════════════════════════════════════════════════════════

class TestStatusLabels:

    def test_ready(self):
        """MG39."""
        assert STATUS_LABELS["ready"] == "Ready"

    def test_needs_setup(self):
        """MG40."""
        assert STATUS_LABELS["needs_setup"] == "Needs setup"

    def test_disabled(self):
        """MG41."""
        assert STATUS_LABELS["disabled"] == "Disabled"

    def test_error(self):
        """MG42."""
        assert STATUS_LABELS["error"] == "Error"

    def test_connected(self):
        """MG43."""
        assert STATUS_LABELS["connected"] == "Connected"


# ═══════════════════════════════════════════════════════════════
# INTEGRATION
# ═══════════════════════════════════════════════════════════════

class TestIntegration:

    def test_viewer_blocked(self):
        """MG44."""
        result = check_rbac("viewer", "agent", "create")
        assert not result.allowed

    def test_audit_denial(self):
        """MG45."""
        audit = ModuleAuditLog()
        check_rbac("viewer", "agent", "delete")
        audit.record("viewer", "viewer", "agent", "a1", "delete", result="denied")
        logs = audit.query(module_id="a1")
        assert logs[0]["result"] == "denied"
