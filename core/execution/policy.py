"""
core/execution/policy.py — Execution policy safety layer.

Enforces safety constraints on all execution actions:
  - No financial transactions
  - No irreversible external actions
  - No legal commitments
  - No hidden network propagation
  - No uncontrolled credential usage

Every tool invocation and artifact build must pass policy checks.
"""
from __future__ import annotations

import structlog
from dataclasses import dataclass

log = structlog.get_logger("execution.policy")


# ── Policy rules ──────────────────────────────────────────────

@dataclass
class PolicyViolation:
    """A detected policy violation."""
    rule: str
    severity: str = "block"  # warn, block
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "description": self.description,
        }


# Blocked keywords in artifact content/context
_BLOCKED_PATTERNS = [
    ("financial_transaction", ["payment", "charge_card", "wire_transfer", "stripe.charges.create"]),
    ("credential_exposure", ["password=", "secret_key=", "api_key=", "private_key="]),
    ("legal_commitment", ["sign_contract", "legal_binding", "terms_acceptance"]),
    ("network_propagation", ["mass_email", "spam", "bulk_send", "broadcast_all"]),
    ("system_modification", ["/etc/", "/usr/", "/bin/", "sudo ", "chmod 777"]),
    ("irreversible_action", ["drop_database", "rm -rf", "format_disk", "delete_account"]),
]

# Tool policy classifications
TOOL_POLICY_MAP: dict[str, str] = {
    "file.workspace.write": "low",
    "git.status": "low",
    "notification.log": "low",
    "http.webhook.post": "medium",
    "n8n.workflow.trigger": "medium",
    "docker.run": "high",
    "shell.execute": "critical",
}


def classify_tool(tool_id: str) -> str:
    """Classify a tool's policy level."""
    return TOOL_POLICY_MAP.get(tool_id, "medium")


def check_content_policy(content: str) -> list[PolicyViolation]:
    """
    Scan content for policy violations.

    Returns list of violations. Empty = safe.
    """
    violations = []
    lower = content.lower()

    for rule_name, patterns in _BLOCKED_PATTERNS:
        for pattern in patterns:
            if pattern.lower() in lower:
                violations.append(PolicyViolation(
                    rule=rule_name,
                    severity="block",
                    description=f"Blocked pattern detected: '{pattern}'",
                ))
                break  # one violation per rule is enough

    return violations


def check_artifact_policy(artifact) -> list[PolicyViolation]:
    """
    Check if an artifact spec violates execution policy.

    Scans: description, expected_outcome, input_context values.
    """
    violations = []

    # Scan text fields
    text_to_scan = " ".join([
        artifact.description or "",
        artifact.expected_outcome or "",
        artifact.generation_rationale or "",
    ])
    violations.extend(check_content_policy(text_to_scan))

    # Scan input context values
    for k, v in (artifact.input_context or {}).items():
        ctx_violations = check_content_policy(str(v)[:500])
        violations.extend(ctx_violations)

    # Check tool dependencies
    for tool_dep in (artifact.required_tools or []):
        tool_class = classify_tool(tool_dep.tool_id)
        if tool_class == "critical":
            violations.append(PolicyViolation(
                rule="critical_tool",
                severity="block",
                description=f"Critical tool '{tool_dep.tool_id}' requires explicit approval",
            ))
        elif tool_class == "high":
            violations.append(PolicyViolation(
                rule="high_risk_tool",
                severity="warn",
                description=f"High-risk tool '{tool_dep.tool_id}' detected",
            ))

    return violations


def get_policy_classification(artifact) -> str:
    """
    Compute overall policy classification for an artifact.

    Returns: low, medium, high, critical
    """
    violations = check_artifact_policy(artifact)
    if any(v.severity == "block" for v in violations):
        return "critical"

    # Check tool risk levels
    tool_levels = []
    for tool_dep in (artifact.required_tools or []):
        tool_levels.append(classify_tool(tool_dep.tool_id))

    if "critical" in tool_levels:
        return "critical"
    elif "high" in tool_levels:
        return "high"
    elif "medium" in tool_levels:
        return "medium"
    return "low"


def is_safe_to_build(artifact) -> tuple[bool, list[PolicyViolation]]:
    """
    Final safety check before build.

    Returns (safe, violations).
    If any blocking violation exists, safe=False.
    """
    violations = check_artifact_policy(artifact)
    blocking = [v for v in violations if v.severity == "block"]
    return len(blocking) == 0, violations
