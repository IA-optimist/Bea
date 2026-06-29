from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent_cyber.findings import FindingStatus, SecurityFinding, Severity, VulnClass
from agent_cyber.reports import CyberReport, CyberReportGenerator


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


def _report(**kwargs) -> CyberReport:
    defaults = dict(
        mission_id="m-001",
        scope_summary="Local codebase review of /app",
        authorization_status="explicit",
    )
    defaults.update(kwargs)
    return CyberReport(**defaults)


gen = CyberReportGenerator()

MANDATORY_SECTIONS = [
    "## 1. Executive Summary",
    "## 2. Scope",
    "## 3. Authorization",
    "## 4. Methodology",
    "## 5. Findings",
    "## 6. Evidence Summary",
    "## 7. Impact",
    "## 8. Recommended Fixes",
    "## 9. Tests to Add",
    "## 10. Limitations",
    "## 11. Blocked Actions",
]


def test_report_missing_scope_raises():
    with pytest.raises((ValueError, ValidationError)):
        CyberReport(
            mission_id="m-001",
            scope_summary="",
            authorization_status="explicit",
        )


def test_report_missing_auth_raises():
    with pytest.raises((ValueError, ValidationError)):
        CyberReport(
            mission_id="m-001",
            scope_summary="Local review",
            authorization_status="",
        )


def test_report_generates_markdown():
    report = _report()
    md, _ = gen.generate(report)
    assert "# Cyber Security Report" in md


def test_report_markdown_all_mandatory_sections():
    report = _report()
    md, _ = gen.generate(report)
    for section in MANDATORY_SECTIONS:
        assert section in md, f"Missing section: {section}"


def test_report_unverified_finding_marked():
    f = _finding(status=FindingStatus.UNVERIFIED)
    report = _report(findings=[f])
    md, _ = gen.generate(report)
    assert "UNVERIFIED" in md
    assert "⚠️" in md


def test_report_confirmed_finding_marked():
    f = _finding(status=FindingStatus.CONFIRMED, evidence_refs=["ev-001"])
    report = _report(findings=[f])
    md, _ = gen.generate(report)
    assert "CONFIRMED" in md or "✅" in md


def test_report_json_serializable():
    report = _report()
    _, data = gen.generate(report)
    # Should not raise
    dumped = json.dumps(data)
    assert "mission_id" in dumped


def test_report_json_contains_findings():
    f = _finding(status=FindingStatus.CANDIDATE)
    report = _report(findings=[f])
    _, data = gen.generate(report)
    assert len(data["findings"]) == 1
    assert data["findings"][0]["vuln_class"] == "sql-injection"


def test_report_scope_summary_in_markdown():
    report = _report(scope_summary="Review of /app/auth module")
    md, _ = gen.generate(report)
    assert "Review of /app/auth module" in md


def test_report_blocked_actions_in_markdown():
    report = _report(actions_blocked=["exploit", "brute_force"])
    md, _ = gen.generate(report)
    assert "exploit" in md
    assert "brute_force" in md


def test_report_approval_required_shown():
    report = _report(approval_required=True)
    md, _ = gen.generate(report)
    assert "APPROVAL REQUIRED" in md


def test_report_redacts_api_key_in_description():
    f = _finding(description="Found key sk-abcdefghijklmnopqrstuvwxyz in config")
    report = _report(findings=[f])
    _, data = gen.generate(report)
    desc = data["findings"][0]["description"]
    assert "sk-" not in desc or "REDACTED" in desc


def test_report_multiple_findings_numbered():
    findings = [_finding(title=f"Finding {i}") for i in range(3)]
    report = _report(findings=findings)
    md, _ = gen.generate(report)
    assert "Finding 1:" in md
    assert "Finding 2:" in md
    assert "Finding 3:" in md
