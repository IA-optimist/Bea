"""
tests/test_elite_pillars.py — Tests for the 3 elite pillars.

Covers: MetaOrchestrator (classification, context, supervision, trace),
        Executor (contracts, error taxonomy, retry),
        Memory (models, ranking, compaction),
        Integration (flow coherence).
"""
from __future__ import annotations
import pytest

import asyncio
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ══════════════════════════════════════════════════════════════
# METAORCHESTRATOR TESTS
# ══════════════════════════════════════════════════════════════

class TestMissionClassifier(unittest.TestCase):
    def test_classify_query(self):
        from core.orchestration.mission_classifier import classify, TaskType, Complexity
        c = classify("What is 2+2?")
        self.assertEqual(c.task_type, TaskType.QUERY)
        self.assertEqual(c.complexity, Complexity.TRIVIAL)
        self.assertFalse(c.needs_approval)
        self.assertFalse(c.needs_planning)

    def test_classify_deployment(self):
        from core.orchestration.mission_classifier import classify, TaskType
        c = classify("Deploy the new version to production server via Docker")
        self.assertEqual(c.task_type, TaskType.DEPLOYMENT)
        self.assertIn(c.risk_level, ("high", "medium", "critical"))
        self.assertTrue(c.needs_approval or c.risk_level == "medium")

    def test_classify_debugging(self):
        from core.orchestration.mission_classifier import classify, TaskType
        c = classify("Fix the broken authentication endpoint that returns 500")
        self.assertEqual(c.task_type, TaskType.DEBUGGING)

    def test_classify_complex(self):
        from core.orchestration.mission_classifier import classify, Complexity
        c = classify(
            "Analyze the entire codebase for security vulnerabilities, "
            "create a detailed report with severity levels, and implement "
            "fixes for any critical issues found in the authentication module "
            "and the API input validation layer"
        )
        self.assertEqual(c.complexity, Complexity.COMPLEX)
        self.assertTrue(c.needs_planning)

    def test_classify_urgent(self):
        from core.orchestration.mission_classifier import classify, Urgency
        c = classify("URGENT: production server is down, database connection failing")
        self.assertEqual(c.urgency, Urgency.CRITICAL)

    def test_classification_has_reasoning(self):
        from core.orchestration.mission_classifier import classify
        c = classify("Build a REST API for user management")
        self.assertTrue(len(c.reasoning) > 10)

    def test_classification_to_dict(self):
        from core.orchestration.mission_classifier import classify
        d = classify("Test the login flow").to_dict()
        self.assertIn("task_type", d)
        self.assertIn("complexity", d)
        self.assertIn("risk_level", d)


class TestContextAssembler(unittest.TestCase):
    def test_assemble_basic(self):
        from core.orchestration.context_assembler import assemble
        ctx = assemble(
            mission_id="test-001",
            goal="Fix a bug",
            classification={"complexity": "simple", "suggested_tools": ["shell"]},
        )
        self.assertEqual(ctx.mission_id, "test-001")
        self.assertIn(ctx.suggested_approach, ("single_tool", "direct_answer", "multi_step_plan"))
        self.assertIsInstance(ctx.prior_skills, list)

    def test_assemble_trivial(self):
        from core.orchestration.context_assembler import assemble
        ctx = assemble("t", "Hi", {"complexity": "trivial"})
        self.assertEqual(ctx.suggested_approach, "direct_answer")
        self.assertEqual(ctx.estimated_steps, 1)

    def test_context_to_dict(self):
        from core.orchestration.context_assembler import assemble
        ctx = assemble("t", "test", {})
        d = ctx.to_dict()
        self.assertIn("mission_id", d)
        self.assertIn("suggested_approach", d)

    def test_planning_prompt(self):
        from core.orchestration.context_assembler import MissionContext as MC
        ctx = MC(prior_skills=[{"name": "Fix API", "steps": ["Check logs"]}])
        prompt = ctx.planning_prompt_context()
        self.assertIn("Fix API", prompt)


@pytest.mark.skip(reason="phantom: module removed")
class TestExecutionSupervisor(unittest.TestCase):
    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_success_first_try(self):
        from core.orchestration.execution_supervisor import supervise

        class FakeSession:
            final_report = "Done successfully"
            auto_count = 1

        async def fake_run(**kw):
            return FakeSession()

        outcome = self._run(supervise(
            fake_run, mission_id="t1", goal="test"
        ))
        self.assertTrue(outcome.success)
        self.assertEqual(outcome.retries, 0)
        self.assertGreaterEqual(outcome.duration_ms, 0)

    def test_retry_on_timeout(self):
        from core.orchestration.execution_supervisor import supervise

        call_count = 0
        class FakeSession:
            final_report = "OK"
            auto_count = 0

        async def flaky_run(**kw):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise asyncio.TimeoutError("slow")
            return FakeSession()

        outcome = self._run(supervise(
            flaky_run, mission_id="t2", goal="test"
        ))
        self.assertTrue(outcome.success)
        self.assertEqual(outcome.retries, 1)
        self.assertIn("retry", outcome.recovery_actions)

    def test_abort_on_permanent_failure(self):
        from core.orchestration.execution_supervisor import supervise

        async def perm_fail(**kw):
            raise PermissionError("Access denied to /etc/shadow")

        outcome = self._run(supervise(
            perm_fail, mission_id="t3", goal="test"
        ))
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.error_class, "permission_denied")

    def test_no_retry_high_risk(self):
        from core.orchestration.execution_supervisor import supervise

        async def fail(**kw):
            raise TimeoutError("slow")

        outcome = self._run(supervise(
            fail, mission_id="t4", goal="test", risk_level="high"
        ))
        self.assertFalse(outcome.success)
        # High risk now hits approval gate first (awaiting_approval)
        # or escalate if approval bypassed
        self.assertIn(outcome.error_class, ("awaiting_approval", "escalate"))

    def test_decision_trace_present(self):
        from core.orchestration.execution_supervisor import supervise

        class S:
            final_report = "ok"
        async def ok(**kw): return S()

        outcome = self._run(supervise(ok, mission_id="t5", goal="test"))
        self.assertTrue(len(outcome.decision_trace) >= 1)


class TestDecisionTrace(unittest.TestCase):
    def test_record_and_summary(self):
        from core.orchestration.decision_trace import DecisionTrace
        t = DecisionTrace(mission_id="dt-001")
        t.record("classify", "query", reason="simple question")
        t.record("execute", "success")
        s = t.summary()
        self.assertEqual(len(s), 2)
        self.assertEqual(s[0]["phase"], "classify")

    def test_save_and_load(self):
        from core.orchestration.decision_trace import DecisionTrace
        t = DecisionTrace(mission_id="dt-save-test")
        t.record("test", "save_test", reason="unit test")
        t.save()
        loaded = DecisionTrace.load("dt-save-test")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["phase"], "test")


# ══════════════════════════════════════════════════════════════
# EXECUTOR TESTS
# ══════════════════════════════════════════════════════════════

class TestExecutionContract(unittest.TestCase):
    def test_success_result(self):
        from executor.contracts import ExecutionResult, ExecutionStatus
        r = ExecutionResult(task_id="task-1", tool_used="shell")
        r.complete(success=True, output="Hello world")
        self.assertTrue(r.success)
        self.assertEqual(r.status, ExecutionStatus.SUCCESS)
        self.assertGreaterEqual(r.duration_ms, 0)
        self.assertEqual(r.raw_output, "Hello world")

    def test_failure_result(self):
        from executor.contracts import ExecutionResult, ExecutionStatus, ErrorClass
        r = ExecutionResult(task_id="task-2", tool_used="http_get")
        r.complete(success=False, error="Connection timeout after 30s")
        self.assertFalse(r.success)
        self.assertEqual(r.status, ExecutionStatus.FAILED)
        self.assertEqual(r.error_class, ErrorClass.TIMEOUT)
        self.assertTrue(r.retryable)

    def test_non_retryable_error(self):
        from executor.contracts import ExecutionResult, ErrorClass
        r = ExecutionResult()
        r.complete(success=False, error="Permission denied: /etc/shadow")
        self.assertEqual(r.error_class, ErrorClass.PERMISSION_DENIED)
        self.assertFalse(r.retryable)

    def test_to_dict(self):
        from executor.contracts import ExecutionResult
        r = ExecutionResult(task_id="t")
        r.complete(success=True, output="ok")
        d = r.to_dict()
        self.assertIn("execution_id", d)
        self.assertIn("duration_ms", d)
        self.assertIn("validation_status", d)


class TestErrorClassification(unittest.TestCase):
    def test_classify_timeout(self):
        from executor.contracts import classify_error, ErrorClass
        self.assertEqual(classify_error("Connection timeout"), ErrorClass.TIMEOUT)

    def test_classify_permission(self):
        from executor.contracts import classify_error, ErrorClass
        self.assertEqual(classify_error("Permission denied"), ErrorClass.PERMISSION_DENIED)

    def test_classify_llm(self):
        from executor.contracts import classify_error, ErrorClass
        self.assertEqual(classify_error("OpenAI rate limit"), ErrorClass.RATE_LIMITED)

    def test_classify_unknown(self):
        from executor.contracts import classify_error, ErrorClass
        self.assertEqual(classify_error("Something weird"), ErrorClass.UNKNOWN)

    def test_retryable_check(self):
        from executor.contracts import is_retryable, ErrorClass
        self.assertTrue(is_retryable(ErrorClass.TIMEOUT))
        self.assertTrue(is_retryable(ErrorClass.RATE_LIMITED))
        self.assertFalse(is_retryable(ErrorClass.PERMISSION_DENIED))
        self.assertFalse(is_retryable(ErrorClass.UNKNOWN))


# ══════════════════════════════════════════════════════════════
# MEMORY TESTS
# ══════════════════════════════════════════════════════════════

# ── Skips pour modules memory retirés du codebase (drift connu) ────────────
import importlib.util

_HAS_MEMORY_MODELS = importlib.util.find_spec("memory.memory_models") is not None
_HAS_MEMORY_RANKER = importlib.util.find_spec("memory.memory_ranker") is not None
_HAS_MEMORY_COMPACTOR = importlib.util.find_spec("memory.memory_compactor") is not None


@pytest.mark.skipif(not _HAS_MEMORY_MODELS, reason="memory.memory_models retiré du codebase (drift connu)")
class TestMemoryModels(unittest.TestCase):
    def test_create_item(self):
        from memory.memory_models import MemoryItem, MemoryType
        m = MemoryItem(content="Docker uses namespaces", memory_type=MemoryType.KNOWLEDGE)
        self.assertEqual(m.memory_type, MemoryType.KNOWLEDGE)
        self.assertTrue(len(m.memory_id) == 12)

    def test_to_dict_roundtrip(self):
        from memory.memory_models import MemoryItem, MemoryType
        m = MemoryItem(
            content="Test fact",
            memory_type=MemoryType.DECISION,
            tags=["test"],
            related_mission_id="m-001",
        )
        d = m.to_dict()
        m2 = MemoryItem.from_dict(d)
        self.assertEqual(m2.content, "Test fact")
        self.assertEqual(m2.memory_type, MemoryType.DECISION)

    def test_touch_access(self):
        from memory.memory_models import MemoryItem
        m = MemoryItem(content="test")
        self.assertEqual(m.access_count, 0)
        m.touch()
        self.assertEqual(m.access_count, 1)
        self.assertIsNotNone(m.last_accessed_at)


@pytest.mark.skipif(not _HAS_MEMORY_RANKER, reason="memory.memory_ranker retiré du codebase (drift connu)")
class TestMemoryRanker(unittest.TestCase):
    def test_rank_by_relevance(self):
        from memory.memory_ranker import rank_memories

        class FakeItem:
            def __init__(self, content, confidence=0.5):
                self.content = content
                self.confidence = confidence
                self.created_at = time.time()
                self.access_count = 0

        items = [
            FakeItem("Docker container networking and ports"),
            FakeItem("Python list comprehension syntax"),
            FakeItem("Docker compose health checks"),
        ]
        results = rank_memories("docker container health", items)
        self.assertTrue(len(results) >= 1)
        # Docker items should rank higher than Python
        top_content = results[0][0].content
        self.assertIn("Docker", top_content)

    def test_empty_query(self):
        from memory.memory_ranker import rank_memories
        self.assertEqual(rank_memories("", []), [])

    def test_min_score_filter(self):
        from memory.memory_ranker import rank_memories

        class FakeItem:
            def __init__(self, content):
                self.content = content
                self.confidence = 0.5
                self.created_at = time.time()

        items = [FakeItem("completely unrelated banana smoothie recipe")]
        results = rank_memories("docker deployment", items, min_score=0.3)
        self.assertEqual(len(results), 0)


@pytest.mark.skipif(not _HAS_MEMORY_COMPACTOR, reason="memory.memory_compactor retiré du codebase (drift connu)")
class TestMemoryCompactor(unittest.TestCase):
    def test_compact_removes_empty(self):
        from memory.memory_compactor import compact_jsonl
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            f.write(json.dumps({"content": "good", "confidence": 0.8, "created_at": time.time()}) + "\n")
            f.write(json.dumps({"content": "", "confidence": 0.5}) + "\n")
            f.write(json.dumps({"content": "also good", "confidence": 0.7, "created_at": time.time()}) + "\n")
            path = f.name

        stats = compact_jsonl(path)
        self.assertEqual(stats["kept"], 2)
        self.assertEqual(stats["removed"], 1)
        os.unlink(path)

    def test_compact_removes_old_low_confidence(self):
        from memory.memory_compactor import compact_jsonl
        old_ts = time.time() - 40 * 86400  # 40 days ago

        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            f.write(json.dumps({"content": "recent", "confidence": 0.8, "created_at": time.time()}) + "\n")
            f.write(json.dumps({"content": "old junk", "confidence": 0.1, "created_at": old_ts}) + "\n")
            path = f.name

        stats = compact_jsonl(path, max_age_days=30, min_confidence=0.2)
        self.assertEqual(stats["kept"], 1)
        self.assertEqual(stats["removed"], 1)
        os.unlink(path)

    def test_dry_run(self):
        from memory.memory_compactor import compact_jsonl
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            f.write(json.dumps({"content": ""}) + "\n")
            path = f.name

        stats = compact_jsonl(path, dry_run=True)
        self.assertEqual(stats["removed"], 1)
        # File should still have the empty entry (dry run)
        with open(path) as f:
            self.assertEqual(len(f.readlines()), 1)
        os.unlink(path)


# ══════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ══════════════════════════════════════════════════════════════

@pytest.mark.skipif(not _HAS_MEMORY_MODELS, reason="test référence memory.memory_models retiré (drift connu)")
class TestPillarIntegration(unittest.TestCase):
    def test_classify_then_assemble(self):
        """Verify classification feeds into context assembly."""
        from core.orchestration.mission_classifier import classify
        from core.orchestration.context_assembler import assemble

        c = classify("Fix the broken Docker deployment on production")
        ctx = assemble("int-001", "Fix Docker", c.to_dict())
        self.assertEqual(ctx.mission_id, "int-001")
        # Classification should influence approach
        self.assertIn(ctx.suggested_approach,
                      ("single_tool", "multi_step_plan", "decompose_and_plan", "direct_answer"))

    def test_executor_contract_in_supervisor(self):
        """Verify supervisor outcome is compatible with executor contract."""
        from core.orchestration.execution_supervisor import ExecutionOutcome
        from executor.contracts import ExecutionResult

        # Both have to_dict
        o = ExecutionOutcome(success=True, result="ok", duration_ms=100)
        r = ExecutionResult()
        r.complete(success=True, output="ok")
        self.assertIn("success", o.to_dict())
        self.assertIn("success", r.to_dict())

    def test_meta_orchestrator_has_classification(self):
        """Verify MetaOrchestrator source includes classification."""
        import inspect
        from core.meta_orchestrator import MetaOrchestrator
        src = inspect.getsource(MetaOrchestrator.run_mission)
        self.assertIn("mission_classifier", src)
        self.assertIn("context_assembler", src)
        self.assertIn("execution_supervisor", src)
        self.assertIn("decision_trace", src)

    def test_memory_type_covers_mission_needs(self):
        """Verify memory types cover all orchestration needs."""
        from memory.memory_models import MemoryType
        types = {t.value for t in MemoryType}
        self.assertIn("knowledge", types)
        self.assertIn("decision", types)
        self.assertIn("procedural", types)
        self.assertIn("working", types)
        self.assertIn("mission_outcome", types)


if __name__ == "__main__":
    unittest.main()
