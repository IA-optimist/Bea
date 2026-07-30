"""Validation helpers for code-mission artifacts.

The coding agent may produce good prose while still failing to materialize
anything a user can inspect. These helpers keep that distinction explicit.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.coding_agent.code_artifacts import validate_python_file


@dataclass(frozen=True)
class ArtifactValidationResult:
    """Result returned by artifact validation gates."""

    ok: bool
    status: str
    message: str
    artifacts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CompletionEvidenceResult:
    """Completion verdict for mission reports and execution sessions."""

    ok: bool
    status: str
    message: str
    error_class: str = ""
    artifacts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


_CODE_MARKERS = ("code", "coding", "coding_agent", "forge", "sha256", "python")
_TEST_MARKERS = ("pytest", "unittest", "ruff", "mypy", "tox", "python -m pytest")
_COMPLETED_STATES = {"COMPLETED", "DONE", "SUCCESS"}
_PROVIDER_UNAVAILABLE = "provider_unavailable"


def validate_code_artifacts(
    session_or_report: Any,
    *,
    repo_root: str | Path = ".",
) -> ArtifactValidationResult:
    """Validate that a needs-actions mission has a materialized artifact."""
    data = _to_mapping(session_or_report)
    verdict = _validate_completion_evidence(
        data,
        repo_root=Path(repo_root),
        force_completion=True,
        require_report_path=False,
        require_report_metadata=False,
    )
    return ArtifactValidationResult(
        ok=verdict.ok,
        status="COMPLETED" if verdict.ok else "NEEDS_ACTION_OUTPUT",
        message=verdict.message,
        artifacts=verdict.artifacts,
        warnings=verdict.warnings,
    )


def validate_mission_report_artifacts(
    report: Mapping[str, Any],
    *,
    repo_root: str | Path = ".",
) -> ArtifactValidationResult:
    """Validate artifact metadata in a mission report dictionary."""
    verdict = _validate_completion_evidence(
        dict(report),
        repo_root=Path(repo_root),
        force_completion=False,
        require_report_path=True,
        require_report_metadata=True,
    )
    return ArtifactValidationResult(
        ok=verdict.ok,
        status="COMPLETED" if verdict.ok else "NEEDS_ACTION_OUTPUT",
        message=verdict.message,
        artifacts=verdict.artifacts,
        warnings=verdict.warnings,
    )


def validate_completion_evidence(
    session_or_report: Any,
    *,
    repo_root: str | Path = ".",
    force_completion: bool = False,
    require_report_path: bool = False,
    require_report_metadata: bool = False,
) -> CompletionEvidenceResult:
    """Return a completion verdict with explicit failure classes."""
    data = _to_mapping(session_or_report)
    return _validate_completion_evidence(
        data,
        repo_root=Path(repo_root),
        force_completion=force_completion,
        require_report_path=require_report_path,
        require_report_metadata=require_report_metadata,
    )


def _validate_completion_evidence(
    data: Mapping[str, Any],
    *,
    repo_root: Path,
    force_completion: bool,
    require_report_path: bool,
    require_report_metadata: bool,
) -> CompletionEvidenceResult:
    warnings: list[str] = []
    artifacts: list[str] = []
    missing: list[str] = []

    needs_actions = bool(data.get("needs_actions"))
    code_mission = _is_code_mission(data)
    completed = force_completion or _is_completed_candidate(data)

    provider_status = _provider_unavailable_status(data)
    if provider_status:
        return CompletionEvidenceResult(
            ok=False,
            status="PROVIDER_UNAVAILABLE",
            message="provider unavailable; completion was not evaluated",
            error_class=provider_status,
            artifacts=artifacts,
            warnings=warnings,
        )

    if not completed:
        return CompletionEvidenceResult(
            ok=True,
            status="SKIPPED",
            message="completion was not requested",
            artifacts=artifacts,
            warnings=warnings,
        )

    report_path_value = str(data.get("report_path") or "").strip()
    if require_report_path and not report_path_value:
        missing.append("report_path is required for a completed mission report")
    elif report_path_value:
        report_path = Path(report_path_value)
        if not report_path.is_absolute():
            report_path = repo_root / report_path
        if not report_path.exists():
            missing.append(f"report_path does not exist: {report_path_value}")
        else:
            artifacts.append(f"report:{report_path_value}")

    if needs_actions and not _has_expected_artifact(data):
        missing.append("expected_artifact is required when needs_actions=True")

    file_paths = _declared_file_paths(data)
    missing_paths = _missing_declared_paths(file_paths, repo_root)
    if missing_paths:
        missing.append("declared file path(s) do not exist: " + ", ".join(missing_paths))
    elif file_paths:
        artifacts.extend(f"file:{path}" for path in file_paths)

    diff = _non_empty_diff(data)
    if diff:
        artifacts.append("diff")

    test_commands = _test_commands(data)
    if test_commands:
        artifacts.extend(f"test:{command}" for command in test_commands)
    elif code_mission:
        missing.append("test command is required for a completed code mission")

    tool_actions = _successful_tool_actions(data)
    if tool_actions:
        artifacts.extend(f"action:{action}" for action in tool_actions)

    if code_mission:
        if require_report_metadata:
            for field_name in ("provider_used", "model_used", "artifacts", "tests_run", "test_result"):
                value = data.get(field_name)
                if value in (None, "", [], {}, ()):  # explicit proof required
                    missing.append(f"{field_name} is required for a completed code mission")
        if not data.get("files_created") and not data.get("unified_diff") and not data.get("diff") and not data.get("patch"):
            missing.append("files_created or a non-empty diff is required for a completed code mission")

    has_materialized_artifact = bool(file_paths or diff or tool_actions)
    if needs_actions and not has_materialized_artifact:
        missing.append("needs_actions=True requires at least one verifiable artifact")

    syntax_missing = _validate_python_artifacts(file_paths, repo_root, artifacts, warnings)
    missing.extend(syntax_missing)

    if missing:
        if any(item.startswith("report_path") for item in missing):
            status = "REPORT_MISSING"
            error_class = "report_missing"
        elif any(item.startswith("syntax validation failed") or item.startswith("declared file path(s)")
                 or item.startswith("files_created or a non-empty diff")
                 or item.startswith("expected_artifact")
                 or item.startswith("needs_actions=True requires")
                 for item in missing):
            status = "ARTIFACT_INVALID"
            error_class = "artifact_invalid"
        else:
            status = "TEST_MISSING"
            error_class = "test_missing"
        return CompletionEvidenceResult(
            ok=False,
            status=status,
            message="completed mission is missing verifiable evidence: " + "; ".join(missing),
            error_class=error_class,
            artifacts=artifacts,
            warnings=warnings,
        )

    return CompletionEvidenceResult(
        ok=True,
        status="COMPLETED",
        message="verifiable artifact evidence present",
        artifacts=artifacts,
        warnings=warnings,
    )


def _validate_python_artifacts(
    paths: Iterable[str],
    repo_root: Path,
    artifacts: list[str],
    warnings: list[str],
) -> list[str]:
    missing: list[str] = []
    for raw_path in paths:
        if not raw_path.endswith(".py"):
            continue
        path = Path(raw_path)
        if not path.is_absolute():
            path = repo_root / path
        if not path.exists():
            continue
        syntax_ok, syntax_error = validate_python_file(path)
        if syntax_ok:
            artifacts.append(f"syntax:{raw_path}")
        else:
            warnings.append(f"syntax validation failed for {raw_path}: {syntax_error}")
            missing.append(f"syntax validation failed for {raw_path}")
    return missing


def _is_completed_candidate(data: Mapping[str, Any]) -> bool:
    success = data.get("success")
    status = str(data.get("status") or "").upper()
    return success is True or status in _COMPLETED_STATES


def _provider_unavailable_status(data: Mapping[str, Any]) -> str:
    for key in ("provider_status", "skip_reason", "error_category"):
        value = str(data.get(key) or "").strip().lower()
        if value == _PROVIDER_UNAVAILABLE:
            return _PROVIDER_UNAVAILABLE
    return ""


def _to_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    data: dict[str, Any] = {}
    for key in (
        "actions_executed",
        "actions_pending",
        "_raw_actions",
        "diff",
        "error",
        "expected_artifact",
        "expected_artifacts",
        "files_changed",
        "files_created",
        "final_report",
        "goal",
        "mission_type",
        "mode",
        "needs_actions",
        "provider_status",
        "patch",
        "provider_used",
        "skip_reason",
        "model_used",
        "report_path",
        "artifacts",
        "tests_run",
        "test_result",
        "syntax_check",
        "syntax_valid",
        "status",
        "success",
        "task_mode",
        "task_type",
        "test_command",
        "test_commands",
        "tests",
        "unified_diff",
        "user_input",
    ):
        if hasattr(value, key):
            data[key] = getattr(value, key)
    return data


def _is_code_mission(data: Mapping[str, Any]) -> bool:
    haystack = " ".join(
        str(data.get(key) or "")
        for key in ("mission_type", "task_type", "task_mode", "mode", "goal", "user_input")
    ).lower()
    return any(marker in haystack for marker in _CODE_MARKERS)


def _declared_file_paths(data: Mapping[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in ("files_created", "created_files", "files_changed", "modified_files"):
        paths.extend(_string_list(data.get(key)))

    expected = data.get("expected_artifact")
    if isinstance(expected, str) and _looks_like_path(expected):
        paths.append(expected)
    elif isinstance(expected, Mapping):
        path = expected.get("path")
        if path:
            paths.append(str(path))

    for item in _iter_items(data.get("expected_artifacts")):
        if isinstance(item, str):
            paths.append(item)
        elif isinstance(item, Mapping) and item.get("path"):
            paths.append(str(item["path"]))

    return _dedupe(paths)


def _missing_declared_paths(paths: Iterable[str], repo_root: Path) -> list[str]:
    missing: list[str] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = repo_root / path
        if not path.exists():
            missing.append(raw_path)
    return missing


def _has_expected_artifact(data: Mapping[str, Any]) -> bool:
    expected = data.get("expected_artifact")
    expected_many = data.get("expected_artifacts")
    if isinstance(expected, str):
        return bool(expected.strip())
    if isinstance(expected, Mapping):
        return bool(expected)
    if list(_iter_items(expected_many)):
        return True
    for action in _iter_items(data.get("actions_executed")):
        if isinstance(action, Mapping) and (
            action.get("target") or action.get("path") or action.get("command")
        ):
            return True
    return False


def _looks_like_path(value: str) -> bool:
    return "/" in value or "\\" in value or "." in Path(value).name


def _non_empty_diff(data: Mapping[str, Any]) -> str:
    for key in ("unified_diff", "diff", "patch"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _test_commands(data: Mapping[str, Any]) -> list[str]:
    commands: list[str] = []
    commands.extend(_string_list(data.get("test_command")))
    commands.extend(_string_list(data.get("test_commands")))
    commands.extend(_string_list(data.get("tests_run")))
    commands.extend(_string_list(data.get("tests")))
    for action in _iter_items(data.get("actions_executed")):
        if isinstance(action, Mapping):
            command = str(action.get("command") or "")
            if command and any(marker in command.lower() for marker in _TEST_MARKERS):
                commands.append(command)
    return _dedupe(commands)


def _successful_tool_actions(data: Mapping[str, Any]) -> list[str]:
    actions: list[str] = []
    executed = list(_iter_items(data.get("actions_executed")))
    raw_actions = list(_iter_items(data.get("_raw_actions")))
    pending = list(_iter_items(data.get("actions_pending")))
    if not executed:
        return actions
    if raw_actions and len(executed) + len(pending) < len(raw_actions):
        return actions
    for idx, action in enumerate(executed, start=1):
        if isinstance(action, Mapping):
            if action.get("success") is False:
                continue
            target = str(action.get("target") or action.get("path") or action.get("command") or f"#{idx}")
            actions.append(target)
        else:
            actions.append(str(action))
    return _dedupe(actions)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [str(item) for item in _iter_items(value) if str(item).strip()]


def _iter_items(value: Any) -> Iterable[Any]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        return [value]
    if isinstance(value, Iterable):
        return value
    return [value]


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result
