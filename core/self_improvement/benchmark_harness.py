"""Deterministic component benchmarks for Bea.

This harness measures the local strengths that matter for the requested
comparison:
  - memory recall and cleanup
  - coding-agent quality gates

It does not pretend to run external products. Instead it compares Bea against
explicit target thresholds that reflect the dimensions where Hermes/Cursor/Codex
are typically expected to be strong.
"""
from __future__ import annotations

import tempfile
import time
from datetime import datetime, timedelta
from dataclasses import asdict, dataclass, field
from pathlib import Path

from core.coding_agent.quality_gate import build_quality_gate_plan
from core.memory_facade import MemoryFacade
from memory.vault_memory import VaultEntry, VaultMemory


@dataclass(frozen=True)
class ComponentScore:
    component: str
    score: float
    passed: bool
    metrics: dict[str, float | int | bool]
    details: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkComparison:
    target: str
    threshold: float
    score: float
    delta: float
    status: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class BeaBenchmarkReport:
    run_id: str
    timestamp: float
    methodology: str
    external_comparison: bool
    memory: ComponentScore
    coding: ComponentScore
    overall_score: float
    comparisons: list[BenchmarkComparison]

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "methodology": self.methodology,
            "external_comparison": self.external_comparison,
            "memory": self.memory.to_dict(),
            "coding": self.coding.to_dict(),
            "overall_score": round(self.overall_score, 3),
            "comparisons": [c.to_dict() for c in self.comparisons],
        }


TARGET_THRESHOLDS = {
    "hermes_memory": 0.90,
    "cursor_coding": 0.88,
    "codex_coding": 0.92,
}
BENCHMARK_METHOD = "internal_smoke_thresholds"


def _score_memory_facade() -> ComponentScore:
    with tempfile.TemporaryDirectory() as tmpdir:
        facade = MemoryFacade(workspace_dir=tmpdir)
        token = f"bea-benchmark-{int(time.time() * 1000)}"

        store_result = facade.store(
            content=f"Persistent recall token {token}",
            content_type="solution",
            metadata={"mission_id": "benchmark-memory"},
        )
        recall_results = facade.search(token, top_k=3)
        dedup_results = []
        for _ in range(3):
            facade.store("Benchmark duplicate value", content_type="solution")
        dedup_results = facade.search("Benchmark duplicate", top_k=10)
        with tempfile.TemporaryDirectory() as ttl_tmp:
            vm = VaultMemory(vault_path=str((Path(ttl_tmp) / "vault.json")))
            anchor = datetime(2026, 1, 1, 12, 0, 0)
            vm.store(VaultEntry(
                key="ttl-benchmark",
                content="TTL probe",
                metadata={"expires_at": (anchor - timedelta(seconds=1)).isoformat()},
            ))
            cleanup_removed = getattr(vm, "cleanup_expired", lambda **kwargs: 0)(now=anchor)
        health = facade.health()

        metrics = {
            "fts_hit": any(r.source == "fts_recall" for r in recall_results),
            "recall_count": len(recall_results),
            "dedup_count": len(dedup_results),
            "cleanup_removed": cleanup_removed,
            "fts_available": bool(health.get("fts_recall", {}).get("available")),
            "store_ok": bool(store_result.get("ok")),
        }

        score_parts = [
            1.0 if metrics["store_ok"] else 0.0,
            1.0 if metrics["fts_hit"] else 0.0,
            1.0 if metrics["dedup_count"] == 1 else 0.0,
            1.0 if metrics["cleanup_removed"] >= 1 else 0.0,
            1.0 if metrics["fts_available"] else 0.0,
        ]
        score = sum(score_parts) / len(score_parts)
        passed = score >= 0.8

        return ComponentScore(
            component="memory",
            score=round(score, 3),
            passed=passed,
            metrics=metrics,
            details={
                    "health": health,
                    "fts_path": str(getattr(facade, "_fts_path", None) or ""),
                },
        )


def _plan_has(plan, names: set[str]) -> bool:
    present = {cmd.name for cmd in plan.commands}
    return names.issubset(present)


def _score_coding_agent() -> ComponentScore:
    scenarios = [
        (
            ["core/memory_facade.py"],
            {"python_lint", "python_regression_tests"},
            {"frontend_build", "frontend_e2e", "docker_compose_config"},
        ),
        (
            ["tests/test_memory_facade.py"],
            {"python_targeted_tests", "python_regression_tests", "python_lint"},
            {"frontend_build", "frontend_e2e", "docker_compose_config"},
        ),
        (
            ["frontend/src/pages/Login.tsx"],
            {"frontend_build", "frontend_e2e"},
            {"python_lint", "python_regression_tests"},
        ),
        (
            ["docker-compose.yml", "Caddyfile"],
            {"docker_compose_config"},
            {"frontend_e2e"},
        ),
        (
            ["requirements.txt"],
            {"security_audit"},
            {"frontend_e2e"},
        ),
    ]

    results: list[bool] = []
    scenario_details: list[dict[str, object]] = []
    for changed_files, expected, forbidden in scenarios:
        plan = build_quality_gate_plan(changed_files)
        present = {cmd.name for cmd in plan.commands}
        expected_ok = expected.issubset(present)
        forbidden_ok = forbidden.isdisjoint(present)
        results.append(expected_ok and forbidden_ok)
        scenario_details.append(
            {
                "changed_files": changed_files,
                "expected": sorted(expected),
                "present": sorted(present),
                "passed": expected_ok and forbidden_ok,
            }
        )

    score = sum(1.0 for ok in results if ok) / len(results)
    metrics = {
        "scenario_count": len(results),
        "passed_scenarios": sum(1 for ok in results if ok),
    }
    return ComponentScore(
        component="coding_agent",
        score=round(score, 3),
        passed=score >= 0.8,
        metrics=metrics,
        details={"scenarios": scenario_details},
    )


def compare_to_target(score: float, threshold: float) -> BenchmarkComparison:
    delta = round(score - threshold, 3)
    status = "above" if delta >= 0 else "below"
    return BenchmarkComparison(
        target="",
        threshold=threshold,
        score=round(score, 3),
        delta=delta,
        status=status,
    )


def run_bea_benchmark() -> BeaBenchmarkReport:
    memory = _score_memory_facade()
    coding = _score_coding_agent()
    overall = round(memory.score * 0.55 + coding.score * 0.45, 3)
    comparisons = [
        BenchmarkComparison(
            target="Hermes-memory target",
            threshold=TARGET_THRESHOLDS["hermes_memory"],
            score=memory.score,
            delta=round(memory.score - TARGET_THRESHOLDS["hermes_memory"], 3),
            status="above" if memory.score >= TARGET_THRESHOLDS["hermes_memory"] else "below",
        ),
        BenchmarkComparison(
            target="Cursor-code target",
            threshold=TARGET_THRESHOLDS["cursor_coding"],
            score=coding.score,
            delta=round(coding.score - TARGET_THRESHOLDS["cursor_coding"], 3),
            status="above" if coding.score >= TARGET_THRESHOLDS["cursor_coding"] else "below",
        ),
        BenchmarkComparison(
            target="Codex-code target",
            threshold=TARGET_THRESHOLDS["codex_coding"],
            score=coding.score,
            delta=round(coding.score - TARGET_THRESHOLDS["codex_coding"], 3),
            status="above" if coding.score >= TARGET_THRESHOLDS["codex_coding"] else "below",
        ),
    ]
    return BeaBenchmarkReport(
        run_id=f"bea-bench-{int(time.time())}",
        timestamp=time.time(),
        methodology=BENCHMARK_METHOD,
        external_comparison=False,
        memory=memory,
        coding=coding,
        overall_score=overall,
        comparisons=comparisons,
    )
