from __future__ import annotations


def test_bea_benchmark_report_shape():
    from core.self_improvement.benchmark_harness import run_bea_benchmark

    report = run_bea_benchmark()
    data = report.to_dict()

    assert "memory" in data
    assert "coding" in data
    assert "comparisons" in data
    assert data["methodology"] == "internal_smoke_thresholds"
    assert data["external_comparison"] is False
    assert isinstance(data["memory"]["passed"], bool)
    assert isinstance(data["coding"]["passed"], bool)
    assert 0.0 <= data["overall_score"] <= 1.0


def test_bea_benchmark_targets_are_named():
    from core.self_improvement.benchmark_harness import run_bea_benchmark

    report = run_bea_benchmark().to_dict()
    targets = {item["target"] for item in report["comparisons"]}

    assert "Hermes-memory target" in targets
    assert "Cursor-code target" in targets
    assert "Codex-code target" in targets
