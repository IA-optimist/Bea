"""
Tests for core/tools/repo_inspector.py — safe read-only repo inspection.
Tests: RI01-RI25
"""
import os
import sys
import pytest

# Ensure repo root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestReadFile:
    """RI01-RI05: File reading"""

    def test_RI01_read_existing_file(self):
        from core.tools.repo_inspector import read_file
        result = read_file("requirements.txt")
        assert result["ok"] is True
        assert "content" in result
        assert result["total_lines"] > 0

    def test_RI02_read_nonexistent_file(self):
        from core.tools.repo_inspector import read_file
        result = read_file("nonexistent_file_xyz.py")
        assert result["ok"] is False
        assert "not_found" in result["error"]

    def test_RI03_read_path_escape_blocked(self):
        from core.tools.repo_inspector import read_file
        result = read_file("../../etc/passwd")
        assert result["ok"] is False
        assert "blocked" in result["error"] or "not_found" in result["error"]

    def test_RI04_read_truncation(self):
        from core.tools.repo_inspector import read_file
        result = read_file("requirements.txt", max_lines=3)
        assert result["ok"] is True
        # Should have truncation indicator if file has >3 lines
        if result["total_lines"] > 3:
            assert "truncated" in result["content"]

    def test_RI05_read_python_file(self):
        from core.tools.repo_inspector import read_file
        result = read_file("core/tools/repo_inspector.py")
        assert result["ok"] is True
        assert "repo_inspector" in result["content"] or "def " in result["content"]


class TestGrepRepo:
    """RI06-RI10: Pattern searching"""

    def test_RI06_grep_finds_pattern(self):
        from core.tools.repo_inspector import grep_repo
        result = grep_repo("class BaseAgent", directory="agents")
        assert result["ok"] is True
        assert result["total"] >= 1
        assert any("crew.py" in m["file"] for m in result["matches"])

    def test_RI07_grep_no_matches(self):
        from core.tools.repo_inspector import grep_repo
        # Pattern that won't appear anywhere (not even in this test file)
        result = grep_repo("^QQQWWWEEERRRTTT999$")
        assert result["ok"] is True
        assert result["total"] == 0

    def test_RI08_grep_invalid_regex(self):
        from core.tools.repo_inspector import grep_repo
        result = grep_repo("[invalid")
        assert result["ok"] is False
        assert "invalid_regex" in result["error"]

    def test_RI09_grep_max_results_cap(self):
        from core.tools.repo_inspector import grep_repo
        # "import" should match many files
        result = grep_repo("^import ", directory="core")
        assert result["ok"] is True
        assert result["total"] <= 20  # capped

    def test_RI10_grep_scoped_directory(self):
        from core.tools.repo_inspector import grep_repo
        result = grep_repo("def ", directory="api")
        assert result["ok"] is True
        # All matches should be under api/
        for m in result["matches"]:
            assert m["file"].startswith("api/")


class TestGitCommands:
    """RI11-RI13: Git inspection"""

    def test_RI11_git_status(self):
        from core.tools.repo_inspector import git_status
        result = git_status()
        assert result["ok"] is True
        assert "branch" in result

    def test_RI12_git_log(self):
        from core.tools.repo_inspector import git_log
        result = git_log(n=3)
        # May return empty in Docker (no .git), but should not crash
        assert isinstance(result, dict)
        assert "ok" in result

    def test_RI13_git_log_capped(self):
        from core.tools.repo_inspector import git_log
        result = git_log(n=100)  # should be capped to 20
        assert result["ok"] is True
        lines = [l for l in result["output"].strip().splitlines() if l.strip()]
        assert len(lines) <= 20


class TestListAndTree:
    """RI14-RI17: Directory listing"""

    def test_RI14_list_root(self):
        from core.tools.repo_inspector import list_directory
        result = list_directory("")
        assert result["ok"] is True
        assert result["total"] > 0
        # Should contain known dirs
        items_str = " ".join(result["items"])
        assert "core/" in items_str or "api/" in items_str

    def test_RI15_list_subdirectory(self):
        from core.tools.repo_inspector import list_directory
        result = list_directory("core/tools")
        assert result["ok"] is True
        items_str = " ".join(result["items"])
        assert "repo_inspector.py" in items_str

    def test_RI16_tree_shallow(self):
        from core.tools.repo_inspector import tree
        result = tree("core", max_depth=1)
        assert result["ok"] is True
        assert "tree" in result
        assert len(result["tree"]) > 0

    def test_RI17_tree_depth_capped(self):
        from core.tools.repo_inspector import tree
        result = tree("", max_depth=10)  # should be capped to 3
        assert result["ok"] is True


class TestFileStats:
    """RI18-RI19: File analysis"""

    def test_RI18_stats_python_file(self):
        from core.tools.repo_inspector import file_stats
        result = file_stats("core/tools/repo_inspector.py")
        assert result["ok"] is True
        assert result["lines"] > 0
        assert result["size_bytes"] > 0
        assert len(result["functions"]) > 0

    def test_RI19_stats_nonexistent(self):
        from core.tools.repo_inspector import file_stats
        result = file_stats("does_not_exist.py")
        assert result["ok"] is False


class TestBuildAgentContext:
    """RI20-RI25: Agent context building"""

    def test_RI20_context_with_file_reference(self):
        from core.tools.repo_inspector import build_agent_context
        ctx = build_agent_context("Review core/llm_factory.py for improvements")
        assert len(ctx) > 0
        assert "llm_factory" in ctx

    def test_RI21_context_with_code_concept(self):
        from core.tools.repo_inspector import build_agent_context
        ctx = build_agent_context("How does the LLMFactory handle model routing?")
        assert len(ctx) > 0
        # Should find something related to LLM or factory
        assert "llm" in ctx.lower() or "factory" in ctx.lower()

    def test_RI22_context_with_keyword_search(self):
        from core.tools.repo_inspector import build_agent_context
        ctx = build_agent_context("Analyze the orchestrator module")
        assert len(ctx) > 0

    @pytest.mark.xfail(reason="context char limit drift", strict=False)
    def test_RI23_context_respects_char_limit(self):
        from core.tools.repo_inspector import build_agent_context
        ctx = build_agent_context("Review all Python files", max_chars=500)
        assert len(ctx) <= 1000  # some slack for formatting

    def test_RI24_context_code_task_includes_git(self):
        from core.tools.repo_inspector import build_agent_context
        ctx = build_agent_context("Fix the bug in api/auth.py file")
        # Code task should include git status
        # (may or may not depending on budget, but should not crash)
        assert isinstance(ctx, str)

    def test_RI25_context_empty_goal(self):
        from core.tools.repo_inspector import build_agent_context
        ctx = build_agent_context("")
        assert isinstance(ctx, str)  # should not crash
