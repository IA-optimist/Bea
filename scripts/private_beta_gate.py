from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


@dataclass
class CheckResult:
    command: str
    exit_code: int
    status: str
    blocker: bool
    summary: str


def run(command: list[str], *, blocker: bool = True, timeout: int = 300) -> CheckResult:
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    output = (result.stdout + result.stderr).strip()
    return CheckResult(
        command=" ".join(command),
        exit_code=result.returncode,
        status="PASS" if result.returncode == 0 else "FAIL",
        blocker=blocker and result.returncode != 0,
        summary=output.splitlines()[-1] if output else "",
    )


def result_to_json(result: CheckResult) -> dict[str, Any]:
    return {
        "command": result.command,
        "exit_code": result.exit_code,
        "status": result.status,
        "blocker": result.blocker,
        "summary": result.summary,
    }


def build_report(*, run_validate_local: bool) -> tuple[dict[str, Any], int]:
    checks = [
        run([sys.executable, "scripts/check_docs_truth.py"], timeout=180),
        run([sys.executable, "scripts/check_client_v1_usage.py"], timeout=120),
    ]
    if run_validate_local:
        checks.append(run([sys.executable, "scripts/validate_local.py", "--quick"], timeout=600))

    blockers = [check for check in checks if check.blocker]
    private_beta_ready = not blockers

    human_required = [
        "HUMAN_REQUIRED: clean Qdrant live memory item ecdaea85-db3 unless a later privacy scan proves 0 private live items",
        "HUMAN_REQUIRED: rotate historical/shared secrets if rotation has not been proved outside the repo",
        "HUMAN_REQUIRED: validate Android mission UI on a physical device",
        "HUMAN_REQUIRED: validate Android offline/network-failure behavior on a physical device",
        "HUMAN_REQUIRED: issue per-tester tokens without committing them",
        "HUMAN_REQUIRED: use RedisSessionStore for multi-process or multi-worker testing",
    ]

    report: dict[str, Any] = {
        "private_beta_ready": private_beta_ready,
        "public_beta_ready": False,
        "scope": "Developer Preview / Private Beta 0.1 for 5-10 technical testers under supervision",
        "checks": [result_to_json(check) for check in checks],
        "blockers": [result.command for result in blockers],
        "human_required": human_required,
        "non_blocking_limitations": [
            "Qdrant live memory cleanup remains required until a clean privacy scan is proved",
            "Historical/shared secret rotation remains required unless proved by the owner",
            "Android APK remains partially validated until mission UI and offline/network-failure are proved",
            "Self-improvement remains disabled by default",
        ],
    }
    return report, 0 if private_beta_ready else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Private Beta 0.1 truth gate")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument(
        "--skip-validate-local",
        action="store_true",
        help="skip validate_local --quick when a faster docs-only gate is needed",
    )
    args = parser.parse_args()

    report, exit_code = build_report(run_validate_local=not args.skip_validate_local)
    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(f"PRIVATE_BETA_READY: {str(report['private_beta_ready']).lower()}\n")
        sys.stdout.write("PUBLIC_BETA_READY: false\n")
        for check in report["checks"]:
            sys.stdout.write(f"{check['status']} {check['command']}\n")
        for item in report["human_required"]:
            sys.stdout.write(f"{item}\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
