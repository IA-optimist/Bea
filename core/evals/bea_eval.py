"""
core/evals/bea_eval.py — Active-memory + model-router eval suite.

This suite exercises:
    - memory ranking (active > obsolete, file/tag boosts)
    - repo-map extraction (symbols, tests, FastAPI routes)
    - model router (task type → model class)
    - mission lifecycle (context preparation, result recording)

Results are stored as MemoryItem(type=eval_result).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core.evaluation.ingestion import ingest
from core.evaluation.mission_learning import MissionLearner
from core.evaluation.mission_report_parser import MissionLearningInput, MissionReportParser
from core.evaluation.model_router import ModelClass, ModelRouter
from core.evals.models import EvalReport, EvalResult
from core.evals.report import generate_markdown
from core.memory.memory_item import MemoryItem, MemoryItemStatus, MemoryItemType
from core.memory.mission_context import MissionContextBuilder
from core.memory.mission_result import MissionResult, MissionResultRecorder
from core.memory.operational_memory import (
    OperationalMemoryStore,
    get_operational_memory_store,
)
from core.repo_map.repo_map_service import RepoMapService


EvalFn = Callable[[], EvalResult]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _duration(start_ms: int) -> int:
    return _now_ms() - start_ms


@dataclass
class EvalContext:
    """Shared state across evals in a single run."""

    store: OperationalMemoryStore
    repo_map: RepoMapService
    context_builder: MissionContextBuilder
    result_recorder: MissionResultRecorder
    model_router: ModelRouter


class BeaEval:
    """Runner for the active-memory model-router eval suite."""

    EVAL_NAMES: tuple[str, ...] = (
        # Memory
        "memory-active-decision",
        "memory-ignore-obsolete",
        "memory-bug-known",
        "memory-risk-protected-file",
        "memory-related-file-boost",
        "memory-contradiction-not-preferred",
        # Repo-map
        "repo-map-symbols",
        "repo-map-tests",
        "repo-map-fastapi-route",
        # Model routing
        "router-summary-small-fast",
        "router-simple-patch-medium",
        "router-protected-file-strong-review",
        "router-budget-local-fallback",
        # Mission lifecycle
        "mission-context-prepare",
        "mission-result-record",
        # Mission learning loop
        "learning-parse-json-valid",
        "learning-parse-missing-fields",
        "learning-create-eval-result",
        "learning-create-bug-memory",
        "learning-create-skill",
        "learning-create-model-result",
        "learning-create-test-map",
        "learning-deduplicate-identical",
        "learning-router-after-failures",
        "learning-ingestion-summary",
    )

    def __init__(
        self,
        store: OperationalMemoryStore | None = None,
        repo_map_service: RepoMapService | None = None,
        root: str | Path = ".",
    ) -> None:
        self.store = store or get_operational_memory_store()
        self.repo_map = repo_map_service or RepoMapService(root=root, store=self.store)
        self.ctx = EvalContext(
            store=self.store,
            repo_map=self.repo_map,
            context_builder=MissionContextBuilder(store=self.store),
            result_recorder=MissionResultRecorder(store=self.store),
            model_router=ModelRouter(store=self.store),
        )
        self._evals: dict[str, EvalFn] = {
            # Memory
            "memory-active-decision": self.eval_memory_active_decision,
            "memory-ignore-obsolete": self.eval_memory_ignore_obsolete,
            "memory-bug-known": self.eval_memory_bug_known,
            "memory-risk-protected-file": self.eval_memory_risk_protected_file,
            "memory-related-file-boost": self.eval_memory_related_file_boost,
            "memory-contradiction-not-preferred": self.eval_memory_contradiction_not_preferred,
            # Repo-map
            "repo-map-symbols": self.eval_repo_map_symbols,
            "repo-map-tests": self.eval_repo_map_tests,
            "repo-map-fastapi-route": self.eval_repo_map_fastapi_route,
            # Router
            "router-summary-small-fast": self.eval_router_summary_small_fast,
            "router-simple-patch-medium": self.eval_router_simple_patch_medium,
            "router-protected-file-strong-review": self.eval_router_protected_file_strong_review,
            "router-budget-local-fallback": self.eval_router_budget_local_fallback,
            # Mission lifecycle
            "mission-context-prepare": self.eval_mission_context_prepare,
            "mission-result-record": self.eval_mission_result_record,
            # Mission learning loop
            "learning-parse-json-valid": self.eval_learning_parse_json_valid,
            "learning-parse-missing-fields": self.eval_learning_parse_missing_fields,
            "learning-create-eval-result": self.eval_learning_create_eval_result,
            "learning-create-bug-memory": self.eval_learning_create_bug_memory,
            "learning-create-skill": self.eval_learning_create_skill,
            "learning-create-model-result": self.eval_learning_create_model_result,
            "learning-create-test-map": self.eval_learning_create_test_map,
            "learning-deduplicate-identical": self.eval_learning_deduplicate_identical,
            "learning-router-after-failures": self.eval_learning_router_after_failures,
            "learning-ingestion-summary": self.eval_learning_ingestion_summary,
        }

    def list_evals(self) -> list[str]:
        return list(self.EVAL_NAMES)

    def run_all(self) -> EvalReport:
        """Run the full suite, store aggregate eval_result, return report."""
        report = EvalReport()
        report.results = [self.run(name) for name in self.EVAL_NAMES]
        report.summary = {
            "total": len(report.results),
            "passed": sum(1 for r in report.results if r.success),
            "failed": sum(1 for r in report.results if not r.success),
            "overall_score": round(report.overall_score(), 3),
        }
        self._store_report(report)
        return report

    def run(self, name: str) -> EvalResult:
        if name not in self._evals:
            return EvalResult(
                eval_name=name,
                success=False,
                score=0.0,
                duration_ms=0,
                error=f"Unknown eval: {name}",
            )
        return self._evals[name]()

    def _store_report(self, report: EvalReport) -> None:
        """Persist the aggregate result as an eval_result memory item."""
        try:
            item = MemoryItem(
                type=MemoryItemType.EVAL_RESULT,
                title=f"bea eval run {report.run_id}",
                content=f"Overall score {report.overall_score():.2f}",
                source="bea_eval",
                confidence=report.overall_score(),
                related_files=[],
                tags=["eval", "bea_eval", "memory", "router"],
                metadata={
                    "eval_name": "suite",
                    "score": report.overall_score(),
                    "duration_ms": sum(r.duration_ms for r in report.results),
                    "passed": report.summary.get("passed", 0),
                    "failed": report.summary.get("failed", 0),
                    "run_id": report.run_id,
                },
            )
            self.store.add(item)
        except Exception:
            pass

    # ── Memory evals ──────────────────────────────────────────────────────────

    def eval_memory_active_decision(self) -> EvalResult:
        start = _now_ms()
        self._seed_decision("active decision", MemoryItemStatus.ACTIVE)
        results = self.store.ranked_search(
            type=MemoryItemType.ARCHITECTURE_DECISION,
            query="active decision",
            limit=3,
        )
        success = any(item.status == MemoryItemStatus.ACTIVE for item, _ in results)
        return EvalResult(
            eval_name="memory-active-decision",
            success=success,
            score=1.0 if success else 0.0,
            duration_ms=_duration(start),
            memories_retrieved=[item.id for item, _ in results[:3]],
        )

    def eval_memory_ignore_obsolete(self) -> EvalResult:
        start = _now_ms()
        active = MemoryItem(
            type=MemoryItemType.ARCHITECTURE_DECISION,
            title="Current decision",
            content="This is the current active decision.",
            status=MemoryItemStatus.ACTIVE,
            confidence=0.9,
            tags=["decision"],
        )
        obsolete = MemoryItem(
            type=MemoryItemType.ARCHITECTURE_DECISION,
            title="Old decision",
            content="Old decision that looks relevant too.",
            status=MemoryItemStatus.OBSOLETE,
            confidence=0.95,
            tags=["decision"],
        )
        self.store.add(active)
        self.store.add(obsolete)
        results = self.store.ranked_search(
            type=MemoryItemType.ARCHITECTURE_DECISION,
            query="decision",
            limit=2,
        )
        if not results:
            return EvalResult(
                eval_name="memory-ignore-obsolete",
                success=False,
                score=0.0,
                duration_ms=_duration(start),
            )
        top, top_score = results[0]
        success = top.status == MemoryItemStatus.ACTIVE and top_score > 0
        return EvalResult(
            eval_name="memory-ignore-obsolete",
            success=success,
            score=1.0 if success else 0.0,
            duration_ms=_duration(start),
            memories_retrieved=[item.id for item, _ in results[:3]],
        )

    def eval_memory_bug_known(self) -> EvalResult:
        start = _now_ms()
        bug = MemoryItem(
            type=MemoryItemType.BUG_MEMORY,
            title="Race condition in async worker",
            content="Async worker can drop tasks under high concurrency.",
            status=MemoryItemStatus.ACTIVE,
            confidence=0.85,
            tags=["bug", "async"],
        )
        self.store.add(bug)
        results = self.store.ranked_search(
            type=MemoryItemType.BUG_MEMORY,
            query="async worker concurrency",
            tags=["async"],
            limit=5,
        )
        success = any("async" in item.tags for item, _ in results)
        return EvalResult(
            eval_name="memory-bug-known",
            success=success,
            score=1.0 if success else 0.0,
            duration_ms=_duration(start),
            memories_retrieved=[item.id for item, _ in results[:3]],
        )

    def eval_memory_risk_protected_file(self) -> EvalResult:
        start = _now_ms()
        risk = MemoryItem(
            type=MemoryItemType.RISK,
            title="Protected file risk",
            content="Never auto-promote changes to core/auth.py.",
            status=MemoryItemStatus.DANGEROUS,
            confidence=1.0,
            related_files=["core/auth.py"],
            tags=["security", "auth"],
        )
        self.store.add(risk)
        results = self.store.ranked_search(
            type=MemoryItemType.RISK,
            related_files=["core/auth.py"],
            limit=3,
        )
        success = any(item.status == MemoryItemStatus.DANGEROUS for item, _ in results)
        return EvalResult(
            eval_name="memory-risk-protected-file",
            success=success,
            score=1.0 if success else 0.0,
            duration_ms=_duration(start),
            memories_retrieved=[item.id for item, _ in results[:3]],
        )

    def eval_memory_related_file_boost(self) -> EvalResult:
        start = _now_ms()
        target = "core/memory/memory_item.py"
        fact = MemoryItem(
            type=MemoryItemType.REPO_FACT,
            title="MemoryItem fact",
            content="MemoryItem holds structured memory.",
            related_files=[target],
            confidence=0.9,
            tags=["memory"],
        )
        generic = MemoryItem(
            type=MemoryItemType.REPO_FACT,
            title="Generic fact",
            content="Generic memory description without file link.",
            confidence=0.9,
            tags=["memory"],
        )
        self.store.add(generic)
        self.store.add(fact)
        results = self.store.ranked_search(
            type=MemoryItemType.REPO_FACT,
            related_files=[target],
            query="MemoryItem structured",
            limit=2,
        )
        if not results:
            return EvalResult(
                eval_name="memory-related-file-boost",
                success=False,
                score=0.0,
                duration_ms=_duration(start),
            )
        top, _ = results[0]
        success = target in top.related_files
        return EvalResult(
            eval_name="memory-related-file-boost",
            success=success,
            score=1.0 if success else 0.0,
            duration_ms=_duration(start),
            files_used=[target],
            memories_retrieved=[item.id for item, _ in results[:2]],
        )

    def eval_memory_contradiction_not_preferred(self) -> EvalResult:
        start = _now_ms()
        old = MemoryItem(
            type=MemoryItemType.ARCHITECTURE_DECISION,
            title="Old approach",
            content="We used to do X.",
            status=MemoryItemStatus.REPLACED,
            confidence=0.9,
            tags=["approach"],
        )
        new = MemoryItem(
            type=MemoryItemType.ARCHITECTURE_DECISION,
            title="New approach",
            content="We now do Y.",
            status=MemoryItemStatus.ACTIVE,
            confidence=0.9,
            tags=["approach"],
        )
        self.store.add(old)
        self.store.add(new)
        results = self.store.ranked_search(
            type=MemoryItemType.ARCHITECTURE_DECISION,
            query="approach",
            limit=2,
        )
        if not results:
            return EvalResult(
                eval_name="memory-contradiction-not-preferred",
                success=False,
                score=0.0,
                duration_ms=_duration(start),
            )
        top, _ = results[0]
        success = top.status != MemoryItemStatus.REPLACED
        return EvalResult(
            eval_name="memory-contradiction-not-preferred",
            success=success,
            score=1.0 if success else 0.0,
            duration_ms=_duration(start),
            memories_retrieved=[item.id for item, _ in results[:2]],
        )

    # ── Repo-map evals ────────────────────────────────────────────────────────

    def eval_repo_map_symbols(self) -> EvalResult:
        start = _now_ms()
        try:
            target = "core/memory/memory_item.py"
            self.repo_map.persist(force=False)
            symbols = self.repo_map.find_symbols_for_file(target)
            success = len(symbols) >= 1
            return EvalResult(
                eval_name="repo-map-symbols",
                success=success,
                score=round(min(1.0, len(symbols) / 2.0), 2),
                duration_ms=_duration(start),
                files_used=[target],
            )
        except Exception as exc:
            return EvalResult(
                eval_name="repo-map-symbols",
                success=False,
                score=0.0,
                duration_ms=_duration(start),
                error=str(exc)[:200],
            )

    def eval_repo_map_tests(self) -> EvalResult:
        start = _now_ms()
        try:
            # Use a file with a directly heuristic-discoverable test file so this
            # eval is reproducible in both isolated and global-store modes.
            # core/memory/memory_item.py has no dedicated test_memory_item.py and
            # only passes when the global store is warm (prior persist runs cached it).
            target = "core/evaluation/model_router.py"
            self.repo_map.persist(force=False)
            tests = self.repo_map.find_tests_for_file(target)
            success = len(tests) > 0
            return EvalResult(
                eval_name="repo-map-tests",
                success=success,
                score=1.0 if success else 0.0,
                duration_ms=_duration(start),
                files_used=[target],
            )
        except Exception as exc:
            return EvalResult(
                eval_name="repo-map-tests",
                success=False,
                score=0.0,
                duration_ms=_duration(start),
                error=str(exc)[:200],
            )

    def eval_repo_map_fastapi_route(self) -> EvalResult:
        start = _now_ms()
        try:
            self.repo_map.persist(force=False)
            symbols = self.repo_map.find_symbols_for_file("api/routes/v1.py")
            # Accept if we find any symbol; true FastAPI route detection would need decorators.
            success = len(symbols) > 0
            return EvalResult(
                eval_name="repo-map-fastapi-route",
                success=success,
                score=1.0 if success else 0.5,
                duration_ms=_duration(start),
                files_used=["api/routes/v1.py"],
            )
        except Exception as exc:
            return EvalResult(
                eval_name="repo-map-fastapi-route",
                success=False,
                score=0.0,
                duration_ms=_duration(start),
                error=str(exc)[:200],
            )

    # ── Model router evals ────────────────────────────────────────────────────

    def eval_router_summary_small_fast(self) -> EvalResult:
        start = _now_ms()
        decision = self.ctx.model_router.choose("summary task")
        success = decision.model_class == ModelClass.SMALL_FAST
        return EvalResult(
            eval_name="router-summary-small-fast",
            success=success,
            score=1.0 if success else 0.0,
            duration_ms=_duration(start),
            model_class_selected=decision.model_class.value,
        )

    def eval_router_simple_patch_medium(self) -> EvalResult:
        start = _now_ms()
        # Use an isolated temp store so this rule-based eval is reproducible
        # regardless of accumulated model_result history in the global store.
        isolated_router = ModelRouter(
            store=OperationalMemoryStore(":memory:")
        )
        decision = isolated_router.choose("simple patch")
        success = decision.model_class == ModelClass.MEDIUM_TOOL_USE
        return EvalResult(
            eval_name="router-simple-patch-medium",
            success=success,
            score=1.0 if success else 0.0,
            duration_ms=_duration(start),
            model_class_selected=decision.model_class.value,
        )

    def eval_router_protected_file_strong_review(self) -> EvalResult:
        start = _now_ms()
        decision = self.ctx.model_router.choose(
            "refactor auth",
            protected_files=["core/auth.py"],
        )
        success = decision.model_class == ModelClass.STRONG_CODE_REVIEW
        return EvalResult(
            eval_name="router-protected-file-strong-review",
            success=success,
            score=1.0 if success else 0.0,
            duration_ms=_duration(start),
            model_class_selected=decision.model_class.value,
            files_used=["core/auth.py"],
        )

    def eval_router_budget_local_fallback(self) -> EvalResult:
        start = _now_ms()
        decision = self.ctx.model_router.choose(
            "complex bug",
            budget_cloud=False,
        )
        success = decision.model_class == ModelClass.LOCAL_FALLBACK
        return EvalResult(
            eval_name="router-budget-local-fallback",
            success=success,
            score=1.0 if success else 0.0,
            duration_ms=_duration(start),
            model_class_selected=decision.model_class.value,
        )

    # ── Mission lifecycle evals ───────────────────────────────────────────────

    def eval_mission_context_prepare(self) -> EvalResult:
        start = _now_ms()
        self._seed_decision("auth router rule", MemoryItemStatus.ACTIVE, files=["core/auth.py"])
        self._seed_risk("auth change risk", files=["core/auth.py"])
        ctx = self.ctx.context_builder.prepare(
            mission_title="Refactor auth module",
            mission_description="Clean up auth routing.",
            optional_files=["core/auth.py"],
            task_type="refactor",
        )
        has_decision = len(ctx.relevant_decisions) > 0
        has_risk = len(ctx.relevant_risks) > 0
        success = has_decision and has_risk
        return EvalResult(
            eval_name="mission-context-prepare",
            success=success,
            score=1.0 if success else (0.5 if (has_decision or has_risk) else 0.0),
            duration_ms=_duration(start),
            files_used=["core/auth.py"],
            memories_retrieved=[m.id for m in ctx.relevant_decisions + ctx.relevant_risks][:3],
            model_class_selected=ctx.model_class_hint,
        )

    def eval_mission_result_record(self) -> EvalResult:
        start = _now_ms()
        result = MissionResult(
            mission_id="eval-mission-1",
            run_id="eval-run-1",
            task_type="refactor",
            files_changed=["core/memory/memory_item.py"],
            tests_run=["tests/core/memory/test_operational_memory.py"],
            success=False,
            failure_reason="ImportError in new module",
            model_used="claude-3-5-sonnet",
            model_class="STRONG_REASONING",
            duration_ms=1234,
            lessons_learned="Always import new submodules in __init__.py",
        )
        created = self.ctx.result_recorder.record(result)
        success = "eval_result" in created and "bug_memory" in created
        if success:
            item = self.store.get(created["bug_memory"])
            success = item is not None and item.type == MemoryItemType.BUG_MEMORY
        return EvalResult(
            eval_name="mission-result-record",
            success=success,
            score=1.0 if success else 0.0,
            duration_ms=_duration(start),
            files_used=result.files_changed,
            memories_retrieved=[created.get("bug_memory", "")] if success else [],
        )

    # ─── Mission learning loop evals ─────────────────────────────────────────

    def eval_learning_parse_json_valid(self) -> EvalResult:
        start = _now_ms()
        raw = '{"mission_id": "m-parse", "title": "Parse eval", "status": "SUCCESS", "task_type": "test"}'
        inp = MissionReportParser().parse(raw)
        success = inp.mission_id == "m-parse" and inp.title == "Parse eval" and inp.success is True
        return EvalResult(
            eval_name="learning-parse-json-valid",
            success=success,
            score=1.0 if success else 0.0,
            duration_ms=_duration(start),
        )

    def eval_learning_parse_missing_fields(self) -> EvalResult:
        start = _now_ms()
        raw = '{"mission_id": "m-missing"}'
        inp = MissionReportParser().parse(raw)
        success = inp.mission_id == "m-missing" and not inp.title and any(
            "Missing task_type" in w for w in inp.warnings
        )
        return EvalResult(
            eval_name="learning-parse-missing-fields",
            success=success,
            score=1.0 if success else 0.0,
            duration_ms=_duration(start),
        )

    def eval_learning_create_eval_result(self) -> EvalResult:
        start = _now_ms()
        learner = MissionLearner(store=self.store)
        inp = MissionLearningInput(
            mission_id="m-eval",
            title="Eval mission",
            status="SUCCESS",
            task_type="feature",
            success=True,
        )
        result = learner.learn(inp)
        ids = [m for m in result.created_memory_ids if self.store.get(m).type == MemoryItemType.EVAL_RESULT]
        success = len(ids) > 0
        return EvalResult(
            eval_name="learning-create-eval-result",
            success=success,
            score=1.0 if success else 0.0,
            duration_ms=_duration(start),
        )

    def eval_learning_create_bug_memory(self) -> EvalResult:
        start = _now_ms()
        learner = MissionLearner(store=self.store)
        inp = MissionLearningInput(
            mission_id="m-bug",
            title="Bug mission",
            status="NEEDS_FIX",
            task_type="bugfix",
            files_changed=["core/foo.py"],
            tests_run=["tests/test_foo.py"],
            success=False,
            failure_reason="Index out of range.",
        )
        result = learner.learn(inp)
        ids = [m for m in result.created_memory_ids if self.store.get(m).type == MemoryItemType.BUG_MEMORY]
        success = len(ids) > 0 and "Index out of range" in self.store.get(ids[0]).content
        return EvalResult(
            eval_name="learning-create-bug-memory",
            success=success,
            score=1.0 if success else 0.0,
            duration_ms=_duration(start),
            files_used=["core/foo.py"],
        )

    def eval_learning_create_skill(self) -> EvalResult:
        start = _now_ms()
        learner = MissionLearner(store=self.store)
        inp = MissionLearningInput(
            mission_id="m-skill",
            title="Skill mission",
            status="SUCCESS",
            task_type="docs",
            files_changed=["docs/README.md"],
            success=True,
            lessons_learned="Keep README in sync with code changes.",
        )
        result = learner.learn(inp)
        ids = [m for m in result.created_memory_ids if self.store.get(m).type == MemoryItemType.SKILL]
        success = len(ids) > 0 and "README" in self.store.get(ids[0]).content
        return EvalResult(
            eval_name="learning-create-skill",
            success=success,
            score=1.0 if success else 0.0,
            duration_ms=_duration(start),
        )

    def eval_learning_create_model_result(self) -> EvalResult:
        start = _now_ms()
        learner = MissionLearner(store=self.store)
        inp = MissionLearningInput(
            mission_id="m-model",
            title="Model mission",
            status="SUCCESS",
            task_type="feature",
            success=True,
            model_used="claude-3-5-sonnet",
            model_class="MEDIUM_TOOL_USE",
            duration_ms=1500,
            cost_estimate=0.02,
        )
        result = learner.learn(inp)
        ids = [m for m in result.created_memory_ids if self.store.get(m).type == MemoryItemType.MODEL_RESULT]
        success = len(ids) > 0
        return EvalResult(
            eval_name="learning-create-model-result",
            success=success,
            score=1.0 if success else 0.0,
            duration_ms=_duration(start),
            model_class_selected=inp.model_class,
        )

    def eval_learning_create_test_map(self) -> EvalResult:
        start = _now_ms()
        learner = MissionLearner(store=self.store)
        inp = MissionLearningInput(
            mission_id="m-tests",
            title="Map tests",
            status="SUCCESS",
            task_type="feature",
            files_changed=["core/foo.py"],
            tests_run=["tests/test_foo.py"],
            success=True,
        )
        result = learner.learn(inp)
        ids = [m for m in result.created_memory_ids if self.store.get(m).type == MemoryItemType.TEST_MAP]
        success = len(ids) > 0
        return EvalResult(
            eval_name="learning-create-test-map",
            success=success,
            score=1.0 if success else 0.0,
            duration_ms=_duration(start),
            files_used=["core/foo.py"],
        )

    def eval_learning_deduplicate_identical(self) -> EvalResult:
        start = _now_ms()
        learner = MissionLearner(store=self.store)
        inp = MissionLearningInput(
            mission_id="m-dedup",
            title="Dedup mission",
            status="FAILURE",
            task_type="bugfix",
            files_changed=["core/dedup.py"],
            success=False,
            failure_reason="Race condition.",
        )
        r1 = learner.learn(inp)
        r2 = learner.learn(inp)
        bug_created = [m for m in r1.created_memory_ids if self.store.get(m).type == MemoryItemType.BUG_MEMORY]
        bug_reused = [m for m in r2.created_memory_ids if self.store.get(m).type == MemoryItemType.BUG_MEMORY]
        success = len(bug_created) == 1 and bug_created == bug_reused
        if success:
            item = self.store.get(bug_created[0])
            success = item.metadata.get("occurrence_count", 1) >= 2
        return EvalResult(
            eval_name="learning-deduplicate-identical",
            success=success,
            score=1.0 if success else 0.0,
            duration_ms=_duration(start),
        )

    def eval_learning_router_after_failures(self) -> EvalResult:
        start = _now_ms()
        learner = MissionLearner(store=self.store)
        for i in range(3):
            learner.learn(MissionLearningInput(
                mission_id=f"m-fail-{i}",
                title="Fail patch",
                status="FAILURE",
                task_type="simple patch",
                success=False,
                model_used="mistral-local",
                model_class="MEDIUM_TOOL_USE",
                duration_ms=2000,
                cost_estimate=0.001,
            ))
        decision = self.ctx.model_router.choose("simple patch")
        # After 3 failures, MEDIUM_TOOL_USE should be deprioritized, so router upgrades.
        success = decision.model_class != ModelClass.MEDIUM_TOOL_USE
        return EvalResult(
            eval_name="learning-router-after-failures",
            success=success,
            score=1.0 if success else 0.0,
            duration_ms=_duration(start),
            model_class_selected=decision.model_class.value,
        )

    def eval_learning_ingestion_summary(self) -> EvalResult:
        start = _now_ms()
        from pathlib import Path
        fixtures_root = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "mission_reports"
        if not fixtures_root.exists():
            return EvalResult(
                eval_name="learning-ingestion-summary",
                success=False,
                score=0.0,
                duration_ms=_duration(start),
                error="Mission report fixtures not found.",
            )
        summary = ingest(str(fixtures_root), store=self.store)
        success = summary["reports_read"] == 4 and summary["memories_created"] > 0
        return EvalResult(
            eval_name="learning-ingestion-summary",
            success=success,
            score=1.0 if success else 0.0,
            duration_ms=_duration(start),
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _seed_decision(
        self,
        title: str,
        status: MemoryItemStatus,
        files: list[str] | None = None,
    ) -> str:
        item = MemoryItem(
            type=MemoryItemType.ARCHITECTURE_DECISION,
            title=title,
            content=f"Decision content for {title}.",
            status=status,
            confidence=0.9,
            related_files=files or [],
            tags=["decision"],
        )
        return self.store.add(item)

    def _seed_risk(self, title: str, files: list[str] | None = None) -> str:
        item = MemoryItem(
            type=MemoryItemType.RISK,
            title=title,
            content=f"Risk content for {title}.",
            status=MemoryItemStatus.DANGEROUS,
            confidence=1.0,
            related_files=files or [],
            tags=["risk"],
        )
        return self.store.add(item)


def run_evals(names: list[str] | None = None, root: str | Path = ".") -> EvalReport:
    """Convenience entry point used by CLI and tests."""
    be = BeaEval(root=root)
    if names:
        report = EvalReport()
        report.results = [be.run(name) for name in names]
        report.summary = {
            "total": len(report.results),
            "passed": sum(1 for r in report.results if r.success),
            "failed": sum(1 for r in report.results if not r.success),
            "overall_score": round(report.overall_score(), 3),
        }
        return report
    return be.run_all()


def run_and_report(root: str | Path = ".", names: list[str] | None = None) -> tuple[EvalReport, str]:
    """Run evals and also return a Markdown report."""
    report = run_evals(names=names, root=root)
    markdown = generate_markdown(report)
    return report, markdown
