"""Security tests — path traversal.

Verifies that all file-handling layers reject paths that escape their sandbox:
  1. core/tools/file_tool._safe_path (FileReadTool / FileWriteTool)
  2. core/tool_executor.read_file_content / write_file_safe (via _check_path_safe)
  3. api/routes/execution._safe_artifact_dir (deploy + build detail endpoints)
"""
from __future__ import annotations

import os
import pytest


# ── helpers ────────────────────────────────────────────────────────────────────

_TRAVERSAL_PATHS = [
    "../../etc/passwd",
    "../../../windows/system32/cmd.exe",
    "/etc/passwd",
    "/app/workspace2/evil",          # starts with /app/workspace but is sibling
    "subdir/../../outside",
    "%2e%2e%2fetc%2fpasswd",         # URL-encoded — Path won't decode, but good to document
    "..\\..\\windows\\system32",     # backslash traversal
]


# ── 1. file_tool._safe_path ───────────────────────────────────────────────────

@pytest.mark.parametrize("evil_path", _TRAVERSAL_PATHS)
def test_safe_path_rejects_traversal(evil_path, tmp_path, monkeypatch):
    """_safe_path returns None for any path that resolves outside workspace."""
    import core.tools.file_tool as ft
    monkeypatch.setattr(ft, "_WORKSPACE", tmp_path)
    result = ft._safe_path(evil_path)
    # Either None (rejected) or a path that's still inside tmp_path
    if result is not None:
        assert result.is_relative_to(tmp_path), (
            f"_safe_path allowed escape: input={evil_path!r} resolved={result}"
        )


def test_safe_path_allows_valid_relative(tmp_path, monkeypatch):
    """_safe_path allows legitimate relative paths inside workspace."""
    import core.tools.file_tool as ft
    monkeypatch.setattr(ft, "_WORKSPACE", tmp_path)
    (tmp_path / "subdir").mkdir()
    result = ft._safe_path("subdir/file.txt")
    assert result is not None
    assert result.is_relative_to(tmp_path)


def test_safe_path_sibling_directory_rejected(tmp_path, monkeypatch):
    """Path that starts with workspace string but is a sibling dir is rejected.

    E.g., workspace=/app/workspace and path resolves to /app/workspace2/evil.
    The old startswith() would accept this — is_relative_to() rejects it.
    """
    import core.tools.file_tool as ft
    # workspace = tmp_path / "workspace"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    # sibling dir that shares a prefix with workspace name
    sibling = tmp_path / "workspace2"
    sibling.mkdir()
    monkeypatch.setattr(ft, "_WORKSPACE", workspace)

    # Path that would escape via the sibling dir
    evil = str(sibling / "secret.txt")
    result = ft._safe_path(evil)
    assert result is None, (
        f"_safe_path accepted sibling-dir escape: {evil!r} → {result}"
    )


# ── 2. tool_executor._check_path_safe ─────────────────────────────────────────

@pytest.mark.parametrize("evil_path", [
    "../../etc/passwd",
    "/etc/passwd",
    "../outside_workspace",
])
def test_check_path_safe_rejects_traversal(evil_path, tmp_path, monkeypatch):
    """_check_path_safe returns an error string for traversal attempts."""
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
    # bust the lazy cache inside _get_file_workspace
    import core.tool_executor as te
    err = te._check_path_safe(evil_path)
    assert err is not None, (
        f"_check_path_safe accepted traversal path: {evil_path!r}"
    )
    assert "path_escape" in err or "error" in err, f"Unexpected error msg: {err!r}"


def test_check_path_safe_allows_workspace_path(tmp_path, monkeypatch):
    """_check_path_safe returns None for a valid path inside workspace."""
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
    import core.tool_executor as te
    err = te._check_path_safe(str(tmp_path / "legit.txt"))
    assert err is None, f"_check_path_safe rejected valid path: {err!r}"


def test_read_file_content_rejects_traversal(tmp_path, monkeypatch):
    """read_file_content returns error dict for paths outside workspace."""
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
    import core.tool_executor as te
    result = te.read_file_content("../../etc/passwd")
    assert result["ok"] is False
    assert "path_escape" in result.get("error", "") or "error" in result.get("error", ""), (
        f"read_file_content did not reject traversal: {result}"
    )


def test_write_file_safe_rejects_traversal(tmp_path, monkeypatch):
    """write_file_safe returns error dict for paths outside workspace."""
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
    import core.tool_executor as te
    result = te.write_file_safe("../../etc/evil", "pwned")
    assert result["ok"] is False
    assert "path_escape" in result.get("error", "") or "error" in result.get("error", ""), (
        f"write_file_safe did not reject traversal: {result}"
    )


# ── 3. api/routes/execution._safe_artifact_dir ────────────────────────────────

def test_safe_artifact_dir_rejects_traversal(tmp_path):
    """_safe_artifact_dir raises HTTPException 400 on path traversal."""
    from fastapi import HTTPException
    from api.routes.execution import _safe_artifact_dir

    builds_dir = tmp_path / "builds"
    builds_dir.mkdir()

    for evil in ("../../etc/passwd", "../outside", "/etc/passwd"):
        with pytest.raises(HTTPException) as exc_info:
            _safe_artifact_dir(builds_dir, evil)
        assert exc_info.value.status_code == 400, (
            f"Expected 400 for {evil!r}, got {exc_info.value.status_code}"
        )


def test_safe_artifact_dir_allows_valid_id(tmp_path):
    """_safe_artifact_dir returns path for valid alphanumeric artifact_id."""
    from api.routes.execution import _safe_artifact_dir

    builds_dir = tmp_path / "builds"
    builds_dir.mkdir()
    (builds_dir / "abc123").mkdir()

    result = _safe_artifact_dir(builds_dir, "abc123")
    assert result.is_relative_to(builds_dir.resolve())


def test_safe_artifact_dir_sibling_rejected(tmp_path):
    """_safe_artifact_dir rejects ids that escape via sibling directory names."""
    from fastapi import HTTPException
    from api.routes.execution import _safe_artifact_dir

    builds_dir = tmp_path / "builds"
    builds_dir.mkdir()
    (tmp_path / "builds2").mkdir()

    # On Windows this is just a non-existent path; on Linux it could escape
    # Either way: must not escape
    evil = "../builds2/secret"
    with pytest.raises(HTTPException) as exc_info:
        _safe_artifact_dir(builds_dir, evil)
    assert exc_info.value.status_code == 400
