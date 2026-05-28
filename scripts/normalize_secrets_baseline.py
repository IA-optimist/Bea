"""Normalize Windows backslashes to forward slashes in .secrets.baseline.

detect-secrets uses os.sep when emitting filenames, so a scan run on
Windows produces backslashes in:

  - the top-level "results" dict keys (filenames),
  - the inner "filename" field of each finding.

CI runs on Linux and expects forward slashes, so a baseline freshly
generated on Windows fails the pre-commit hook with a diff full of
`/` vs `\\` noise.

This normalizer only rewrites those two specific places — it does NOT
touch the regex `pattern` strings inside the `filters_used` section,
which legitimately contain `\\.` and other regex escapes.

Usage:
    python scripts/normalize_secrets_baseline.py [path/to/.secrets.baseline]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BS = "\\"
FS = "/"


def normalize(data: dict) -> dict:
    # Top-level "results" maps filenames → list of findings.
    results = data.get("results")
    if isinstance(results, dict):
        new_results = {}
        for fname, findings in results.items():
            fixed_name = fname.replace(BS, FS) if isinstance(fname, str) else fname
            fixed_findings = []
            if isinstance(findings, list):
                for finding in findings:
                    if isinstance(finding, dict):
                        finding = dict(finding)
                        inner = finding.get("filename")
                        if isinstance(inner, str):
                            finding["filename"] = inner.replace(BS, FS)
                    fixed_findings.append(finding)
            new_results[fixed_name] = fixed_findings
        data["results"] = new_results

    # Filters / plugins / version etc. are left untouched. Regex patterns
    # in filters_used contain legitimate `\\.` escapes that must not be
    # rewritten.
    return data


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    target = Path(args[0]) if args else Path(".secrets.baseline")
    if not target.exists():
        sys.stderr.write(f"baseline not found: {target}\n")
        return 2
    data = json.loads(target.read_text(encoding="utf-8"))
    fixed = normalize(data)
    target.write_text(json.dumps(fixed, indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(f"normalized {target}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
