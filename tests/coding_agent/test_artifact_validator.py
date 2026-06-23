from __future__ import annotations

import json
from types import SimpleNamespace

from core.coding_agent.artifact_validator import (
    validate_code_artifacts,
    validate_mission_report_artifacts,
)
from scripts import smoke_e2e_cycle


def _write_report(tmp_path, **overrides):
    report_path = tmp_path / "report.json"
    report = {
        "mission_id": "sha256-artifact-test",
        "goal": "Create sha256_file(path) with a unit test.",
        "mission_type": "coding_agent",
        "task_type": "coding_agent",
        "success": True,
        "needs_actions": True,
        "agents_used": ["forge-builder"],
        "tools_used": ["write_file", "pytest"],
        "plan_steps": ["create source", "create test", "run tests"],
        "complexity": "low",
        "error_category": "",
        "duration_s": 1.0,
        "provider_used": "fixture-local",
        "model_used": "fixture-forge-builder",
        "artifacts": ["src/sha256_file.py", "tests/test_sha256_file.py"],
        "files_created": ["src/sha256_file.py", "tests/test_sha256_file.py"],
        "tests_run": ["python -m pytest tests/test_sha256_file.py -q"],
        "test_result": {"syntax_check": {"passed": True}, "pytest": {"passed": True}},
        "report_path": str(report_path),
    }
    report.update(overrides)
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return report_path, report


def test_code_mission_with_created_file_accepts_completed(tmp_path):
    source = tmp_path / "src" / "sha256_file.py"
    source.parent.mkdir()
    source.write_text("def sha256_file(path: str) -> str:\n    return 'abc'\n", encoding="utf-8")
    test_file = tmp_path / "tests" / "test_sha256_file.py"
    test_file.parent.mkdir()
    test_file.write_text("def test_sha256_file():\n    assert True\n", encoding="utf-8")
    report_path, report = _write_report(
        tmp_path,
        files_created=["src/sha256_file.py", "tests/test_sha256_file.py"],
        tests_run=["pytest tests/test_sha256_file.py -q"],
        expected_artifact="src/sha256_file.py",
    )

    result = validate_mission_report_artifacts(report, repo_root=tmp_path)

    assert result.ok is True
    assert result.status == "COMPLETED"
    assert str(report_path) == report["report_path"]


def test_code_mission_with_nonempty_diff_accepts_completed(tmp_path):
    _report_path, report = _write_report(
        tmp_path,
        expected_artifact={"type": "diff", "description": "sha256_file implementation patch"},
        unified_diff="--- a/src/sha256_file.py\n+++ b/src/sha256_file.py\n@@ -0,0 +1 @@\n+def sha256_file(path): ...\n",
        files_created=[],
        tests_run=["pytest tests/test_sha256_file.py -q"],
    )

    result = validate_mission_report_artifacts(report, repo_root=tmp_path)

    assert result.ok is True
    assert result.status == "COMPLETED"


def test_code_mission_with_only_text_refuses_completed(tmp_path):
    _report_path, report = _write_report(
        tmp_path,
        final_response="Here is the function you can paste into a file.",
    )

    result = validate_mission_report_artifacts(report, repo_root=tmp_path)

    assert result.ok is False
    assert result.status == "NEEDS_ACTION_OUTPUT"
    assert "verifiable artifact" in result.message


def test_code_mission_with_missing_declared_file_refuses_completed(tmp_path):
    _report_path, report = _write_report(
        tmp_path,
        files_created=["src/missing_sha256_file.py"],
        expected_artifact="src/missing_sha256_file.py",
        tests_run=["pytest tests/test_sha256_file.py -q"],
    )

    result = validate_mission_report_artifacts(report, repo_root=tmp_path)

    assert result.ok is False
    assert result.status == "NEEDS_ACTION_OUTPUT"
    assert "do not exist" in result.message


def test_needs_actions_without_artifact_returns_needs_action_output(tmp_path):
    session = SimpleNamespace(
        needs_actions=True,
        final_report="I wrote the code.",
        actions_executed=[],
        actions_pending=[],
        _raw_actions=[],
    )

    result = validate_code_artifacts(session, repo_root=tmp_path)

    assert result.ok is False
    assert result.status == "NEEDS_ACTION_OUTPUT"
    assert "needs_actions=True" in result.message


def test_report_without_report_path_has_clear_warning(tmp_path):
    _report_path, report = _write_report(
        tmp_path,
        expected_artifact={"type": "diff", "description": "single file patch"},
        unified_diff="--- a/a.py\n+++ b/a.py\n@@ -0,0 +1 @@\n+print('ok')\n",
        files_created=[],
        tests_run=["pytest tests/test_sha256_file.py -q"],
    )
    del report["report_path"]

    result = validate_mission_report_artifacts(report, repo_root=tmp_path)

    assert result.ok is True
    assert any("report_path" in warning for warning in result.warnings)


def test_non_code_completed_without_artifact_is_allowed(tmp_path):
    report_path = tmp_path / "report.json"
    report = {
        "mission_id": "identity-check",
        "goal": "Describe current identity.",
        "mission_type": "analysis",
        "success": True,
        "needs_actions": False,
        "report_path": str(report_path),
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")

    result = validate_mission_report_artifacts(report, repo_root=tmp_path)

    assert result.ok is True
    assert result.status == "COMPLETED"


def test_ingestion_report_remains_contract_compatible(tmp_path):
    source = tmp_path / "src" / "sha256_file.py"
    source.parent.mkdir()
    source.write_text("def sha256_file(path: str) -> str:\n    return 'abc'\n", encoding="utf-8")
    _report_path, report = _write_report(
        tmp_path,
        files_created=["src/sha256_file.py"],
        expected_artifact="src/sha256_file.py",
        tests_run=["pytest tests/test_sha256_file.py -q"],
    )

    smoke_e2e_cycle.validate_report_contract(report["report_path"])
    result = validate_mission_report_artifacts(report, repo_root=tmp_path)

    assert result.ok is True


def test_supervisor_refuses_code_session_without_test_artifact(tmp_path):
    from core.orchestration.execution_supervisor import _check_session_outcome

    source = tmp_path / "sha256_file.py"
    source.write_text("def sha256_file(path: str) -> str:\n    return 'abc'\n", encoding="utf-8")
    session = SimpleNamespace(
        error=None,
        agents_plan=[{"agent": "forge-builder"}],
        outputs={
            "forge-builder": SimpleNamespace(
                success=True,
                content="Created sha256_file.py",
                error="",
            )
        },
        final_report="Created sha256_file.py",
        mode="code",
        needs_actions=True,
        expected_artifact=str(source),
        actions_executed=[{"target": str(source)}],
        actions_pending=[],
        _raw_actions=[{"target": str(source)}],
    )

    ok, reason, error_class = _check_session_outcome(session)

    assert ok is False
    assert error_class == "needs_action_output"
    assert "test command is required" in reason


def test_code_mission_partial_actions_refuse_completed(tmp_path):
    _report_path, report = _write_report(
        tmp_path,
        files_created=["src/sha256_file.py"],
        actions_executed=[],
        actions_pending=[],
        _raw_actions=[{"target": "src/sha256_file.py"}],
    )

    result = validate_mission_report_artifacts(report, repo_root=tmp_path)

    assert result.ok is False
    assert result.status == "NEEDS_ACTION_OUTPUT"
    assert "actions appear partial" in result.message


def test_code_mission_tests_run_without_test_result_refuse_completed(tmp_path):
    _report_path, report = _write_report(
        tmp_path,
        files_created=["src/sha256_file.py"],
        tests_run=["pytest tests/test_sha256_file.py -q"],
        test_result={},
    )

    result = validate_mission_report_artifacts(report, repo_root=tmp_path)

    assert result.ok is False
    assert result.status == "NEEDS_ACTION_OUTPUT"
    assert "test_result is required" in result.message


def test_python_artifact_without_syntax_validation_refuse_completed(tmp_path):
    source = tmp_path / "src" / "solution.py"
    source.parent.mkdir()
    source.write_text("def solve(): pass\n", encoding="utf-8")
    _report_path, report = _write_report(
        tmp_path,
        goal="Write a python solution module",
        files_created=["src/solution.py"],
        expected_artifact="src/solution.py",
        tests_run=["pytest tests/test_solution.py -q"],
        test_result=None,
    )

    result = validate_mission_report_artifacts(report, repo_root=tmp_path)

    assert result.ok is False
    assert result.status == "NEEDS_ACTION_OUTPUT"
    assert "python artifact requires syntax validation proof" in result.message
