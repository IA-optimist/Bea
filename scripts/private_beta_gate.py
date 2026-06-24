"""
Béa — Private Beta Readiness Gate

Usage:
    python scripts/private_beta_gate.py [--json]

Exit codes:
    0  -> private beta gate OK (no blockers)
    1  -> blocker(s) found
    2  -> runtime/internal error

Output:
    Human-readable summary by default. Pass --json for a stable JSON report.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
# Make repo-local packages (config, api, core...) importable.
_REPO_ROOT_STR = str(REPO_ROOT)
if _REPO_ROOT_STR not in sys.path:
    sys.path.insert(0, _REPO_ROOT_STR)

# Files / dirs we never want to scan for real secrets.
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "env", "node_modules", "storage", ".qdrant-initialized", "logs", "workspace"}
SKIP_PATH_SUBSTRINGS = (".git", ".venv", "venv", "node_modules", "storage/", ".qdrant")

# Files allowed to contain secret-shaped placeholders.
ALLOWED_SECRET_PATHS = {
    ".env.example",
    ".env.production.example",
    ".gitleaks.toml",
    ".secrets.baseline",
}


@dataclass
class Finding:
    category: str
    level: str  # BLOCKER | WARNING | HUMAN_REQUIRED
    message: str
    file: str | None = None
    line: int | None = None


@dataclass
class GateReport:
    ready_for_private_beta: bool = False
    ready_for_public_beta: bool = False
    blockers: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)
    human_required: list[Finding] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)

    def total_issues(self) -> int:
        return len(self.blockers) + len(self.warnings) + len(self.human_required)


def _is_allowed_secret_path(rel: str) -> bool:
    for allowed in ALLOWED_SECRET_PATHS:
        if allowed in rel or rel.endswith(allowed):
            return True
    if rel.startswith("tests/") or "/tests/" in rel:
        return True
    if "docs/archive" in rel:
        return True
    if "docs/archive_legacy" in rel:
        return True
    return False


def _collect_text_files() -> list[Path]:
    out: list[Path] = []
    exts = {".py", ".md", ".yml", ".yaml", ".json", ".toml", ".sh", ".ps1", ".html", ".js", ".ts", ".tsx", ".dart"}
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            if Path(f).suffix.lower() in exts:
                p = Path(root) / f
                rel = p.relative_to(REPO_ROOT).as_posix()
                if any(s in rel for s in SKIP_PATH_SUBSTRINGS):
                    continue
                out.append(p)
    return out


# Generic, reasonably safe secret regexes. Redact matches before printing.
_SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("cloud_api_key", re.compile(r"\b(sk-[a-zA-Z0-9_-]{20,})\b")),
    ("github_pat", re.compile(r"\b(ghp_[a-zA-Z0-9]{36,})\b")),
    ("github_oauth", re.compile(r"\b(gho_[a-zA-Z0-9]{36,})\b")),
    ("gitlab_pat", re.compile(r"\b(glpat-[a-zA-Z0-9_\-]{20,})\b")),
    ("slack_token", re.compile(r"\b(xoxb-[a-zA-Z0-9_\-]{10,})\b")),
    ("discord_webhook", re.compile(r"https://discord\.com/api/webhooks/\d+/[a-zA-Z0-9_\-]+")),
    ("aws_key", re.compile(r"\b(AKIA[0-9A-Z]{16})\b")),
]

# Literal placeholders we do NOT want to flag as leaked secrets.
_PLACEHOLDER_RE = re.compile(r"^(CHANGE_ME|YOUR_KEY|REPLACE_ME|sk-CHANGE_ME|jv-CHANGE_ME|test-secret|example).*$", re.I)


def _redact(raw: str) -> str:
    """Keep enough to identify a false positive but never the full secret."""
    if not raw or len(raw) < 12:
        return "<redacted-short>"
    return raw[:6] + "..." + raw[-4:]


def _scan_for_secrets(report: GateReport) -> None:
    files = _collect_text_files()
    hits = []
    for p in files:
        rel = p.relative_to(REPO_ROOT).as_posix()
        if _is_allowed_secret_path(rel):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for name, pat in _SECRET_PATTERNS:
            for m in pat.finditer(text):
                value = m.group(1) if m.lastindex else m.group(0)
                if not value or _PLACEHOLDER_RE.match(value):
                    continue
                # Skip obviously fake fixture values.
                if any(fake in value.lower() for fake in {"test", "example", "change_me", "your_", "fake"}):
                    if len(value) < 40:
                        continue
                hits.append((rel, name, _redact(value)))
    if hits:
        dedup = sorted(set(hits))
        for rel, name, redacted in dedup[:20]:
            report.blockers.append(
                Finding(
                    category="secret_scan",
                    level="BLOCKER",
                    message=f"Possible {name} leaked in {rel} (value: {redacted})",
                    file=rel,
                )
            )
        if len(dedup) > 20:
            report.blockers.append(
                Finding(
                    category="secret_scan",
                    level="BLOCKER",
                    message=f"... and {len(dedup) - 20} additional secret-shaped matches",
                )
            )


def _scan_for_dangerous_claims(report: GateReport) -> None:
    files = [p for p in _collect_text_files() if p.suffix.lower() in {".md", ".txt"}]
    # We care about claims in root docs / README / github / SECURITY files,
    # not archived historical reports.
    sensitive_prefixes = ("README", "SECURITY_MODEL", "PUBLIC_BETA_CHECKLIST", "README_PUBLIC_BETA")
    claim_re = re.compile(
        r"(?<!not\s)(?<!non\s)\b(?:"
        r"production[\s\-]?ready|"
        r"stable[\s\-]?production|"
        r"stable[\s\-]?public[\s\-]?beta|"
        r"fully[\s\-]?autonomous|"
        r"enterprise[\s\-]?ready|"
        r"guaranteed[\s\-]?availability"
        r")\b",
        re.I,
    )
    for p in files:
        rel = p.relative_to(REPO_ROOT).as_posix()
        if "docs/archive" in rel or "docs/archive_legacy" in rel:
            continue
        if not (rel.startswith(sensitive_prefixes) or rel.startswith(".github/") or rel == "README.md"):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            if claim_re.search(line):
                report.blockers.append(
                    Finding(
                        category="dangerous_claim",
                        level="BLOCKER",
                        message=f"Overclaim in {rel}:{line_no}: use 'private beta' / 'developer preview' / 'experimental' only",
                        file=rel,
                        line=line_no,
                    )
                )


def _check_gitignore(report: GateReport) -> None:
    gitignore = REPO_ROOT / ".gitignore"
    report.checks["gitignore_present"] = gitignore.exists()
    if not gitignore.exists():
        report.blockers.append(Finding("gitignore", "BLOCKER", ".gitignore is missing"))
        return
    content = gitignore.read_text(encoding="utf-8", errors="ignore")
    report.checks["gitignore_has_env"] = ".env" in content
    report.checks["gitignore_has_env_production"] = ".env.production" in content
    if not report.checks["gitignore_has_env"]:
        report.blockers.append(Finding("gitignore", "BLOCKER", ".gitignore does not ignore .env"))
    if not report.checks["gitignore_has_env_production"]:
        report.blockers.append(Finding("gitignore", "BLOCKER", ".gitignore does not ignore .env.production"))


def _check_env_examples(report: GateReport) -> None:
    skip_re = re.compile(
        r"^\s*[^#]*\bBEA_SKIP_IMPROVEMENT_GATE\s*=\s*(1|true|yes)\b",
        re.IGNORECASE,
    )
    for name in (".env.example", ".env.production.example"):
        p = REPO_ROOT / name
        if not p.exists():
            report.blockers.append(Finding("env_example", "BLOCKER", f"{name} is missing"))
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        if skip_re.search(text):
            report.blockers.append(
                Finding("env_example", "BLOCKER", f"{name} activates BEA_SKIP_IMPROVEMENT_GATE")
            )
        if name == ".env.example":
            report.checks["env_example_has_self_improve_off"] = (
                "SELF_IMPROVE_ENABLED=false" in text or "SELF_IMPROVE_ENABLED=false" in text.replace(" ", "")
            )
            if not report.checks["env_example_has_self_improve_off"]:
                report.blockers.append(
                    Finding("env_example", "BLOCKER", ".env.example does not set SELF_IMPROVE_ENABLED=false")
                )
            if "JARVIS_PRODUCTION=true" in text and "JARVIS_PRODUCTION=false" not in text:
                report.blockers.append(
                    Finding("env_example", "BLOCKER", ".env.example enables JARVIS_PRODUCTION=true by default")
                )


def _check_settings_defaults(report: GateReport) -> None:
    try:
        from config.settings import get_settings

        s = get_settings()
        report.checks["self_improve_default"] = s.self_improve_enabled
        report.checks["bea_skip_gate_default"] = s.bea_skip_improvement_gate
        if s.self_improve_enabled:
            report.blockers.append(
                Finding("settings", "BLOCKER", "SELF_IMPROVE_ENABLED / BEA_CONTINUOUS_IMPROVEMENT defaults to true")
            )
        if s.bea_skip_improvement_gate:
            report.blockers.append(
                Finding("settings", "BLOCKER", "BEA_SKIP_IMPROVEMENT_GATE defaults to true")
            )
    except Exception as exc:
        report.blockers.append(
            Finding("settings", "BLOCKER", f"Could not import config.settings: {exc}")
        )


def _check_public_paths(report: GateReport) -> None:
    try:
        from api.access_enforcement import is_public_path

        required_public = {"/health"}
        unexpectedly_public = []
        for path in ("/api/v3/missions", "/api/v2/session", "/metrics", "/api/v3/system/registry"):
            if not is_public_path(path):
                continue
            unexpectedly_public.append(path)
        if unexpectedly_public:
            report.blockers.append(
                Finding(
                    "auth",
                    "BLOCKER",
                    f"These sensitive routes are public: {unexpectedly_public}",
                )
            )
        if not is_public_path("/health"):
            report.blockers.append(Finding("auth", "BLOCKER", "/health is not public"))
        report.checks["public_paths"] = {"required_public": list(required_public), "unexpectedly_public": unexpectedly_public}
    except Exception as exc:
        report.warnings.append(
            Finding("auth", "WARNING", f"Could not verify public paths: {exc}")
        )


def _check_required_docs(report: GateReport) -> None:
    required = {
        "README.md",
        "README_PUBLIC_BETA.md",
        "PUBLIC_BETA_CHECKLIST.md",
        "docs/BETA_TESTER_GUIDE.md",
        "docs/FEEDBACK_GUIDE.md",
        "docs/KNOWN_LIMITATIONS.md",
        "docs/PRIVACY_FOR_TESTERS.md",
        "docs/TROUBLESHOOTING.md",
        "docs/PRIVATE_BETA_RUNBOOK.md",
        "docs/API_VERSIONING.md",
    }
    missing = [f for f in required if not (REPO_ROOT / f).exists()]
    for m in missing:
        report.blockers.append(Finding("docs", "BLOCKER", f"Required document missing: {m}"))
    report.checks["required_docs_present"] = sorted(required - set(missing))


def _check_issue_templates(report: GateReport) -> None:
    templates = [
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/beta_feedback.yml",
        ".github/ISSUE_TEMPLATE/security_report.md",
        ".github/ISSUE_TEMPLATE/config.yml",
    ]
    missing = [t for t in templates if not (REPO_ROOT / t).exists()]
    if missing:
        report.blockers.append(
            Finding("issue_templates", "BLOCKER", f"Missing issue templates: {missing}")
        )
    report.checks["issue_templates_present"] = sorted(set(templates) - set(missing))


def _run_external(script: str, *args: str) -> tuple[int, str]:
    exe = REPO_ROOT / script
    if not exe.exists():
        return -1, "missing"
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        result = subprocess.run(
            [sys.executable, str(exe), *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        return result.returncode, (result.stdout or "") + (result.stderr or "")
    except Exception as exc:
        return 2, str(exc)


def _check_memory_hygiene(report: GateReport) -> None:
    seed = "scripts/seed_bea_memory.py"
    audit = "scripts/audit_memory_store.py"
    if not (REPO_ROOT / seed).exists() or not (REPO_ROOT / audit).exists():
        report.blockers.append(
            Finding("memory_hygiene", "BLOCKER", "Memory seed / audit scripts are missing")
        )
        return
    rc, out = _run_external(seed, "--report", "--profile", "public")
    report.checks["memory_seed_report_rc"] = rc
    if rc != 0:
        report.blockers.append(
            Finding("memory_hygiene", "BLOCKER", f"seed_bea_memory.py --report --profile public failed (rc={rc})")
        )
    rc2, out2 = _run_external(audit, "--dry-run", "--privacy-scan", "--json")
    report.checks["memory_audit_scan_rc"] = rc2
    if rc2 != 0:
        report.blockers.append(
            Finding("memory_hygiene", "BLOCKER", f"audit_memory_store.py --dry-run --privacy-scan --json failed (rc={rc2})")
        )


def _add_humans(report: GateReport) -> None:
    report.human_required.append(
        Finding(
            "secrets_rotation",
            "HUMAN_REQUIRED",
            "Rotate secrets that may have been exposed historically (JWT_SECRET_KEY, JARVIS_API_TOKEN, OPENROUTER_API_KEY, POSTGRES_PASSWORD)",
        )
    )
    report.human_required.append(
        Finding(
            "flutter_token_revocation",
            "HUMAN_REQUIRED",
            "Revoke any hardcoded Flutter API token before distributing an APK (see docs/SECURITY_AUDIT.md §8.7)",
        )
    )
    report.human_required.append(
        Finding(
            "github_remote_status",
            "HUMAN_REQUIRED",
            "Verify origin/main is aligned with the cleaned history and CI is green",
        )
    )


def run_gate() -> GateReport:
    report = GateReport()
    _check_gitignore(report)
    _check_env_examples(report)
    _check_settings_defaults(report)
    _check_public_paths(report)
    _scan_for_secrets(report)
    _scan_for_dangerous_claims(report)
    _check_required_docs(report)
    _check_issue_templates(report)
    _check_memory_hygiene(report)
    _add_humans(report)

    report.ready_for_public_beta = False
    report.ready_for_private_beta = len(report.blockers) == 0
    return report


def _finding_to_dict(f: Finding) -> dict[str, Any]:
    return {k: v for k, v in {"category": f.category, "level": f.level, "message": f.message, "file": f.file, "line": f.line}.items() if v is not None}


def _report_to_dict(report: GateReport) -> dict[str, Any]:
    return {
        "ready_for_private_beta": report.ready_for_private_beta,
        "ready_for_public_beta": report.ready_for_public_beta,
        "blockers": [_finding_to_dict(f) for f in report.blockers],
        "warnings": [_finding_to_dict(f) for f in report.warnings],
        "human_required": [_finding_to_dict(f) for f in report.human_required],
        "checks": report.checks,
        "total_issues": report.total_issues(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Béa private beta readiness gate")
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    args = parser.parse_args()

    report = run_gate()
    data = _report_to_dict(report)

    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print("=" * 60)
        print("Béa Private Beta Readiness Gate")
        print("=" * 60)
        print(f"Ready for private beta : {report.ready_for_private_beta}")
        print(f"Ready for public beta  : {report.ready_for_public_beta}")
        print(f"Total issues           : {report.total_issues()}")
        print()
        if report.blockers:
            print(f"BLOCKERS ({len(report.blockers)}):")
            for f in report.blockers:
                loc = f"{f.file}:{f.line}" if f.line else (f.file or "-")
                print(f"  [{f.category}] {loc} - {f.message}")
        if report.warnings:
            print(f"WARNINGS ({len(report.warnings)}):")
            for f in report.warnings:
                print(f"  [{f.category}] {f.message}")
        if report.human_required:
            print(f"HUMAN REQUIRED ({len(report.human_required)}):")
            for f in report.human_required:
                print(f"  [{f.category}] {f.message}")
        print()
        print("Checks:")
        for k, v in sorted(report.checks.items()):
            print(f"  {k}: {v}")

    return 0 if report.ready_for_private_beta else 1


if __name__ == "__main__":
    sys.exit(main())
