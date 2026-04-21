"""
Tests — Identity Manager (45 tests)

Schema
  IM1.  Identity to_dict has no secret values
  IM2.  Identity types enum complete
  IM3.  is_active / is_high_risk properties
  IM4.  mark_used updates timestamp
  IM5.  SecretLink structure

Templates
  IM6.  Gmail template exists with required fields
  IM7.  Stripe template is critical risk
  IM8.  GitHub template has token secret type
  IM9.  All 14 templates registered
  IM10. Template field validation
  IM11. Custom template registration
  IM12. list_templates returns all

Policy
  IM13. Admin has all identity permissions
  IM14. Operator limited to use+list+link
  IM15. Viewer list only
  IM16. Agent use only
  IM17. Environment isolation (no cross-env by default)
  IM18. Rate limit enforcement
  IM19. Inactive identity denied

Graph
  IM20. Add nodes and edges
  IM21. Link identity to service
  IM22. Link identity to domain
  IM23. Get connections returns in/out
  IM24. Rotation cascade (BFS)
  IM25. Graph export to dict

Audit
  IM26. Record creates entry with chain hash
  IM27. Query by identity_id
  IM28. Query by action
  IM29. Persistence to file

Manager Integration
  IM30. Create identity from template
  IM31. Create identity with vault secrets
  IM32. Create identity validates required fields
  IM33. High-risk identity gets approval status
  IM34. Use identity retrieves vault secrets
  IM35. Use identity denied for wrong environment
  IM36. Use identity denied for revoked
  IM37. Link to service updates graph
  IM38. Rotate secret updates vault
  IM39. Revoke cascades to vault secrets
  IM40. Delete removes identity + secrets
  IM41. List filters by environment
  IM42. List filters by provider
  IM43. Get graph returns structure
  IM44. Audit logs recorded for all actions
  IM45. Persistence roundtrip
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock

from core.identity.identity_schema import (
    Identity, IdentityType, SecretLink,
)
from core.identity.identity_templates import (
    get_template, list_templates, register_template, template_providers,
    IdentityTemplate, TEMPLATES,
)
from core.identity.identity_policy import (
    IdentityPolicy, IdentityPolicyEngine, check_identity_permission,
)
from core.identity.identity_graph import IdentityGraph
from core.identity.identity_audit import IdentityAuditLog, IdentityAction
from core.identity.identity_manager import IdentityManager


# ═══════════════════════════════════════════════════════════════
# SCHEMA
# ═══════════════════════════════════════════════════════════════

class TestSchema:

    def test_to_dict_no_secrets(self):
        """IM1."""
        i = Identity(
            identity_id="id-test", identity_type="api_account",
            display_name="Test", provider="github",
            linked_secrets=["sec-abc", "sec-def"],
        )
        d = i.to_dict()
        # Only count of secrets, not the IDs
        assert d["linked_secrets"] == 2
        assert "sec-abc" not in str(d)

    def test_identity_types(self):
        """IM2."""
        types = [e.value for e in IdentityType]
        assert "email_account" in types
        assert "payment_account" in types
        assert "developer_account" in types
        assert len(types) == 7

    def test_properties(self):
        """IM3."""
        active = Identity("id-1", "api_account", "test", "test", status="active", risk_level="high")
        assert active.is_active
        assert active.is_high_risk
        inactive = Identity("id-2", "api_account", "test", "test", status="revoked", risk_level="low")
        assert not inactive.is_active
        assert not inactive.is_high_risk

    def test_mark_used(self):
        """IM4."""
        i = Identity("id-1", "api_account", "test", "test")
        assert i.last_used_at is None
        i.mark_used()
        assert i.last_used_at is not None

    def test_secret_link(self):
        """IM5."""
        link = SecretLink(secret_id="sec-1", secret_role="api_key", identity_id="id-1")
        d = link.to_dict()
        assert d["secret_id"] == "sec-1"
        assert d["role"] == "api_key"


# ═══════════════════════════════════════════════════════════════
# TEMPLATES
# ═══════════════════════════════════════════════════════════════

class TestTemplates:

    def test_gmail(self):
        """IM6."""
        t = get_template("gmail")
        assert t is not None
        assert "email" in t.required_fields
        assert "password" in t.required_fields
        assert t.risk_level == "high"

    def test_stripe_critical(self):
        """IM7."""
        t = get_template("stripe")
        assert t.risk_level == "critical"
        assert t.requires_approval

    def test_github_token(self):
        """IM8."""
        t = get_template("github")
        roles = [s["role"] for s in t.secret_types]
        assert "token" in roles

    def test_all_14_templates(self):
        """IM9."""
        providers = template_providers()
        assert len(providers) >= 14
        for expected in ["gmail", "stripe", "github", "vercel", "supabase",
                         "notion", "slack", "discord", "telegram", "cloudflare",
                         "namecheap", "openrouter", "anthropic", "openai"]:
            assert expected in providers

    def test_field_validation(self):
        """IM10."""
        t = get_template("gmail")
        ok, missing = t.validate_fields({"email": "test@test.com", "password": "pass"})
        assert ok
        ok, missing = t.validate_fields({"email": "test@test.com"})
        assert not ok
        assert "password" in missing

    def test_custom_template(self):
        """IM11."""
        custom = IdentityTemplate(
            provider="custom_saas",
            display_name="Custom SaaS",
            identity_type="saas_account",
            required_fields=["api_key"],
        )
        register_template(custom)
        assert get_template("custom_saas") is not None
        # Cleanup
        TEMPLATES.pop("custom_saas", None)

    def test_list_templates(self):
        """IM12."""
        templates = list_templates()
        assert len(templates) >= 14
        assert all("provider" in t for t in templates)


# ═══════════════════════════════════════════════════════════════
# POLICY
# ═══════════════════════════════════════════════════════════════

class TestPolicy:

    def test_admin_all(self):
        """IM13."""
        for action in ["create", "update", "delete", "use", "reveal", "list", "link", "rotate", "revoke", "logs"]:
            assert check_identity_permission("admin", action)

    def test_operator_limited(self):
        """IM14."""
        assert check_identity_permission("operator", "use")
        assert check_identity_permission("operator", "list")
        assert check_identity_permission("operator", "link")
        assert not check_identity_permission("operator", "create")
        assert not check_identity_permission("operator", "delete")

    def test_viewer_list_only(self):
        """IM15."""
        assert check_identity_permission("viewer", "list")
        assert not check_identity_permission("viewer", "use")

    def test_agent_use_only(self):
        """IM16."""
        assert check_identity_permission("agent", "use")
        assert not check_identity_permission("agent", "list")

    def test_environment_isolation(self):
        """IM17."""
        engine = IdentityPolicyEngine()
        policy = IdentityPolicy(allow_cross_env=False)
        ok, _ = engine.check_use("id-1", "active", "dev", policy, "agent", "prod")
        assert not ok
        ok, _ = engine.check_use("id-1", "active", "prod", policy, "agent", "prod")
        assert ok

    def test_rate_limit(self):
        """IM18."""
        engine = IdentityPolicyEngine()
        policy = IdentityPolicy(max_uses_per_hour=3)
        for _ in range(3):
            ok, _ = engine.check_use("id-rl", "active", "prod", policy, "agent", "prod")
            assert ok
        ok, reason = engine.check_use("id-rl", "active", "prod", policy, "agent", "prod")
        assert not ok

    def test_inactive_denied(self):
        """IM19."""
        engine = IdentityPolicyEngine()
        policy = IdentityPolicy()
        ok, reason = engine.check_use("id-1", "revoked", "prod", policy, "agent", "prod")
        assert not ok
        assert "not active" in reason.lower()


# ═══════════════════════════════════════════════════════════════
# GRAPH
# ═══════════════════════════════════════════════════════════════

class TestGraph:

    def test_add_nodes_edges(self):
        """IM20."""
        g = IdentityGraph()
        g.add_node("id-1", "identity", "Gmail")
        g.add_node("gmail.com", "service", "Gmail Service")
        g.add_edge("id-1", "gmail.com", "authenticates")
        assert g.node_count == 2
        assert g.edge_count == 1

    def test_link_to_service(self):
        """IM21."""
        g = IdentityGraph()
        g.add_node("id-1", "identity")
        g.link_identity_to_service("id-1", "api.stripe.com")
        assert g.node_count == 2  # id-1 + auto-created service

    def test_link_to_domain(self):
        """IM22."""
        g = IdentityGraph()
        g.add_node("id-1", "identity")
        g.link_identity_to_domain("id-1", "example.com")
        edges = [e for e in g._edges if e.edge_type == "owns_domain"]
        assert len(edges) == 1

    def test_connections(self):
        """IM23."""
        g = IdentityGraph()
        g.add_node("id-1", "identity")
        g.link_identity_to_service("id-1", "svc-a")
        g.link_identity_to_service("id-1", "svc-b")
        conn = g.get_connections("id-1")
        assert conn["total"] == 2
        assert len(conn["outgoing"]) == 2

    def test_rotation_cascade(self):
        """IM24."""
        g = IdentityGraph()
        g.add_node("id-1", "identity")
        g.add_node("svc-a", "service")
        g.add_node("svc-b", "service")
        g.add_edge("id-1", "svc-a", "authenticates")
        g.add_edge("svc-a", "svc-b", "delegates_to")
        cascade = g.find_rotation_cascade("id-1")
        assert "svc-a" in cascade
        assert "svc-b" in cascade

    def test_export(self):
        """IM25."""
        g = IdentityGraph()
        g.add_node("id-1", "identity")
        g.link_identity_to_service("id-1", "svc")
        d = g.to_dict()
        assert d["node_count"] == 2
        assert d["edge_count"] == 1


# ═══════════════════════════════════════════════════════════════
# AUDIT
# ═══════════════════════════════════════════════════════════════

class TestAudit:

    def test_record_chain(self):
        """IM26."""
        audit = IdentityAuditLog()
        e1 = audit.record(IdentityAction.CREATE, "id-1", "admin")
        e2 = audit.record(IdentityAction.USE, "id-1", "coder")
        assert e1.chain_hash
        assert e2.chain_hash
        assert e1.chain_hash != e2.chain_hash

    def test_query_by_id(self):
        """IM27."""
        audit = IdentityAuditLog()
        audit.record(IdentityAction.CREATE, "id-1", "admin")
        audit.record(IdentityAction.CREATE, "id-2", "admin")
        results = audit.query(identity_id="id-1")
        assert len(results) == 1

    def test_query_by_action(self):
        """IM28."""
        audit = IdentityAuditLog()
        audit.record(IdentityAction.CREATE, "id-1", "admin")
        audit.record(IdentityAction.USE, "id-1", "agent")
        results = audit.query(action=IdentityAction.CREATE)
        assert len(results) == 1

    def test_persistence(self, tmp_path):
        """IM29."""
        log = tmp_path / "audit.jsonl"
        audit = IdentityAuditLog(log)
        audit.record(IdentityAction.CREATE, "id-1", "admin")
        assert log.exists()


# ═══════════════════════════════════════════════════════════════
# MANAGER INTEGRATION
# ═══════════════════════════════════════════════════════════════

class TestManagerIntegration:

    def _manager(self, tmp_path, vault=None):
        return IdentityManager(vault=vault, data_dir=tmp_path / "identity")

    def _mock_vault(self):
        vault = MagicMock()
        mock_meta = MagicMock()
        mock_meta.secret_id = "sec-mock-1"
        vault.create_secret.return_value = mock_meta
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.safe_dict.return_value = {"success": True, "secret_id": "sec-mock-1"}
        vault.use_secret.return_value = mock_result
        vault.update_secret.return_value = True
        vault.revoke_secret.return_value = True
        vault.delete_secret.return_value = True
        return vault

    def test_create_from_template(self, tmp_path):
        """IM30."""
        mgr = self._manager(tmp_path)
        identity = mgr.create_identity(
            provider="github",
            fields={"username": "jarvis-bot"},
            display_name="Jarvis GitHub",
        )
        assert identity.identity_id.startswith("id-")
        assert identity.provider == "github"
        assert identity.status == "active"  # github is not high-risk

    def test_create_with_vault(self, tmp_path):
        """IM31."""
        vault = self._mock_vault()
        mgr = self._manager(tmp_path, vault=vault)
        identity = mgr.create_identity(
            provider="github",
            fields={"username": "jarvis"},
            secrets={"token": "ghp_test123"},
        )
        vault.create_secret.assert_called_once()
        assert len(identity.linked_secrets) == 1

    def test_create_validates_fields(self, tmp_path):
        """IM32."""
        mgr = self._manager(tmp_path)
        with pytest.raises(ValueError, match="Missing required"):
            mgr.create_identity(provider="gmail", fields={})

    def test_high_risk_pending(self, tmp_path):
        """IM33."""
        mgr = self._manager(tmp_path)
        identity = mgr.create_identity(
            provider="stripe",
            fields={"email": "test@test.com"},
        )
        assert identity.status == "pending"  # stripe requires approval

    def test_use_identity(self, tmp_path):
        """IM34."""
        vault = self._mock_vault()
        mgr = self._manager(tmp_path, vault=vault)
        identity = mgr.create_identity(
            provider="github", fields={"username": "j"},
            secrets={"token": "ghp_test"},
        )
        result = mgr.use_identity(identity.identity_id, "coder", "github.com")
        assert result.success
        assert result.secrets_injected == 1

    def test_use_wrong_env(self, tmp_path):
        """IM35."""
        mgr = self._manager(tmp_path)
        identity = mgr.create_identity(
            provider="github", fields={"username": "j"},
            environment="dev",
        )
        result = mgr.use_identity(identity.identity_id, "agent", "github.com", environment="prod")
        assert not result.success
        assert "mismatch" in result.error.lower()

    def test_use_revoked(self, tmp_path):
        """IM36."""
        mgr = self._manager(tmp_path)
        identity = mgr.create_identity(
            provider="github", fields={"username": "j"},
        )
        mgr.revoke_identity(identity.identity_id)
        result = mgr.use_identity(identity.identity_id, "agent", "github.com")
        assert not result.success

    def test_link_service(self, tmp_path):
        """IM37."""
        mgr = self._manager(tmp_path)
        identity = mgr.create_identity(
            provider="github", fields={"username": "j"},
        )
        ok = mgr.link_to_service(identity.identity_id, "ci-pipeline")
        assert ok
        conn = mgr.get_connections(identity.identity_id)
        assert conn["total"] >= 1

    def test_rotate_secret(self, tmp_path):
        """IM38."""
        vault = self._mock_vault()
        mgr = self._manager(tmp_path, vault=vault)
        identity = mgr.create_identity(
            provider="github", fields={"username": "j"},
            secrets={"token": "old_token"},
        )
        ok = mgr.rotate_secret(identity.identity_id, "token", "new_token")
        assert ok
        vault.update_secret.assert_called_once()

    def test_revoke_cascades(self, tmp_path):
        """IM39."""
        vault = self._mock_vault()
        mgr = self._manager(tmp_path, vault=vault)
        identity = mgr.create_identity(
            provider="github", fields={"username": "j"},
            secrets={"token": "ghp_test"},
        )
        mgr.revoke_identity(identity.identity_id)
        vault.revoke_secret.assert_called()
        assert mgr.get_identity(identity.identity_id).status == "revoked"

    def test_delete_removes(self, tmp_path):
        """IM40."""
        vault = self._mock_vault()
        mgr = self._manager(tmp_path, vault=vault)
        identity = mgr.create_identity(
            provider="github", fields={"username": "j"},
            secrets={"token": "ghp_test"},
        )
        mgr.delete_identity(identity.identity_id)
        assert mgr.identity_count == 0
        vault.delete_secret.assert_called()

    def test_list_by_env(self, tmp_path):
        """IM41."""
        mgr = self._manager(tmp_path)
        mgr.create_identity(provider="github", fields={"username": "dev"}, environment="dev")
        mgr.create_identity(provider="github", fields={"username": "prod"}, environment="prod")
        dev_list = mgr.list_identities(environment="dev")
        assert len(dev_list) == 1
        assert dev_list[0]["environment"] == "dev"

    def test_list_by_provider(self, tmp_path):
        """IM42."""
        mgr = self._manager(tmp_path)
        mgr.create_identity(provider="github", fields={"username": "j"})
        mgr.create_identity(provider="notion", fields={"email": "j@test.com"})
        gh = mgr.list_identities(provider="github")
        assert len(gh) == 1

    def test_get_graph(self, tmp_path):
        """IM43."""
        mgr = self._manager(tmp_path)
        mgr.create_identity(provider="github", fields={"username": "j"})
        graph = mgr.get_graph()
        assert graph["node_count"] >= 1

    def test_audit_recorded(self, tmp_path):
        """IM44."""
        mgr = self._manager(tmp_path)
        mgr.create_identity(provider="github", fields={"username": "j"})
        logs = mgr.get_audit_logs()
        assert len(logs) >= 1
        assert logs[0]["action"] == "identity_created"

    def test_persistence(self, tmp_path):
        """IM45."""
        mgr = self._manager(tmp_path)
        identity = mgr.create_identity(
            provider="github", fields={"username": "j"}, display_name="PersistTest",
        )
        iid = identity.identity_id

        # Create new manager instance (simulating restart)
        mgr2 = IdentityManager(vault=None, data_dir=tmp_path / "identity")
        loaded = mgr2.get_identity(iid)
        assert loaded is not None
        assert loaded.provider == "github"
