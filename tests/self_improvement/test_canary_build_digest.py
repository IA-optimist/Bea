"""
Tests for T4.3 (canary gate) and T4.5 (build digest).

T4.3: CanaryGate rejects patches that introduce compile errors
T4.5: compute_build_digest produces a stable, structured fingerprint
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

from core.self_improvement.build_digest import compute_build_digest
from core.self_improvement.canary_gate import CanaryGate, CanaryResult, get_canary_gate


# ── T4.3 — CanaryGate ─────────────────────────────────────────────────────────

class TestCanaryGate:

    def test_skipped_when_no_changed_files(self) -> None:
        gate = CanaryGate()
        result = gate.run(changed_files=[])
        assert result.skipped is True
        assert result.passed is True
        assert result.reason == "no_python_files"

    def test_skipped_when_no_py_files(self, tmp_path: Path) -> None:
        txt = tmp_path / "data.txt"
        txt.write_text("hello")
        gate = CanaryGate()
        result = gate.run(sandbox_path=tmp_path, changed_files=["data.txt"])
        assert result.skipped is True
        assert result.passed is True

    def test_pass_on_valid_python(self, tmp_path: Path) -> None:
        good = tmp_path / "good.py"
        good.write_text("x = 1\n")
        gate = CanaryGate()
        result = gate.run(sandbox_path=tmp_path, changed_files=["good.py"])
        assert result.passed is True
        assert result.skipped is False
        assert result.returncode == 0

    def test_fail_on_syntax_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.py"
        bad.write_text("def foo(\n")  # unclosed paren → SyntaxError
        gate = CanaryGate()
        result = gate.run(sandbox_path=tmp_path, changed_files=["bad.py"])
        assert result.passed is False
        assert result.skipped is False
        assert "compile_fail" in result.reason
        assert result.returncode != 0

    def test_fail_gives_rollback_info_in_stdout(self, tmp_path: Path) -> None:
        bad = tmp_path / "oops.py"
        bad.write_text("class Broken:\n    def f(self\n")
        gate = CanaryGate()
        result = gate.run(sandbox_path=tmp_path, changed_files=["oops.py"])
        assert result.passed is False
        # stdout contains error message (stderr from py_compile)
        assert len(result.stdout) > 0

    def test_multiple_files_fail_if_any_broken(self, tmp_path: Path) -> None:
        good = tmp_path / "good.py"
        good.write_text("y = 2\n")
        bad = tmp_path / "bad.py"
        bad.write_text("x = (\n")  # unclosed paren
        gate = CanaryGate()
        result = gate.run(sandbox_path=tmp_path, changed_files=["good.py", "bad.py"])
        assert result.passed is False

    def test_singleton_is_canary_gate(self) -> None:
        g1 = get_canary_gate()
        g2 = get_canary_gate()
        assert g1 is g2
        assert isinstance(g1, CanaryGate)

    def test_skipped_when_file_does_not_exist_in_sandbox(self, tmp_path: Path) -> None:
        gate = CanaryGate()
        result = gate.run(sandbox_path=tmp_path, changed_files=["nonexistent.py"])
        assert result.skipped is True
        assert result.passed is True


# ── T4.5 — build_digest ───────────────────────────────────────────────────────

class TestBuildDigest:

    def test_returns_required_keys(self) -> None:
        digest = compute_build_digest()
        assert "python" in digest
        assert "platform" in digest
        assert "files" in digest
        assert "digest" in digest

    def test_python_version_matches_runtime(self) -> None:
        digest = compute_build_digest()
        expected = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        assert digest["python"] == expected

    def test_consistent_output_same_inputs(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.txt").write_text("pytest==8.0.0\n")
        (tmp_path / "pyproject.toml").write_text("[project]\nname='bea'\n")
        d1 = compute_build_digest(tmp_path)
        d2 = compute_build_digest(tmp_path)
        assert d1["digest"] == d2["digest"]
        assert d1["files"] == d2["files"]

    def test_different_content_gives_different_digest(self, tmp_path: Path) -> None:
        req = tmp_path / "requirements.txt"
        req.write_text("pytest==8.0.0\n")
        d1 = compute_build_digest(tmp_path)
        req.write_text("pytest==9.0.0\n")
        d2 = compute_build_digest(tmp_path)
        assert d1["digest"] != d2["digest"]
        assert d1["files"]["requirements.txt"] != d2["files"]["requirements.txt"]

    def test_empty_dir_returns_no_build_files(self, tmp_path: Path) -> None:
        digest = compute_build_digest(tmp_path)
        assert digest["files"] == {}
        assert digest["digest"] == "no_build_files"

    def test_digest_is_short_hex(self) -> None:
        digest = compute_build_digest()
        d = digest["digest"]
        assert isinstance(d, str)
        assert len(d) <= 16
        # Either valid hex or the sentinel "no_build_files"
        if d != "no_build_files":
            int(d, 16)  # must be parseable as hex


# ── Integration: gate.record() includes build_digest ─────────────────────────

class TestGateRecordBuildDigest:

    def test_record_stores_build_digest(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from kernel.improvement.gate import ImprovementGate

        history_path = tmp_path / "workspace" / "self_improvement" / "history.json"
        monkeypatch.chdir(tmp_path)

        gate = ImprovementGate()
        gate.record("SUCCESS", {"patch_id": "test-123"})

        assert history_path.exists()
        history = json.loads(history_path.read_text("utf-8"))
        assert len(history) == 1
        entry = history[0]
        assert entry["outcome"] == "SUCCESS"
        assert entry["patch_id"] == "test-123"
        assert "build_digest" in entry
        assert "python" in entry["build_digest"]
        assert "digest" in entry["build_digest"]
