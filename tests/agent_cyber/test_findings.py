from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_cyber.findings import (
    Exploitability,
    FindingStatus,
    SecurityFinding,
    Severity,
    VulnClass,
)


def _finding(**kwargs) -> SecurityFinding:
    defaults = dict(
        mission_id="m-001",
        title="Test Finding",
        description="A test security finding",
        vuln_class=VulnClass.SQL_INJECTION,
        severity=Severity.HIGH,
        confidence=0.8,
    )
    defaults.update(kwargs)
    return SecurityFinding(**defaults)


def test_finding_valid_minimal():
    f = _finding()
    assert f.finding_id is not None
    assert f.status == FindingStatus.CANDIDATE
    assert f.exploitability == Exploitability.NOT_TESTED


def test_finding_missing_confidence_raises():
    with pytest.raises(ValidationError):
        SecurityFinding(
            mission_id="m-001",
            title="T",
            description="D",
            vuln_class=VulnClass.XSS,
            severity=Severity.MEDIUM,
        )


def test_finding_confidence_out_of_range_raises():
    with pytest.raises(ValidationError):
        _finding(confidence=1.5)


def test_finding_confirmed_without_evidence_raises():
    with pytest.raises(ValueError):
        _finding(status=FindingStatus.CONFIRMED, evidence_refs=[])


def test_finding_confirmed_with_evidence_ok():
    f = _finding(status=FindingStatus.CONFIRMED, evidence_refs=["ev-001"])
    assert f.status == FindingStatus.CONFIRMED


def test_finding_unverified_without_evidence_ok():
    f = _finding(status=FindingStatus.UNVERIFIED)
    assert f.status == FindingStatus.UNVERIFIED


def test_finding_candidate_default_ok():
    f = _finding()
    assert f.status == FindingStatus.CANDIDATE


def test_finding_vuln_class_enum():
    f = _finding(vuln_class=VulnClass.PATH_TRAVERSAL)
    assert f.vuln_class == VulnClass.PATH_TRAVERSAL


def test_finding_invalid_vuln_class_raises():
    with pytest.raises(ValidationError):
        _finding(vuln_class="buffer-overflow")


def test_finding_with_location():
    f = _finding(
        affected_file="api/routes.py",
        affected_function="get_user",
        affected_lines=[42, 43, 44],
    )
    assert f.affected_file == "api/routes.py"
    assert f.affected_function == "get_user"
    assert 42 in (f.affected_lines or [])


def test_finding_severity_enum():
    for sev in (Severity.INFORMATIONAL, Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL):
        f = _finding(severity=sev)
        assert f.severity == sev


def test_finding_all_vuln_classes_valid():
    for vc in VulnClass:
        f = _finding(vuln_class=vc)
        assert f.vuln_class == vc


def test_finding_remediation_optional():
    f = _finding(remediation="Use parameterized queries")
    assert f.remediation == "Use parameterized queries"


def test_finding_false_positive_no_evidence_ok():
    f = _finding(status=FindingStatus.FALSE_POSITIVE)
    assert f.status == FindingStatus.FALSE_POSITIVE


def test_finding_fixed_no_evidence_ok():
    f = _finding(status=FindingStatus.FIXED)
    assert f.status == FindingStatus.FIXED
