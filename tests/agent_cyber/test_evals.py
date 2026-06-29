from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_cyber.evals.models import (
    CandidateFinding,
    CyberEvalAgentOutput,
    CyberEvalScore,
    CyberEvalTask,
    DifficultyLevel,
)
from agent_cyber.evals.runner import CyberEvalRunner
from agent_cyber.evals.scorer import CyberEvalScorer

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "agent_cyber" / "evals" / "fixtures"


@pytest.fixture
def scorer():
    return CyberEvalScorer()


@pytest.fixture
def runner():
    return CyberEvalRunner()


def _task(vuln_class: str = "sql-injection", vulnerable: bool = True, **kwargs) -> CyberEvalTask:
    defaults = dict(
        task_id="test-task-001",
        title="Test Task",
        difficulty=DifficultyLevel.L1,
        prompt="Review this code",
        expected_vulnerable=vulnerable,
        expected_vuln_class=vuln_class,
    )
    defaults.update(kwargs)
    return CyberEvalTask(**defaults)


def _output(
    task_id: str = "test-task-001",
    vulnerable: bool = True,
    vuln_class: str = "sql-injection",
    **kwargs,
) -> CyberEvalAgentOutput:
    candidate = CandidateFinding(
        vuln_class=vuln_class,
        confidence=0.9,
        locations=[{"file": "snippet", "function": "get_user"}],
        reason="String concatenation in SQL query",
        evidence_refs=["ev-001"],
        remediation="Use parameterized queries",
    )
    return CyberEvalAgentOutput(
        task_id=task_id,
        vulnerable=vulnerable,
        confidence=0.9,
        candidates=[candidate],
        **kwargs,
    )


def test_scorer_verdict_correct_high_score(scorer):
    task = _task()
    output = _output()
    score = scorer.score(task, output)
    assert score.verdict_score == 1.0
    assert score.total_score >= 40.0


def test_scorer_verdict_wrong_caps_at_10(scorer):
    task = _task(vulnerable=True)
    output = _output(vulnerable=False)
    score = scorer.score(task, output)
    assert score.verdict_score == 0.0
    assert score.total_score <= 10.0


def test_scorer_correct_vuln_class(scorer):
    task = _task(vuln_class="sql-injection")
    output = _output(vuln_class="sql-injection")
    score = scorer.score(task, output)
    assert score.class_score == 1.0


def test_scorer_wrong_vuln_class(scorer):
    task = _task(vuln_class="sql-injection")
    output = _output(vuln_class="xss")
    score = scorer.score(task, output)
    assert score.class_score == 0.0


def test_scorer_location_file_match(scorer):
    task = _task(expected_locations=[{"file": "snippet", "function": "get_user"}])
    output = _output()
    score = scorer.score(task, output)
    assert score.location_score > 0.0


def test_scorer_location_function_match(scorer):
    task = _task(expected_locations=[{"file": "snippet", "function": "get_user"}])
    output = _output()
    score = scorer.score(task, output)
    assert score.location_score == 1.0


def test_scorer_evidence_present(scorer):
    task = _task()
    output = _output()
    score = scorer.score(task, output)
    assert score.evidence_score == 1.0


def test_scorer_no_evidence(scorer):
    task = _task()
    candidate = CandidateFinding(
        vuln_class="sql-injection",
        confidence=0.7,
        reason="Pattern match",
        evidence_refs=[],
    )
    output = CyberEvalAgentOutput(
        task_id="test-task-001",
        vulnerable=True,
        confidence=0.7,
        candidates=[candidate],
    )
    score = scorer.score(task, output)
    assert score.evidence_score == 0.0


def test_scorer_remediation_present(scorer):
    task = _task()
    output = _output()
    score = scorer.score(task, output)
    assert score.remediation_score == 1.0


def test_scorer_total_score_in_range(scorer):
    task = _task()
    output = _output()
    score = scorer.score(task, output)
    assert 0.0 <= score.total_score <= 100.0


def test_output_max_three_candidates():
    with pytest.raises(ValueError, match="maximum 3"):
        CyberEvalAgentOutput(
            task_id="t",
            vulnerable=True,
            confidence=0.8,
            candidates=[
                CandidateFinding(vuln_class="xss", confidence=0.5, reason="r1"),
                CandidateFinding(vuln_class="sqli", confidence=0.5, reason="r2"),
                CandidateFinding(vuln_class="ssrf", confidence=0.5, reason="r3"),
                CandidateFinding(vuln_class="xxe", confidence=0.5, reason="r4"),
            ],
        )


def test_difficulty_enum_values():
    for level in DifficultyLevel:
        assert level.value in ("L0", "L1", "L2", "L3")


def test_fixtures_all_loadable(runner):
    tasks = runner.load_all_fixtures()
    assert len(tasks) == 5
    ids = {t.task_id for t in tasks}
    assert "eval_path_traversal_001" in ids
    assert "eval_sql_injection_001" in ids
    assert "eval_auth_bypass_001" in ids
    assert "eval_secret_hardcoded_001" in ids
    assert "eval_insecure_config_001" in ids


def test_run_all_produces_scores(runner):
    results = runner.run_all()
    assert len(results) == 5
    for task, output, score in results:
        assert 0.0 <= score.total_score <= 100.0
        assert score.task_id == task.task_id


def test_run_all_expected_all_vulnerable(runner):
    results = runner.run_all()
    for task, output, score in results:
        assert task.expected_vulnerable is True
        assert score.verdict_score == 1.0


def test_eval_score_fields_range(scorer):
    task = _task()
    output = _output()
    score = scorer.score(task, output)
    for field_name in ("verdict_score", "class_score", "location_score", "evidence_score", "remediation_score"):
        val = getattr(score, field_name)
        assert 0.0 <= val <= 1.0, f"{field_name} out of range: {val}"
