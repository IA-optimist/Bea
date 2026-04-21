"""
tests/test_e2e_final.py — End-to-end final stabilization tests.

Verifies the complete system behaves deterministically:
- Contract unity
- Memory effectiveness
- Skill lifecycle
- Trace completeness
- Loop stability
- Capability health
- No legacy leakage
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestContractUnity(unittest.TestCase):
    """Phase 1: ONE canonical ExecutionResult."""

    def test_single_canonical_class(self):
        from executor.contracts import ExecutionResult
        self.assertTrue(hasattr(ExecutionResult, 'complete'))
        self.assertTrue(hasattr(ExecutionResult, 'to_dict'))

    def test_no_alias_in_runner(self):
        import executor.runner as mod
        # Should NOT have an ExecutionResult attribute anymore
        src = open(mod.__file__).read()
        self.assertNotIn("ExecutionResult = ActionResult", src)

    def test_no_alias_in_safe_executor(self):
        import core.self_improvement.safe_executor as mod
        src = open(mod.__file__).read()
        self.assertNotIn("ExecutionResult = PatchResult", src)

    def test_error_taxonomy_complete(self):
        from executor.contracts import ErrorClass
        expected = {"none", "tool_not_available", "dependency_failure", "timeout",
                    "invalid_input", "permission_denied", "execution_exception",
                    "validation_failed", "llm_unavailable",
                    "external_service_failure", "rate_limited", "unknown"}
        actual = {e.value for e in ErrorClass}
        self.assertEqual(expected, actual)

    def test_classify_error_deterministic(self):
        from executor.contracts import classify_error, ErrorClass
        self.assertEqual(classify_error("timeout exceeded"), ErrorClass.TIMEOUT)
        self.assertEqual(classify_error("permission denied"), ErrorClass.PERMISSION_DENIED)
        self.assertEqual(classify_error("rate limit hit"), ErrorClass.RATE_LIMITED)
        self.assertEqual(classify_error("???"), ErrorClass.UNKNOWN)

    def test_retry_engine_deleted(self):
        self.assertFalse(os.path.exists(
            os.path.join(os.path.dirname(os.path.dirname(__file__)),
                         "executor", "retry_engine.py")))


class TestMetaOrchestratorAlignment(unittest.TestCase):
    """Phase 2: MetaOrchestrator decides, Executor performs."""

    def test_run_mission_exists(self):
        from core.meta_orchestrator import MetaOrchestrator
        self.assertTrue(hasattr(MetaOrchestrator, 'run_mission'))

    def test_pipeline_phases_present(self):
        import inspect
        from core.meta_orchestrator import MetaOrchestrator
        src = inspect.getsource(MetaOrchestrator)  # class source — features now in helpers
        for phase in ["classify", "assemble", "supervise", "reflection",
                       "learning_loop", "refine_skill", "trace"]:
            self.assertIn(phase, src, f"Missing phase: {phase}")

    def test_classification_deterministic(self):
        from core.orchestration.mission_classifier import classify
        c1 = classify("Deploy the application to production")
        c2 = classify("Deploy the application to production")
        self.assertEqual(c1.task_type.value, c2.task_type.value)
        self.assertEqual(c1.urgency.value, c2.urgency.value)


class TestMemoryEffectiveness(unittest.TestCase):
    """Phase 3: Memory improves decisions."""

    def test_context_assembler_retrieves_skills(self):
        from core.orchestration.context_assembler import MissionContext
        ctx = MissionContext(mission_id="test", goal="test")
        self.assertIsInstance(ctx.prior_skills, list)
        self.assertIsInstance(ctx.relevant_memories, list)
        self.assertIsInstance(ctx.recent_failures, list)

    def test_working_memory_bounded(self):
        from memory.working_memory import WorkingMemory
        wm = WorkingMemory(token_budget=5)
        wm.add("x " * 100, "test", relevance=0.5)
        # Should not exceed budget
        self.assertLessEqual(wm.used_tokens(), wm.token_budget + 50)

    @unittest.skipUnless(
        importlib.util.find_spec("memory.memory_decay") is not None,
        "memory.memory_decay retiré du codebase (drift connu)",
    )
    def test_memory_decay_preserves_high_use(self):
        from memory.memory_decay import apply_decay
        old_ts = time.time() - 60 * 86400
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            f.write(json.dumps({
                "content": "high use",
                "confidence": 0.8,
                "created_at": old_ts,
                "last_accessed_at": old_ts,
                "use_count": 20,
            }) + "\n")
            f.write(json.dumps({
                "content": "no use",
                "confidence": 0.8,
                "created_at": old_ts,
                "last_accessed_at": old_ts,
                "use_count": 0,
            }) + "\n")
            path = f.name
        apply_decay(path)
        with open(path) as fh:
            high = json.loads(fh.readline())
            low = json.loads(fh.readline())
        self.assertGreater(high["confidence"], low["confidence"])
        os.unlink(path)


class TestSkillLifecycle(unittest.TestCase):
    """Phase 4: Skill creation → retrieval → refinement."""

    def test_full_skill_lifecycle(self):
        from core.skills.skill_service import SkillService
        tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        tmp.close()
        svc = SkillService(store_path=tmp.name)

        # Create
        skill = svc.record_outcome(
            mission_id="lc-001",
            goal="Optimize PostgreSQL slow query with index analysis",
            result="Created composite index on (user_id, created_at). " * 5,
            status="DONE",
            confidence=0.6,
        )
        self.assertIsNotNone(skill)

        # Retrieve
        results = svc.search_skills("PostgreSQL query optimization", top_k=3)
        self.assertGreater(len(results), 0)

        # Refine
        original = skill.confidence
        svc.refine_skill(skill.skill_id, "Better result", success=True)
        updated = svc.get_skill(skill.skill_id)
        self.assertGreater(updated["confidence"], original)

        os.unlink(tmp.name)


class TestCapabilityLayer(unittest.TestCase):
    """Phase 5: Unified capability model."""

    def test_capability_types_complete(self):
        from executor.capability_contracts import CapabilityType
        expected = {"native_tool", "plugin", "mcp_tool"}
        actual = {ct.value for ct in CapabilityType}
        self.assertEqual(expected, actual)

    def test_capability_health_tracker(self):
        from executor.capability_health import CapabilityHealthTracker
        t = CapabilityHealthTracker()
        t.reset()
        t.record_success("shell", duration_ms=50)
        t.record_failure("broken_tool", error="crash")
        stats = t.all_stats()
        self.assertEqual(len(stats), 2)


class TestMissionLoopStability(unittest.TestCase):
    """Phase 6: No infinite loops, no useless retries."""

    def test_retry_has_max(self):
        from core.orchestration.execution_supervisor import _MAX_RETRIES as _DEFAULT_MAX_RETRIES
        self.assertLessEqual(_DEFAULT_MAX_RETRIES, 5)

    def test_reflection_prevents_empty_done(self):
        from core.orchestration.reflection import reflect, ReflectionVerdict
        r = reflect(goal="Important task", result="")
        self.assertEqual(r.verdict, ReflectionVerdict.EMPTY)

    def test_budget_prevents_runaway(self):
        from executor.observation import ExecutionBudget, Observation, ObservationType
        b = ExecutionBudget(max_steps=3)
        for _ in range(4):
            b.record(Observation(obs_type=ObservationType.TOOL_OUTPUT))
        exceeded, _ = b.is_exceeded()
        self.assertTrue(exceeded)


class TestObservabilityCompleteness(unittest.TestCase):
    """Phase 7: Full traceability."""

    def test_decision_trace_records(self):
        from core.orchestration.decision_trace import DecisionTrace
        dt = DecisionTrace(mission_id="obs-test")
        dt.record("classify", "info_request", reason="keyword match")
        dt.record("plan", "direct_answer")
        dt.record("execute", "success", duration_ms=100)
        dt.record_cost(tokens_in=500, tokens_out=200, cost_usd=0.002)
        summary = dt.summary()
        self.assertEqual(len(summary), 3)
        cost = dt.cost_summary()
        self.assertEqual(cost["tokens_in"], 500)

    def test_trace_saves_and_loads(self):
        from core.orchestration.decision_trace import DecisionTrace
        dt = DecisionTrace(mission_id="save-load-test")
        dt.record("test", "test_action", reason="testing")
        dt.save()
        loaded = DecisionTrace.load("save-load-test")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["phase"], "test")


class TestNoLegacyLeakage(unittest.TestCase):
    """Phase 8: No dead code."""

    def test_no_retry_engine(self):
        executor_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "executor")
        self.assertNotIn("retry_engine.py", os.listdir(executor_dir))

    def test_no_telegram_in_code(self):
        src_dir = os.path.dirname(os.path.dirname(__file__))
        for subdir in ["core", "executor", "memory"]:
            path = os.path.join(src_dir, subdir)
            if not os.path.isdir(path):
                continue
            for f in os.listdir(path):
                if f.endswith(".py"):
                    with open(os.path.join(path, f)) as fh:
                        content = fh.read()
                    self.assertNotIn("telegram", content.lower(),
                                     f"Telegram reference in {subdir}/{f}")


if __name__ == "__main__":
    unittest.main()
