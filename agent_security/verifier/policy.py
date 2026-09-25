from __future__ import annotations

import re
from typing import Optional

from agent_security.verifier.models import (
    ActionIntent,
    ActionType,
    RiskLevel,
    VerifierDecision,
    VerifierVerdict,
)

# ── Protected target patterns → HALT ───────────────────────────────────────
_HALT_TARGET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"verifier", re.IGNORECASE),
    re.compile(r"security[_\-/]config", re.IGNORECASE),
    re.compile(r"(audit[_\-]?log|audit\.log)", re.IGNORECASE),
    re.compile(r"policy\.py", re.IGNORECASE),
    re.compile(r"credential", re.IGNORECASE),
    re.compile(r"kill.?switch", re.IGNORECASE),
    re.compile(r"invariant", re.IGNORECASE),
    re.compile(r"sandbox[_\-/]config", re.IGNORECASE),
    re.compile(r"capability[_\-/]registry", re.IGNORECASE),
    re.compile(r"\.env$", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
]

# Action types that always require human approval
_HOLD_ACTION_TYPES: frozenset[ActionType] = frozenset({
    ActionType.SELF_MODIFICATION,
    ActionType.SPAWN_AGENT,
    ActionType.MODIFY_MEMORY,
    ActionType.MODIFY_SECURITY_CONFIG,
})

# Allowed workspace prefixes for filesystem writes
_ALLOWED_WRITE_PREFIXES: tuple[str, ...] = (
    "C:/Users/maxen/Documents/Béa/",
    "C:\\Users\\maxen\\Documents\\Béa\\",
    "/workspace/",
)

# Whitelisted external domains for network requests
_WHITELISTED_DOMAINS: frozenset[str] = frozenset({
    "api.github.com",
    "pypi.org",
    "huggingface.co",
    "railway.app",
})

# Known trusted API service names
_KNOWN_APIS: frozenset[str] = frozenset({
    "github", "pypi", "openrouter", "stripe", "railway", "mistral", "anthropic",
})

# IMPORTANT: policy NEVER reads intent.metadata, intent.risk_hint, or any free-text field.
# Those exist for audit logging only.


class VerifierPolicy:
    """
    Deterministic, stateless policy engine.
    Deny-by-default. No LLM. No natural language parsing.
    Fail-closed: any internal exception → DENY verdict returned (never raised).
    """

    def evaluate(self, intent: ActionIntent) -> VerifierDecision:
        """Evaluate intent. Never raises — always returns a VerifierDecision."""
        try:
            return self._evaluate_inner(intent)
        except Exception as exc:
            return VerifierDecision(
                verdict=VerifierVerdict.DENY,
                reason=f"policy internal error (fail-closed): {type(exc).__name__}",
                action_id=intent.action_id,
                risk_level=RiskLevel.CRITICAL,
            )

    def _evaluate_inner(self, intent: ActionIntent) -> VerifierDecision:
        # Priority order: HALT > HOLD > DENY > (implicit allowlist) > DENY default
        halt = self._check_halt(intent)
        if halt:
            return halt

        hold = self._check_hold(intent)
        if hold:
            return hold

        deny = self._check_deny(intent)
        if deny:
            return deny

        return self._check_allow(intent)

    def _check_halt(self, intent: ActionIntent) -> Optional[VerifierDecision]:
        """HALT: action targets a protected system component."""
        for pattern in _HALT_TARGET_PATTERNS:
            if pattern.search(intent.target):
                return VerifierDecision(
                    verdict=VerifierVerdict.HALT,
                    reason=f"target matches protected pattern '{pattern.pattern}'",
                    action_id=intent.action_id,
                    risk_level=RiskLevel.CRITICAL,
                )
        # MODIFY_SECURITY_CONFIG is always HALT regardless of target
        if intent.action_type == ActionType.MODIFY_SECURITY_CONFIG:
            return VerifierDecision(
                verdict=VerifierVerdict.HALT,
                reason="MODIFY_SECURITY_CONFIG is always HALT in v0",
                action_id=intent.action_id,
                risk_level=RiskLevel.CRITICAL,
            )
        return None

    def _check_hold(self, intent: ActionIntent) -> Optional[VerifierDecision]:
        """HOLD: high-risk action types requiring human approval."""
        if intent.action_type in _HOLD_ACTION_TYPES:
            return VerifierDecision(
                verdict=VerifierVerdict.HOLD,
                reason=f"action_type {intent.action_type.value!r} requires human approval",
                action_id=intent.action_id,
                risk_level=RiskLevel.HIGH,
                requires_human_approval=True,
            )
        # Write outside workspace
        if intent.action_type == ActionType.FILESYSTEM_WRITE:
            if not self._is_allowed_write_path(intent.target):
                return VerifierDecision(
                    verdict=VerifierVerdict.HOLD,
                    reason=f"write target {intent.target!r} is outside allowed workspace",
                    action_id=intent.action_id,
                    risk_level=RiskLevel.HIGH,
                    requires_human_approval=True,
                )
        # Network to non-whitelisted domain
        if intent.action_type == ActionType.NETWORK_REQUEST:
            domain = self._extract_domain(intent.target)
            if domain and domain not in _WHITELISTED_DOMAINS:
                return VerifierDecision(
                    verdict=VerifierVerdict.HOLD,
                    reason=f"network domain {domain!r} is not whitelisted",
                    action_id=intent.action_id,
                    risk_level=RiskLevel.HIGH,
                    requires_human_approval=True,
                )
        # API call to unknown service
        if intent.action_type == ActionType.API_CALL:
            service = str(intent.parameters.get("service", ""))
            if not service or service.lower() not in _KNOWN_APIS:
                return VerifierDecision(
                    verdict=VerifierVerdict.HOLD,
                    reason=f"API call to unknown service {service!r}",
                    action_id=intent.action_id,
                    risk_level=RiskLevel.HIGH,
                    requires_human_approval=True,
                )
        return None

    def _check_deny(self, intent: ActionIntent) -> Optional[VerifierDecision]:
        """DENY: invalid or explicitly blocked actions."""
        # Belt-and-suspenders: Pydantic already enforces these, but policy re-checks
        if not intent.actor_id or not intent.action_id:
            return VerifierDecision(
                verdict=VerifierVerdict.DENY,
                reason="missing actor_id or action_id",
                action_id=intent.action_id or "unknown",
                risk_level=RiskLevel.HIGH,
            )
        # EXEC_COMMAND: denied in v0 (no sandbox authorization yet)
        if intent.action_type == ActionType.EXEC_COMMAND:
            return VerifierDecision(
                verdict=VerifierVerdict.DENY,
                reason="EXEC_COMMAND requires explicit sandbox authorization — denied in v0 by default",
                action_id=intent.action_id,
                risk_level=RiskLevel.HIGH,
            )
        return None

    def _check_allow(self, intent: ActionIntent) -> VerifierDecision:
        """Final allowlist — only explicitly permitted action types pass."""
        # Safe reads and message sends
        if intent.action_type in {ActionType.FILESYSTEM_READ, ActionType.SEND_MESSAGE}:
            return VerifierDecision(
                verdict=VerifierVerdict.ALLOW,
                reason=f"{intent.action_type.value} allowed (policy allowlist)",
                action_id=intent.action_id,
                risk_level=RiskLevel.LOW,
            )
        # Filesystem write to allowed workspace
        if intent.action_type == ActionType.FILESYSTEM_WRITE and self._is_allowed_write_path(intent.target):
            return VerifierDecision(
                verdict=VerifierVerdict.ALLOW,
                reason="filesystem write to allowed workspace path",
                action_id=intent.action_id,
                risk_level=RiskLevel.LOW,
            )
        # Network to whitelisted domain
        if intent.action_type == ActionType.NETWORK_REQUEST:
            domain = self._extract_domain(intent.target)
            if domain and domain in _WHITELISTED_DOMAINS:
                return VerifierDecision(
                    verdict=VerifierVerdict.ALLOW,
                    reason=f"network request to whitelisted domain {domain!r}",
                    action_id=intent.action_id,
                    risk_level=RiskLevel.LOW,
                )
        # Default deny — not in allowlist
        return VerifierDecision(
            verdict=VerifierVerdict.DENY,
            reason=f"action_type {intent.action_type.value!r} not in allowlist (deny-by-default)",
            action_id=intent.action_id,
            risk_level=RiskLevel.MEDIUM,
        )

    @staticmethod
    def _is_allowed_write_path(target: str) -> bool:
        normalized = target.replace("\\", "/")
        return any(normalized.startswith(p.replace("\\", "/")) for p in _ALLOWED_WRITE_PREFIXES)

    @staticmethod
    def _extract_domain(target: str) -> Optional[str]:
        match = re.search(r"https?://([^/:\s?#]+)", target)
        return match.group(1) if match else None
