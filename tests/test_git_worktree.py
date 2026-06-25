"""Tests pour l'isolation git worktree."""
from pathlib import Path
from unittest.mock import patch

import pytest

from tools.git_worktree import (
    _sanitize_id,
    WorktreeContext,
    EnterWorktreeTool,
    ExitWorktreeTool,
    ListWorktreesTool,
)


def test_sanitize_id_removes_special_chars():
    assert _sanitize_id("mission/abc:123") == "mission-abc-123"


def test_sanitize_id_truncates():
    long_id = "a" * 100
    assert len(_sanitize_id(long_id)) <= 40


@pytest.mark.asyncio
async def test_enter_worktree_tool_success():
    tool = EnterWorktreeTool()

    async def mock_git(args, cwd=None):
        return 0, "ok", ""

    with patch("tools.git_worktree._git", side_effect=mock_git):
        result = await tool({"mission_id": "test-123"})

    assert result.success
    assert "worktree_path" in result.metadata
    assert "branch" in result.metadata
    assert result.metadata["branch"] == "bea/mission-test-123"


@pytest.mark.asyncio
async def test_enter_worktree_tool_failure():
    tool = EnterWorktreeTool()

    async def mock_git(args, cwd=None):
        return 1, "", "fatal: branch already exists"

    with patch("tools.git_worktree._git", side_effect=mock_git):
        result = await tool({"mission_id": "test-123"})

    assert not result.success
    assert "échouée" in result.error


@pytest.mark.asyncio
async def test_exit_worktree_no_merge():
    tool = ExitWorktreeTool()

    calls = []

    async def mock_git(args, cwd=None):
        calls.append(args[0] if args else "")
        return 0, "ok", ""

    with patch("tools.git_worktree._git", side_effect=mock_git):
        result = await tool({"mission_id": "test-123", "merge_to_main": False})

    assert result.success
    assert "merge" not in calls


@pytest.mark.asyncio
async def test_list_worktrees():
    tool = ListWorktreesTool()

    mock_output = (
        "worktree /repo\n"
        "HEAD abc123\n"
        "branch refs/heads/main\n"
        "\n"
        "worktree /repo/.bea_worktrees/mission-abc\n"
        "HEAD def456\n"
        "branch refs/heads/bea/mission-abc\n"
    )

    async def mock_git(args, cwd=None):
        return 0, mock_output, ""

    with patch("tools.git_worktree._git", side_effect=mock_git):
        result = await tool({})

    assert result.success
    assert result.metadata["count"] == 1
    assert result.output[0]["branch"] == "refs/heads/bea/mission-abc"


@pytest.mark.asyncio
async def test_worktree_context_cleanup_on_exit():
    calls = []

    async def mock_git(args, cwd=None):
        calls.append(list(args))
        return 0, "ok", ""

    with patch("tools.git_worktree._git", side_effect=mock_git):
        with patch("tools.git_worktree._WORKTREE_BASE") as mock_base:
            mock_base.__truediv__ = lambda self, x: Path(f"/tmp/bea_worktrees/{x}")
            mock_base.mkdir = lambda **kw: None

            async with WorktreeContext(mission_id="ctx-test"):
                pass

    # Verify worktree remove and branch -D were both called during cleanup
    assert any(args[:2] == ["worktree", "remove"] for args in calls)
    assert any(args[:2] == ["branch", "-D"] for args in calls)
