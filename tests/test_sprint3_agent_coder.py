"""Sprint 3 coding-agent primitives."""
from __future__ import annotations

import subprocess
from pathlib import Path

from core.coding_agent.repo_map import build_repo_map
from core.coding_agent.swe_lite import run_swe_lite_v1
from scripts.sprint3_worktree import create_worktree, rollback


def test_repo_map_indexes_symbols_and_imports() -> None:
    repo_map = build_repo_map(Path.cwd(), max_files=1000)

    assert repo_map.parser == "ast"
    assert "core/coding_agent/repo_map.py" in repo_map.files
    assert any(symbol.name == "build_repo_map" for symbol in repo_map.symbols)
    assert any(import_info.module == "core.coding_agent.repo_map" for import_info in repo_map.imports)

    ranked = repo_map.rank_symbols("repo map build", max_symbols=10)
    assert ranked
    assert ranked[0].name == "build_repo_map"


def test_sprint3_worktree_create_and_rollback(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)

    created = create_worktree(tmp_path, "sprint3-smoke", base="HEAD")
    assert created["ok"] is True
    worktree = Path(created["worktree"])
    assert worktree.exists()

    removed = rollback(tmp_path, worktree, created["branch"])
    assert removed["ok"] is True


def test_swe_lite_v1_passes_for_sprint3_primitives() -> None:
    report = run_swe_lite_v1(Path.cwd())

    assert report.passed is True
    assert report.score >= 0.85
    assert {case.name for case in report.cases} == {
        "shell-true-hardening",
        "repo-map-indexing",
        "worktree-per-task",
    }
