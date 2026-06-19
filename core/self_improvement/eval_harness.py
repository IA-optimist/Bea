"""Deterministic agent evaluation harness.

Frozen tasks, frozen scoring, no external model calls.
This is the reproducible PR/self-improvement harness, not a smoke threshold.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from core.self_improvement.benchmark_suite import BenchmarkResult, get_benchmark_suite


@dataclass(frozen=True)
class EvalTask:
    task_id: str
    scenario_id: str
    mission_result: dict[str, object]


@dataclass(frozen=True)
class EvalTaskResult:
    task_id: str
    scenario_id: str
    benchmark: BenchmarkResult

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class AgentEvalReport:
    run_id: str
    timestamp: float
    methodology: str
    total: int
    passed: int
    failed: int
    pass_rate: float
    results: list[EvalTaskResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "methodology": self.methodology,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": round(self.pass_rate, 3),
            "results": [r.to_dict() for r in self.results],
        }


_FIXED_TRACE_ID = "tr-eval-fixed"
_FIXED_TIMESTAMP = 0.0
_RUN_ID = "bea-agent-harness-v1"
_METHODOLOGY = "frozen_tasks_and_deterministic_scoring"


def _mission_result(status: str, summary: str, duration_seconds: float = 12.5) -> dict[str, object]:
    return {
        "status": status,
        "result_envelope": {
            "trace_id": _FIXED_TRACE_ID,
            "status": status,
            "agent_outputs": [
                {
                    "agent_name": "bea-eval",
                    "status": "SUCCESS" if status != "FAILED" else "FAILURE",
                    "output_text": summary,
                }
            ],
            "metrics": {"duration_seconds": duration_seconds},
        },
        "decision_trace": {"trace_id": _FIXED_TRACE_ID},
    }


def build_frozen_eval_tasks() -> list[EvalTask]:
    """Return the frozen evaluation tasks in stable order."""
    return [
        EvalTask("eval-simple-answer", "simple_answer", _mission_result("COMPLETED", "Simple factual answer")),
        EvalTask("eval-reasoning", "multi_step_reasoning", _mission_result("COMPLETED", "Business reasoning summary")),
        EvalTask("eval-web-research", "web_research", _mission_result("COMPLETED", "Research results")),
        EvalTask("eval-trace", "trace_continuity", _mission_result("COMPLETED", "Trace continuity proof")),
        EvalTask("eval-failure", "failure_handling", _mission_result("FAILED", "Intentional failure path", duration_seconds=2.0)),
        EvalTask("eval-policy", "policy_negative_roi", _mission_result("COMPLETED", "Policy check passed")),
        EvalTask("eval-budget", "budget_respect", _mission_result("COMPLETED", "Budget respected", duration_seconds=45.0)),
        EvalTask("eval-envelope", "envelope_structure", _mission_result("COMPLETED", "Envelope shape verified")),
    ]


def run_agent_harness() -> AgentEvalReport:
    """Run the frozen harness and return a deterministic report."""
    suite = get_benchmark_suite()
    tasks = build_frozen_eval_tasks()
    results: list[EvalTaskResult] = []
    passed = 0

    for task in tasks:
        scenario = suite.get_scenario(task.scenario_id)
        if scenario is None:
            raise KeyError(f"Unknown benchmark scenario: {task.scenario_id}")
        benchmark = suite.evaluate_result(scenario, task.mission_result)
        if benchmark.passed:
            passed += 1
        results.append(
            EvalTaskResult(
                task_id=task.task_id,
                scenario_id=task.scenario_id,
                benchmark=benchmark,
            )
        )

    total = len(results)
    failed = total - passed
    pass_rate = passed / total if total else 0.0
    return AgentEvalReport(
        run_id=_RUN_ID,
        timestamp=_FIXED_TIMESTAMP,
        methodology=_METHODOLOGY,
        total=total,
        passed=passed,
        failed=failed,
        pass_rate=pass_rate,
        results=results,
    )
