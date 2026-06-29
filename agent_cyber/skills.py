from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from agent_cyber.actions import BLOCKED_ACTION_NAMES
from agent_cyber.scope import RiskLevel


class CyberSkill(BaseModel):
    skill_id: str
    name: str
    description: str
    allowed_actions: list[str]
    required_capabilities: list[str] = Field(default_factory=list)
    required_scope_fields: list[str] = Field(default_factory=list)
    risk_level: RiskLevel
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    evidence_required: bool = True
    tests_required: bool = True
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_skill_safety(self) -> "CyberSkill":
        if not self.allowed_actions:
            raise ValueError("CyberSkill requires at least one allowed_action")
        for action in self.allowed_actions:
            if action in BLOCKED_ACTION_NAMES:
                raise ValueError(f"CyberSkill cannot include blocked action: {action}")
        return self


DEFENSIVE_SKILLS_V1_DATA: list[dict] = [
    {
        "skill_id": "security_headers_review",
        "name": "Security Headers Review",
        "description": "Analyzes HTTP response headers for security issues (CSP, HSTS, X-Frame-Options, etc.)",
        "allowed_actions": ["security_headers_review", "generate_report"],
        "required_capabilities": ["cyber.config_review"],
        "required_scope_fields": ["targets"],
        "risk_level": "low",
        "evidence_required": True,
        "tests_required": False,
        "limitations": ["Static analysis only — no live HTTP requests in v1 unless scope.max_requests > 0"],
    },
    {
        "skill_id": "dependency_vulnerability_review",
        "name": "Dependency Vulnerability Review",
        "description": "Audits requirements.txt/pyproject.toml/pubspec.yaml for known CVEs",
        "allowed_actions": ["dependency_audit", "generate_report"],
        "required_capabilities": ["cyber.dependency_audit"],
        "required_scope_fields": [],
        "risk_level": "low",
        "evidence_required": True,
        "tests_required": False,
        "limitations": ["Requires pip-audit or equivalent tool accessible in sandbox"],
    },
    {
        "skill_id": "secrets_scan_review",
        "name": "Secrets Scan Review",
        "description": "Scans codebase for hardcoded secrets, API keys, tokens",
        "allowed_actions": ["secret_scan", "generate_report"],
        "required_capabilities": ["cyber.secret_scan"],
        "required_scope_fields": ["allowed_paths"],
        "risk_level": "medium",
        "evidence_required": True,
        "tests_required": False,
        "limitations": ["Only local files. Results are redacted before logging."],
    },
    {
        "skill_id": "auth_flow_review",
        "name": "Auth Flow Review",
        "description": "Static analysis of authentication code for common vulnerabilities",
        "allowed_actions": ["auth_review", "code_review", "generate_report"],
        "required_capabilities": ["cyber.auth_review"],
        "required_scope_fields": ["allowed_paths"],
        "risk_level": "medium",
        "evidence_required": True,
        "tests_required": True,
        "limitations": ["Static analysis only. Cannot test live auth endpoints in v1."],
    },
    {
        "skill_id": "access_control_review",
        "name": "Access Control Review",
        "description": "Reviews RBAC, permission checks, and access control patterns",
        "allowed_actions": ["access_control_review", "code_review", "generate_report"],
        "required_capabilities": ["cyber.auth_review"],
        "required_scope_fields": ["allowed_paths"],
        "risk_level": "medium",
        "evidence_required": True,
        "tests_required": True,
        "limitations": ["Static analysis only."],
    },
    {
        "skill_id": "input_validation_review",
        "name": "Input Validation Review",
        "description": "Analyzes input sanitization, validation, and injection prevention",
        "allowed_actions": ["code_review", "static_analysis", "generate_report"],
        "required_capabilities": ["cyber.code_review"],
        "required_scope_fields": ["allowed_paths"],
        "risk_level": "low",
        "evidence_required": True,
        "tests_required": False,
        "limitations": ["Static analysis only."],
    },
    {
        "skill_id": "mcp_security_review",
        "name": "MCP Security Review",
        "description": "Reviews MCP server/tool configurations for security issues",
        "allowed_actions": ["config_review", "code_review", "generate_report"],
        "required_capabilities": ["cyber.config_review"],
        "required_scope_fields": ["allowed_paths"],
        "risk_level": "medium",
        "evidence_required": True,
        "tests_required": False,
        "limitations": ["Static configuration analysis only."],
    },
    {
        "skill_id": "ai_agent_security_review",
        "name": "AI Agent Security Review",
        "description": "Audits AI agent code for prompt injection, tool misuse, sandbox escapes",
        "allowed_actions": ["code_review", "static_analysis", "generate_report"],
        "required_capabilities": ["cyber.code_review"],
        "required_scope_fields": ["allowed_paths"],
        "risk_level": "high",
        "evidence_required": True,
        "tests_required": True,
        "limitations": ["Static analysis. Cannot test live agent runtime."],
    },
    {
        "skill_id": "config_review",
        "name": "Configuration Review",
        "description": "Reviews app/infra configuration for security misconfigurations",
        "allowed_actions": ["config_review", "generate_report"],
        "required_capabilities": ["cyber.config_review"],
        "required_scope_fields": [],
        "risk_level": "low",
        "evidence_required": True,
        "tests_required": False,
        "limitations": [],
    },
    {
        "skill_id": "regression_test_planner",
        "name": "Regression Test Planner",
        "description": "Generates regression test plans for found vulnerabilities",
        "allowed_actions": ["generate_regression_tests", "generate_report"],
        "required_capabilities": ["cyber.regression_tests"],
        "required_scope_fields": [],
        "risk_level": "safe",
        "evidence_required": True,
        "tests_required": False,
        "limitations": ["Generates test PLANS only — not runnable code in v1."],
    },
    {
        "skill_id": "remediation_planner",
        "name": "Remediation Planner",
        "description": "Proposes targeted fixes for confirmed or suspected vulnerabilities",
        "allowed_actions": ["propose_fix", "generate_report"],
        "required_capabilities": ["cyber.fix_proposal"],
        "required_scope_fields": [],
        "risk_level": "medium",
        "evidence_required": True,
        "tests_required": True,
        "limitations": ["Proposals only — actual code changes go through CodeAgent + SecurityReviewer."],
    },
]

DEFENSIVE_SKILLS_V1: list[CyberSkill] = [
    CyberSkill(**skill) for skill in DEFENSIVE_SKILLS_V1_DATA
]

SKILL_REGISTRY: dict[str, CyberSkill] = {s.skill_id: s for s in DEFENSIVE_SKILLS_V1}
