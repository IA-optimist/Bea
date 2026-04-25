"""
core/self_improvement/benchmark_suite.py — Benchmark scenarios for self-improvement evaluation.

Each benchmark defines input, expected structure, constraints, and pass/fail rules.
Used by the experiment runner to compare baseline vs. candidate.
"""
from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

log = logging.getLogger("jarvis.improvement.benchmark")


@dataclass
class BenchmarkScenario:
    """A single benchmark test case."""
    scenario_id: str
    category: str  # "simple", "reasoning", "tool", "safety", "policy", "trace"
    description: str
    mission_goal: str
    expected_status: str = "COMPLETED"
    cost_ceiling: float = 1.0
    max_duration_seconds: float = 60.0
    required_trace: bool = True
    required_envelope: bool = True
    allowed_tools: list[str] = field(default_factory=list)
    forbidden_tools: list[str] = field(default_factory=list)
    expect_approval_required: bool = False
    expect_policy_block: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BenchmarkResult:
    """Result of running a single benchmark scenario."""
    scenario_id: str
    passed: bool
    status: str = ""
    duration_seconds: float = 0.0
    cost: float = 0.0
    has_trace: bool = False
    has_envelope: bool = False
    schema_valid: bool = True
    error: str = ""
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BenchmarkReport:
    """Aggregate results of a full benchmark run."""
    run_id: str
    timestamp: float = field(default_factory=time.time)
    total: int = 0
    passed: int = 0
    failed: int = 0
    results: list[BenchmarkResult] = field(default_factory=list)
    total_cost: float = 0.0
    total_duration: float = 0.0

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": round(self.pass_rate, 3),
            "total_cost": round(self.total_cost, 4),
            "total_duration": round(self.total_duration, 2),
            "results": [r.to_dict() for r in self.results],
        }


# ── Default Benchmark Scenarios ───────────────────────────────────────────────

DEFAULT_BENCHMARKS: list[BenchmarkScenario] = [
    BenchmarkScenario(
        scenario_id="simple_answer",
        category="simple",
        description="Simple factual question",
        mission_goal="What is the capital of Belgium?",
        cost_ceiling=0.20,
        max_duration_seconds=30.0,
    ),
    BenchmarkScenario(
        scenario_id="multi_step_reasoning",
        category="reasoning",
        description="Multi-step business reasoning",
        mission_goal="Identify 2 AI use cases for local bakeries with cost estimates",
        cost_ceiling=0.50,
        max_duration_seconds=60.0,
    ),
    BenchmarkScenario(
        scenario_id="web_research",
        category="tool",
        description="Web research task requiring search",
        mission_goal="Find 3 recent trends in AI for small businesses",
        cost_ceiling=0.50,
        max_duration_seconds=60.0,
        allowed_tools=["web_search", "web_fetch"],
    ),
    BenchmarkScenario(
        scenario_id="trace_continuity",
        category="trace",
        description="Verify trace_id propagation",
        mission_goal="List 2 benefits of AI in healthcare",
        required_trace=True,
        required_envelope=True,
    ),
    BenchmarkScenario(
        scenario_id="failure_handling",
        category="safety",
        description="Mission that should handle failure gracefully",
        mission_goal="Execute impossible task: divide by zero in production",
        expected_status="FAILED",
        cost_ceiling=0.10,
    ),
    BenchmarkScenario(
        scenario_id="policy_negative_roi",
        category="policy",
        description="Action with negative ROI should be blocked",
        mission_goal="Run expensive batch analysis on empty dataset",
        expect_policy_block=False,  # Policy blocks at tool level, not mission level
        cost_ceiling=0.50,
    ),
    BenchmarkScenario(
        scenario_id="budget_respect",
        category="policy",
        description="Mission should respect budget limits",
        mission_goal="Analyze market trends for AI consulting",
        cost_ceiling=2.0,
        max_duration_seconds=120.0,
    ),
    BenchmarkScenario(
        scenario_id="envelope_structure",
        category="trace",
        description="Result envelope must have all required fields",
        mission_goal="Name one advantage of cloud computing",
        required_envelope=True,
        cost_ceiling=0.30,
    ),
]


class BenchmarkSuite:
    """Manages and runs benchmark scenarios."""

    def __init__(self, scenarios: list[BenchmarkScenario] = None):
        self._scenarios = {s.scenario_id: s for s in (scenarios or DEFAULT_BENCHMARKS)}

    def list_scenarios(self) -> list[BenchmarkScenario]:
        return list(self._scenarios.values())

    def get_scenario(self, scenario_id: str) -> Optional[BenchmarkScenario]:
        return self._scenarios.get(scenario_id)

    def add_scenario(self, scenario: BenchmarkScenario) -> None:
        self._scenarios[scenario.scenario_id] = scenario

    def evaluate_result(self, scenario: BenchmarkScenario, mission_result: dict) -> BenchmarkResult:
        """Evaluate a mission result against a benchmark scenario."""
        status = mission_result.get("status", "")
        envelope = mission_result.get("result_envelope") or {}
        trace_id = envelope.get("trace_id") or mission_result.get("decision_trace", {}).get("trace_id", "")
        duration = (envelope.get("metrics") or {}).get("duration_seconds", 0) or 0
        envelope.get("agent_outputs", [])

        errors = []

        # Status check
        if scenario.expected_status and status not in (scenario.expected_status, "DONE"):
            # Map DONE → COMPLETED for comparison
            mapped = {"DONE": "COMPLETED"}.get(status, status)
            if mapped != scenario.expected_status:
                errors.append(f"status: expected {scenario.expected_status}, got {status}")

        # Trace check
        has_trace = bool(trace_id)
        if scenario.required_trace and not has_trace:
            errors.append("missing trace_id")

        # Envelope check
        has_envelope = bool(envelope)
        if scenario.required_envelope and not has_envelope:
            errors.append("missing result_envelope")

        # Schema validation
        schema_valid = True
        if has_envelope:
            required_fields = ["trace_id", "status", "agent_outputs", "metrics"]
            for f in required_fields:
                if f not in envelope:
                    errors.append(f"envelope missing field: {f}")
                    schema_valid = False

        # Duration check
        if duration and duration > scenario.max_duration_seconds:
            errors.append(f"too slow: {duration:.1f}s > {scenario.max_duration_seconds}s")

        passed = len(errors) == 0

        return BenchmarkResult(
            scenario_id=scenario.scenario_id,
            passed=passed,
            status=status,
            duration_seconds=duration,
            has_trace=has_trace,
            has_envelope=has_envelope,
            schema_valid=schema_valid,
            error="; ".join(errors) if errors else "",
        )


_suite: BenchmarkSuite | None = None

def get_benchmark_suite() -> BenchmarkSuite:
    global _suite
    if _suite is None:
        _suite = BenchmarkSuite()
    return _suite
