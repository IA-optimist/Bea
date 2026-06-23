#!/usr/bin/env python3
"""Pre-release check script for Béa.

Usage:
    python scripts/release_check.py          # human-readable
    python scripts/release_check.py --json   # machine-readable JSON
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

REQUIRED_FILES = [
    ("VERSION", "Version file"),
    ("CHANGELOG.md", "Changelog"),
    ("RELEASE_NOTES.md", "Release notes"),
    (".env.example", "Environment example"),
    ("README_PUBLIC_BETA.md", "Public beta README"),
    ("docs/PUBLIC_BETA_CHECKLIST.md", "Public beta checklist"),
]

SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9_-]{20,}"),
    re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]{16,}", re.IGNORECASE),
    re.compile(r"bea-[a-zA-Z0-9_\-]{16,}"),
    # Real OpenRouter keys start with sk-or-v1-, already caught by sk- above
]

PRODUCTION_READY_PHRASES = [
    "production ready",
    "production-ready",
    "stable public beta",
    "guaranteed uptime",
    "enterprise ready",
]


def check_file_exists(path: str, label: str) -> dict:
    exists = (ROOT / path).exists()
    return {
        "check": label,
        "path": path,
        "status": "pass" if exists else "fail",
        "message": "Found" if exists else "Missing",
    }


def check_no_secrets_in_env_example() -> dict:
    path = ROOT / ".env.example"
    if not path.exists():
        return {
            "check": "No secrets in .env.example",
            "status": "skip",
            "message": "File not found",
        }
    content = path.read_text(encoding="utf-8")
    for pat in SECRET_PATTERNS:
        m = pat.search(content)
        if m:
            return {
                "check": "No secrets in .env.example",
                "status": "fail",
                "message": f"Potential secret found: pattern '{pat.pattern[:30]}...'",
            }
    return {"check": "No secrets in .env.example", "status": "pass", "message": "Clean"}


def check_not_production_ready() -> dict:
    files_to_check = ["RELEASE_NOTES.md", "README_PUBLIC_BETA.md", "CHANGELOG.md"]
    for fname in files_to_check:
        path = ROOT / fname
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8").lower()
        for phrase in PRODUCTION_READY_PHRASES:
            idx = content.find(phrase)
            if idx == -1:
                continue
            # Allow "not production ready" or "never production-ready"
            context = content[max(0, idx - 15) : idx + len(phrase) + 15]
            if "not " not in context and "never" not in context:
                return {
                    "check": "No production-ready claims",
                    "status": "warning",
                    "message": f'Found "{phrase}" in {fname} without negation',
                }
    return {"check": "No production-ready claims", "status": "pass", "message": "Clean"}


def check_version_consistent() -> dict:
    vfile = ROOT / "VERSION"
    pyproject = ROOT / "pyproject.toml"
    if not vfile.exists():
        return {
            "check": "Version consistency",
            "status": "warning",
            "message": "VERSION file missing — using pyproject.toml",
        }
    if not pyproject.exists():
        return {"check": "Version consistency", "status": "skip", "message": "No pyproject.toml"}
    version_txt = vfile.read_text(encoding="utf-8").strip()
    pyproject_content = pyproject.read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', pyproject_content, re.MULTILINE)
    if not m:
        return {
            "check": "Version consistency",
            "status": "skip",
            "message": "No version field in pyproject.toml",
        }
    pyproject_ver = m.group(1)
    # dev-preview suffix is OK — check base version matches
    base = version_txt.split("-")[0]
    if base != pyproject_ver:
        return {
            "check": "Version consistency",
            "status": "warning",
            "message": f"VERSION={version_txt!r} base {base!r} != pyproject {pyproject_ver!r}",
        }
    return {
        "check": "Version consistency",
        "status": "pass",
        "message": f"VERSION={version_txt!r} consistent with pyproject {pyproject_ver!r}",
    }


def get_version() -> str:
    vfile = ROOT / "VERSION"
    if vfile.exists():
        return vfile.read_text(encoding="utf-8").strip()
    pyproject = ROOT / "pyproject.toml"
    if pyproject.exists():
        content = pyproject.read_text(encoding="utf-8")
        m = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
        if m:
            return m.group(1)
    return "unknown"


def main() -> int:
    checks: list[dict] = []
    for path, label in REQUIRED_FILES:
        checks.append(check_file_exists(path, label))
    checks.append(check_no_secrets_in_env_example())
    checks.append(check_not_production_ready())
    checks.append(check_version_consistent())

    version = get_version()
    failed = [c for c in checks if c["status"] == "fail"]
    warnings = [c for c in checks if c["status"] == "warning"]

    overall = "fail" if failed else ("pending" if warnings else "pass")
    report = {
        "overall_status": overall,
        "version": version,
        "checks": checks,
        "warnings": [w["message"] for w in warnings],
        "failures": [f["message"] for f in failed],
    }

    if "--json" in sys.argv:
        print(json.dumps(report, indent=2))
    else:
        print(f"Version : {version}")
        print(f"Overall : {overall.upper()}")
        icons = {"pass": "OK", "fail": "FAIL", "warning": "WARN", "skip": "SKIP"}
        for c in checks:
            icon = icons.get(c["status"], "?")
            print(f"  [{icon}] {c['check']}: {c['message']}")
        if warnings:
            print(f"\nWarnings ({len(warnings)}):")
            for w in warnings:
                print(f"  - {w}")
        if failed:
            print(f"\nFailures ({len(failed)}):")
            for f in failed:
                print(f"  - {f}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
