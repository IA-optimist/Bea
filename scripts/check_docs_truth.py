from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

DOCS = [
    "README.md",
    "README_PUBLIC_BETA.md",
    "PUBLIC_BETA_CHECKLIST.md",
    "RELEASE_NOTES.md",
    "docs/STATUS.md",
    "docs/ALPHA_READINESS.md",
    "docs/API_VERSIONING.md",
    "docs/APK_PHYSICAL_DEVICE_VALIDATION.md",
    "docs/PRIVATE_BETA_SCOPE.md",
    "docs/PRIVATE_BETA_RUNBOOK.md",
    "docs/PUBLIC_BETA_CHECKLIST.md",
    "docs/TESTER_QUICKSTART.md",
    "docs/TESTER_SAFETY_RULES.md",
    "docs/BETA_ACCESS_SETUP.md",
    "docs/BETA_INCIDENT_RUNBOOK.md",
    "docs/BETA_TESTER_GUIDE.md",
    "docs/FEEDBACK_GUIDE.md",
    "docs/KNOWN_LIMITATIONS.md",
    "docs/PRIVACY_FOR_TESTERS.md",
    "docs/TROUBLESHOOTING.md",
    "reports/private_beta/GO_NO_GO.md",
    "reports/private_beta/private_beta_gate_result.md",
    "reports/private_beta/private_beta_gate_result.json",
    "reports/private_beta/docs_truth_baseline.md",
    "reports/private_beta/docs_truth_final.md",
]

TRUTH_DOCS = [
    "README_PUBLIC_BETA.md",
    "PUBLIC_BETA_CHECKLIST.md",
    "docs/STATUS.md",
    "docs/PRIVATE_BETA_SCOPE.md",
    "reports/private_beta/GO_NO_GO.md",
    "reports/private_beta/docs_truth_final.md",
]

FORBIDDEN_PATTERNS = {
    "PUBLIC_BETA_READY true": re.compile(r"PUBLIC_BETA_READY\s*[:=]\s*true", re.I),
    "public_beta_ready true": re.compile(r'"public_beta_ready"\s*:\s*true', re.I),
    "release-hardening phrase": re.compile(r"\bproduction[- ]ready\b", re.I),
    "open-beta claim phrase": re.compile(r"\bpublic beta ready\b", re.I),
    "autonomy overclaim": re.compile(r"\bfully autonomous\b", re.I),
    "broad validation overclaim": re.compile(r"\bfully validated\b", re.I),
    "forbidden maturity word": re.compile(r"\bstable\b", re.I),
}


def read(path: str) -> str:
    full_path = ROOT / path
    if not full_path.exists():
        raise AssertionError(f"missing required doc: {path}")
    return full_path.read_text(encoding="utf-8")


def run_check_client_v1_usage() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_client_v1_usage.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise AssertionError(
            "docs say 0 active Flutter /api/v1 calls, but "
            "scripts/check_client_v1_usage.py failed:\n"
            f"{result.stdout}{result.stderr}"
        )


def assert_no_forbidden_claims() -> None:
    errors: list[str] = []
    for path in DOCS:
        text = read(path)
        for label, pattern in FORBIDDEN_PATTERNS.items():
            match = pattern.search(text)
            if match:
                errors.append(f"{path}: forbidden {label}: {match.group(0)!r}")
    if errors:
        raise AssertionError("\n".join(errors))


def assert_truth_docs_aligned() -> None:
    errors: list[str] = []
    for path in TRUTH_DOCS:
        text = read(path)
        required = {
            "PUBLIC_BETA_READY: false": "PUBLIC_BETA_READY: false",
            "Developer Preview": "Developer Preview",
            "5-10 technical testers": "5-10 technical testers",
            "HUMAN_REQUIRED": "HUMAN_REQUIRED",
        }
        if path == "reports/private_beta/GO_NO_GO.md":
            required.pop("Developer Preview")
        if path == "reports/private_beta/docs_truth_final.md":
            required["DOCS_TRUTH_SYNC: true"] = "DOCS_TRUTH_SYNC: true"
        for label, needle in required.items():
            if needle not in text:
                errors.append(f"{path}: missing {label}")
    if errors:
        raise AssertionError("\n".join(errors))


def assert_apk_claims_are_partial() -> None:
    text = read("docs/APK_PHYSICAL_DEVICE_VALIDATION.md")
    required = [
        "Current status: partially validated",
        "mission UI",
        "offline/network-failure",
        "HUMAN_REQUIRED",
    ]
    missing = [needle for needle in required if needle not in text]
    if missing:
        raise AssertionError(
            "docs/APK_PHYSICAL_DEVICE_VALIDATION.md missing partial validation "
            f"markers: {missing}"
        )


def assert_v1_claims_are_proved() -> None:
    combined = "\n".join(read(path) for path in DOCS)
    if "0 active `/api/v1` calls" in combined or "0 active /api/v1 calls" in combined:
        run_check_client_v1_usage()


def assert_qdrant_is_not_claimed_clean() -> None:
    errors: list[str] = []
    pattern = re.compile(
        r"qdrant live memory\s*(is|:)\s*(explicitly\s*)?\b(clean|clear)\b",
        re.I,
    )
    for path in DOCS:
        text = read(path)
        if pattern.search(text):
            errors.append(f"{path}: claims Qdrant live memory is clean without a live proof")
    if errors:
        raise AssertionError("\n".join(errors))


def assert_ci_smoke_not_marked_missing() -> None:
    workflow = ROOT / ".github/workflows/pr-smoke.yml"
    if not workflow.exists():
        return
    errors: list[str] = []
    pattern = re.compile(r"(pr smoke|smoke)[^\n]{0,120}(missing|not configured|absent)", re.I)
    for path in DOCS:
        text = read(path)
        if pattern.search(text):
            errors.append(f"{path}: marks PR smoke missing while workflow exists")
    if errors:
        raise AssertionError("\n".join(errors))


def assert_dependency_claims_not_stale() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    docs_text = "\n".join(read(path).lower() for path in DOCS)
    for dep in ["psutil", "structlog", "langchain", "fastapi", "pytest"]:
        if dep in requirements and re.search(rf"{dep}.{{0,80}}(missing|absent|manquant)", docs_text):
            raise AssertionError(f"docs claim {dep} is missing, but requirements.txt contains it")


def assert_gate_json() -> None:
    data = json.loads(read("reports/private_beta/private_beta_gate_result.json"))
    if data.get("public_beta_ready") is not False:
        raise AssertionError("private_beta_gate_result.json must keep public_beta_ready false")
    if data.get("private_beta_ready") is not True:
        raise AssertionError("private_beta_gate_result.json must keep private_beta_ready true")
    human_required = data.get("human_required") or []
    if not human_required:
        raise AssertionError("private_beta_gate_result.json must list human_required items")


def main() -> int:
    checks = [
        assert_no_forbidden_claims,
        assert_truth_docs_aligned,
        assert_apk_claims_are_partial,
        assert_v1_claims_are_proved,
        assert_qdrant_is_not_claimed_clean,
        assert_ci_smoke_not_marked_missing,
        assert_dependency_claims_not_stale,
        assert_gate_json,
    ]
    failures: list[str] = []
    for check in checks:
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - this is a reporting script.
            failures.append(f"{check.__name__}: {exc}")

    if failures:
        sys.stdout.write("DOCS_TRUTH_SYNC: false\n")
        for failure in failures:
            sys.stdout.write(f"- {failure}\n")
        return 1

    sys.stdout.write("DOCS_TRUTH_SYNC: true\n")
    sys.stdout.write("PUBLIC_BETA_READY: false\n")
    sys.stdout.write("Private Beta 0.1 docs are aligned for 5-10 technical testers.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
