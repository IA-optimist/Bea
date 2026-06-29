from __future__ import annotations

import re
import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator

try:
    from core.observability.redactor import redact as _redact
except ImportError:
    def _redact(v: str) -> str:  # type: ignore[misc]
        return v

_SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9_-]{16,}"), "[REDACTED_KEY]"),
    (re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._-]{20,}"), r"\1[REDACTED_TOKEN]"),
    (re.compile(r"bea-[A-Za-z0-9_-]{16,}"), "[BEA_TOKEN_REDACTED]"),
]


def _redact_summary(v: str) -> str:
    for pattern, replacement in _SECRET_PATTERNS:
        v = pattern.sub(replacement, v)
    return _redact(v)


class EvidenceType(str, Enum):
    FILE_LOCATION = "file_location"
    CODE_SNIPPET = "code_snippet"
    TEST_OUTPUT = "test_output"
    TOOL_OUTPUT = "tool_output"
    DEPENDENCY_REPORT = "dependency_report"
    SECRET_SCAN_RESULT = "secret_scan_result"
    CONFIG_VALUE = "config_value"
    HTTP_OBSERVATION = "http_observation"
    USER_PROVIDED_AUTHORIZATION = "user_provided_authorization"


class Evidence(BaseModel):
    evidence_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    evidence_type: EvidenceType
    source: str
    content_summary: str
    raw_ref: Optional[str] = None
    file: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    function: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    redacted: bool = False

    @field_validator("content_summary")
    @classmethod
    def no_secrets_in_summary(cls, v: str) -> str:
        return _redact_summary(v)


class ClaimType(str, Enum):
    VULNERABILITY_EXISTS = "vulnerability_exists"
    VULNERABILITY_ABSENT = "vulnerability_absent"
    TEST_PASSED = "test_passed"
    FIX_VALID = "fix_valid"
    RISK_ASSESSMENT = "risk_assessment"
    SCOPE_AUTHORIZED = "scope_authorized"


class ClaimStatus(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    REJECTED = "rejected"


class Claim(BaseModel):
    claim_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    claim_type: ClaimType
    content: str
    severity: str = "informational"
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_refs: list[str] = Field(default_factory=list)
    status: ClaimStatus = ClaimStatus.UNVERIFIED


class EvidenceGate:
    """Anti-hallucination: requires evidence for critical claims."""

    def __init__(self) -> None:
        self._evidence: dict[str, Evidence] = {}

    def attach_evidence(self, evidence: Evidence) -> None:
        self._evidence[evidence.evidence_id] = evidence

    def validate_claim(self, claim: Claim) -> Claim:
        """Validate and update claim status based on attached evidence."""
        # Check evidence_refs exist
        missing = [ref for ref in claim.evidence_refs if ref not in self._evidence]
        if missing:
            return claim.model_copy(update={"status": ClaimStatus.REJECTED})

        has_evidence = bool(claim.evidence_refs)

        if claim.claim_type == ClaimType.VULNERABILITY_EXISTS:
            # Can be unverified without evidence (pattern match, suspicion)
            if not has_evidence:
                return claim.model_copy(update={"status": ClaimStatus.UNVERIFIED})
            return claim.model_copy(update={"status": ClaimStatus.VERIFIED})

        if claim.claim_type == ClaimType.VULNERABILITY_ABSENT:
            if not has_evidence:
                return claim.model_copy(update={"status": ClaimStatus.UNVERIFIED})
            return claim.model_copy(update={"status": ClaimStatus.VERIFIED})

        if claim.claim_type == ClaimType.TEST_PASSED:
            if not has_evidence:
                return claim.model_copy(update={"status": ClaimStatus.REJECTED})
            has_test_output = any(
                self._evidence[r].evidence_type == EvidenceType.TEST_OUTPUT
                for r in claim.evidence_refs
                if r in self._evidence
            )
            if not has_test_output:
                return claim.model_copy(update={"status": ClaimStatus.REJECTED})
            return claim.model_copy(update={"status": ClaimStatus.VERIFIED})

        if claim.claim_type == ClaimType.FIX_VALID:
            if not has_evidence:
                return claim.model_copy(update={"status": ClaimStatus.UNVERIFIED})
            has_code_or_test = any(
                self._evidence[r].evidence_type in (EvidenceType.CODE_SNIPPET, EvidenceType.TEST_OUTPUT)
                for r in claim.evidence_refs
                if r in self._evidence
            )
            if not has_code_or_test:
                return claim.model_copy(update={"status": ClaimStatus.UNVERIFIED})
            return claim.model_copy(update={"status": ClaimStatus.VERIFIED})

        if claim.claim_type == ClaimType.SCOPE_AUTHORIZED:
            if not has_evidence:
                return claim.model_copy(update={"status": ClaimStatus.REJECTED})
            has_auth = any(
                self._evidence[r].evidence_type == EvidenceType.USER_PROVIDED_AUTHORIZATION
                for r in claim.evidence_refs
                if r in self._evidence
            )
            if not has_auth:
                return claim.model_copy(update={"status": ClaimStatus.REJECTED})
            return claim.model_copy(update={"status": ClaimStatus.VERIFIED})

        if claim.claim_type == ClaimType.RISK_ASSESSMENT:
            if not has_evidence:
                return claim.model_copy(update={"status": ClaimStatus.UNVERIFIED})
            return claim.model_copy(update={"status": ClaimStatus.VERIFIED})

        # Default: unverified
        return claim.model_copy(update={"status": ClaimStatus.UNVERIFIED})
