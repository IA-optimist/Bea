"""Tests unitaires pour gateway/local_tools.py.

Couvre : blocklist, truncation, execute_shell, execute_python,
read_file/write_file/edit_file, grep_search, glob_search.
"""
from __future__ import annotations

import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from gateway.local_tools import (
    _BLOCKLIST,
    _MAX_OUT,
    _truncate,
    edit_file,
    execute_python,
    execute_shell,
    glob_search,
    grep_search,
    list_dir,
    read_file,
    write_file,
)


# ── _BLOCKLIST ────────────────────────────────────────────────────────────────

class TestBlocklist:
    def test_rm_rf_root_blocked(self):
        assert _BLOCKLIST.search("rm -rf /")

    def test_rmdir_recursive_blocked(self):
        assert _BLOCKLIST.search("rd /s C:\\Windows")

    def test_format_drive_blocked(self):
        assert _BLOCKLIST.search("format c:")

    def test_shutdown_blocked(self):
        assert _BLOCKLIST.search("shutdown -r now")

    def test_fork_bomb_blocked(self):
        assert _BLOCKLIST.search(":() { :|: & }; :")

    def test_safe_echo_not_blocked(self):
        assert not _BLOCKLIST.search("echo hello world")

    def test_safe_ls_not_blocked(self):
        assert not _BLOCKLIST.search("ls -la /tmp")

    def test_safe_python_not_blocked(self):
        assert not _BLOCKLIST.search("python -c 'print(1)'")

    def test_safe_dir_not_blocked(self):
        assert not _BLOCKLIST.search("dir C:\\Users")


# ── _truncate ─────────────────────────────────────────────────────────────────

class TestTruncate:
    def test_short_string_unchanged(self):
        assert _truncate("hello") == "hello"

    def test_empty_string(self):
        assert _truncate("") == ""

    def test_none_becomes_empty(self):
        assert _truncate(None) == ""

    def test_long_string_truncated(self):
        big = "x" * (_MAX_OUT + 100)
        result = _truncate(big)
        assert len(result) < len(big)
        assert "tronqué" in result

    def test_exact_max_not_truncated(self):
        exact = "x" * _MAX_OUT
        assert _truncate(exact) == exact


# ── execute_shell ─────────────────────────────────────────────────────────────

class TestExecuteShell:
    def test_missing_command_returns_error(self):
        result = execute_shell({})
        assert "erreur" in result.lower()

    def test_blocklisted_command_refused(self):
        result = execute_shell({"command": "rm -rf /"})
        assert "REFUSÉ" in result or "refus" in result.lower()

    def test_shutdown_blocked(self):
        result = execute_shell({"command": "shutdown -h now"})
        assert "REFUSÉ" in result or "refus" in result.lower()

    def test_simple_echo(self):
        result = execute_shell({"command": "echo hello_test_bea"})
        assert "hello_test_bea" in result or "erreur" not in result.lower()

    def test_cmd_alias_accepted(self):
        # 'cmd' key is an alias for 'command'
        result = execute_shell({"cmd": "echo alias_ok"})
        assert "erreur" not in result.lower() or "alias_ok" in result


# ── execute_python ────────────────────────────────────────────────────────────

class TestExecutePython:
    def test_missing_code_returns_error(self):
        result = execute_python({})
        assert "erreur" in result.lower()

    def test_simple_print(self):
        result = execute_python({"code": "print('bea_test_42')"})
        assert "bea_test_42" in result

    def test_arithmetic(self):
        result = execute_python({"code": "print(6 * 7)"})
        assert "42" in result

    def test_syntax_error_caught(self):
        result = execute_python({"code": "def broken( "})
        # Should return stderr, not raise
        assert isinstance(result, str)

    def test_script_alias(self):
        result = execute_python({"script": "print('via_script_alias')"})
        assert "via_script_alias" in result


# ── read_file / write_file / edit_file ────────────────────────────────────────

class TestFileOps:
    def test_write_then_read(self, tmp_path):
        p = tmp_path / "test.txt"
        result = write_file({"path": str(p), "content": "bonjour béa"})
        assert "ok" in result.lower()
        content = read_file({"path": str(p)})
        assert "bonjour" in content

    def test_read_missing_file(self, tmp_path):
        result = read_file({"path": str(tmp_path / "nonexistent.txt")})
        assert "erreur" in result.lower()

    def test_write_missing_path_arg(self):
        result = write_file({"content": "hello"})
        assert "erreur" in result.lower()

    def test_read_missing_path_arg(self):
        result = read_file({})
        assert "erreur" in result.lower()

    def test_edit_replace(self, tmp_path):
        p = tmp_path / "edit.txt"
        p.write_text("hello world", encoding="utf-8")
        result = edit_file({"path": str(p), "old": "world", "new": "replaced"})
        assert "ok" in result.lower()
        assert p.read_text(encoding="utf-8") == "hello replaced"

    def test_edit_not_found(self, tmp_path):
        p = tmp_path / "nope.txt"
        p.write_text("abc")
        result = edit_file({"path": str(p), "old": "xyz", "new": "bbb"})
        assert "erreur" in result.lower() or "introuvable" in result.lower()

    def test_write_creates_parent_dirs(self, tmp_path):
        p = tmp_path / "deep" / "dir" / "file.txt"
        write_file({"path": str(p), "content": "nested"})
        assert p.exists()


# ── grep_search ───────────────────────────────────────────────────────────────

class TestGrepSearch:
    def test_finds_pattern(self, tmp_path):
        (tmp_path / "a.txt").write_text("hello world\nfoo bar")
        result = grep_search({"pattern": "hello", "path": str(tmp_path)})
        assert "hello" in result

    def test_missing_pattern_error(self, tmp_path):
        result = grep_search({"path": str(tmp_path)})
        assert "erreur" in result.lower()

    def test_no_match_returns_sentinel(self, tmp_path):
        (tmp_path / "b.txt").write_text("nothing interesting")
        result = grep_search({"pattern": "xyznotfound999", "path": str(tmp_path)})
        assert "AUCUN_RESULTAT" in result


# ── glob_search ───────────────────────────────────────────────────────────────

class TestGlobSearch:
    def test_finds_py_files(self, tmp_path):
        (tmp_path / "foo.py").write_text("")
        (tmp_path / "bar.txt").write_text("")
        result = glob_search({"pattern": "*.py", "path": str(tmp_path)})
        assert "foo.py" in result
        assert "bar.txt" not in result

    def test_missing_pattern_error(self):
        result = glob_search({"path": "."})
        assert "erreur" in result.lower()

    def test_no_match_returns_sentinel(self, tmp_path):
        result = glob_search({"pattern": "*.xyz_nonexistent", "path": str(tmp_path)})
        assert "AUCUN_FICHIER" in result


# ── list_dir ──────────────────────────────────────────────────────────────────

class TestListDir:
    def test_lists_contents(self, tmp_path):
        (tmp_path / "alpha.txt").write_text("")
        (tmp_path / "subdir").mkdir()
        result = list_dir({"path": str(tmp_path)})
        assert "alpha.txt" in result
        assert "subdir" in result

    def test_nonexistent_path(self, tmp_path):
        result = list_dir({"path": str(tmp_path / "ghost")})
        assert "erreur" in result.lower() or "introuvable" in result.lower()
