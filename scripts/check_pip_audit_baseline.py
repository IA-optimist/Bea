"""Delta gate for pip-audit.

Audit follow-up: ``requirements.txt`` already lists ~4 CVE TODOs that the
team has deliberately deferred (FastAPI bump, cryptography bump, pytest
bump). Manual TODO comments do not protect against **new** CVEs introduced
by a future bump of an unrelated dependency.

This script runs after ``pip-audit`` and compares the result to
``quality/pip-audit-baseline.json``:

  - Vulnerability IDs in the baseline are **acknowledged debt** and may
    keep showing up without failing CI.
  - Any new vulnerability ID fails the CI step.

The baseline format::

    {
      "ignored_ids": ["GHSA-...", "PYSEC-...", "CVE-..."],
      "notes": "Free text — each entry should justify why it is deferred."
    }

To bump the baseline:

  1. Run ``pip-audit -r requirements.txt --format json > audit.json`` locally
     (or download it from the failed CI artifact).
  2. Add the new vulnerability ID to ``ignored_ids`` with a written
     justification in the corresponding row of ``requirements.txt``.
  3. Re-run CI.

Usage::

    pip-audit -r requirements.txt --format json --output audit.json --strict
    python scripts/check_pip_audit_baseline.py audit.json \\
        quality/pip-audit-baseline.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _extract_vuln_ids(audit_report: dict) -> list[tuple[str, str, str]]:
    """Return [(vuln_id, package_name, fix_versions), ...] from pip-audit JSON.

    pip-audit's schema::

      {"dependencies": [{"name": "...", "version": "...",
                          "vulns": [{"id": "CVE-...", "fix_versions": [...]}]}]}
    """
    rows: list[tuple[str, str, str]] = []
    for dep in audit_report.get("dependencies", []):
        name = dep.get("name", "?")
        for vuln in dep.get("vulns", []):
            vid = vuln.get("id", "?")
            fix = ",".join(vuln.get("fix_versions", []) or []) or "(no fix yet)"
            rows.append((vid, name, fix))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit_json", type=Path,
                        help="JSON output from `pip-audit --format json`")
    parser.add_argument("baseline_json", type=Path,
                        help="quality/pip-audit-baseline.json")
    args = parser.parse_args(argv)

    if not args.audit_json.exists():
        sys.stderr.write(f"audit report not found: {args.audit_json}\n")
        return 2
    if not args.baseline_json.exists():
        sys.stderr.write(f"baseline not found: {args.baseline_json}\n")
        sys.stderr.write(
            "Create it with `{\"ignored_ids\": []}` to start from a clean "
            "slate (CI will then report every vuln as new).\n"
        )
        return 2

    audit = json.loads(args.audit_json.read_text(encoding="utf-8"))
    baseline = json.loads(args.baseline_json.read_text(encoding="utf-8"))
    ignored = set(baseline.get("ignored_ids", []))

    rows = _extract_vuln_ids(audit)
    new = [(vid, pkg, fix) for vid, pkg, fix in rows if vid not in ignored]
    deferred = [(vid, pkg, fix) for vid, pkg, fix in rows if vid in ignored]

    if deferred:
        sys.stdout.write(
            f"Acknowledged (in baseline): {len(deferred)} vulnerabilities.\n"
        )
        for vid, pkg, fix in deferred:
            sys.stdout.write(f"  {vid:20s}  {pkg:24s}  fix: {fix}\n")

    if not new:
        sys.stdout.write(
            "\nNo new vulnerabilities beyond the baseline. OK.\n"
        )
        return 0

    sys.stderr.write(
        f"\nNEW vulnerabilities not in baseline ({len(new)}):\n"
    )
    for vid, pkg, fix in new:
        sys.stderr.write(f"  {vid:20s}  {pkg:24s}  fix: {fix}\n")
    sys.stderr.write(
        "\nEither bump the affected package, or — if the bump is risky —\n"
        "add the vulnerability ID to quality/pip-audit-baseline.json with a\n"
        "written justification in the matching row of requirements.txt.\n"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
