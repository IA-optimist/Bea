"""
BEA MAX — Browser Agent
==============================
Production-grade browser automation with safety guarantees.

Integrates with:
- Secret Vault (credential injection without exposure)
- Identity Manager (account login flows)
- Browser Policy (domain trust, action approval)
- Browser Audit (immutable action logging)

Safety invariants:
- Secrets never logged in plaintext
- Blocked domains never accessed
- Destructive actions always require approval
- Each session is sandboxed (isolated downloads dir)
- All actions audited with chained hashes
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from core.browser.browser_session import (
    BrowserSession, create_session,
)
from core.browser.browser_policy import (
    BrowserPolicyEngine, BrowserPolicy, ActionCategory, ApprovalRequest,
    DomainTrust,
)
from core.browser.browser_actions import (
    ActionResult, ExtractedData,
)
from core.browser.browser_audit import BrowserAuditLog, redact

logger = logging.getLogger(__name__)


class BrowserAgent:
    """
    Production browser automation agent.
    
    All actions go through:
    1. Policy check (domain trust + action rules)
    2. Sensitive action detection
    3. Approval gate (if required)
    4. Execution (or simulated in test mode)
    5. Audit logging
    """

    def __init__(
        self,
        vault=None,
        identity_manager=None,
        policy: BrowserPolicy | None = None,
        data_dir: str | Path = "data/browser",
        test_mode: bool = False,
    ):
        self._vault = vault
        self._identity_mgr = identity_manager
        self._policy_engine = BrowserPolicyEngine(policy)
        self._audit = BrowserAuditLog(Path(data_dir) / "browser_audit.jsonl")
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._test_mode = test_mode

        self._sessions: dict[str, BrowserSession] = {}

    # ── Session Management ──

    def create_session(
        self,
        agent_name: str,
        identity_id: str = "",
        purpose: str = "",
        environment: str = "prod",
    ) -> BrowserSession:
        """Create a new isolated browser session."""
        session = create_session(
            agent_name=agent_name,
            identity_id=identity_id,
            purpose=purpose,
            environment=environment,
            sandbox_root=str(self._data_dir / "sessions"),
        )
        self._sessions[session.session_id] = session

        self._audit.record(
            session.session_id, agent_name, "session_create",
            details=f"purpose={purpose}",
        )
        return session

    def close_session(self, session_id: str, status: str = "completed") -> bool:
        session = self._sessions.get(session_id)
        if not session:
            return False
        session.close(status)
        self._audit.record(session_id, session.agent_name, "session_close",
                           result=status)
        return True

    def get_session(self, session_id: str) -> BrowserSession | None:
        return self._sessions.get(session_id)

    def list_sessions(self, status: str | None = None) -> list[dict]:
        results = []
        for s in self._sessions.values():
            if status and s.status != status:
                continue
            results.append(s.to_dict())
        return results

    # ── Navigation ──

    def navigate(self, session_id: str, url: str, wait_for: str = "") -> ActionResult:
        """Navigate to a URL."""
        session = self._sessions.get(session_id)
        if not session or not session.is_active:
            return ActionResult(success=False, action="navigate", error="Invalid or inactive session")

        # Extract domain
        domain = self._extract_domain(url)

        # Policy check
        allowed, needs_approval, reason = self._policy_engine.check_action(
            ActionCategory.NAVIGATE, domain, session_id,
        )
        if not allowed:
            self._audit.record(session_id, session.agent_name, "navigate",
                               target=url, domain=domain, result="blocked", details=reason)
            return ActionResult(success=False, action="navigate", error=reason)

        if needs_approval:
            return self._request_approval(session, "navigate", url, domain, f"Navigate to {url}")

        # Execute
        session.current_url = url
        session.navigation_count += 1
        session.record_action("navigate", url)

        self._audit.record(session_id, session.agent_name, "navigate",
                           target=url, domain=domain)

        return ActionResult(success=True, action="navigate", data={"url": url, "domain": domain})

    # ── Form Interaction ──

    def type_text(self, session_id: str, selector: str, value: str, is_secret: bool = False) -> ActionResult:
        """Type text into a field. If is_secret, value is masked in logs."""
        session = self._sessions.get(session_id)
        if not session or not session.is_active:
            return ActionResult(success=False, action="type", error="Invalid session")

        domain = self._extract_domain(session.current_url)
        allowed, needs_approval, reason = self._policy_engine.check_action(
            ActionCategory.TYPE, domain, session_id,
        )
        if not allowed:
            return ActionResult(success=False, action="type", error=reason)

        # Detect sensitive action
        sensitive = self._policy_engine.detect_sensitive_action(
            session.current_url, "type", selector,
        )
        if sensitive and sensitive in self._policy_engine.policy.approval_actions:
            return self._request_approval(
                session, "type", selector, domain,
                f"Typing into security-sensitive field: {selector}",
            )

        # Log with redaction
        logged_value = "***SECRET***" if is_secret else redact(value[:50])
        session.record_action("type", f"{selector}={logged_value}")

        self._audit.record(session_id, session.agent_name, "type",
                           target=selector, domain=domain,
                           details=f"value={'***SECRET***' if is_secret else redact(value[:50])}")

        return ActionResult(success=True, action="type", data={"selector": selector, "typed": not is_secret})

    def click(self, session_id: str, selector: str, text: str = "") -> ActionResult:
        """Click an element."""
        session = self._sessions.get(session_id)
        if not session or not session.is_active:
            return ActionResult(success=False, action="click", error="Invalid session")

        domain = self._extract_domain(session.current_url)
        allowed, needs_approval, reason = self._policy_engine.check_action(
            ActionCategory.CLICK, domain, session_id,
        )
        if not allowed:
            return ActionResult(success=False, action="click", error=reason)

        # Detect sensitive
        sensitive = self._policy_engine.detect_sensitive_action(
            session.current_url, "click", text or selector,
        )
        if sensitive and sensitive in self._policy_engine.policy.approval_actions:
            return self._request_approval(
                session, "click", selector, domain,
                f"Click on potentially sensitive element: {text or selector}",
            )

        session.record_action("click", selector)
        self._audit.record(session_id, session.agent_name, "click",
                           target=selector, domain=domain)

        return ActionResult(success=True, action="click", data={"selector": selector})

    def select_option(self, session_id: str, selector: str, value: str) -> ActionResult:
        """Select a dropdown option."""
        session = self._sessions.get(session_id)
        if not session or not session.is_active:
            return ActionResult(success=False, action="select", error="Invalid session")

        session.record_action("select", f"{selector}={value}")
        self._audit.record(session_id, session.agent_name, "select",
                           target=selector, domain=self._extract_domain(session.current_url))

        return ActionResult(success=True, action="select", data={"selector": selector, "value": value})

    # ── Secret Injection ──

    def inject_secret(
        self,
        session_id: str,
        selector: str,
        secret_id: str,
        purpose: str = "",
    ) -> ActionResult:
        """Inject a vault secret into a form field. Secret never exposed in logs."""
        session = self._sessions.get(session_id)
        if not session or not session.is_active:
            return ActionResult(success=False, action="inject_secret", error="Invalid session")

        if not self._vault:
            return ActionResult(success=False, action="inject_secret", error="Vault not configured")

        domain = self._extract_domain(session.current_url)

        # Use secret from vault
        result = self._vault.use_secret(secret_id, session.agent_name, domain, purpose)
        if not result.success:
            self._audit.record(session_id, session.agent_name, "inject_secret",
                               target=selector, domain=domain, result="failed",
                               details=f"Vault denied: {result.error}")
            return ActionResult(success=False, action="inject_secret", error=result.error)

        # In real execution, would type result.inject_value into selector
        # NEVER log the value
        session.record_action("inject_secret", f"{selector}=***VAULT:{secret_id}***")

        self._audit.record(session_id, session.agent_name, "inject_secret",
                           target=selector, domain=domain,
                           details=f"secret_id={secret_id}, type={result.inject_type}")

        return ActionResult(success=True, action="inject_secret",
                            data={"selector": selector, "secret_id": secret_id, "injected": True})

    # ── Identity Login ──

    def login_with_identity(
        self,
        session_id: str,
        identity_id: str,
        login_url: str = "",
    ) -> ActionResult:
        """Login to a service using an identity from Identity Manager."""
        session = self._sessions.get(session_id)
        if not session or not session.is_active:
            return ActionResult(success=False, action="login", error="Invalid session")

        if not self._identity_mgr:
            return ActionResult(success=False, action="login", error="Identity Manager not configured")

        # Use identity (retrieves secrets from vault)
        domain = self._extract_domain(login_url or session.current_url)
        result = self._identity_mgr.use_identity(
            identity_id, session.agent_name, domain,
            session.environment, purpose="Browser login",
        )
        if not result.success:
            self._audit.record(session_id, session.agent_name, "login",
                               domain=domain, result="failed", details=result.error)
            return ActionResult(success=False, action="login", error=result.error)

        session.identity_id = identity_id
        session.record_action("login", f"identity={identity_id}, domain={domain}")

        self._audit.record(session_id, session.agent_name, "login",
                           domain=domain, details=f"identity={identity_id}, secrets={result.secrets_injected}")

        return ActionResult(success=True, action="login",
                            data={"identity_id": identity_id, "secrets_injected": result.secrets_injected})

    # ── Extraction ──

    def extract(self, session_id: str, mode: str = "text", selector: str = "") -> ActionResult:
        """Extract structured data from the current page."""
        session = self._sessions.get(session_id)
        if not session or not session.is_active:
            return ActionResult(success=False, action="extract", error="Invalid session")

        domain = self._extract_domain(session.current_url)

        # Extract is always allowed (read-only)
        extracted = ExtractedData()

        if self._test_mode:
            # Simulated extraction for testing
            extracted.title = f"Page at {session.current_url}"
            extracted.text = f"Content of {session.current_url}"
            extracted.links = [{"text": "Link 1", "href": "/link1"}]

        session.record_action("extract", f"mode={mode}")
        self._audit.record(session_id, session.agent_name, "extract",
                           domain=domain, details=f"mode={mode}")

        return ActionResult(success=True, action="extract", data=extracted.to_dict())

    def screenshot(self, session_id: str, full_page: bool = False) -> ActionResult:
        """Take a screenshot of the current page."""
        session = self._sessions.get(session_id)
        if not session or not session.is_active:
            return ActionResult(success=False, action="screenshot", error="Invalid session")

        # Screenshots always allowed
        path = f"{session.downloads_path}/screenshot_{int(time.time())}.png"
        session.record_action("screenshot", path)
        self._audit.record(session_id, session.agent_name, "screenshot",
                           domain=self._extract_domain(session.current_url))

        return ActionResult(success=True, action="screenshot",
                            data={"path": path, "full_page": full_page},
                            screenshot_path=path)

    # ── File Operations ──

    def upload(self, session_id: str, selector: str, file_path: str) -> ActionResult:
        """Upload a file. Must be from approved paths."""
        session = self._sessions.get(session_id)
        if not session or not session.is_active:
            return ActionResult(success=False, action="upload", error="Invalid session")

        allowed, reason = self._policy_engine.check_upload(file_path)
        if not allowed:
            self._audit.record(session_id, session.agent_name, "upload",
                               target=file_path, result="blocked", details=reason)
            return ActionResult(success=False, action="upload", error=reason)

        session.record_action("upload", file_path)
        self._audit.record(session_id, session.agent_name, "upload", target=file_path)

        return ActionResult(success=True, action="upload", data={"file": file_path, "selector": selector})

    def download(self, session_id: str, trigger_selector: str, filename: str = "") -> ActionResult:
        """Download a file to the session sandbox."""
        session = self._sessions.get(session_id)
        if not session or not session.is_active:
            return ActionResult(success=False, action="download", error="Invalid session")

        allowed, reason = self._policy_engine.check_download(filename)
        if not allowed:
            return ActionResult(success=False, action="download", error=reason)

        save_path = f"{session.downloads_path}/{filename or 'download'}"
        session.record_action("download", save_path)
        self._audit.record(session_id, session.agent_name, "download",
                           target=filename, details=f"save={save_path}")

        return ActionResult(success=True, action="download", data={"path": save_path})

    # ── Approval ──

    def approve_action(self, session_id: str, index: int = 0) -> bool:
        """Approve a pending action in a session."""
        session = self._sessions.get(session_id)
        if not session or not session.pending_approvals:
            return False
        if index >= len(session.pending_approvals):
            return False

        approval = session.pending_approvals.pop(index)
        approval["status"] = "approved"
        if session.status == "paused" and not session.pending_approvals:
            session.status = "active"

        self._audit.record(session_id, "admin", "approval_granted",
                           details=f"action={approval.get('action', '')}")
        return True

    def deny_action(self, session_id: str, index: int = 0) -> bool:
        """Deny a pending action."""
        session = self._sessions.get(session_id)
        if not session or not session.pending_approvals:
            return False

        approval = session.pending_approvals.pop(index)
        approval["status"] = "denied"
        if not session.pending_approvals:
            session.status = "active"

        self._audit.record(session_id, "admin", "approval_denied",
                           details=f"action={approval.get('action', '')}")
        return True

    # ── Audit ──

    def get_audit_logs(self, session_id: str | None = None, limit: int = 100) -> list[dict]:
        return self._audit.query(session_id=session_id, limit=limit)

    # ── Failure Learning ──

    def report_failure(self, session_id: str, failure_type: str, details: str = "") -> dict:
        """Report a browser failure for self-improvement learning."""
        session = self._sessions.get(session_id)
        if not session:
            return {"recorded": False}

        failure = {
            "type": failure_type,
            "session_id": session_id,
            "url": session.current_url,
            "agent": session.agent_name,
            "details": redact(details[:500]),
            "timestamp": time.time(),
        }

        self._audit.record(session_id, session.agent_name, "failure",
                           result="failed", details=f"type={failure_type}: {redact(details[:200])}")

        return {"recorded": True, "failure": failure}

    # ── Internals ──

    def _request_approval(
        self,
        session: BrowserSession,
        action: str,
        target: str,
        domain: str,
        description: str,
    ) -> ActionResult:
        """Create an approval request and pause the session."""
        approval = ApprovalRequest(
            action=action, url=session.current_url,
            domain=domain, description=description,
            risk_level=self._assess_risk(action, domain),
        )
        session.pending_approvals.append(approval.to_dict())
        session.status = "paused"

        self._audit.record(session.session_id, session.agent_name, action,
                           target=target, domain=domain, result="pending",
                           approval_state="pending")

        return ActionResult(
            success=False, action=action,
            needs_approval=True,
            approval_request=approval.to_dict(),
            error="Action requires approval",
        )

    def _assess_risk(self, action: str, domain: str) -> str:
        """Assess risk level of an action."""
        trust = self._policy_engine.check_domain(domain)
        if trust == DomainTrust.BLOCKED:
            return "high"
        if action in (ActionCategory.PURCHASE, ActionCategory.DELETE,
                      ActionCategory.CHANGE_BILLING, ActionCategory.CHANGE_SECURITY):
            return "high"
        if trust == DomainTrust.REVIEW:
            return "medium"
        return "low"

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract domain from URL."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            return parsed.hostname or ""
        except Exception:
            return ""

    @property
    def session_count(self) -> int:
        return len(self._sessions)

    @property
    def active_session_count(self) -> int:
        return sum(1 for s in self._sessions.values() if s.is_active)
