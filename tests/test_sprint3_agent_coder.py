"""Sprint 3 coding-agent primitives."""
from __future__ import annotations

import subprocess
from pathlib import Path

from core.coding_agent.failure_memory import FailureMemory, FailureRecord
from core.coding_agent.repo_map import build_repo_map
from core.coding_agent.swe_lite import run_swe_lite_v1
from scripts.sprint3_worktree import create_worktree, rollback


def test_failure_memory_records_and_searches_similar_issues(tmp_path: Path) -> None:
    memory_path = tmp_path / "failure_memory.json"
    memory = FailureMemory(memory_path)

    # First attempt failed
    memory.record_failure(
        issue="shell=True in local command runner",
        cause="subprocess used shell=True for Windows cmd",
        files_touched=("gateway/local_tools.py",),
        error_text="linter blocked shell=True",
        tags=("sprint3",),
    )

    # Winning fix
    memory.record_success(
        issue="shell=True in local command runner",
        cause="subprocess used shell=True for Windows cmd",
        files_touched=("gateway/local_tools.py",),
        error_text="linter blocked shell=True",
        successful_correction="use shlex.split + subprocess.run without shell=True",
        tags=("sprint3",),
    )

    # Search for a similar new issue
    results = memory.search("unsafe subprocess shell execution in gateway", top_k=3)
    assert len(results) == 2
    best_score, best_record = results[0]
    assert best_record.outcome == "success"
    assert "shlex" in best_record.successful_correction
    assert "gateway/local_tools.py" in best_record.files_touched


def test_failure_memory_persists_across_instances(tmp_path: Path) -> None:
    memory_path = tmp_path / "memory.json"
    m1 = FailureMemory(memory_path)
    m1.add(FailureRecord(
        issue="repo map too slow",
        cause="parsed every file in node_modules",
        files_touched=("core/coding_agent/repo_map.py",),
        error_text="timeout",
        successful_correction="exclude node_modules and add EXCLUDED_DIRS",
        outcome="success",
    ))

    m2 = FailureMemory(memory_path)
    results = m2.search("repo map slow with node_modules")
    assert results
    assert results[0][1].successful_correction == "exclude node_modules and add EXCLUDED_DIRS"


def test_repo_map_indexes_symbols_and_imports() -> None:
    repo_map = build_repo_map(Path.cwd(), max_files=1000)

    assert repo_map.parser == "ast"
    assert "core/coding_agent/repo_map.py" in repo_map.files
    assert any(symbol.name == "build_repo_map" for symbol in repo_map.symbols)
    assert any(import_info.module == "core.coding_agent.repo_map" for import_info in repo_map.imports)

    ranked = repo_map.rank_symbols("repo map build", max_symbols=10)
    assert ranked
    # build_repo_map must appear in the top-3 ranked symbols (exact position
    # is algorithm-dependent and may vary with codebase growth).
    top_names = [s.name for s in ranked[:3]]
    assert "build_repo_map" in top_names, (
        f"Expected 'build_repo_map' in top-3 ranked symbols, got: {top_names}"
    )


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
