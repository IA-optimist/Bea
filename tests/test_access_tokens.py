"""
Tests — Access Token System

Phase B1: Token model
  T1. Create token returns raw + token object
  T2. Raw token starts with 'jv-'
  T3. Token hash is stored, not raw token
  T4. Token has correct role

Phase B2: Validation
  T5. Valid token passes validation
  T6. Invalid token returns None
  T7. Revoked token returns None
  T8. Expired token returns None
  T9. Use-limited token expires after max uses
  T10. Use count increments on validation

Phase B3: Management
  T11. List tokens (no raw tokens exposed)
  T12. Revoke token
  T13. Re-enable revoked token
  T14. Delete token
  T15. Token stats

Phase B4: Persistence
  T16. Tokens persist to disk
  T17. Reload preserves all fields

Phase B5: Auth integration
  T18. verify_token supports access tokens
  T19. verify_token supports JWT tokens
  T20. Role permissions enforced
  T21. Admin has manage_tokens permission
  T22. User does NOT have manage_tokens
  T23. Viewer has read-only

Phase B6: Multi-role
  T24. Admin token validates
  T25. User token validates
  T26. Viewer token validates
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestTokenModel:

    def test_create_returns_raw_and_object(self, tmp_path):
        """T1: Create returns raw token + AccessToken."""
        from api.access_tokens import TokenManager
        mgr = TokenManager(tmp_path / "tokens.json")
        raw, token = mgr.create_token("Test User", role="user")
        assert raw is not None
        assert token is not None
        assert token.name == "Test User"

    def test_raw_token_format(self, tmp_path):
        """T2: Raw token starts with 'jv-'."""
        from api.access_tokens import TokenManager
        mgr = TokenManager(tmp_path / "tokens.json")
        raw, _ = mgr.create_token("Test", role="user")
        assert raw.startswith("jv-")
        assert len(raw) > 20

    def test_hash_stored_not_raw(self, tmp_path):
        """T3: Token hash is stored, raw is never in storage."""
        from api.access_tokens import TokenManager
        mgr = TokenManager(tmp_path / "tokens.json")
        raw, token = mgr.create_token("Test", role="user")
        # Hash is stored
        assert token.token_hash != ""
        assert token.token_hash != raw
        # Raw not in persisted file
        content = (tmp_path / "tokens.json").read_text()
        assert raw not in content

    def test_correct_role(self, tmp_path):
        """T4: Token has correct role."""
        from api.access_tokens import TokenManager
        mgr = TokenManager(tmp_path / "tokens.json")
        _, admin_token = mgr.create_token("Admin", role="admin")
        _, user_token = mgr.create_token("User", role="user")
        _, viewer_token = mgr.create_token("Viewer", role="viewer")
        assert admin_token.role == "admin"
        assert user_token.role == "user"
        assert viewer_token.role == "viewer"


class TestValidation:

    def test_valid_token_passes(self, tmp_path):
        """T5: Valid token passes validation."""
        from api.access_tokens import TokenManager
        mgr = TokenManager(tmp_path / "tokens.json")
        raw, _ = mgr.create_token("Test", role="user")
        result = mgr.validate_token(raw)
        assert result is not None
        assert result.role == "user"

    def test_invalid_token_fails(self, tmp_path):
        """T6: Invalid token returns None."""
        from api.access_tokens import TokenManager
        mgr = TokenManager(tmp_path / "tokens.json")
        assert mgr.validate_token("jv-totally-invalid-token") is None
        assert mgr.validate_token("") is None
        assert mgr.validate_token("not-a-jv-token") is None

    def test_revoked_token_fails(self, tmp_path):
        """T7: Revoked token returns None."""
        from api.access_tokens import TokenManager
        mgr = TokenManager(tmp_path / "tokens.json")
        raw, token = mgr.create_token("Test", role="user")
        mgr.revoke_token(token.id)
        assert mgr.validate_token(raw) is None

    def test_expired_token_fails(self, tmp_path):
        """T8: Expired token returns None."""
        from api.access_tokens import TokenManager
        mgr = TokenManager(tmp_path / "tokens.json")
        raw, token = mgr.create_token("Test", role="user", expires_days=0)
        # Force expiry
        token.expires_at = time.time() - 100
        assert mgr.validate_token(raw) is None

    def test_use_limited_expires(self, tmp_path):
        """T9: Use-limited token expires after max uses."""
        from api.access_tokens import TokenManager
        mgr = TokenManager(tmp_path / "tokens.json")
        raw, _ = mgr.create_token("Test", role="user", max_uses=2)
        assert mgr.validate_token(raw) is not None  # use 1
        assert mgr.validate_token(raw) is not None  # use 2
        assert mgr.validate_token(raw) is None       # use 3 → expired

    def test_use_count_increments(self, tmp_path):
        """T10: Use count increments on validation."""
        from api.access_tokens import TokenManager
        mgr = TokenManager(tmp_path / "tokens.json")
        raw, token = mgr.create_token("Test", role="user")
        assert token.use_count == 0
        mgr.validate_token(raw)
        assert token.use_count == 1
        mgr.validate_token(raw)
        assert token.use_count == 2


class TestManagement:

    def test_list_no_raw(self, tmp_path):
        """T11: List tokens never exposes raw tokens."""
        from api.access_tokens import TokenManager
        mgr = TokenManager(tmp_path / "tokens.json")
        raw, _ = mgr.create_token("Test", role="user")
        listing = mgr.list_tokens()
        assert len(listing) == 1
        # No raw token in listing
        assert "token" not in listing[0] or listing[0].get("token") != raw
        assert "token_hash" not in listing[0]

    def test_revoke(self, tmp_path):
        """T12: Revoke token."""
        from api.access_tokens import TokenManager
        mgr = TokenManager(tmp_path / "tokens.json")
        _, token = mgr.create_token("Test", role="user")
        assert mgr.revoke_token(token.id)
        assert not token.enabled

    def test_enable(self, tmp_path):
        """T13: Re-enable revoked token."""
        from api.access_tokens import TokenManager
        mgr = TokenManager(tmp_path / "tokens.json")
        raw, token = mgr.create_token("Test", role="user")
        mgr.revoke_token(token.id)
        assert mgr.validate_token(raw) is None
        mgr.enable_token(token.id)
        assert mgr.validate_token(raw) is not None

    def test_delete(self, tmp_path):
        """T14: Delete token permanently."""
        from api.access_tokens import TokenManager
        mgr = TokenManager(tmp_path / "tokens.json")
        _, token = mgr.create_token("Test", role="user")
        assert mgr.delete_token(token.id)
        assert len(mgr.list_tokens()) == 0

    def test_stats(self, tmp_path):
        """T15: Token stats."""
        from api.access_tokens import TokenManager
        mgr = TokenManager(tmp_path / "tokens.json")
        mgr.create_token("Admin", role="admin")
        mgr.create_token("User1", role="user")
        mgr.create_token("User2", role="user")
        mgr.create_token("Viewer", role="viewer")
        stats = mgr.get_stats()
        assert stats["total"] == 4
        assert stats["active"] == 4
        assert stats["by_role"]["admin"] == 1
        assert stats["by_role"]["user"] == 2
        assert stats["by_role"]["viewer"] == 1


class TestPersistence:

    def test_persist_to_disk(self, tmp_path):
        """T16: Tokens persist to disk."""
        from api.access_tokens import TokenManager
        mgr1 = TokenManager(tmp_path / "tokens.json")
        raw, token = mgr1.create_token("Test", role="user")
        assert (tmp_path / "tokens.json").exists()

        mgr2 = TokenManager(tmp_path / "tokens.json")
        assert len(mgr2.list_tokens()) == 1

    def test_reload_preserves_fields(self, tmp_path):
        """T17: Reload preserves all fields."""
        from api.access_tokens import TokenManager
        mgr1 = TokenManager(tmp_path / "tokens.json")
        raw, token = mgr1.create_token("Max Phone", role="admin",
                                         expires_days=30, max_uses=100)
        mgr1.validate_token(raw)  # increment use_count

        mgr2 = TokenManager(tmp_path / "tokens.json")
        reloaded = mgr2.get_token_by_id(token.id)
        assert reloaded is not None
        assert reloaded.name == "Max Phone"
        assert reloaded.role == "admin"
        assert reloaded.use_count == 1
        assert reloaded.max_uses == 100


class TestAuthIntegration:

    def test_verify_access_token(self, tmp_path):
        """T18: verify_token supports access tokens."""
        from api.access_tokens import TokenManager, reset_token_manager
        reset_token_manager()
        # Create manager at default path
        import api.access_tokens as at
        at._manager = TokenManager(tmp_path / "tokens.json")
        raw, _ = at._manager.create_token("Test", role="user")

        from api.auth import verify_token
        result = verify_token(raw)
        assert result is not None
        assert result["role"] == "user"
        assert result["auth_type"] == "access_token"

        reset_token_manager()

    def test_role_permissions(self):
        """T20: Role permissions enforced."""
        from api.auth import has_permission
        assert has_permission("admin", "manage_tokens")
        assert has_permission("admin", "write")
        assert has_permission("admin", "read")
        assert has_permission("user", "write")
        assert has_permission("user", "read")
        assert has_permission("user", "approve")
        assert has_permission("viewer", "read")

    def test_admin_has_manage_tokens(self):
        """T21: Admin has manage_tokens permission."""
        from api.auth import has_permission
        assert has_permission("admin", "manage_tokens")

    def test_user_no_manage_tokens(self):
        """T22: User does NOT have manage_tokens."""
        from api.auth import has_permission
        assert not has_permission("user", "manage_tokens")

    def test_viewer_read_only(self):
        """T23: Viewer has read-only."""
        from api.auth import has_permission
        assert has_permission("viewer", "read")
        assert not has_permission("viewer", "write")
        assert not has_permission("viewer", "approve")
        assert not has_permission("viewer", "manage_tokens")


class TestMultiRole:

    def test_admin_token(self, tmp_path):
        """T24: Admin token validates with admin role."""
        from api.access_tokens import TokenManager
        mgr = TokenManager(tmp_path / "tokens.json")
        raw, _ = mgr.create_token("Admin", role="admin")
        result = mgr.validate_token(raw)
        assert result.role == "admin"

    def test_user_token(self, tmp_path):
        """T25: User token validates with user role."""
        from api.access_tokens import TokenManager
        mgr = TokenManager(tmp_path / "tokens.json")
        raw, _ = mgr.create_token("User", role="user")
        result = mgr.validate_token(raw)
        assert result.role == "user"

    def test_viewer_token(self, tmp_path):
        """T26: Viewer token validates with viewer role."""
        from api.access_tokens import TokenManager
        mgr = TokenManager(tmp_path / "tokens.json")
        raw, _ = mgr.create_token("Viewer", role="viewer")
        result = mgr.validate_token(raw)
        assert result.role == "viewer"
