from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from agent_cyber.findings import FindingStatus, SecurityFinding

try:
    from core.observability.redactor import redact as _redact
except ImportError:
    def _redact(v: str) -> str:  # type: ignore[misc]
        return v


class CyberReport(BaseModel):
    report_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    mission_id: str
    scope_summary: str
    authorization_status: str
    actions_performed: list[str] = Field(default_factory=list)
    actions_blocked: list[str] = Field(default_factory=list)
    findings: list[SecurityFinding] = Field(default_factory=list)
    evidence_summary: str = ""
    risk_summary: str = ""
    remediation_plan: str = ""
    regression_tests_recommended: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    approval_required: bool = False
    generated_at: datetime = Field(default_factory=datetime.utcnow)

    @model_validator(mode="after")
    def requires_scope_and_auth(self) -> "CyberReport":
        if not self.scope_summary:
            raise ValueError("CyberReport requires scope_summary")
        if not self.authorization_status:
            raise ValueError("CyberReport requires authorization_status")
        return self


class CyberReportGenerator:
    """Generates redacted Markdown and JSON reports from CyberReport."""

    _UNVERIFIED_MARK = "⚠️ UNVERIFIED"
    _CONFIRMED_MARK = "✅ CONFIRMED"
    _CANDIDATE_MARK = "🔍 CANDIDATE"

    def generate(self, report: CyberReport) -> tuple[str, dict]:
        md = self._to_markdown(report)
        data = self._to_json(report)
        return md, data

    def _to_markdown(self, report: CyberReport) -> str:
        ts = report.generated_at.strftime("%Y-%m-%d %H:%M UTC")
        lines: list[str] = []

        lines.append(f"# Cyber Security Report — Mission `{report.mission_id}`")
        lines.append(f"*Generated: {ts}*")
        lines.append("")

        # 1. Executive Summary
        lines.append("## 1. Executive Summary")
        total = len(report.findings)
        confirmed = sum(1 for f in report.findings if f.status == FindingStatus.CONFIRMED)
        unverified = sum(1 for f in report.findings if f.status == FindingStatus.UNVERIFIED)
        candidate = sum(1 for f in report.findings if f.status == FindingStatus.CANDIDATE)
        lines.append(
            f"This report covers {total} finding(s): "
            f"{confirmed} confirmed, {candidate} candidate, {unverified} unverified."
        )
        if report.approval_required:
            lines.append("\n> **⚠️ APPROVAL REQUIRED** before any remediation action.")
        lines.append("")

        # 2. Scope
        lines.append("## 2. Scope")
        lines.append(_redact(report.scope_summary))
        lines.append("")

        # 3. Authorization
        lines.append("## 3. Authorization")
        lines.append(f"Authorization status: **{_redact(report.authorization_status)}**")
        lines.append("")

        # 4. Methodology
        lines.append("## 4. Methodology")
        lines.append("Static analysis only — no live exploitation, no brute force, no post-exploitation.")
        if report.actions_performed:
            lines.append("\nActions performed:")
            for action in report.actions_performed:
                lines.append(f"- `{action}`")
        lines.append("")

        # 5. Findings
        lines.append("## 5. Findings")
        if not report.findings:
            lines.append("No findings.")
        else:
            for i, f in enumerate(report.findings, 1):
                status_mark = {
                    FindingStatus.CONFIRMED: self._CONFIRMED_MARK,
                    FindingStatus.UNVERIFIED: self._UNVERIFIED_MARK,
                    FindingStatus.CANDIDATE: self._CANDIDATE_MARK,
                    FindingStatus.FALSE_POSITIVE: "❌ FALSE POSITIVE",
                    FindingStatus.FIXED: "🟢 FIXED",
                }.get(f.status, f.status.value)
                lines.append(f"### Finding {i}: {f.title} — {status_mark}")
                lines.append(f"- **Class**: `{f.vuln_class.value}`")
                lines.append(f"- **Severity**: `{f.severity.value}`")
                lines.append(f"- **Confidence**: {f.confidence:.0%}")
                if f.affected_file:
                    loc = f.affected_file
                    if f.affected_function:
                        loc += f"::{f.affected_function}"
                    lines.append(f"- **Location**: `{loc}`")
                lines.append(f"\n**Description**: {_redact(f.description)}")
                if f.impact:
                    lines.append(f"\n**Impact**: {_redact(f.impact)}")
                if f.remediation:
                    lines.append(f"\n**Remediation**: {_redact(f.remediation)}")
                if f.status == FindingStatus.UNVERIFIED:
                    lines.append(
                        "\n> ⚠️ This finding is **unverified** — it is based on pattern analysis "
                        "without confirmed evidence. Do not treat as a confirmed vulnerability."
                    )
                lines.append("")

        # 6. Evidence Summary
        lines.append("## 6. Evidence Summary")
        lines.append(_redact(report.evidence_summary) if report.evidence_summary else "No evidence summary provided.")
        lines.append("")

        # 7. Impact
        lines.append("## 7. Impact")
        lines.append(_redact(report.risk_summary) if report.risk_summary else "No risk summary provided.")
        lines.append("")

        # 8. Recommended Fixes
        lines.append("## 8. Recommended Fixes")
        lines.append(_redact(report.remediation_plan) if report.remediation_plan else "See individual finding remediations above.")
        lines.append("")

        # 9. Tests to Add
        lines.append("## 9. Tests to Add")
        if report.regression_tests_recommended:
            for t in report.regression_tests_recommended:
                lines.append(f"- {_redact(t)}")
        else:
            lines.append("No regression tests recommended.")
        lines.append("")

        # 10. Limitations
        lines.append("## 10. Limitations")
        default_limitations = [
            "This report covers static analysis only — no live exploitation was performed.",
            "Unverified findings require manual confirmation before any action.",
            "Analysis is limited to files/targets in scope.",
        ]
        all_limitations = report.limitations or default_limitations
        for l in all_limitations:
            lines.append(f"- {_redact(l)}")
        lines.append("")

        # 11. Blocked Actions
        lines.append("## 11. Blocked Actions")
        lines.append("The following actions were **deliberately blocked** in this assessment (by design):")
        if report.actions_blocked:
            for a in report.actions_blocked:
                lines.append(f"- `{a}`")
        else:
            lines.append(
                "- `exploit`, `brute_force`, `waf_bypass`, `post_exploitation`, "
                "`persistence`, `exfiltration`, `privilege_escalation`, "
                "`destructive_test`, `unauthorized_scan`, `payload_escalation`"
            )
        lines.append("")

        return "\n".join(lines)

    def _to_json(self, report: CyberReport) -> dict:
        data: dict[str, Any] = report.model_dump(mode="json")
        # Redact description and other free-text fields
        if "findings" in data:
            for f in data["findings"]:
                for key in ("description", "impact", "remediation"):
                    if f.get(key):
                        f[key] = _redact(f[key])
        for key in ("scope_summary", "evidence_summary", "risk_summary", "remediation_plan"):
            if data.get(key):
                data[key] = _redact(data[key])
        return data
