"""
core/execution/quality_gate.py — Artifact quality verification before delivery.

Verifies built artifacts for completeness, validity, coherence, and
placeholder content. Auto-corrects fixable issues.

Design:
  - Type-specific checks (HTML, Python, JSON, content)
  - Universal checks (exists, size, empty, binary)
  - Scoring: 1.0 base, -0.3 per critical, -0.1 per warning, -0.02 per info
  - Auto-correct: placeholder removal, secret scrubbing, whitespace cleanup
  - Single pass: verify → optional auto_correct → re-verify
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
import structlog

log = structlog.get_logger("execution.quality_gate")

# Placeholder patterns
_PLACEHOLDER_RE = re.compile(
    r"\b(?:TODO|FIXME|PLACEHOLDER|lorem\s+ipsum|TBD|XXX)\b"
    r"|href\s*=\s*[\"']#placeholder[\"']"
    r"|\[(?:your|fill|add|insert)\b",
    re.IGNORECASE,
)

# Secret patterns
_SECRET_RE = re.compile(
    r"(?:sk-[a-zA-Z0-9]{20,})"
    r"|(?:ghp_[a-zA-Z0-9]{36,})"
    r"|(?:api[_-]?key\s*[=:]\s*['\"][a-zA-Z0-9]{16,}['\"])"
    r"|(?:password\s*[=:]\s*['\"][^'\"]{4,}['\"])",
    re.IGNORECASE,
)


@dataclass
class QualityIssue:
    """A single quality issue found during verification."""
    category: str       # completeness, validity, coherence, placeholder, structure
    severity: str       # critical, warning, info
    description: str
    location: str = ""  # file path or field name
    auto_correctable: bool = False

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "severity": self.severity,
            "description": self.description,
            "location": self.location,
            "auto_correctable": self.auto_correctable,
        }


@dataclass
class QualityReport:
    """Full quality report for an artifact."""
    passed: bool
    score: float
    issues: list[QualityIssue] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)
    correctable: bool = False

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "score": round(self.score, 3),
            "issues": [i.to_dict() for i in self.issues],
            "checks_run": self.checks_run,
            "correctable": self.correctable,
        }


@dataclass
class CorrectionResult:
    """Result of auto-correction attempt."""
    corrected: bool
    fixes_applied: list[str] = field(default_factory=list)
    remaining_issues: int = 0

    def to_dict(self) -> dict:
        return {
            "corrected": self.corrected,
            "fixes_applied": self.fixes_applied,
            "remaining_issues": self.remaining_issues,
        }


class ArtifactQualityGate:
    """Verifies and optionally auto-corrects built artifacts."""

    def verify(
        self,
        artifact_path: str,
        artifact_type: str,
        build_result: dict | None = None,
    ) -> QualityReport:
        """
        Run all applicable quality checks on an artifact.

        Returns QualityReport with score, issues, and correctability.
        """
        issues: list[QualityIssue] = []
        checks_run: list[str] = []

        path = Path(artifact_path)

        # Universal checks
        checks_run.append("file_exists")
        if not path.exists():
            issues.append(QualityIssue(
                category="completeness", severity="critical",
                description="Artifact file does not exist",
                location=str(path),
            ))
            return self._build_report(issues, checks_run)

        checks_run.append("file_size")
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        if size == 0:
            issues.append(QualityIssue(
                category="completeness", severity="critical",
                description="Artifact file is empty (0 bytes)",
                location=str(path),
            ))
            return self._build_report(issues, checks_run)
        if size < 50:
            issues.append(QualityIssue(
                category="completeness", severity="warning",
                description=f"Artifact file is very small ({size} bytes)",
                location=str(path),
            ))

        # Read content
        try:
            content = path.read_text(errors="replace")
        except Exception as e:
            issues.append(QualityIssue(
                category="validity", severity="critical",
                description=f"Cannot read artifact: {str(e)[:100]}",
                location=str(path),
            ))
            return self._build_report(issues, checks_run)

        # Universal content checks
        checks_run.append("placeholder_check")
        placeholders = _PLACEHOLDER_RE.findall(content)
        if placeholders:
            issues.append(QualityIssue(
                category="placeholder", severity="warning",
                description=f"Contains {len(placeholders)} placeholder(s): {placeholders[:3]}",
                location=str(path),
                auto_correctable=True,
            ))

        checks_run.append("secret_check")
        secrets = _SECRET_RE.findall(content)
        if secrets:
            issues.append(QualityIssue(
                category="validity", severity="critical",
                description=f"Contains {len(secrets)} potential secret(s)",
                location=str(path),
                auto_correctable=True,
            ))

        # Type-specific checks
        type_key = artifact_type.lower().replace("-", "_")
        checker = getattr(self, f"_check_{type_key}", None)
        if checker:
            type_issues, type_checks = checker(content, path)
            issues.extend(type_issues)
            checks_run.extend(type_checks)

        return self._build_report(issues, checks_run)

    def auto_correct(
        self, artifact_path: str, issues: list[QualityIssue]
    ) -> CorrectionResult:
        """
        Attempt to auto-correct identified issues.

        Only corrects issues marked as auto_correctable.
        """
        path = Path(artifact_path)
        if not path.exists():
            return CorrectionResult(corrected=False, remaining_issues=len(issues))

        try:
            content = path.read_text(errors="replace")
        except Exception:
            return CorrectionResult(corrected=False, remaining_issues=len(issues))

        fixes: list[str] = []
        correctable = [i for i in issues if i.auto_correctable]
        remaining = len(issues) - len(correctable)

        for issue in correctable:
            if issue.category == "placeholder":
                content = _PLACEHOLDER_RE.sub("<!-- content needed -->", content)
                fixes.append("Replaced placeholder text with comment markers")
            elif issue.category == "validity" and "secret" in issue.description:
                content = _SECRET_RE.sub("${ENV_VAR}", content)
                fixes.append("Replaced potential secrets with env var references")

        # Always: strip trailing whitespace
        lines = content.split("\n")
        content = "\n".join(line.rstrip() for line in lines)
        if content != path.read_text(errors="replace"):
            fixes.append("Cleaned trailing whitespace")

        if fixes:
            try:
                path.write_text(content)
            except Exception:
                return CorrectionResult(
                    corrected=False,
                    fixes_applied=[],
                    remaining_issues=len(issues),
                )

        return CorrectionResult(
            corrected=len(fixes) > 0,
            fixes_applied=fixes,
            remaining_issues=remaining,
        )

    # ── Type-specific checkers ─────────────────────────────────

    @staticmethod
    def _check_landing_page(content: str, path: Path) -> tuple[list[QualityIssue], list[str]]:
        issues: list[QualityIssue] = []
        checks = ["html_structure", "html_content_length"]

        # HTML structure
        has_html = "<html" in content.lower()
        has_body = "<body" in content.lower()
        has_h1 = "<h1" in content.lower()

        if not has_html:
            issues.append(QualityIssue(
                category="structure", severity="warning",
                description="Missing <html> tag",
                location=str(path),
            ))
        if not has_body:
            issues.append(QualityIssue(
                category="structure", severity="warning",
                description="Missing <body> tag",
                location=str(path),
            ))
        if not has_h1:
            issues.append(QualityIssue(
                category="structure", severity="info",
                description="Missing <h1> heading",
                location=str(path),
            ))

        # Content length
        if len(content) < 500:
            issues.append(QualityIssue(
                category="completeness", severity="warning",
                description=f"Landing page content is short ({len(content)} chars, expect >500)",
                location=str(path),
            ))

        return issues, checks

    @staticmethod
    def _check_api_service(content: str, path: Path) -> tuple[list[QualityIssue], list[str]]:
        issues: list[QualityIssue] = []
        checks = ["python_syntax", "has_routes"]

        # Python syntax check
        try:
            compile(content, str(path), "exec")
        except SyntaxError as e:
            issues.append(QualityIssue(
                category="validity", severity="critical",
                description=f"Python syntax error: {str(e)[:100]}",
                location=str(path),
            ))

        # Has route definitions
        if not re.search(r"@\w+\.(get|post|put|delete|route)\b|app\.add_route|router\.", content):
            issues.append(QualityIssue(
                category="completeness", severity="warning",
                description="No API route definitions found",
                location=str(path),
            ))

        return issues, checks

    @staticmethod
    def _check_automation_workflow(content: str, path: Path) -> tuple[list[QualityIssue], list[str]]:
        issues: list[QualityIssue] = []
        checks = ["json_yaml_validity", "has_steps"]

        # Try JSON parse
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                if "steps" not in data and "nodes" not in data and "trigger" not in data:
                    issues.append(QualityIssue(
                        category="structure", severity="warning",
                        description="Workflow missing 'steps', 'nodes', or 'trigger' key",
                        location=str(path),
                    ))
        except json.JSONDecodeError:
            # Try YAML-like check (has key: value pairs)
            if not re.search(r"^\w+:", content, re.MULTILINE):
                issues.append(QualityIssue(
                    category="validity", severity="critical",
                    description="Content is neither valid JSON nor YAML",
                    location=str(path),
                ))

        return issues, checks

    @staticmethod
    def _check_content_asset(content: str, path: Path) -> tuple[list[QualityIssue], list[str]]:
        issues: list[QualityIssue] = []
        checks = ["word_count", "lorem_check"]

        words = len(content.split())
        if words < 100:
            issues.append(QualityIssue(
                category="completeness", severity="warning",
                description=f"Content has only {words} words (expect >100)",
                location=str(path),
            ))

        if "lorem ipsum" in content.lower():
            issues.append(QualityIssue(
                category="placeholder", severity="warning",
                description="Contains lorem ipsum placeholder text",
                location=str(path),
                auto_correctable=True,
            ))

        return issues, checks

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _build_report(
        issues: list[QualityIssue], checks_run: list[str]
    ) -> QualityReport:
        """Build QualityReport from issues, computing score."""
        score = 1.0
        for issue in issues:
            if issue.severity == "critical":
                score -= 0.3
            elif issue.severity == "warning":
                score -= 0.1
            elif issue.severity == "info":
                score -= 0.02
        score = max(0.0, score)

        correctable = any(i.auto_correctable for i in issues)
        passed = len([i for i in issues if i.severity == "critical"]) == 0 and score >= 0.5

        return QualityReport(
            passed=passed,
            score=score,
            issues=issues,
            checks_run=checks_run,
            correctable=correctable,
        )
