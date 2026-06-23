"""Validation helpers for code-mission artifacts.

The coding agent may produce good prose while still failing to materialize
anything a user can inspect. These helpers keep that distinction explicit.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ArtifactValidationResult:
    """Result returned by artifact validation gates."""

    ok: bool
    status: str
    message: str
    artifacts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # Aliases for callers that prefer .valid / .reason
    @property
    def valid(self) -> bool:
        return self.ok

    @property
    def reason(self) -> str:
        return self.message


_CODE_MARKERS = ("code", "coding", "coding_agent", "forge", "sha256", "python")
_TEST_MARKERS = ("pytest", "unittest", "ruff", "mypy", "tox", "python -m pytest")


def validate_code_artifacts(
    session_or_report: Any,
    *,
    repo_root: str | Path = ".",
) -> ArtifactValidationResult:
    """Validate that a needs-actions mission has a materialized artifact."""
    data = _to_mapping(session_or_report)
    return _validate(data, repo_root=Path(repo_root))


def validate_mission_report_artifacts(
    report: Mapping[str, Any],
    *,
    repo_root: str | Path = ".",
) -> ArtifactValidationResult:
    """Validate artifact metadata in a mission report dictionary."""
    return _validate(dict(report), repo_root=Path(repo_root))


def _validate(data: Mapping[str, Any], *, repo_root: Path) -> ArtifactValidationResult:
    warnings: list[str] = []
    artifacts: list[str] = []
    missing: list[str] = []

    if not data.get("report_path"):
        warnings.append("report_path is missing; ingestion traceability is weaker")

    needs_actions = bool(data.get("needs_actions"))
    code_mission = _is_code_mission(data)
    if not needs_actions and not code_mission:
        return ArtifactValidationResult(
            ok=True,
            status="COMPLETED",
            message="mission does not require action artifacts",
            warnings=warnings,
        )

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

    tool_actions = _successful_tool_actions(data)
    if tool_actions:
        artifacts.extend(f"action:{action}" for action in tool_actions)

    if code_mission and not test_commands:
        missing.append("test command is required for a completed code mission")

    # Partial action gate: planned actions must fit inside executed + pending.
    if not _actions_accounted_for(data):
        raw, executed, pending = _count_action_progress(data)
        missing.append(
            f"actions appear partial: {raw} planned > "
            f"{executed} executed + {pending} pending"
        )

    if code_mission and _has_python_artifact(data, file_paths) and not _has_syntax_validation(data):
        missing.append("python artifact requires syntax validation proof")

    report_like = bool(
        data.get("report_path")
        or data.get("provider_used")
        or data.get("model_used")
        or data.get("test_result")
        or data.get("artifacts")
        or data.get("files_created")
        or data.get("tests_run")
    )

    if code_mission and report_like:
        for field_name in ("provider_used", "model_used", "artifacts", "tests_run", "test_result"):
            value = data.get(field_name)
            if value in (None, "", [], {}, ()):  # explicit proof required
                missing.append(f"{field_name} is required for a completed code mission")
        if not data.get("files_created") and not data.get("unified_diff") and not data.get("diff") and not data.get("patch"):
            missing.append("files_created or a non-empty diff is required for a completed code mission")

    has_materialized_artifact = bool(file_paths or diff or tool_actions)
    if needs_actions and not has_materialized_artifact:
        missing.append("needs_actions=True requires at least one verifiable artifact")

    success = data.get("success")
    completed_status = str(data.get("status") or "").upper() in {"COMPLETED", "DONE", "SUCCESS"}
    if (success is True or completed_status) and missing:
        return ArtifactValidationResult(
            ok=False,
            status="NEEDS_ACTION_OUTPUT",
            message="completed action mission is missing verifiable artifact evidence: "
            + "; ".join(missing),
            artifacts=artifacts,
            warnings=warnings,
        )

    if missing:
        return ArtifactValidationResult(
            ok=False,
            status="NEEDS_ACTION_OUTPUT",
            message="action mission is missing verifiable artifact evidence: " + "; ".join(missing),
            artifacts=artifacts,
            warnings=warnings,
        )

    return ArtifactValidationResult(
        ok=True,
        status="COMPLETED",
        message="verifiable artifact evidence present",
        artifacts=artifacts,
        warnings=warnings,
    )


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
        "patch",
        "provider_used",
        "model_used",
        "report_path",
        "artifacts",
        "files_created",
        "tests_run",
        "test_result",
        "status",
        "success",
        "task_mode",
        "task_type",
        "test_command",
        "test_commands",
        "tests",
        "tests_run",
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

    paths.extend(_extract_expected_artifact_paths(data))
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
    if not executed:
        return actions
    if not _actions_accounted_for(data):
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


def _count_action_progress(data: Mapping[str, Any]) -> tuple[int, int, int]:
    """Return (raw, executed, pending) counts for action accounting gates."""
    raw = sum(1 for _ in _iter_items(data.get("_raw_actions")))
    executed = sum(1 for _ in _iter_items(data.get("actions_executed")))
    pending = sum(1 for _ in _iter_items(data.get("actions_pending")))
    return raw, executed, pending


def _actions_accounted_for(data: Mapping[str, Any]) -> bool:
    """Planned actions must fit inside executed + pending."""
    raw, executed, pending = _count_action_progress(data)
    if raw and executed + pending < raw:
        return False
    return True


def _extract_expected_artifact_paths(data: Mapping[str, Any]) -> list[str]:
    """Return normalized paths from expected_artifact / expected_artifacts."""
    paths: list[str] = []
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
    return paths


def _has_python_artifact(data: Mapping[str, Any], file_paths: Iterable[str]) -> bool:
    expected_paths = _extract_expected_artifact_paths(data)
    return any(str(path).endswith(".py") for path in (*expected_paths, *file_paths))


def _has_syntax_validation(data: Mapping[str, Any]) -> bool:
    """True when the report contains an explicit Python syntax-validation proof."""
    test_result = data.get("test_result")
    if isinstance(test_result, Mapping):
        for key in ("syntax_check", "py_compile"):
            check = test_result.get(key)
            if isinstance(check, Mapping) and check.get("passed") is True:
                return True
            if isinstance(check, dict) and check.get("passed") is True:
                return True
    return False


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


def validate_coding_report(
    report: Mapping[str, Any],
    *,
    artifact_root: str | Path | None = None,
) -> ArtifactValidationResult:
    """Validate a mission report dict for completion truth.

    Convenience wrapper over ``validate_mission_report_artifacts`` with a
    normalised call signature. Returns an ``ArtifactValidationResult`` with
    ``.valid`` / ``.reason`` aliases in addition to ``.ok`` / ``.message``.

    ``artifact_root`` defaults to the current working directory when ``None``.
    """
    root = Path(artifact_root) if artifact_root is not None else Path(".")
    return validate_mission_report_artifacts(report, repo_root=root)
