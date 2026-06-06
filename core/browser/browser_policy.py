"""
JARVIS MAX — Browser Policy Engine
======================================
Controls what the browser agent can and cannot do.

- Domain trust levels (trusted / review_required / blocked)
- Action-level deny/allow rules
- Payment/destructive action detection
- File upload/download restrictions
- Approval requirements by action type
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field


class DomainTrust:
    TRUSTED = "trusted"
    REVIEW = "review_required"
    BLOCKED = "blocked"


class ActionCategory:
    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    SELECT = "select"
    UPLOAD = "upload"
    DOWNLOAD = "download"
    SCREENSHOT = "screenshot"
    EXTRACT = "extract"
    INJECT_SECRET = "inject_secret"  # nosec B105 — enum value, not a credential
    SUBMIT_FORM = "submit_form"
    EXECUTE_JS = "execute_js"
    PURCHASE = "purchase"
    DELETE = "delete"
    CHANGE_BILLING = "change_billing"
    CHANGE_SECURITY = "change_security"
    ACCEPT_LEGAL = "accept_legal"
    SOCIAL_POST = "social_post"
    ACCOUNT_RECOVERY = "account_recovery"


# Actions that ALWAYS require human approval
APPROVAL_REQUIRED_ACTIONS = frozenset({
    ActionCategory.PURCHASE,
    ActionCategory.DELETE,
    ActionCategory.CHANGE_BILLING,
    ActionCategory.CHANGE_SECURITY,
    ActionCategory.ACCEPT_LEGAL,
    ActionCategory.SOCIAL_POST,
    ActionCategory.ACCOUNT_RECOVERY,
})

# Actions blocked by default (can be unblocked per-policy)
DEFAULT_BLOCKED_ACTIONS = frozenset({
    ActionCategory.EXECUTE_JS,
})


@dataclass
class ApprovalRequest:
    """Browser action approval request."""
    action: str
    url: str
    domain: str
    description: str
    risk_level: str = "medium"      # low/medium/high
    reason: str = ""
    approved: bool | None = None    # None = pending
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "action": self.action, "url": self.url[:200],
            "domain": self.domain, "description": self.description[:200],
            "risk": self.risk_level, "reason": self.reason[:200],
            "status": "pending" if self.approved is None else (
                "approved" if self.approved else "denied"),
        }


@dataclass
class BrowserPolicy:
    """Configurable browser policy."""
    # Domain rules
    trusted_domains: list[str] = field(default_factory=list)
    blocked_domains: list[str] = field(default_factory=lambda: [
        "*.gov", "*.mil", "*.bank",
    ])
    default_trust: str = "review_required"

    # Action rules
    blocked_actions: set[str] = field(default_factory=lambda: set(DEFAULT_BLOCKED_ACTIONS))
    approval_actions: set[str] = field(default_factory=lambda: set(APPROVAL_REQUIRED_ACTIONS))

    # File rules
    allowed_upload_paths: list[str] = field(default_factory=lambda: ["data/uploads/"])
    max_download_size_mb: int = 100
    allowed_download_types: list[str] = field(default_factory=lambda: [
        ".pdf", ".csv", ".json", ".txt", ".png", ".jpg", ".svg",
    ])

    # Limits
    max_navigation_per_session: int = 100
    max_actions_per_minute: int = 30
    session_timeout_s: int = 1800  # 30 min

    def to_dict(self) -> dict:
        return {
            "trusted_domains": self.trusted_domains,
            "blocked_domains": self.blocked_domains,
            "blocked_actions": sorted(self.blocked_actions),
            "approval_actions": sorted(self.approval_actions),
            "max_nav": self.max_navigation_per_session,
            "max_actions_min": self.max_actions_per_minute,
            "timeout_s": self.session_timeout_s,
        }


class BrowserPolicyEngine:
    """Evaluates browser actions against policy."""

    def __init__(self, policy: BrowserPolicy | None = None):
        self._policy = policy or BrowserPolicy()
        self._action_counts: dict[str, list[float]] = {}  # session → timestamps

    @property
    def policy(self) -> BrowserPolicy:
        return self._policy

    def check_domain(self, domain: str) -> str:
        """Return trust level for a domain."""
        domain_lower = domain.lower()

        # Check blocked
        for pattern in self._policy.blocked_domains:
            if self._match_domain(domain_lower, pattern):
                return DomainTrust.BLOCKED

        # Check trusted
        for pattern in self._policy.trusted_domains:
            if self._match_domain(domain_lower, pattern):
                return DomainTrust.TRUSTED

        return self._policy.default_trust

    def check_action(
        self,
        action: str,
        domain: str,
        session_id: str = "",
    ) -> tuple[bool, bool, str]:
        """
        Check if an action is allowed.
        Returns (allowed, needs_approval, reason).
        """
        # Blocked actions
        if action in self._policy.blocked_actions:
            return False, False, f"Action '{action}' is blocked by policy"

        # Blocked domain
        trust = self.check_domain(domain)
        if trust == DomainTrust.BLOCKED:
            return False, False, f"Domain '{domain}' is blocked"

        # Approval required
        needs_approval = action in self._policy.approval_actions
        if trust == DomainTrust.REVIEW:
            needs_approval = True

        # Rate limit
        if session_id and not self._check_rate(session_id):
            return False, False, "Rate limit exceeded"

        reason = "approval_required" if needs_approval else "allowed"
        return True, needs_approval, reason

    def check_upload(self, file_path: str) -> tuple[bool, str]:
        """Check if a file upload is allowed."""
        for allowed in self._policy.allowed_upload_paths:
            if file_path.startswith(allowed):
                return True, "allowed"
        return False, f"Upload from '{file_path}' not in allowed paths"

    def check_download(self, filename: str, size_mb: float = 0) -> tuple[bool, str]:
        """Check if a download is allowed."""
        if size_mb > self._policy.max_download_size_mb:
            return False, f"Download too large ({size_mb}MB > {self._policy.max_download_size_mb}MB)"

        ext = ""
        if "." in filename:
            ext = "." + filename.rsplit(".", 1)[-1].lower()
        if ext and ext not in self._policy.allowed_download_types:
            return False, f"Download type '{ext}' not allowed"

        return True, "allowed"

    def detect_sensitive_action(self, url: str, action: str, text: str = "") -> str | None:
        """Detect if an action is sensitive (payment, delete, etc.)."""
        combined = f"{url} {action} {text}".lower()

        patterns = {
            ActionCategory.PURCHASE: r"(payment|checkout|buy|purchase|order|pay now|subscribe)",
            ActionCategory.DELETE: r"(delete|remove|destroy|cancel account|deactivate)",
            ActionCategory.CHANGE_BILLING: r"(billing|payment method|credit card|invoice)",
            ActionCategory.CHANGE_SECURITY: r"(password|2fa|mfa|security|api.key|token)",
            ActionCategory.ACCEPT_LEGAL: r"(terms|agree|consent|privacy policy|tos|eula)",
        }

        for category, pattern in patterns.items():
            if re.search(pattern, combined):
                return category
        return None

    def _match_domain(self, domain: str, pattern: str) -> bool:
        """Match domain against pattern (supports *.suffix wildcards)."""
        if pattern.startswith("*."):
            suffix = pattern[1:]  # .gov, .bank etc
            return domain.endswith(suffix)
        return domain == pattern or domain.endswith("." + pattern)

    def _check_rate(self, session_id: str) -> bool:
        now = time.time()
        window = now - 60
        if session_id not in self._action_counts:
            self._action_counts[session_id] = []
        self._action_counts[session_id] = [
            t for t in self._action_counts[session_id] if t > window
        ]
        if len(self._action_counts[session_id]) >= self._policy.max_actions_per_minute:
            return False
        self._action_counts[session_id].append(now)
        return True
