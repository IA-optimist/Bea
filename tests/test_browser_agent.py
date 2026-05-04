"""
Tests — Browser Agent (45 tests)

Session Lifecycle
  BA1.  Create session returns valid session
  BA2.  Session has isolated downloads dir
  BA3.  Close session updates status
  BA4.  List sessions filters by status
  BA5.  Session tracks action count
  BA6.  Session records action history
  BA7.  Session duration computed

Policy Engine
  BA8.  Trusted domain recognized
  BA9.  Blocked domain rejected
  BA10. Default trust is review_required
  BA11. Blocked action rejected
  BA12. Approval action detected
  BA13. Rate limit enforced
  BA14. Upload from allowed path OK
  BA15. Upload from disallowed path blocked
  BA16. Download with allowed extension OK
  BA17. Download with blocked extension rejected
  BA18. Download size limit enforced
  BA19. Sensitive action detection (payment)
  BA20. Sensitive action detection (delete)
  BA21. Wildcard domain matching

Audit
  BA22. Action recorded with chain hash
  BA23. Secret values redacted in audit
  BA24. Token patterns redacted
  BA25. Query by session_id
  BA26. Persistence to file

Navigation & Actions
  BA27. Navigate to trusted domain succeeds
  BA28. Navigate to blocked domain fails
  BA29. Navigate to review domain requires approval
  BA30. Type text succeeds
  BA31. Type secret masks value in logs
  BA32. Click succeeds
  BA33. Select option succeeds
  BA34. Extract returns structured data
  BA35. Screenshot succeeds

Secret Injection
  BA36. Inject secret from vault succeeds
  BA37. Inject secret without vault fails
  BA38. Secret value never in audit

Identity Login
  BA39. Login with identity succeeds
  BA40. Login without identity manager fails

Approval Flow
  BA41. Approval pauses session
  BA42. Approve resumes session
  BA43. Deny resolves approval

Failure Learning
  BA44. Failure report recorded
  BA45. Failure details redacted
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from unittest.mock import MagicMock

from core.browser.browser_session import create_session
from core.browser.browser_policy import (
    BrowserPolicyEngine, BrowserPolicy, ActionCategory, DomainTrust,
)
from core.browser.browser_audit import BrowserAuditLog, redact
from core.browser.browser_agent import BrowserAgent


# ═══════════════════════════════════════════════════════════════
# SESSION LIFECYCLE
# ═══════════════════════════════════════════════════════════════

class TestSession:

    def test_create(self, tmp_path):
        """BA1."""
        session = create_session("coder", sandbox_root=str(tmp_path))
        assert session.session_id.startswith("bs-")
        assert session.is_active

    def test_isolated_downloads(self, tmp_path):
        """BA2."""
        session = create_session("agent", sandbox_root=str(tmp_path))
        assert Path(session.downloads_path).exists()
        assert session.session_id in session.downloads_path

    def test_close(self, tmp_path):
        """BA3."""
        session = create_session("agent", sandbox_root=str(tmp_path))
        session.close("completed")
        assert session.status == "completed"
        assert not session.is_active

    def test_list_filter(self, tmp_path):
        """BA4."""
        agent = BrowserAgent(data_dir=tmp_path, test_mode=True)
        agent.create_session("a1")
        s2 = agent.create_session("a2")
        agent.close_session(s2.session_id)
        active = agent.list_sessions(status="active")
        assert len(active) == 1

    def test_action_count(self, tmp_path):
        """BA5."""
        session = create_session("agent", sandbox_root=str(tmp_path))
        session.record_action("click", "button")
        session.record_action("type", "input")
        assert session.action_count == 2

    def test_action_history(self, tmp_path):
        """BA6."""
        session = create_session("agent", sandbox_root=str(tmp_path))
        session.record_action("navigate", "https://example.com")
        assert len(session.action_history) == 1
        assert session.action_history[0]["action"] == "navigate"

    def test_duration(self, tmp_path):
        """BA7."""
        session = create_session("agent", sandbox_root=str(tmp_path))
        session.start_time = time.time() - 60
        assert session.duration_s >= 59


# ═══════════════════════════════════════════════════════════════
# POLICY ENGINE
# ═══════════════════════════════════════════════════════════════

class TestPolicy:

    def test_trusted_domain(self):
        """BA8."""
        policy = BrowserPolicy(trusted_domains=["github.com"])
        engine = BrowserPolicyEngine(policy)
        assert engine.check_domain("github.com") == DomainTrust.TRUSTED

    def test_blocked_domain(self):
        """BA9."""
        engine = BrowserPolicyEngine()
        assert engine.check_domain("pentagon.gov") == DomainTrust.BLOCKED

    def test_default_review(self):
        """BA10."""
        engine = BrowserPolicyEngine()
        assert engine.check_domain("random-site.com") == DomainTrust.REVIEW

    def test_blocked_action(self):
        """BA11."""
        engine = BrowserPolicyEngine()
        allowed, _, reason = engine.check_action(ActionCategory.EXECUTE_JS, "example.com")
        assert not allowed

    def test_approval_action(self):
        """BA12."""
        engine = BrowserPolicyEngine()
        allowed, needs_approval, _ = engine.check_action(ActionCategory.PURCHASE, "shop.com")
        assert allowed
        assert needs_approval

    def test_rate_limit(self):
        """BA13."""
        policy = BrowserPolicy(max_actions_per_minute=3)
        engine = BrowserPolicyEngine(policy)
        for _ in range(3):
            ok, _, _ = engine.check_action("click", "example.com", "sess1")
            assert ok
        ok, _, _ = engine.check_action("click", "example.com", "sess1")
        assert not ok

    def test_upload_allowed(self):
        """BA14."""
        engine = BrowserPolicyEngine()
        ok, _ = engine.check_upload("data/uploads/file.csv")
        assert ok

    def test_upload_blocked(self):
        """BA15."""
        engine = BrowserPolicyEngine()
        ok, _ = engine.check_upload("/etc/passwd")
        assert not ok

    def test_download_allowed(self):
        """BA16."""
        engine = BrowserPolicyEngine()
        ok, _ = engine.check_download("report.pdf")
        assert ok

    def test_download_blocked_ext(self):
        """BA17."""
        engine = BrowserPolicyEngine()
        ok, _ = engine.check_download("malware.exe")
        assert not ok

    def test_download_size_limit(self):
        """BA18."""
        engine = BrowserPolicyEngine()
        ok, _ = engine.check_download("huge.pdf", size_mb=200)
        assert not ok

    def test_detect_payment(self):
        """BA19."""
        engine = BrowserPolicyEngine()
        result = engine.detect_sensitive_action("https://shop.com/checkout", "click", "Pay Now")
        assert result == ActionCategory.PURCHASE

    def test_detect_delete(self):
        """BA20."""
        engine = BrowserPolicyEngine()
        result = engine.detect_sensitive_action("https://app.com/settings", "click", "Delete Account")
        assert result == ActionCategory.DELETE

    def test_wildcard_domain(self):
        """BA21."""
        engine = BrowserPolicyEngine()
        assert engine.check_domain("secret.mil") == DomainTrust.BLOCKED
        assert engine.check_domain("finance.bank") == DomainTrust.BLOCKED


# ═══════════════════════════════════════════════════════════════
# AUDIT
# ═══════════════════════════════════════════════════════════════

class TestAudit:

    def test_chain_hash(self):
        """BA22."""
        audit = BrowserAuditLog()
        e1 = audit.record("s1", "agent", "navigate")
        e2 = audit.record("s1", "agent", "click")
        assert e1.chain_hash != e2.chain_hash

    def test_secret_redacted(self):
        """BA23."""
        audit = BrowserAuditLog()
        e = audit.record("s1", "agent", "type", target="password=MySecret123")
        assert "MySecret123" not in e.to_dict()["target"]

    def test_token_redacted(self):
        """BA24."""
        text = "Using token sk-abc123456 for API"
        result = redact(text)
        assert "sk-abc123456" not in result
        assert "REDACTED" in result

    def test_query_session(self):
        """BA25."""
        audit = BrowserAuditLog()
        audit.record("s1", "agent", "navigate")
        audit.record("s2", "agent", "click")
        results = audit.query(session_id="s1")
        assert len(results) == 1

    def test_persistence(self, tmp_path):
        """BA26."""
        log = tmp_path / "audit.jsonl"
        audit = BrowserAuditLog(log)
        audit.record("s1", "agent", "navigate")
        assert log.exists()


# ═══════════════════════════════════════════════════════════════
# NAVIGATION & ACTIONS
# ═══════════════════════════════════════════════════════════════

class TestActions:

    def _agent(self, tmp_path, **kwargs):
        return BrowserAgent(data_dir=tmp_path, test_mode=True, **kwargs)

    def test_navigate_trusted(self, tmp_path):
        """BA27."""
        policy = BrowserPolicy(trusted_domains=["github.com"])
        agent = self._agent(tmp_path, policy=policy)
        session = agent.create_session("coder")
        result = agent.navigate(session.session_id, "https://github.com/repo")
        assert result.success

    def test_navigate_blocked(self, tmp_path):
        """BA28."""
        agent = self._agent(tmp_path)
        session = agent.create_session("agent")
        result = agent.navigate(session.session_id, "https://secret.gov/classified")
        assert not result.success

    def test_navigate_review_approval(self, tmp_path):
        """BA29."""
        agent = self._agent(tmp_path)
        session = agent.create_session("agent")
        result = agent.navigate(session.session_id, "https://unknown-site.com")
        assert result.needs_approval

    def test_type_text(self, tmp_path):
        """BA30."""
        policy = BrowserPolicy(trusted_domains=["app.com"])
        agent = self._agent(tmp_path, policy=policy)
        session = agent.create_session("agent")
        agent.navigate(session.session_id, "https://app.com")
        result = agent.type_text(session.session_id, "#email", "test@test.com")
        assert result.success

    def test_type_secret_masked(self, tmp_path):
        """BA31."""
        policy = BrowserPolicy(trusted_domains=["app.com"])
        agent = self._agent(tmp_path, policy=policy)
        session = agent.create_session("agent")
        agent.navigate(session.session_id, "https://app.com")
        # Use a generic field name to avoid sensitive action detection on "password"
        result = agent.type_text(session.session_id, "#credential-field", "super_secret", is_secret=True)
        assert result.success
        # Check audit doesn't contain the secret
        logs = agent.get_audit_logs(session.session_id)
        for log in logs:
            assert "super_secret" not in str(log)

    def test_click(self, tmp_path):
        """BA32."""
        policy = BrowserPolicy(trusted_domains=["app.com"])
        agent = self._agent(tmp_path, policy=policy)
        session = agent.create_session("agent")
        agent.navigate(session.session_id, "https://app.com")
        result = agent.click(session.session_id, "#submit")
        assert result.success

    def test_select(self, tmp_path):
        """BA33."""
        agent = self._agent(tmp_path)
        session = agent.create_session("agent")
        result = agent.select_option(session.session_id, "#country", "FR")
        assert result.success

    def test_extract(self, tmp_path):
        """BA34."""
        policy = BrowserPolicy(trusted_domains=["example.com"])
        agent = self._agent(tmp_path, policy=policy)
        session = agent.create_session("agent")
        agent.navigate(session.session_id, "https://example.com")
        result = agent.extract(session.session_id, mode="text")
        assert result.success
        assert "title" in result.data

    def test_screenshot(self, tmp_path):
        """BA35."""
        agent = self._agent(tmp_path)
        session = agent.create_session("agent")
        result = agent.screenshot(session.session_id)
        assert result.success
        assert result.screenshot_path


# ═══════════════════════════════════════════════════════════════
# SECRET INJECTION
# ═══════════════════════════════════════════════════════════════

class TestSecretInjection:

    def test_inject_with_vault(self, tmp_path):
        """BA36."""
        vault = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.inject_type = "header"
        mock_result.error = ""
        vault.use_secret.return_value = mock_result

        policy = BrowserPolicy(trusted_domains=["api.openai.com"])
        agent = BrowserAgent(vault=vault, data_dir=tmp_path, test_mode=True, policy=policy)
        session = agent.create_session("coder")
        agent.navigate(session.session_id, "https://api.openai.com")
        result = agent.inject_secret(session.session_id, "#api-key", "sec-123")
        assert result.success
        assert result.data["injected"]

    def test_inject_without_vault(self, tmp_path):
        """BA37."""
        agent = BrowserAgent(data_dir=tmp_path, test_mode=True)
        session = agent.create_session("agent")
        result = agent.inject_secret(session.session_id, "#key", "sec-1")
        assert not result.success

    def test_secret_not_in_audit(self, tmp_path):
        """BA38."""
        vault = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.inject_type = "header"
        mock_result.inject_value = "sk-REAL_SECRET_VALUE"
        mock_result.error = ""
        vault.use_secret.return_value = mock_result

        agent = BrowserAgent(vault=vault, data_dir=tmp_path, test_mode=True)
        session = agent.create_session("agent")
        agent.inject_secret(session.session_id, "#field", "sec-1")
        logs = agent.get_audit_logs(session.session_id)
        full_log_text = str(logs)
        assert "sk-REAL_SECRET_VALUE" not in full_log_text


# ═══════════════════════════════════════════════════════════════
# IDENTITY LOGIN
# ═══════════════════════════════════════════════════════════════

class TestIdentityLogin:

    def test_login_with_identity(self, tmp_path):
        """BA39."""
        id_mgr = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.secrets_injected = 2
        mock_result.error = ""
        id_mgr.use_identity.return_value = mock_result

        agent = BrowserAgent(identity_manager=id_mgr, data_dir=tmp_path, test_mode=True)
        session = agent.create_session("agent")
        result = agent.login_with_identity(session.session_id, "id-github")
        assert result.success
        assert result.data["secrets_injected"] == 2

    def test_login_without_mgr(self, tmp_path):
        """BA40."""
        agent = BrowserAgent(data_dir=tmp_path, test_mode=True)
        session = agent.create_session("agent")
        result = agent.login_with_identity(session.session_id, "id-1")
        assert not result.success


# ═══════════════════════════════════════════════════════════════
# APPROVAL FLOW
# ═══════════════════════════════════════════════════════════════

class TestApproval:

    def test_approval_pauses(self, tmp_path):
        """BA41."""
        agent = BrowserAgent(data_dir=tmp_path, test_mode=True)
        session = agent.create_session("agent")
        # Navigate to unknown domain → needs approval → paused
        result = agent.navigate(session.session_id, "https://unknown.com")
        assert result.needs_approval
        assert session.status == "paused"

    def test_approve_resumes(self, tmp_path):
        """BA42."""
        agent = BrowserAgent(data_dir=tmp_path, test_mode=True)
        session = agent.create_session("agent")
        agent.navigate(session.session_id, "https://unknown.com")
        assert agent.approve_action(session.session_id)
        assert session.status == "active"

    def test_deny(self, tmp_path):
        """BA43."""
        agent = BrowserAgent(data_dir=tmp_path, test_mode=True)
        session = agent.create_session("agent")
        agent.navigate(session.session_id, "https://unknown.com")
        assert agent.deny_action(session.session_id)
        assert session.status == "active"


# ═══════════════════════════════════════════════════════════════
# FAILURE LEARNING
# ═══════════════════════════════════════════════════════════════

class TestFailure:

    def test_failure_recorded(self, tmp_path):
        """BA44."""
        agent = BrowserAgent(data_dir=tmp_path, test_mode=True)
        session = agent.create_session("agent")
        result = agent.report_failure(session.session_id, "selector_not_found", "Could not find #submit")
        assert result["recorded"]

    def test_failure_redacted(self, tmp_path):
        """BA45."""
        agent = BrowserAgent(data_dir=tmp_path, test_mode=True)
        session = agent.create_session("agent")
        agent.report_failure(session.session_id, "auth_failed", "password=MyP@ss123 invalid")
        logs = agent.get_audit_logs(session.session_id)
        for log in logs:
            if log["action"] == "failure":
                assert "MyP@ss123" not in log["details"]
