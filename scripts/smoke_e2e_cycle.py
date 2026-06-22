#!/usr/bin/env python3
# ruff: noqa: T201
"""Reproducible end-to-end smoke for the Bea mission learning cycle.

The smoke uses local fixtures by default and does not require a real LLM,
OpenRouter key, or Ollama. It proves:
  - coding-agent report contract
  - mission report ingestion
  - operational memories persisted
  - bea_eval remains green
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REQUIRED_REPORT_FIELDS = (
    "mission_id",
    "goal",
    "mission_type",
    "success",
    "agents_used",
    "tools_used",
    "plan_steps",
    "complexity",
    "error_category",
    "duration_s",
    "report_path",
)


class SmokeE2EError(RuntimeError):
    """Raised when the smoke cycle detects a failed gate."""


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def validate_report_contract(report_path: str | Path) -> dict[str, Any]:
    """Load and validate the coding-agent report contract."""
    path = Path(report_path)
    if not path.exists():
        raise SmokeE2EError(f"report.json does not exist: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SmokeE2EError(f"report.json is not valid JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SmokeE2EError(f"report.json must contain an object: {path}")

    missing = [field for field in REQUIRED_REPORT_FIELDS if field not in data]
    if missing:
        fields = ", ".join(missing)
        raise SmokeE2EError(f"{path}: missing required report field(s): {fields}")
    return data


def _fixture_payload(kind: str, report_path: Path, artifact_root: Path | None = None) -> dict[str, Any]:
    success = kind == "success"
    mission_id = f"smoke-e2e-{kind}"
    goal = (
        "Add a local smoke gate for the Bea mission learning cycle."
        if success
        else "Exercise a failing coding-agent mission for bug-memory ingestion."
    )
    duration_s = 2.4 if success else 1.7
    return {
        "mission_id": mission_id,
        "goal": goal,
        "title": goal,
        "mission_type": "coding_agent",
        "task_type": "coding_agent",
        "status": "SUCCESS" if success else "FAILED",
        "success": success,
        "agents_used": ["codex"],
        "tools_used": ["pytest", "ruff", "ingest_mission_report"],
        "plan_steps": [
            "create fixture report",
            "ingest mission report",
            "verify operational memory types",
            "run bea_eval",
        ],
        "complexity": "low",
        "error_category": "" if success else "test_failure",
        "duration_s": duration_s,
        "duration_ms": int(duration_s * 1000),
        "report_path": str(report_path),
        "model_used": "fixture-coding-agent",
        "model_class": "SMALL_FAST",
        "files_changed": ["scripts/smoke_e2e_cycle.py"],
        "tests_run": [
            "tests/smoke/test_e2e_cycle_smoke.py",
            "tests/coding_agent/test_report_contract.py",
        ],
        "tests": [
            "tests/smoke/test_e2e_cycle_smoke.py",
            "tests/coding_agent/test_report_contract.py",
        ],
        "lessons_learned": (
            "Use a fixture-backed smoke gate to prove ingestion before expensive runtime tests."
            if success
            else ""
        ),
        "failure_reason": "" if success else "Fixture mission failed to prove bug_memory creation.",
        "risks_detected": [],
    }


def _write_fixture(kind: str, directory: Path) -> Path:
    path = directory / f"{kind}_report.json"
    if kind == "sha256":
        payload = _build_sha256_fixture(path, directory)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path
    payload = _fixture_payload(kind, path)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _write_sha256_artifacts(artifact_root: Path) -> None:
    source = artifact_root / "src" / "sha256_file.py"
    test_file = artifact_root / "tests" / "test_sha256_file.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    test_file.parent.mkdir(parents=True, exist_ok=True)
    (artifact_root / "src" / "__init__.py").write_text("", encoding="utf-8")
    source.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "",
                "import hashlib",
                "from pathlib import Path",
                "",
                "",
                "def sha256_file(path: str) -> str:",
                "    digest = hashlib.sha256()",
                "    with Path(path).open('rb') as handle:",
                "        for chunk in iter(lambda: handle.read(8192), b''):",
                "            digest.update(chunk)",
                "    return digest.hexdigest()",
                "",
            ]
        ),
        encoding="utf-8",
    )
    test_file.write_text(
        "\n".join(
            [
                "import hashlib",
                "",
                "from src.sha256_file import sha256_file",
                "",
                "",
                "def test_sha256_file(tmp_path):",
                "    target = tmp_path / 'payload.bin'",
                "    target.write_bytes(b'bea-smoke')",
                "    assert sha256_file(str(target)) == hashlib.sha256(b'bea-smoke').hexdigest()",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _run_sha256_pytest(artifact_root: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(artifact_root)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_sha256_file.py", "-q"],
        cwd=str(artifact_root),
        env=env,
        capture_output=True,
        text=True,
    )
    return {
        "command": "python -m pytest tests/test_sha256_file.py -q",
        "returncode": proc.returncode,
        "passed": proc.returncode == 0,
        "stdout": proc.stdout[-1200:],
        "stderr": proc.stderr[-1200:],
    }


def _build_sha256_fixture(report_path: Path, directory: Path) -> dict[str, Any]:
    artifact_root = directory / "sha256_artifacts"
    source_response = """Voici l'implémentation demandée.

```python
from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()
```

Le reste est de la documentation et ne doit pas finir dans le fichier .py.
"""
    from core.coding_agent.code_artifacts import materialize_python_artifact, validate_python_file

    source_result = materialize_python_artifact(source_response, artifact_root / "src" / "sha256_file.py")
    if not source_result.ok:
        raise SmokeE2EError(f"sha256 source materialization failed: {source_result.message}")

    _write_sha256_artifacts(artifact_root)
    syntax_ok, syntax_error = validate_python_file(artifact_root / "src" / "sha256_file.py")
    if not syntax_ok:
        raise SmokeE2EError(f"sha256 syntax validation failed: {syntax_error}")

    test_result = _run_sha256_pytest(artifact_root)
    if not test_result["passed"]:
        raise SmokeE2EError(
            "sha256 pytest failed "
            f"(exit {test_result['returncode']}). stdout={test_result['stdout']} stderr={test_result['stderr']}"
        )

    files_created = [
        "src/__init__.py",
        "src/sha256_file.py",
        "tests/test_sha256_file.py",
    ]
    report = {
        "mission_id": "smoke-e2e-sha256",
        "goal": "Create sha256_file(path: str) -> str with a unit test.",
        "title": "Create sha256_file(path: str) -> str with a unit test.",
        "mission_type": "coding_agent",
        "task_type": "coding_agent",
        "status": "SUCCESS",
        "success": True,
        "needs_actions": True,
        "agents_used": ["forge-builder"],
        "tools_used": ["materialize_python_artifact", "py_compile", "pytest", "ingest_mission_report"],
        "plan_steps": [
            "extract code from forge-builder response",
            "write python source",
            "run py_compile",
            "run pytest",
            "ingest mission report",
            "run bea_eval",
        ],
        "complexity": "low",
        "error_category": "",
        "duration_s": 4.2,
        "duration_ms": 4200,
        "report_path": str(report_path),
        "artifact_root": str(artifact_root),
        "provider_used": "fixture-local",
        "model_used": "fixture-forge-builder",
        "model_class": "SMALL_FAST",
        "artifacts": [
            str(artifact_root / "src" / "sha256_file.py"),
            str(artifact_root / "tests" / "test_sha256_file.py"),
            str(report_path),
        ],
        "files_created": files_created,
        "files_changed": ["src/sha256_file.py", "tests/test_sha256_file.py"],
        "expected_artifact": "src/sha256_file.py",
        "tests_run": [test_result["command"]],
        "test_result": {
            "syntax_check": {
                "command": f"py_compile {artifact_root / 'src' / 'sha256_file.py'}",
                "passed": syntax_ok,
                "error": syntax_error,
            },
            "pytest": test_result,
        },
        "tests": ["tests/test_sha256_file.py"],
        "lessons_learned": (
            "A code mission is only completed when source extraction, syntax validation "
            "and test proof all succeed."
        ),
        "failure_reason": "",
        "risks_detected": [],
    }
    return report


def _prepare_reports(
    *,
    report_path: str | Path | None,
    fixture: str,
    work_dir: Path,
) -> list[Path]:
    if report_path is not None:
        return [Path(report_path)]

    fixture_dir = work_dir / "fixtures"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    if fixture == "both":
        return [_write_fixture("success", fixture_dir), _write_fixture("failure", fixture_dir)]
    return [_write_fixture(fixture, fixture_dir)]


def _run_command(
    runner: CommandRunner,
    cmd: list[str],
    *,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return runner(
        cmd,
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )


def _json_from_stdout(stdout: str, command_name: str) -> dict[str, Any]:
    start = stdout.find("{")
    if start < 0:
        raise SmokeE2EError(f"{command_name} did not emit JSON")
    try:
        return json.loads(stdout[start:])
    except json.JSONDecodeError as exc:
        raise SmokeE2EError(f"{command_name} emitted invalid JSON: {exc}") from exc


def _expected_memory_types(report: dict[str, Any]) -> set[str]:
    expected = {"eval_result"}
    if report.get("model_used"):
        expected.add("model_result")
    if report.get("success") is True:
        expected.add("skill")
    else:
        expected.add("bug_memory")
    if report.get("tests") or report.get("tests_run"):
        expected.add("test_map")
    return expected


def _assert_memory_types(reports: list[dict[str, Any]], memory_types: dict[str, int]) -> None:
    expected: set[str] = set()
    for report in reports:
        expected.update(_expected_memory_types(report))

    missing = [memory_type for memory_type in sorted(expected) if memory_types.get(memory_type, 0) < 1]
    if missing:
        raise SmokeE2EError(
            "ingestion did not create expected memory type(s): "
            + ", ".join(missing)
            + f"; actual={memory_types}"
        )


def _validate_action_artifacts(report: dict[str, Any], report_path: Path) -> dict[str, Any]:
    if not report.get("needs_actions"):
        return {"ok": True, "status": "SKIPPED", "message": "needs_actions is false"}

    from core.coding_agent.artifact_validator import validate_mission_report_artifacts

    artifact_root = Path(str(report.get("artifact_root") or report_path.parent))
    result = validate_mission_report_artifacts(report, repo_root=artifact_root)
    if not result.ok:
        raise SmokeE2EError(f"{report_path}: {result.message}")
    return {
        "ok": result.ok,
        "status": result.status,
        "message": result.message,
        "artifacts": result.artifacts,
        "warnings": result.warnings,
    }


def _run_bea_eval(
    *,
    env: dict[str, str],
    command_runner: CommandRunner,
) -> dict[str, Any]:
    cmd = [sys.executable, str(ROOT / "scripts" / "bea_eval.py"), "--json"]
    proc = _run_command(command_runner, cmd, env=env)
    if proc.returncode != 0:
        raise SmokeE2EError(
            "bea_eval failed "
            f"(exit {proc.returncode}). stdout={proc.stdout[-1000:]} stderr={proc.stderr[-1000:]}"
        )
    data = _json_from_stdout(proc.stdout, "bea_eval")
    failed = data.get("summary", {}).get("failed")
    if failed not in (0, None):
        raise SmokeE2EError(f"bea_eval reported failed={failed}")
    return {"returncode": proc.returncode, "summary": data.get("summary", {})}


def _run_smoke_cycle_in_dir(
    *,
    report_path: str | Path | None,
    fixture: str,
    run_bea_eval: bool,
    work_dir: Path,
    command_runner: CommandRunner,
) -> dict[str, Any]:
    reports = _prepare_reports(report_path=report_path, fixture=fixture, work_dir=work_dir)
    report_payloads = [validate_report_contract(path) for path in reports]
    artifact_validation = [
        _validate_action_artifacts(report, path)
        for report, path in zip(report_payloads, reports, strict=True)
    ]

    db_path = work_dir / "operational_memory.db"
    env = os.environ.copy()
    env["BEA_OPERATIONAL_MEMORY_DB"] = str(db_path)
    env["BEA_ROOT"] = str(work_dir)

    ingest_target = reports[0] if len(reports) == 1 else reports[0].parent
    ingest_cmd = [
        sys.executable,
        str(ROOT / "scripts" / "ingest_mission_report.py"),
        str(ingest_target),
        "--json",
    ]
    ingest_proc = _run_command(command_runner, ingest_cmd, env=env)
    if ingest_proc.returncode != 0:
        raise SmokeE2EError(
            "ingest_mission_report failed "
            f"(exit {ingest_proc.returncode}). stdout={ingest_proc.stdout[-1000:]} "
            f"stderr={ingest_proc.stderr[-1000:]}"
        )
    ingestion = _json_from_stdout(ingest_proc.stdout, "ingest_mission_report")
    if ingestion.get("errors"):
        raise SmokeE2EError(f"ingestion returned errors: {ingestion['errors']}")

    from core.memory.operational_memory import OperationalMemoryStore

    store = OperationalMemoryStore(db_path=str(db_path))
    try:
        stats = store.stats()
    finally:
        store.close()
    memory_types = dict(stats.get("by_type", {}))
    _assert_memory_types(report_payloads, memory_types)

    bea_eval = {"skipped": True}
    if run_bea_eval:
        bea_eval = _run_bea_eval(env=env, command_runner=command_runner)

    return {
        "ok": True,
        "reports": [str(path) for path in reports],
        "reports_read": ingestion.get("reports_read", 0),
        "memories_created": ingestion.get("memories_created", 0),
        "memories_updated": ingestion.get("memories_updated", 0),
        "memory_types": memory_types,
        "artifact_validation": artifact_validation,
        "ingestion": ingestion,
        "bea_eval": bea_eval,
        "operational_memory_db": str(db_path),
    }


def run_smoke_cycle(
    *,
    report_path: str | Path | None = None,
    fixture: str = "both",
    run_bea_eval: bool = True,
    work_dir: str | Path | None = None,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """Run the local E2E cycle smoke and return a structured summary."""
    if fixture not in {"success", "failure", "both", "sha256"}:
        raise SmokeE2EError(f"unknown fixture: {fixture}")

    runner = command_runner or subprocess.run
    if work_dir is not None:
        path = Path(work_dir)
        path.mkdir(parents=True, exist_ok=True)
        return _run_smoke_cycle_in_dir(
            report_path=report_path,
            fixture=fixture,
            run_bea_eval=run_bea_eval,
            work_dir=path,
            command_runner=runner,
        )

    with tempfile.TemporaryDirectory(prefix="bea-e2e-smoke-") as tmp:
        return _run_smoke_cycle_in_dir(
            report_path=report_path,
            fixture=fixture,
            run_bea_eval=run_bea_eval,
            work_dir=Path(tmp),
            command_runner=runner,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Bea E2E mission learning smoke")
    parser.add_argument("--report", help="Path to a coding-agent report.json")
    parser.add_argument(
        "--fixture",
        choices=("success", "failure", "both", "sha256"),
        default="both",
        help="Fixture to generate when --report is not provided",
    )
    parser.add_argument("--work-dir", help="Directory for fixtures and temporary memory DB")
    parser.add_argument("--skip-bea-eval", action="store_true", help="Skip scripts/bea_eval.py --json")
    parser.add_argument("--json", action="store_true", help="Print JSON summary")
    args = parser.parse_args(argv)

    try:
        result = run_smoke_cycle(
            report_path=args.report,
            fixture=args.fixture,
            run_bea_eval=not args.skip_bea_eval,
            work_dir=args.work_dir,
        )
    except SmokeE2EError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("[OK] Bea E2E cycle smoke passed")
        print(f"  Reports read:     {result['reports_read']}")
        print(f"  Memories created: {result['memories_created']}")
        print(f"  Memory types:     {result['memory_types']}")
        print(f"  bea_eval:         {result['bea_eval']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
