from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from core.coding_agent.artifact_validator import (
    validate_code_artifacts,
    validate_completion_evidence,
)


def test_code_session_with_markdown_python_file_is_not_completed(tmp_path):
    source = tmp_path / "src" / "sha256_file.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "from __future__ import annotations\n\n"
        "This markdown text must not be accepted as Python.\n",
        encoding="utf-8",
    )
    session = SimpleNamespace(
        goal="Create sha256_file(path: str) -> str",
        mission_type="coding_agent",
        needs_actions=True,
        files_created=["src/sha256_file.py"],
        expected_artifact="src/sha256_file.py",
        tests_run=["python -m pytest tests/test_sha256_file.py -q"],
        actions_executed=[{"target": "src/sha256_file.py", "success": True}],
    )

    result = validate_code_artifacts(session, repo_root=tmp_path)

    assert result.ok is False
    assert result.status == "NEEDS_ACTION_OUTPUT"
    assert "syntax validation failed" in result.message


def test_report_missing_report_path_is_rejected(tmp_path):
    source = tmp_path / "src" / "sha256_file.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def sha256_file(path: str) -> str:\n    return 'ok'\n",
        encoding="utf-8",
    )
    report = {
        "mission_id": "sha256-false-completed",
        "goal": "Create sha256_file(path: str) -> str",
        "mission_type": "coding_agent",
        "task_type": "coding_agent",
        "status": "SUCCESS",
        "success": True,
        "needs_actions": True,
        "provider_used": "fixture-local",
        "model_used": "fixture-forge-builder",
        "artifacts": ["src/sha256_file.py"],
        "files_created": ["src/sha256_file.py"],
        "tests_run": ["python -m pytest tests/test_sha256_file.py -q"],
        "test_result": {"syntax_check": {"passed": True}, "pytest": {"passed": True}},
    }

    result = validate_completion_evidence(
        report,
        repo_root=tmp_path,
        require_report_path=True,
        require_report_metadata=True,
    )

    assert result.ok is False
    assert result.status == "REPORT_MISSING"
    assert result.error_class == "report_missing"


def test_provider_unavailable_is_reported_separately():
    report = {
        "mission_id": "provider-unavailable",
        "goal": "Check provider availability",
        "mission_type": "analysis",
        "status": "FAILED",
        "success": False,
        "provider_status": "provider_unavailable",
    }

    result = validate_completion_evidence(report, require_report_path=False)

    assert result.ok is False
    assert result.status == "PROVIDER_UNAVAILABLE"
    assert result.error_class == "provider_unavailable"


def test_non_code_success_without_artifact_is_allowed():
    report = {
        "mission_id": "identity",
        "goal": "Describe the current role.",
        "mission_type": "analysis",
        "status": "SUCCESS",
        "success": True,
    }

    result = validate_completion_evidence(report)

    assert result.ok is True
    assert result.status == "COMPLETED"
