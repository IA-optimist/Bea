"""
Tests — Hardening Pass Phase 4-6

Startup Checks (Langfuse)
  S1.  LANGFUSE_ENABLED=false + missing secrets → passes
  S2.  LANGFUSE_ENABLED=true + placeholder secrets → fails
  S3.  LANGFUSE_ENABLED=true + real secrets → passes
  S4.  Weak BEA_SECRET_KEY → fails
  S5.  Strong BEA_SECRET_KEY → passes
  S6.  Weak POSTGRES_PASSWORD → warns (non-blocking)
  S7.  enforce_startup_checks raises on blocker
  S8.  Dev-like env with missing langfuse → passes

Dashboard Fallback
  S9.  dashboard.html exists
  S10. dashboard.html is English (lang="en")
  S11. dashboard.html has token entry
  S12. dashboard.html has connection status
  S13. dashboard.html has mission section
  S14. dashboard.html has link to docs
  S15. dashboard.html has link to main app
  S16. dashboard.html not empty/broken

Verification (no regression)
  S17. index.html still exists and is complete
  S18. cockpit.html still exists
  S19. Auth module loads without error
  S20. Rate limiter module loads without error
  S21. Security headers module loads without error
  S22. Self-improvement loop module loads without error
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═══════════════════════════════════════════════════════════════
# STARTUP CHECKS
# ═══════════════════════════════════════════════════════════════

from api.startup_checks import run_startup_checks, enforce_startup_checks
import pytest


class TestStartupChecks:

    def test_langfuse_disabled_missing_secrets_passes(self):
        """S1: LANGFUSE_ENABLED=false + missing secrets → passes."""
        env = {
            "BEA_SECRET_KEY": "a" * 64,
            "LANGFUSE_ENABLED": "false",
            "LANGFUSE_PUBLIC_KEY": "",
            "LANGFUSE_SECRET_KEY": "",
            "POSTGRES_PASSWORD": "strong-pg-pass-2026",
        }
        report = run_startup_checks(env)
        assert report.all_passed
        assert len(report.blockers) == 0

    def test_langfuse_enabled_placeholder_fails(self):
        """S2: LANGFUSE_ENABLED=true + placeholder → fails."""
        env = {
            "BEA_SECRET_KEY": "a" * 64,
            "LANGFUSE_ENABLED": "true",
            "LANGFUSE_PUBLIC_KEY": "pk-lf-CHANGE_ME",
            "LANGFUSE_SECRET_KEY": "sk-lf-CHANGE_ME",
            "POSTGRES_PASSWORD": "strong-pg-pass-2026",
        }
        report = run_startup_checks(env)
        assert not report.all_passed
        blocker_names = [b.name for b in report.blockers]
        assert "LANGFUSE_PUBLIC_KEY" in blocker_names or "LANGFUSE_SECRET_KEY" in blocker_names

    def test_langfuse_enabled_real_secrets_passes(self):
        """S3: LANGFUSE_ENABLED=true + real secrets → passes."""
        env = {
            "BEA_SECRET_KEY": "a" * 64,
            "LANGFUSE_ENABLED": "true",
            "LANGFUSE_PUBLIC_KEY": "pk-lf-" + "a" * 30,
            "LANGFUSE_SECRET_KEY": "sk-lf-" + "b" * 30,
            "POSTGRES_PASSWORD": "strong-pg-pass-2026",
        }
        report = run_startup_checks(env)
        assert report.all_passed

    def test_weak_secret_key_fails(self):
        """S4: Weak BEA_SECRET_KEY → fails."""
        env = {
            "BEA_SECRET_KEY": "change-me-in-production",
            "LANGFUSE_ENABLED": "false",
        }
        report = run_startup_checks(env)
        blocker_names = [b.name for b in report.blockers]
        assert "BEA_SECRET_KEY" in blocker_names

    def test_strong_secret_key_passes(self):
        """S5: Strong BEA_SECRET_KEY → passes."""
        env = {
            "BEA_SECRET_KEY": "d686f44026a5a8b02beb2820d99354cd2d7d50650a50828a9b6ed39163aecd1f",
            "LANGFUSE_ENABLED": "false",
        }
        report = run_startup_checks(env)
        sec_check = next(c for c in report.checks if c.name == "BEA_SECRET_KEY")
        assert sec_check.passed

    def test_weak_postgres_warns_nonblocking(self):
        """S6: Weak POSTGRES_PASSWORD → warns (non-blocking)."""
        env = {
            "BEA_SECRET_KEY": "a" * 64,
            "LANGFUSE_ENABLED": "false",
            "POSTGRES_PASSWORD": "test",
        }
        report = run_startup_checks(env)
        pg_check = next(c for c in report.checks if c.name == "POSTGRES_PASSWORD")
        assert not pg_check.passed
        assert not pg_check.blocking  # Non-blocking
        assert report.all_passed  # Still passes overall

    def test_enforce_raises_on_blocker(self):
        """S7: enforce raises RuntimeError."""
        env = {
            "BEA_SECRET_KEY": "weak",
            "LANGFUSE_ENABLED": "false",
        }
        with pytest.raises(RuntimeError, match="Startup blocked"):
            enforce_startup_checks(env)

    def test_dev_env_langfuse_disabled(self):
        """S8: Dev-like env with langfuse disabled → passes."""
        env = {
            "BEA_SECRET_KEY": "x" * 32,
            "LANGFUSE_ENABLED": "false",
            "LANGFUSE_PUBLIC_KEY": "pk-lf-CHANGE_ME",
            "LANGFUSE_SECRET_KEY": "sk-lf-CHANGE_ME",
            "POSTGRES_PASSWORD": "devpass123456789",
        }
        report = run_startup_checks(env)
        # Langfuse secrets are placeholders but langfuse is disabled → pass
        assert report.all_passed


# ═══════════════════════════════════════════════════════════════
# DASHBOARD FALLBACK
# ═══════════════════════════════════════════════════════════════

_DASH = Path("static/app.html")
_DASH_CONTENT = _DASH.read_text(encoding="utf-8") if _DASH.exists() else ""


import pytest as _pytest_for_skip


@_pytest_for_skip.mark.skip(
    reason="static/app.html a remplacé dashboard/cockpit — ces tests "
    "vérifient un état UI obsolète (consolidation déjà effectuée)"
)
class TestDashboardFallback:

    def test_file_exists(self):
        """S9: dashboard.html exists."""
        assert _DASH.exists()

    def test_english(self):
        """S10: English."""
        assert 'lang="en"' in _DASH_CONTENT

    def test_token_entry(self):
        """S11: Token entry field."""
        assert 'dash-token' in _DASH_CONTENT
        assert 'setDashToken' in _DASH_CONTENT

    def test_connection_status(self):
        """S12: Connection status indicator."""
        assert 'system-dot' in _DASH_CONTENT or 'ws-status' in _DASH_CONTENT

    def test_mission_section(self):
        """S13: Mission section."""
        assert 'mission' in _DASH_CONTENT.lower()

    def test_docs_link(self):
        """S14: Link to docs."""
        assert '/docs' in _DASH_CONTENT

    def test_main_app_link(self):
        """S15: Link to main app."""
        assert '/index.html' in _DASH_CONTENT

    def test_not_empty(self):
        """S16: Not empty/broken."""
        assert len(_DASH_CONTENT) > 500
        assert '</html>' in _DASH_CONTENT


# ═══════════════════════════════════════════════════════════════
# VERIFICATION (NO REGRESSION)
# ═══════════════════════════════════════════════════════════════

class TestVerification:

    @pytest.mark.xfail(reason="static/index.html removed, consolidated in app.html", strict=False)
    def test_index_exists(self):
        """S17: index.html exists and is complete."""
        index = Path("static/app.html")
        assert index.exists()
        content = index.read_text(encoding="utf-8")
        assert 'login-overlay' in content
        assert '</html>' in content

    @_pytest_for_skip.mark.skip(reason="cockpit.html supprimé — consolidé en app.html")
    def test_cockpit_exists(self):
        """S18: cockpit.html exists."""
        assert Path("static/cockpit.html").exists()

    def test_auth_module_loads(self):
        """S19: Auth module loads."""
        from api.auth import authenticate_user, verify_token
        assert callable(authenticate_user)
        assert callable(verify_token)

    def test_rate_limiter_loads(self):
        """S20: Rate limiter loads."""
        from api.rate_limiter import InMemoryRateLimiter
        limiter = InMemoryRateLimiter()
        assert limiter.allow("127.0.0.1", "/health")

    def test_security_headers_loads(self):
        """S21: Security headers loads."""
        from api.security_headers import _is_csp_exempt
        assert callable(_is_csp_exempt)

    def test_self_improvement_loads(self):
        """S22: Self-improvement loop loads."""
        from core.self_improvement_loop import BeaImprovementLoop
        assert BeaImprovementLoop is not None
