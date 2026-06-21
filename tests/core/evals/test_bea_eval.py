"""Tests for core.evals.bea_eval (active-memory model-router suite)."""
from __future__ import annotations

import pytest

from core.evals.bea_eval import BeaEval, run_and_report, run_evals
from core.evals.report import generate_markdown
from core.memory.operational_memory import OperationalMemoryStore
from core.repo_map.repo_map_service import RepoMapService


@pytest.fixture
def fixture_repo(tmp_path):
    (tmp_path / "core" / "memory").mkdir(parents=True)
    (tmp_path / "core" / "memory" / "memory_item.py").write_text(
        "class MemoryItem:\n    pass\n"
    )
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "routes.py").write_text(
        "from fastapi import APIRouter\n\nrouter = APIRouter()\n"
    )
    return tmp_path


@pytest.fixture
def bea_eval(fixture_repo):
    store = OperationalMemoryStore(db_path=":memory:")
    repo_svc = RepoMapService(root=fixture_repo, store=store, max_files=100)
    return BeaEval(store=store, repo_map_service=repo_svc, root=fixture_repo)


def test_list_evals_contains_expected(bea_eval):
    names = bea_eval.list_evals()
    assert "memory-active-decision" in names
    assert "repo-map-symbols" in names
    assert "router-summary-small-fast" in names
    assert "mission-context-prepare" in names
    assert "mission-result-record" in names
    assert "learning-parse-json-valid" in names
    assert "learning-deduplicate-identical" in names
    assert len(names) == 25


def test_learning_parse_json_valid(bea_eval):
    result = bea_eval.run("learning-parse-json-valid")
    assert result.success is True


def test_learning_create_eval_result(bea_eval):
    result = bea_eval.run("learning-create-eval-result")
    assert result.success is True


def test_learning_create_bug_memory(bea_eval):
    result = bea_eval.run("learning-create-bug-memory")
    assert result.success is True


def test_learning_deduplicate_identical(bea_eval):
    result = bea_eval.run("learning-deduplicate-identical")
    assert result.success is True


def test_learning_router_after_failures(bea_eval):
    result = bea_eval.run("learning-router-after-failures")
    assert result.success is True


def test_learning_ingestion_summary(bea_eval):
    result = bea_eval.run("learning-ingestion-summary")
    assert result.success is True


def test_memory_active_decision(bea_eval):
    result = bea_eval.run("memory-active-decision")
    assert result.success is True
    assert result.score == 1.0


def test_memory_ignore_obsolete(bea_eval):
    result = bea_eval.run("memory-ignore-obsolete")
    assert result.success is True


def test_memory_related_file_boost(bea_eval):
    result = bea_eval.run("memory-related-file-boost")
    assert result.success is True


def test_repo_map_symbols(bea_eval):
    result = bea_eval.run("repo-map-symbols")
    assert result.success is True


def test_router_summary_small_fast(bea_eval):
    result = bea_eval.run("router-summary-small-fast")
    assert result.success is True
    assert result.model_class_selected == "SMALL_FAST"


def test_router_protected_file_strong_review(bea_eval):
    result = bea_eval.run("router-protected-file-strong-review")
    assert result.success is True
    assert result.model_class_selected == "STRONG_CODE_REVIEW"


def test_router_budget_local_fallback(bea_eval):
    result = bea_eval.run("router-budget-local-fallback")
    assert result.success is True
    assert result.model_class_selected == "LOCAL_FALLBACK"


def test_mission_context_prepare(bea_eval):
    result = bea_eval.run("mission-context-prepare")
    assert result.success is True
    assert result.model_class_selected == "STRONG_CODE_REVIEW"


def test_mission_result_record(bea_eval):
    result = bea_eval.run("mission-result-record")
    assert result.success is True


def test_run_all_at_least_ten_evals_pass(bea_eval):
    report = bea_eval.run_all()
    passed = sum(1 for r in report.results if r.success)
    assert passed >= 15
    assert report.summary["total"] == 25
    assert 0.0 <= report.overall_score() <= 1.0


def test_run_evals_convenience(fixture_repo):
    report = run_evals(names=["router-summary-small-fast"], root=fixture_repo)
    assert len(report.results) == 1


def test_markdown_report_generated(bea_eval):
    report = bea_eval.run_all()
    markdown = generate_markdown(report)
    assert "# Bea Eval Report" in markdown
    assert report.run_id in markdown
    assert "memory" in markdown or "router" in markdown


def test_run_and_report(fixture_repo):
    report, markdown = run_and_report(root=fixture_repo)
    assert len(report.results) == 25
    assert "# Bea Eval Report" in markdown
