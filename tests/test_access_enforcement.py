"""
Tests — Access Enforcement + Plan Limits + Token Gating

Phase B3: Enforcement
  E1. No token → 401 with user-friendly message
  E2. Invalid token → 401 with user-friendly message
  E3. Expired token → 403 "expired" message
  E4. Revoked token → 403 "revoked" message
  E5. Valid user token → allowed
  E6. Valid admin token → allowed
  E7. Public paths bypass auth
  E8. Write permission enforced
  E9. Viewer blocked from write operations

Phase B4: Plans
  E10. Plan definitions exist (admin, paid_pro, paid_basic, free_trial, custom)
  E11. Admin plan has unlimited limits
  E12. Free trial has restricted limits
  E13. Plan limits accessible from token

Phase B5: Usage limits
  E14. Daily mission limit tracking
  E15. Daily limit reset on new day
  E16. Admin bypasses daily limit
  E17. Free trial hits limit at 10/day
  E18. Record mission increments counter

Phase B6: Session UX
  E19. Web login overlay exists
  E20. Web logout button exists
  E21. Mobile login screen exists
  E22. User-friendly error messages (no jargon)

Phase B7: Admin panel
  E23. Token management endpoints exist
  E24. Admin can create token with plan
  E25. Token list includes plan info

Phase D: Comprehensive validation
  E26. No token blocks API access
  E27. Valid token unblocks API access
  E28. Expired token shows clear message
  E29. Revoked token shows clear message
  E30. Admin full access
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPO = Path(__file__).parent.parent


class TestEnforcement:

    def test_no_token_blocked(self, tmp_path):
        """E1: No token → 401."""
        from api.access_enforcement import check_access
        result = check_access(None, path="/api/v3/missions")
        assert not result.allowed
        assert result.error_code == 401
        assert "access token" in result.error_message.lower() or "authentication" in result.error_message.lower()

    def test_invalid_token_blocked(self, tmp_path):
        """E2: Invalid token → 401."""
        from api.access_enforcement import check_access
        result = check_access("jv-totally-fake-token", path="/api/v3/missions")
        assert not result.allowed
        assert result.error_code == 401
        assert "invalid" in result.error_message.lower()

    def test_expired_token_message(self, tmp_path):
        """E3: Expired token → 403 with expired message."""
        from api.access_tokens import TokenManager, reset_token_manager
        import api.access_tokens as at
        reset_token_manager()
        at._manager = TokenManager(tmp_path / "tokens.json")
        raw, token = at._manager.create_token("Test", role="user")
        token.expires_at = time.time() - 100  # Force expired
        at._manager._save()

        from api.access_enforcement import check_access
        result = check_access(raw, path="/api/v3/missions")
        assert not result.allowed
        assert result.error_code == 403
        assert "expired" in result.error_message.lower()
        reset_token_manager()

    def test_revoked_token_message(self, tmp_path):
        """E4: Revoked token → 403 with revoked message."""
        from api.access_tokens import TokenManager, reset_token_manager
        import api.access_tokens as at
        reset_token_manager()
        at._manager = TokenManager(tmp_path / "tokens.json")
        raw, token = at._manager.create_token("Test", role="user")
        at._manager.revoke_token(token.id)

        from api.access_enforcement import check_access
        result = check_access(raw, path="/api/v3/missions")
        assert not result.allowed
        assert result.error_code == 403
        assert "revoked" in result.error_message.lower()
        reset_token_manager()

    def test_valid_user_allowed(self, tmp_path):
        """E5: Valid user token → allowed."""
        from api.access_tokens import TokenManager, reset_token_manager
        import api.access_tokens as at
        reset_token_manager()
        at._manager = TokenManager(tmp_path / "tokens.json")
        raw, _ = at._manager.create_token("Test User", role="user")

        from api.access_enforcement import check_access
        result = check_access(raw, path="/api/v3/missions")
        assert result.allowed
        assert result.user["role"] == "user"
        reset_token_manager()

    def test_valid_admin_allowed(self, tmp_path):
        """E6: Valid admin token → allowed."""
        from api.access_tokens import TokenManager, reset_token_manager
        import api.access_tokens as at
        reset_token_manager()
        at._manager = TokenManager(tmp_path / "tokens.json")
        raw, _ = at._manager.create_token("Admin", role="admin", plan_type="admin")

        from api.access_enforcement import check_access
        result = check_access(raw, path="/api/v3/missions")
        assert result.allowed
        assert result.user["role"] == "admin"
        reset_token_manager()

    def test_public_paths_bypass(self):
        """E7: Public paths bypass auth."""
        from api.access_enforcement import check_access, is_public_path
        assert is_public_path("/health")
        assert is_public_path("/app.html")
        assert is_public_path("/auth/login")
        assert not is_public_path("/index.html")  # Removed: orphan page deleted
        assert not is_public_path("/api/v3/missions")

        result = check_access(None, path="/health")
        assert result.allowed

    def test_write_permission_enforced(self, tmp_path):
        """E8: Write permission checked."""
        from api.access_tokens import TokenManager, reset_token_manager
        import api.access_tokens as at
        reset_token_manager()
        at._manager = TokenManager(tmp_path / "tokens.json")
        raw, _ = at._manager.create_token("Viewer", role="viewer")

        from api.access_enforcement import check_access
        result = check_access(raw, path="/api/v3/missions", permission="write")
        assert not result.allowed
        assert result.error_code == 403
        reset_token_manager()

    def test_viewer_blocked_from_write(self, tmp_path):
        """E9: Viewer role blocked from write."""
        from api.access_tokens import TokenManager, reset_token_manager
        import api.access_tokens as at
        reset_token_manager()
        at._manager = TokenManager(tmp_path / "tokens.json")
        raw, _ = at._manager.create_token("Viewer", role="viewer")

        from api.access_enforcement import check_access
        # Read allowed
        r1 = check_access(raw, path="/api/v3/missions", permission="read")
        assert r1.allowed
        # Write blocked
        r2 = check_access(raw, path="/api/v3/missions", permission="write")
        assert not r2.allowed
        reset_token_manager()


class TestPlans:

    def test_plan_definitions_exist(self):
        """E10: All plan definitions exist."""
        from api.access_tokens import PLAN_DEFINITIONS
        assert "admin" in PLAN_DEFINITIONS
        assert "paid_pro" in PLAN_DEFINITIONS
        assert "paid_basic" in PLAN_DEFINITIONS
        assert "free_trial" in PLAN_DEFINITIONS
        assert "custom" in PLAN_DEFINITIONS

    def test_admin_unlimited(self):
        """E11: Admin plan has unlimited limits."""
        from api.access_tokens import PLAN_DEFINITIONS
        admin = PLAN_DEFINITIONS["admin"]
        assert admin.missions_per_day == 0  # unlimited
        assert admin.concurrent_missions == 0  # unlimited
        assert admin.model_tier == "premium"
        assert admin.multimodal_enabled is True
        assert admin.premium_tools_enabled is True

    def test_free_trial_restricted(self):
        """E12: Free trial has restricted limits."""
        from api.access_tokens import PLAN_DEFINITIONS
        trial = PLAN_DEFINITIONS["free_trial"]
        assert trial.missions_per_day == 10
        assert trial.concurrent_missions == 1
        assert trial.model_tier == "basic"
        assert trial.multimodal_enabled is False

    def test_plan_from_token(self, tmp_path):
        """E13: Plan limits accessible from token."""
        from api.access_tokens import TokenManager
        mgr = TokenManager(tmp_path / "tokens.json")
        _, token = mgr.create_token("Trial User", role="user", plan_type="free_trial")
        limits = token.plan_limits
        assert limits.missions_per_day == 10
        assert limits.model_tier == "basic"


class TestUsageLimits:

    def test_daily_tracking(self, tmp_path):
        """E14: Daily mission limit tracking."""
        from api.access_tokens import TokenManager
        mgr = TokenManager(tmp_path / "tokens.json")
        _, token = mgr.create_token("Trial", role="user", plan_type="free_trial")
        assert token.check_daily_limit()
        for _ in range(10):
            token.record_mission()
        assert not token.check_daily_limit()

    def test_daily_reset(self, tmp_path):
        """E15: Daily limit resets on new day."""
        from api.access_tokens import TokenManager
        mgr = TokenManager(tmp_path / "tokens.json")
        _, token = mgr.create_token("Trial", role="user", plan_type="free_trial")
        for _ in range(10):
            token.record_mission()
        assert not token.check_daily_limit()
        # Simulate next day
        token.daily_reset_date = "2020-01-01"
        assert token.check_daily_limit()

    def test_admin_bypasses_limit(self, tmp_path):
        """E16: Admin bypasses daily limit."""
        from api.access_tokens import TokenManager, reset_token_manager
        import api.access_tokens as at
        reset_token_manager()
        at._manager = TokenManager(tmp_path / "tokens.json")
        raw, token = at._manager.create_token("Admin", role="admin", plan_type="admin")

        from api.access_enforcement import check_mission_access
        result = check_mission_access(raw)
        assert result.allowed
        reset_token_manager()

    def test_trial_hits_limit(self, tmp_path):
        """E17: Free trial hits limit at 10/day."""
        from api.access_tokens import TokenManager, reset_token_manager
        import api.access_tokens as at
        reset_token_manager()
        at._manager = TokenManager(tmp_path / "tokens.json")
        raw, token = at._manager.create_token("Trial", role="user", plan_type="free_trial")
        for _ in range(10):
            token.record_mission()

        from api.access_enforcement import check_mission_access
        result = check_mission_access(raw)
        assert not result.allowed
        assert result.error_code == 429
        assert "limit" in result.error_message.lower()
        reset_token_manager()

    def test_record_increments(self, tmp_path):
        """E18: Record mission increments counter."""
        from api.access_tokens import TokenManager
        mgr = TokenManager(tmp_path / "tokens.json")
        _, token = mgr.create_token("User", role="user", plan_type="paid_basic")
        assert token.daily_missions == 0
        token.record_mission()
        assert token.daily_missions == 1
        token.record_mission()
        assert token.daily_missions == 2


class TestSessionUX:

    def test_web_login_overlay(self):
        """E19: Web SPA has login section."""
        content = (REPO / "static/app.html").read_text(encoding="utf-8")
        assert 'doLogin' in content
        assert 'token' in content.lower()

    def test_web_logout(self):
        """E20: Web has logout function."""
        content = (REPO / "static/app.html").read_text(encoding="utf-8")
        assert 'logout()' in content
        assert 'déconnecter' in content.lower()

    def test_mobile_login_screen(self):
        """E21: Mobile login screen exists."""
        content = (REPO / "beamax_app/lib/screens/login_screen.dart").read_text(encoding="utf-8")
        assert 'LoginScreen' in content
        assert 'token' in content.lower()  # UI is French: "Token invalide" / "token login"
        assert 'onLoginSuccess' in content  # Login success callback present

    def test_user_friendly_errors(self):
        """E22: Error messages are user-friendly."""
        content = (REPO / "static/app.html").read_text(encoding="utf-8")
        assert 'invalide' in content.lower()  # French: "Token invalide"
        assert 'expirée' in content.lower() or 'erreur' in content.lower()
        # Enforcement module has friendly messages
        from api.access_enforcement import get_user_friendly_error
        assert "authentication" in get_user_friendly_error(401).lower()
        assert "permission" in get_user_friendly_error(403).lower()
        assert "limit" in get_user_friendly_error(429).lower()


class TestAdminPanel:

    def test_token_management_routes(self):
        """E23: Token management endpoints exist."""
        content = (REPO / "api/routes/token_management.py").read_text(encoding="utf-8")
        assert '/api/v3/tokens' in content
        assert 'create_token' in content
        assert 'revoke' in content
        assert 'delete' in content

    def test_create_with_plan(self, tmp_path):
        """E24: Admin can create token with plan."""
        from api.access_tokens import TokenManager
        mgr = TokenManager(tmp_path / "tokens.json")
        raw, token = mgr.create_token("Pro Customer", role="user", plan_type="paid_pro")
        assert token.plan_type == "paid_pro"
        limits = token.plan_limits
        assert limits.missions_per_day == 100
        assert limits.premium_tools_enabled is True

    def test_list_includes_plan(self, tmp_path):
        """E25: Token list includes plan info."""
        from api.access_tokens import TokenManager
        mgr = TokenManager(tmp_path / "tokens.json")
        mgr.create_token("User", role="user", plan_type="free_trial")
        listing = mgr.list_tokens()
        assert len(listing) == 1
        assert "plan_type" in listing[0]
        assert listing[0]["plan_type"] == "free_trial"
        assert "plan_limits" in listing[0]


class TestComprehensive:

    def test_no_token_blocks_api(self, tmp_path):
        """E26: No token blocks API."""
        from api.access_enforcement import check_access
        result = check_access(None, path="/api/v3/missions")
        assert not result.allowed

    def test_valid_token_unblocks(self, tmp_path):
        """E27: Valid token unblocks API."""
        from api.access_tokens import TokenManager, reset_token_manager
        import api.access_tokens as at
        reset_token_manager()
        at._manager = TokenManager(tmp_path / "tokens.json")
        raw, _ = at._manager.create_token("User", role="user")
        from api.access_enforcement import check_access
        result = check_access(raw, path="/api/v3/missions")
        assert result.allowed
        reset_token_manager()

    def test_expired_clear_message(self, tmp_path):
        """E28: Expired token shows clear message."""
        from api.access_tokens import TokenManager, reset_token_manager
        import api.access_tokens as at
        reset_token_manager()
        at._manager = TokenManager(tmp_path / "tokens.json")
        raw, token = at._manager.create_token("User", role="user")
        token.expires_at = time.time() - 1
        from api.access_enforcement import check_access
        result = check_access(raw, path="/api/v3/missions")
        assert not result.allowed
        # Message is user-friendly
        assert any(word in result.error_message.lower() for word in ["expired", "renew"])
        reset_token_manager()

    def test_revoked_clear_message(self, tmp_path):
        """E29: Revoked shows clear message."""
        from api.access_tokens import TokenManager, reset_token_manager
        import api.access_tokens as at
        reset_token_manager()
        at._manager = TokenManager(tmp_path / "tokens.json")
        raw, token = at._manager.create_token("User", role="user")
        at._manager.revoke_token(token.id)
        from api.access_enforcement import check_access
        result = check_access(raw, path="/api/v3/missions")
        assert not result.allowed
        assert "revoked" in result.error_message.lower() or "contact" in result.error_message.lower()
        reset_token_manager()

    def test_admin_full_access(self, tmp_path):
        """E30: Admin has full access."""
        from api.access_tokens import TokenManager, reset_token_manager
        import api.access_tokens as at
        reset_token_manager()
        at._manager = TokenManager(tmp_path / "tokens.json")
        raw, _ = at._manager.create_token("Admin", role="admin", plan_type="admin")
        from api.access_enforcement import check_access, check_mission_access
        r1 = check_access(raw, path="/api/v3/missions", permission="write")
        assert r1.allowed
        r2 = check_access(raw, path="/api/v3/tokens", permission="manage_tokens")
        assert r2.allowed
        r3 = check_mission_access(raw)
        assert r3.allowed
        reset_token_manager()
