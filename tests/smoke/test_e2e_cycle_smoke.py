from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts import smoke_e2e_cycle

ROOT = Path(__file__).resolve().parents[2]


def _runner_with_mocked_bea_eval(calls: list[list[str]]):
    def run(cmd: list[str], **kwargs):
        calls.append([str(part) for part in cmd])
        if Path(cmd[1]).name == "bea_eval.py":
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps({"summary": {"failed": 0}, "results": []}),
                stderr="",
            )
        return subprocess.run(cmd, **kwargs)

    return run


def test_smoke_cycle_success_fixture_creates_expected_memories(tmp_path):
    result = smoke_e2e_cycle.run_smoke_cycle(
        fixture="success",
        run_bea_eval=False,
        work_dir=tmp_path,
    )

    assert result["reports_read"] == 1
    assert result["memory_types"]["eval_result"] >= 1
    assert result["memory_types"]["model_result"] >= 1
    assert result["memory_types"]["skill"] >= 1
    assert result["memory_types"]["test_map"] >= 1


def test_smoke_cycle_failure_fixture_creates_bug_memory(tmp_path):
    result = smoke_e2e_cycle.run_smoke_cycle(
        fixture="failure",
        run_bea_eval=False,
        work_dir=tmp_path,
    )

    assert result["reports_read"] == 1
    assert result["memory_types"]["eval_result"] >= 1
    assert result["memory_types"]["model_result"] >= 1
    assert result["memory_types"]["bug_memory"] >= 1
    assert result["memory_types"]["test_map"] >= 1


def test_smoke_cycle_calls_bea_eval_json_with_mocked_runner(tmp_path):
    calls: list[list[str]] = []

    result = smoke_e2e_cycle.run_smoke_cycle(
        fixture="success",
        run_bea_eval=True,
        work_dir=tmp_path,
        command_runner=_runner_with_mocked_bea_eval(calls),
    )

    assert result["bea_eval"]["returncode"] == 0
    assert any(Path(call[1]).name == "bea_eval.py" and "--json" in call for call in calls)


def test_smoke_script_cli_runs_from_repo_root(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/smoke_e2e_cycle.py",
            "--fixture",
            "success",
            "--skip-bea-eval",
            "--work-dir",
            str(tmp_path),
            "--json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["bea_eval"]["skipped"] is True
