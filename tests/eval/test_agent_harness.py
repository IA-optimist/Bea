from __future__ import annotations


def test_agent_harness_is_deterministic() -> None:
    from core.self_improvement.eval_harness import run_agent_harness

    first = run_agent_harness().to_dict()
    second = run_agent_harness().to_dict()

    assert first == second
    assert first["run_id"] == "bea-agent-harness-v1"
    assert first["timestamp"] == 0.0
    assert first["methodology"] == "frozen_tasks_and_deterministic_scoring"
    assert first["total"] == 8
    assert first["passed"] == 8
    assert first["failed"] == 0
    assert first["pass_rate"] == 1.0


def test_agent_harness_covers_expected_scenarios() -> None:
    from core.self_improvement.eval_harness import build_frozen_eval_tasks

    task_ids = [task.task_id for task in build_frozen_eval_tasks()]

    assert task_ids == [
        "eval-simple-answer",
        "eval-reasoning",
        "eval-web-research",
        "eval-trace",
        "eval-failure",
        "eval-policy",
        "eval-budget",
        "eval-envelope",
    ]
