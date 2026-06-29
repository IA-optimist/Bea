from __future__ import annotations

from enum import Enum


class CyberActionType(str, Enum):
    CODE_REVIEW = "code_review"
    DEPENDENCY_AUDIT = "dependency_audit"
    SECRET_SCAN = "secret_scan"
    CONFIG_REVIEW = "config_review"
    AUTH_REVIEW = "auth_review"
    ACCESS_CONTROL_REVIEW = "access_control_review"
    SECURITY_HEADERS_REVIEW = "security_headers_review"
    STATIC_ANALYSIS = "static_analysis"
    GENERATE_REPORT = "generate_report"
    PROPOSE_FIX = "propose_fix"
    GENERATE_REGRESSION_TESTS = "generate_regression_tests"


class BlockedCyberActionType(str, Enum):
    EXPLOIT = "exploit"
    BRUTE_FORCE = "brute_force"
    WAF_BYPASS = "waf_bypass"
    POST_EXPLOITATION = "post_exploitation"
    PERSISTENCE = "persistence"
    EXFILTRATION = "exfiltration"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    DESTRUCTIVE_TEST = "destructive_test"
    UNAUTHORIZED_SCAN = "unauthorized_scan"
    PAYLOAD_ESCALATION = "payload_escalation"


# Fast O(1) block check
BLOCKED_ACTION_NAMES: frozenset[str] = frozenset(a.value for a in BlockedCyberActionType)

# Fast O(1) allowed check
ALLOWED_ACTION_NAMES: frozenset[str] = frozenset(a.value for a in CyberActionType)
