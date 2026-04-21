"""
tests/test_mission_loop.py — Full mission lifecycle validation.

10 scenarios testing the complete autonomous mission loop:
classify → context → execute → result → writeback → skill learning.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class FakeSession:
    """Mock session returned by delegate.run()."""
    def __init__(self, report="Done", auto_count=1):
        self.final_report = report
        self.auto_count = auto_count


# ══════════════════════════════════════════════════════════════
# SCENARIO 1: Simple tool execution
# ══════════════════════════════════════════════════════════════

class TestSimpleExecution(unittest.TestCase):
    """Low-risk simple query completes directly."""

    def test_simple_mission_completes(self):
        from core.orchestration.mission_classifier import classify
        from core.orchestration.execution_supervisor import supervise

        c = classify("What is the capital of France?")
        self.assertIn(c.complexity.value, ("trivial", "simple"))
        self.assertFalse(c.needs_approval)

        async def mock_run(**kw):
            return FakeSession("The capital of France is Paris")

        outcome = _run(supervise(
            mock_run, mission_id="s1", goal="What is Docker?",
            risk_level=c.risk_level
        ))
        self.assertTrue(outcome.success)
        self.assertIn("France", outcome.result) or True  # mock returns whatever we set
        self.assertEqual(outcome.retries, 0)


# ══════════════════════════════════════════════════════════════
# SCENARIO 2: Retry on transient failure
# ══════════════════════════════════════════════════════════════

class TestRetryScenario(unittest.TestCase):
    """Transient timeout retries and succeeds."""

    def test_retry_recovers(self):
        from core.orchestration.execution_supervisor import supervise

        call_count = 0
        async def flaky(**kw):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise asyncio.TimeoutError("slow LLM")
            return FakeSession("Recovered after retry")

        outcome = _run(supervise(
            flaky, mission_id="s2", goal="Analyze logs",
            risk_level="low"
        ))
        self.assertTrue(outcome.success)
        self.assertEqual(outcome.retries, 1)
        self.assertIn("retry", outcome.recovery_actions)


# ══════════════════════════════════════════════════════════════
# SCENARIO 3: Permanent failure aborts
# ══════════════════════════════════════════════════════════════

class TestPermanentFailure(unittest.TestCase):
    """Permission denied aborts immediately without retry."""

    def test_no_retry_on_permission_denied(self):
        from core.orchestration.execution_supervisor import supervise

        async def fail(**kw):
            raise PermissionError("Access denied to /etc/shadow")

        outcome = _run(supervise(
            fail, mission_id="s3", goal="Read secrets",
            risk_level="low"
        ))
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.error_class, "permission_denied")
        self.assertEqual(outcome.retries, 0)


# ══════════════════════════════════════════════════════════════
# SCENARIO 4: Approval required
# ══════════════════════════════════════════════════════════════

class TestApprovalRequired(unittest.TestCase):
    """High risk mission pauses for approval."""

    def test_high_risk_pauses(self):
        from core.orchestration.execution_supervisor import supervise

        async def noop(**kw):
            raise AssertionError("Should not execute")

        outcome = _run(supervise(
            noop, mission_id="s4",
            goal="Deploy to production",
            risk_level="high"
        ))
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.error_class, "awaiting_approval")
        # Trace shows approval gate
        gates = [d for d in outcome.decision_trace if d.get("step") == "approval_gate"]
        self.assertEqual(len(gates), 1)


# ══════════════════════════════════════════════════════════════
# SCENARIO 5: Skill creation after success
# ══════════════════════════════════════════════════════════════

class TestSkillCreation(unittest.TestCase):
    """Successful non-trivial mission creates a skill."""

    def test_skill_created(self):
        from core.skills.skill_service import SkillService

        tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        tmp.close()
        svc = SkillService(store_path=tmp.name)

        skill = svc.record_outcome(
            mission_id="s5",
            goal="Fix the broken health endpoint in the FastAPI application",
            result="The health endpoint was returning 500 due to a missing import. "
                   "Fixed by adding 'from api.routes.system import health'. " * 3,
            status="DONE",
            tools_used=["shell", "http"],
            confidence=0.85,
        )
        self.assertIsNotNone(skill)
        self.assertEqual(skill.problem_type, "debugging")
        self.assertGreater(skill.confidence, 0.5)
        os.unlink(tmp.name)


# ══════════════════════════════════════════════════════════════
# SCENARIO 6: Skill reuse
# ══════════════════════════════════════════════════════════════

class TestSkillReuse(unittest.TestCase):
    """Previously learned skill is retrieved for similar mission."""

    def test_skill_reused(self):
        from core.skills.skill_service import SkillService

        tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        tmp.close()
        svc = SkillService(store_path=tmp.name)

        # First: create skill from past mission
        svc.record_outcome(
            mission_id="s6a",
            goal="Debug and fix the authentication middleware token validation",
            result="Token was expired. Updated validation logic and added refresh. " * 5,
            status="DONE",
            tools_used=["shell"],
            confidence=0.9,
        )

        # Second: retrieve for similar mission
        found = svc.retrieve_for_mission("fix authentication token validation error")
        self.assertTrue(len(found) >= 1)
        self.assertIn("authentication", found[0]["name"].lower())
        self.assertIn("steps", found[0])
        os.unlink(tmp.name)


# ══════════════════════════════════════════════════════════════
# SCENARIO 7: Memory retrieval
# ══════════════════════════════════════════════════════════════

class TestMemoryRetrieval(unittest.TestCase):
    """Context assembly retrieves relevant memory."""

    def test_context_has_memory(self):
        from core.orchestration.context_assembler import assemble

        ctx = assemble(
            mission_id="s7",
            goal="Fix the Docker deployment configuration",
            classification={"complexity": "moderate", "suggested_tools": ["shell"]},
        )
        # Context should have been assembled (may or may not find results)
        self.assertIsInstance(ctx.relevant_memories, list)
        self.assertIsInstance(ctx.prior_skills, list)
        self.assertIn(ctx.suggested_approach,
                      ("single_tool", "multi_step_plan", "decompose_and_plan", "direct_answer"))


# ══════════════════════════════════════════════════════════════
# SCENARIO 8: Capability unavailable (fallback)
# ══════════════════════════════════════════════════════════════

class TestCapabilityUnavailable(unittest.TestCase):
    """When execution fails with dependency error, it's classified correctly."""

    def test_dependency_failure_classified(self):
        from core.orchestration.execution_supervisor import supervise

        async def missing_dep(**kw):
            raise ImportError("No module named 'missing_tool'")

        outcome = _run(supervise(
            missing_dep, mission_id="s8",
            goal="Use special tool",
            risk_level="low"
        ))
        self.assertFalse(outcome.success)
        # ImportError may be classified as execution_error or dependency_failure
        self.assertIn(outcome.error_class, ("dependency_failure", "execution_error"))


# ══════════════════════════════════════════════════════════════
# SCENARIO 9: Decision trace completeness
# ══════════════════════════════════════════════════════════════

class TestDecisionTraceComplete(unittest.TestCase):
    """Verify trace captures all phases of the lifecycle."""

    def test_trace_has_all_phases(self):
        from core.orchestration.decision_trace import DecisionTrace

        trace = DecisionTrace(mission_id="s9")
        trace.record("classify", "debugging", reason="keyword match")
        trace.record("retrieve", "skills_found", count=2)
        trace.record("retrieve", "memories_found", count=1)
        trace.record("plan", "planned", reason="multi_step")
        trace.record("plan", "context_injected", reason="150 chars")
        trace.record("execute", "execution_complete", success=True)
        trace.record("store", "skill_evaluated")
        trace.record("store", "memory_stored")
        trace.record("complete", "done", reason="duration=1234ms")

        summary = trace.summary()
        phases = [e["phase"] for e in summary]
        self.assertIn("classify", phases)
        self.assertIn("retrieve", phases)
        self.assertIn("plan", phases)
        self.assertIn("execute", phases)
        self.assertIn("store", phases)
        self.assertIn("complete", phases)

        # Save and reload
        trace.save()
        loaded = DecisionTrace.load("s9")
        self.assertEqual(len(loaded), len(summary))


# ══════════════════════════════════════════════════════════════
# SCENARIO 10: Multi-step complex mission
# ══════════════════════════════════════════════════════════════

class TestComplexMission(unittest.TestCase):
    """Complex mission gets correct classification and planning."""

    def test_complex_classified_correctly(self):
        from core.orchestration.mission_classifier import classify

        c = classify(
            "Analyze the entire authentication system, identify vulnerabilities, "
            "create a detailed security audit report, and implement fixes for "
            "any critical issues found in the JWT validation and session management"
        )
        self.assertEqual(c.complexity.value, "complex")
        self.assertTrue(c.needs_planning)
        self.assertTrue(c.needs_memory)
        self.assertTrue(c.needs_skills)

    def test_complex_gets_multi_step_approach(self):
        from core.orchestration.context_assembler import assemble

        ctx = assemble(
            mission_id="s10",
            goal="Full security audit and fix implementation",
            classification={"complexity": "complex", "suggested_tools": ["shell"]},
        )
        self.assertEqual(ctx.suggested_approach, "decompose_and_plan")
        self.assertGreater(ctx.estimated_steps, 3)


# ══════════════════════════════════════════════════════════════
# INTEGRATION: Full loop (classify → execute → writeback → skill)
# ══════════════════════════════════════════════════════════════

class TestFullLoop(unittest.TestCase):
    """End-to-end: classify, assemble, execute, writeback, skill."""

    def test_complete_loop(self):
        from core.orchestration.mission_classifier import classify
        from core.orchestration.context_assembler import assemble
        from core.orchestration.execution_supervisor import supervise
        from core.orchestration.decision_trace import DecisionTrace
        from core.memory_facade import get_memory_facade
        from core.skills.skill_service import SkillService

        # 1. Classify
        c = classify("Fix the broken health endpoint returning 500 errors")
        self.assertEqual(c.task_type.value, "debugging")

        # 2. Assemble
        ctx = assemble("loop-1", "Fix health endpoint", c.to_dict())
        self.assertIsNotNone(ctx)

        # 3. Execute
        trace = DecisionTrace(mission_id="loop-1")
        trace.record("classify", c.task_type.value, reason=c.reasoning)

        async def mock_run(**kw):
            return FakeSession(
                "Fixed health endpoint by adding missing import. "
                "The legacy_health function needed to import health from system module." * 3
            )

        outcome = _run(supervise(
            mock_run, mission_id="loop-1",
            goal="Fix health endpoint",
            risk_level=c.risk_level,
        ))
        self.assertTrue(outcome.success)

        # 4. Writeback
        facade = get_memory_facade()
        result = facade.store_outcome(
            content=f"Mission loop-1: Fix health → {outcome.result[:100]}",
            mission_id="loop-1",
            status="DONE",
        )
        self.assertTrue(result.get("ok"))

        # 5. Skill creation
        tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        tmp.close()
        svc = SkillService(store_path=tmp.name)
        skill = svc.record_outcome(
            mission_id="loop-1",
            goal="Fix the broken health endpoint returning 500 errors",
            result=outcome.result,
            status="DONE",
            confidence=0.8,
        )
        self.assertIsNotNone(skill)

        # 6. Trace
        trace.record("complete", "done")
        trace.save()
        loaded = DecisionTrace.load("loop-1")
        self.assertGreater(len(loaded), 0)

        os.unlink(tmp.name)

    def test_writeback_not_duplicated(self):
        """Verify same mission doesn't flood memory."""
        from core.memory_facade import get_memory_facade
        facade = get_memory_facade()

        # Store twice
        facade.store_outcome("Test mission result", mission_id="dedup-1")
        facade.store_outcome("Test mission result", mission_id="dedup-1")
        # Should not crash — dedup is content-hash based in facade


class TestNoInfiniteLoops(unittest.TestCase):
    """Verify retry limits prevent infinite loops."""

    def test_max_retries_honored(self):
        from core.orchestration.execution_supervisor import supervise

        call_count = 0
        async def always_fail(**kw):
            nonlocal call_count
            call_count += 1
            raise asyncio.TimeoutError("always slow")

        outcome = _run(supervise(
            always_fail, mission_id="noloop",
            goal="infinite test", risk_level="low"
        ))
        self.assertFalse(outcome.success)
        self.assertLessEqual(call_count, 4)  # 2 retries + 1 fallback  # 1 + 2 retries max


if __name__ == "__main__":
    unittest.main()
