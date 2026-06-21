"""Tests for core.evals.report."""
from __future__ import annotations

from core.evals.models import EvalReport, EvalResult
from core.evals.report import generate_markdown


def test_generate_markdown_includes_summary():
    report = EvalReport()
    report.results = [
        EvalResult(eval_name="router-a", success=True, score=1.0, duration_ms=10),
        EvalResult(eval_name="memory-b", success=False, score=0.0, duration_ms=20, error="boom"),
    ]
    report.summary = {"total": 2, "passed": 1, "failed": 1, "overall_score": 0.5}
    md = generate_markdown(report)
    assert "# Bea Eval Report" in md
    assert "router-a" in md
    assert "memory-b" in md
    assert "boom" in md
    assert "Overall score" in md
