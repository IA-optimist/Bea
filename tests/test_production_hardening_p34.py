"""
tests/test_production_hardening_p34.py — Pass 34 Security Hardening Tests

Covers:
  P1.  enforce_production_secrets() — passes in dev mode (no JARVIS_PRODUCTION)
  P2.  enforce_production_secrets() — raises RuntimeError on default secret key
  P3.  enforce_production_secrets() — raises RuntimeError on missing admin password
  P4.  enforce_production_secrets() — raises RuntimeError on missing API token
  P5.  enforce_production_secrets() — accumulates all errors before raising
  P6.  enforce_production_secrets() — passes with all secrets properly set
  P7.  JARVIS_REQUIRE_AUTH — valid token passes even with flag set
  P7b. JARVIS_REQUIRE_AUTH — wrong token raises 401, not 503
  P8.  JARVIS_REQUIRE_AUTH — HTTP 503 when flag set + no token configured
  P9.  JARVIS_REQUIRE_AUTH — auth disabled (pass-through) when neither flag nor token
  P10. is_path_protected() — protected paths correctly identified
  P11. is_path_allowed() — protected paths blocked even if in ALLOWED_SCOPE
  P12. is_path_allowed() — workspace/ allowed when not protected
  P13. production_mode property — False without env, True with JARVIS_PRODUCTION=1
"""
from __future__ import annotations

import importlib
import os

import pytest
from unittest.mock import patch


# ─── helpers ──────────────────────────────────────────────────────────────────

def _with_env(env_overrides: dict, fn):
    """Run fn() with os.environ patched by env_overrides. Returns fn()'s result."""
    with patch.dict(os.environ, env_overrides, clear=False):
        return fn()


def _settings_in_env(env_overrides: dict):
    """Return a fresh Settings() with env_overrides active at instantiation time.
    NOTE: production_mode is a dynamic property — must call enforce_*() within
    the same env context. Use the _with_env helper for that."""
    with patch.dict(os.environ, env_overrides, clear=False):
        import config.settings as _mod
        return _mod.Settings()


def _check_auth_with_env(env_overrides: dict, token=None, authorization=None):
    """Run _check_auth() in a patched env, reloading _deps for module-level constants."""
    with patch.dict(os.environ, env_overrides, clear=False):
        import api._deps as _deps_mod
        importlib.reload(_deps_mod)
        _deps_mod._check_auth(token=token, authorization=authorization)


# ═══════════════════════════════════════════════════════════════════
# P1–P6, P13: enforce_production_secrets()
# ═══════════════════════════════════════════════════════════════════

class TestEnforceProductionSecrets:

    def _run_enforce(self, env_overrides):
        """Create Settings and call enforce_production_secrets() inside the same env patch."""
        with patch.dict(os.environ, env_overrides, clear=False):
            import config.settings as _mod
            s = _mod.Settings()
            s.enforce_production_secrets()  # called while patch is still active

    def test_P1_dev_mode_no_raise(self):
        """No JARVIS_PRODUCTION → no-op regardless of secret quality."""
        self._run_enforce({
            "JARVIS_PRODUCTION": "",
            "JARVIS_SECRET_KEY": "change-me-in-production",
            "JARVIS_ADMIN_PASSWORD": "",
            "JARVIS_API_TOKEN": "",
        })

    def test_P2_production_default_secret_raises(self):
        """JARVIS_PRODUCTION=1 + default secret → RuntimeError."""
        with pytest.raises(RuntimeError, match="PRODUCTION STARTUP BLOCKED"):
            self._run_enforce({
                "JARVIS_PRODUCTION": "1",
                "JARVIS_SECRET_KEY": "change-me-in-production",
                "JARVIS_ADMIN_PASSWORD": "secure-pw",
                "JARVIS_API_TOKEN": "secure-token",
            })

    def test_P3_production_no_admin_password_raises(self):
        """JARVIS_PRODUCTION=1 + missing admin password → RuntimeError."""
        with pytest.raises(RuntimeError, match="JARVIS_ADMIN_PASSWORD"):
            self._run_enforce({
                "JARVIS_PRODUCTION": "1",
                "JARVIS_SECRET_KEY": "x" * 40,
                "JARVIS_ADMIN_PASSWORD": "",
                "JARVIS_API_TOKEN": "secure-token",
            })

    def test_P4_production_no_api_token_raises(self):
        """JARVIS_PRODUCTION=1 + missing API token → RuntimeError."""
        with pytest.raises(RuntimeError, match="JARVIS_API_TOKEN"):
            self._run_enforce({
                "JARVIS_PRODUCTION": "1",
                "JARVIS_SECRET_KEY": "x" * 40,
                "JARVIS_ADMIN_PASSWORD": "secure-pw",
                "JARVIS_API_TOKEN": "",
            })

    def test_P5_accumulates_all_errors(self):
        """All three issues → RuntimeError listing all of them in one message."""
        with pytest.raises(RuntimeError) as exc_info:
            self._run_enforce({
                "JARVIS_PRODUCTION": "1",
                "JARVIS_SECRET_KEY": "change-me-in-production",
                "JARVIS_ADMIN_PASSWORD": "",
                "JARVIS_API_TOKEN": "",
            })
        msg = str(exc_info.value)
        assert "JARVIS_ADMIN_PASSWORD" in msg
        assert "JARVIS_API_TOKEN" in msg

    def test_P6_all_secrets_set_no_raise(self):
        """JARVIS_PRODUCTION=1 + all secrets properly set → no error."""
        self._run_enforce({
            "JARVIS_PRODUCTION": "1",
            "JARVIS_SECRET_KEY": "a-very-secure-secret-key-that-is-long-enough",
            "JARVIS_ADMIN_PASSWORD": "$ecureP@ssw0rd!",
            "JARVIS_API_TOKEN": "prod-token-abc123",
        })

    def test_P13_production_mode_property_false(self):
        """production_mode returns False when JARVIS_PRODUCTION not set."""
        with patch.dict(os.environ, {"JARVIS_PRODUCTION": ""}, clear=False):
            import config.settings as _mod
            s = _mod.Settings()
            assert s.production_mode is False

    @pytest.mark.parametrize("val", ["1", "true", "True", "yes"])
    def test_P13_production_mode_property_true(self, val):
        """production_mode returns True for various truthy values."""
        with patch.dict(os.environ, {"JARVIS_PRODUCTION": val}, clear=False):
            import config.settings as _mod
            s = _mod.Settings()
            assert s.production_mode is True, f"Expected True for JARVIS_PRODUCTION={val}"


# ═══════════════════════════════════════════════════════════════════
# P7–P9: JARVIS_REQUIRE_AUTH guard in _check_auth()
# ═══════════════════════════════════════════════════════════════════

class TestRequireAuthGuard:

    @pytest.fixture(autouse=True)
    def _restore_deps(self):
        # Ces tests font importlib.reload(api._deps) avec un env patché, ce qui
        # fige les globals module (_REQUIRE_AUTH, _API_TOKEN). patch.dict restaure
        # l'env mais PAS le module rechargé → fuite vers d'autres tests d'auth
        # (ex. AC01). On recharge _deps après coup, l'env étant revenu au baseline
        # conftest (JARVIS_API_TOKEN="test").
        yield
        import api._deps as _deps
        importlib.reload(_deps)

    def test_P8_require_auth_no_token_raises_503(self):
        """JARVIS_REQUIRE_AUTH=1 + no JARVIS_API_TOKEN → HTTP 503."""
        from fastapi import HTTPException
        env = {"JARVIS_REQUIRE_AUTH": "1", "JARVIS_API_TOKEN": ""}
        with patch.dict(os.environ, env, clear=False):
            import api._deps as _deps
            importlib.reload(_deps)
            with pytest.raises(HTTPException) as exc_info:
                _deps._check_auth(token=None, authorization=None)
        assert exc_info.value.status_code == 503
        assert "JARVIS_API_TOKEN" in exc_info.value.detail

    def test_P9_no_token_no_flag_passes(self):
        """No JARVIS_API_TOKEN + no JARVIS_REQUIRE_AUTH → auth disabled, no raise."""
        env = {"JARVIS_REQUIRE_AUTH": "", "JARVIS_API_TOKEN": ""}
        with patch.dict(os.environ, env, clear=False):
            import api._deps as _deps
            importlib.reload(_deps)
            _deps._check_auth(token=None, authorization=None)  # must not raise

    def test_P7_valid_token_passes(self):
        """Valid static token → no raise even with REQUIRE_AUTH set."""
        from fastapi import HTTPException
        token = "my-static-api-token"
        env = {"JARVIS_API_TOKEN": token, "JARVIS_REQUIRE_AUTH": "1"}
        with patch.dict(os.environ, env, clear=False):
            import api._deps as _deps
            importlib.reload(_deps)
            try:
                _deps._check_auth(token=token, authorization=None)
            except HTTPException as e:
                pytest.fail(f"Unexpected HTTPException {e.status_code}: {e.detail}")

    def test_P7b_wrong_token_raises_401(self):
        """Configured token + wrong submitted token → 401, not 503."""
        from fastapi import HTTPException
        env = {"JARVIS_API_TOKEN": "correct-token", "JARVIS_REQUIRE_AUTH": "1"}
        with patch.dict(os.environ, env, clear=False):
            import api._deps as _deps
            importlib.reload(_deps)
            with pytest.raises(HTTPException) as exc_info:
                _deps._check_auth(token="wrong-token", authorization=None)
        assert exc_info.value.status_code == 401

    @pytest.mark.parametrize("val", ["1", "true", "True", "yes", "YES"])
    def test_require_auth_truthy_values(self, val):
        """JARVIS_REQUIRE_AUTH accepts '1', 'true', 'yes' (case-insensitive)."""
        from fastapi import HTTPException
        env = {"JARVIS_REQUIRE_AUTH": val, "JARVIS_API_TOKEN": ""}
        with patch.dict(os.environ, env, clear=False):
            import api._deps as _deps
            importlib.reload(_deps)
            with pytest.raises(HTTPException) as exc_info:
                _deps._check_auth(token=None, authorization=None)
        assert exc_info.value.status_code == 503, f"Failed for JARVIS_REQUIRE_AUTH={val}"

    @pytest.mark.parametrize("val", ["false", "False", "0", "no", ""])
    def test_require_auth_falsy_values_pass(self, val):
        """JARVIS_REQUIRE_AUTH=false/0/'' → auth disabled, no raise."""
        env = {"JARVIS_REQUIRE_AUTH": val, "JARVIS_API_TOKEN": ""}
        with patch.dict(os.environ, env, clear=False):
            import api._deps as _deps
            importlib.reload(_deps)
            _deps._check_auth(token=None, authorization=None)


# ═══════════════════════════════════════════════════════════════════
# P10–P12: safety_boundary consistency after Pass 34 fix
# ═══════════════════════════════════════════════════════════════════

class TestSafetyBoundaryConsistency:

    @pytest.fixture(autouse=True)
    def load_sb(self):
        from core.self_improvement import safety_boundary
        self.sb = safety_boundary

    def test_P10_meta_orchestrator_is_protected(self):
        """core/meta_orchestrator.py must be in the protected set."""
        assert self.sb.is_path_protected("core/meta_orchestrator.py") is True

    def test_P11_protected_path_denied_by_allowed(self):
        """is_path_allowed() must return False for all protected files."""
        for path in [
            "core/meta_orchestrator.py",
            "core/tool_executor.py",
            "core/policy/policy_engine.py",
            "api/main.py",
            "main.py",
        ]:
            assert self.sb.is_path_allowed(path) is False, f"Should be denied: {path}"

    def test_P12_workspace_path_allowed(self):
        """workspace/ files are in ALLOWED_SCOPE and not protected → allowed."""
        assert self.sb.is_path_allowed("workspace/prompts/some_prompt.txt") is True

    def test_config_path_allowed(self):
        """config/ is in ALLOWED_SCOPE → allowed."""
        assert self.sb.is_path_allowed("config/custom.yaml") is True

    def test_random_path_denied(self):
        """A path outside both scopes is denied."""
        assert self.sb.is_path_allowed("some_random_dir/something.py") is False

    def test_protection_takes_precedence(self):
        """Protected gate must run before ALLOWED_SCOPE check.
        core/tool_executor.py is protected — is_path_allowed() must return False."""
        protected = "core/tool_executor.py"
        assert self.sb.is_path_protected(protected) is True
        assert self.sb.is_path_allowed(protected) is False


# ═══════════════════════════════════════════════════════════════════
# Phase C: enforce_llm_key() — startup LLM gate
# ═══════════════════════════════════════════════════════════════════

class TestEnforceLLMKey:
    """enforce_llm_key() must hard-fail when no LLM provider is configured."""

    def _run_llm_check(self, env_overrides):
        with patch.dict(os.environ, env_overrides, clear=False):
            import config.settings as _mod
            s = _mod.Settings()
            s.enforce_llm_key()

    def test_no_llm_key_raises(self):
        """No LLM key + no Ollama + DRY_RUN=false → RuntimeError.

        has_llm_key now considers Ollama as a valid local provider.
        To reproduce the 'no LLM' state, we must also clear OLLAMA_HOST.
        """
        with pytest.raises(RuntimeError, match="NO LLM KEY"):
            self._run_llm_check({
                "OPENAI_API_KEY": "",
                "ANTHROPIC_API_KEY": "",
                "OPENROUTER_API_KEY": "",
                "OLLAMA_HOST": "",
                "DRY_RUN": "false",
            })

    def test_openai_key_passes(self):
        """OPENAI_API_KEY set → no raise."""
        self._run_llm_check({
            "OPENAI_API_KEY": "sk-test-key",
            "ANTHROPIC_API_KEY": "",
            "OPENROUTER_API_KEY": "",
            "DRY_RUN": "false",
        })

    def test_anthropic_key_passes(self):
        """ANTHROPIC_API_KEY alone → no raise."""
        self._run_llm_check({
            "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEY": "sk-ant-test",
            "OPENROUTER_API_KEY": "",
            "DRY_RUN": "false",
        })

    def test_openrouter_key_passes(self):
        """OPENROUTER_API_KEY alone → no raise."""
        self._run_llm_check({
            "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "OPENROUTER_API_KEY": "sk-or-test",
            "DRY_RUN": "false",
        })

    def test_dry_run_bypasses_llm_check(self):
        """DRY_RUN=true → no raise even with no LLM key (dev/test mode)."""
        self._run_llm_check({
            "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "OPENROUTER_API_KEY": "",
            "DRY_RUN": "true",
        })

    def test_has_llm_key_property(self):
        """has_llm_key property reflects presence of any cloud key OR local Ollama."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-x", "ANTHROPIC_API_KEY": "", "OPENROUTER_API_KEY": ""}, clear=False):
            import config.settings as _mod
            s = _mod.Settings()
            assert s.has_llm_key is True

        # No cloud key AND no Ollama → False
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "", "OPENROUTER_API_KEY": "", "OLLAMA_HOST": ""},
            clear=False,
        ):
            import config.settings as _mod
            s = _mod.Settings()
            assert s.has_llm_key is False

        # No cloud key BUT Ollama host configured → True (local provider counts)
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "", "OPENROUTER_API_KEY": "", "OLLAMA_HOST": "http://ollama:11434"},
            clear=False,
        ):
            import config.settings as _mod
            s = _mod.Settings()
            assert s.has_llm_key is True
