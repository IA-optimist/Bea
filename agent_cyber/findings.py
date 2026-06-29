from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class VulnClass(str, Enum):
    COMMAND_INJECTION = "command-injection"
    SQL_INJECTION = "sql-injection"
    XSS = "xss"
    PATH_TRAVERSAL = "path-traversal"
    AUTH_BYPASS = "auth-bypass"
    ACCESS_CONTROL = "access-control"
    INSECURE_DESERIALIZATION = "insecure-deserialization"
    XXE = "xxe"
    SSRF = "ssrf"
    CRYPTO_WEAKNESS = "crypto-weakness"
    RACE_CONDITION = "race-condition"
    SECRET_EXPOSURE = "secret-exposure"
    DEPENDENCY_VULNERABILITY = "dependency-vulnerability"
    INSECURE_CONFIGURATION = "insecure-configuration"
    INPUT_VALIDATION = "input-validation"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    INFORMATIONAL = "informational"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingStatus(str, Enum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    UNVERIFIED = "unverified"
    FALSE_POSITIVE = "false_positive"
    FIXED = "fixed"


class Exploitability(str, Enum):
    NOT_TESTED = "not_tested"
    THEORETICAL = "theoretical"
    VALIDATED_IN_LAB = "validated_in_lab"
    OUT_OF_SCOPE = "out_of_scope"


class SecurityFinding(BaseModel):
    finding_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    mission_id: str
    title: str
    description: str
    vuln_class: VulnClass
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    status: FindingStatus = FindingStatus.CANDIDATE
    affected_file: Optional[str] = None
    affected_function: Optional[str] = None
    affected_lines: Optional[list[int]] = None
    affected_component: Optional[str] = None
    evidence_refs: list[str] = Field(default_factory=list)
    exploitability: Exploitability = Exploitability.NOT_TESTED
    impact: str = ""
    remediation: str = ""
    regression_tests: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    reviewer_verdict: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @model_validator(mode="after")
    def confirmed_requires_evidence(self) -> "SecurityFinding":
        if self.status == FindingStatus.CONFIRMED and not self.evidence_refs:
            raise ValueError("CONFIRMED finding requires at least one evidence_ref")
        return self
