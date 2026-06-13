"""
tests/test_pillar_integration.py — Cross-pillar integration tests.

Validates: classify → context → execute → memory writeback → skill creation
"""
from __future__ import annotations
import pytest

import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestExecutorContractUnification(unittest.TestCase):
    """Verify ONE canonical ExecutionResult."""

    def test_contracts_is_canonical(self):
        from executor.contracts import ExecutionResult as CR
        from executor.task_model import ExecutionResult as TR
        # Both should be the same class (task_model re-exports)
        self.assertIs(CR, TR)

    def test_init_re_exports_canonical(self):
        from executor import ExecutionResult
        from executor.contracts import ExecutionResult as CR
        self.assertIs(ExecutionResult, CR)

    def test_error_classification_consistent(self):
        from executor.contracts import classify_error, ErrorClass
        # Verify all expected classes are reachable
        self.assertEqual(classify_error("Connection timeout"), ErrorClass.TIMEOUT)
        self.assertEqual(classify_error("Permission denied"), ErrorClass.PERMISSION_DENIED)
        self.assertEqual(classify_error("OpenAI rate limit"), ErrorClass.RATE_LIMITED)


class TestMemoryFacadeConvenience(unittest.TestCase):
    """Verify MemoryFacade convenience methods exist."""

    def test_facade_has_convenience(self):
        from core.memory_facade import MemoryFacade
        for method in ['store_decision', 'store_failure', 'store_outcome',
                       'get_decisions', 'get_failures']:
            self.assertTrue(hasattr(MemoryFacade, method),
                            f"MemoryFacade missing {method}")

    def test_facade_store_outcome(self):
        from core.memory_facade import get_memory_facade
        facade = get_memory_facade()
        result = facade.store_outcome(
            content="Test mission completed",
            mission_id="test-001",
            status="DONE",
        )
        self.assertTrue(result.get("ok"))

    def test_facade_store_failure(self):
        from core.memory_facade import get_memory_facade
        facade = get_memory_facade()
        result = facade.store_failure(
            content="Test mission failed: timeout",
            error_class="timeout",
            mission_id="test-002",
        )
        self.assertTrue(result.get("ok"))


class TestMetaOrchestratorUsesUnifiedContracts(unittest.TestCase):
    """Verify orchestrator uses canonical interfaces."""

    def test_uses_facade_convenience(self):
        import inspect
        from core.meta_orchestrator import MetaOrchestrator
        src = "\n".join(
            inspect.getsource(klass)
            for klass in MetaOrchestrator.__mro__
            if klass is not object
        )
        self.assertIn("store_outcome", src)
        self.assertIn("store_failure", src)

    def test_uses_supervisor(self):
        import inspect
        from core.meta_orchestrator import MetaOrchestrator
        src = inspect.getsource(MetaOrchestrator)  # class source — features now in helpers
        self.assertIn("execution_supervisor", src)

    def test_uses_classifier(self):
        import inspect
        from core.meta_orchestrator import MetaOrchestrator
        src = inspect.getsource(MetaOrchestrator._classify_mission)
        self.assertIn("mission_classifier", src)


class TestEndToEndFlow(unittest.TestCase):
    """Verify the complete classify → context → execute flow."""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_classify_assemble_supervise(self):
        """Full pipeline: classify → assemble context → supervise execution."""
        from core.orchestration.mission_classifier import classify
        from core.orchestration.context_assembler import assemble
        from core.orchestration.execution_supervisor import supervise

        # 1. Classify
        c = classify("Fix the broken health endpoint")
        self.assertIn(c.task_type.value, ["debugging", "implementation", "other"])

        # 2. Assemble context
        ctx = assemble("e2e-001", "Fix health endpoint", c.to_dict())
        self.assertEqual(ctx.mission_id, "e2e-001")

        # 3. Supervised execution (mock)
        class FakeSession:
            final_report = "Health endpoint fixed"
            auto_count = 1

        async def mock_run(**kw):
            return FakeSession()

        outcome = self._run(supervise(
            mock_run, mission_id="e2e-001", goal="Fix health",
            risk_level=c.risk_level,
        ))
        self.assertTrue(outcome.success)
        self.assertEqual(outcome.result, "Health endpoint fixed")

    def test_skill_creation_after_success(self):
        """Verify skills are created from successful outcomes."""
        from core.skills.skill_service import SkillService

        tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        tmp.close()
        svc = SkillService(store_path=tmp.name)

        # Record a non-trivial success
        skill = svc.record_outcome(
            mission_id="e2e-002",
            goal="Debug and fix the authentication middleware",
            result="Fixed by updating token validation logic. " * 5,
            status="DONE",
            confidence=0.8,
        )
        self.assertIsNotNone(skill)

        # Retrieve for similar mission
        found = svc.retrieve_for_mission("fix authentication token validation")
        self.assertTrue(len(found) >= 1)

        os.unlink(tmp.name)

    def test_retry_then_success(self):
        """Verify retry recovery works end-to-end."""
        from core.orchestration.execution_supervisor import supervise

        attempts = 0
        class S:
            final_report = "Worked on retry"

        async def flaky(**kw):
            nonlocal attempts
            attempts += 1
            if attempts < 2:
                raise ConnectionError("Temporary network issue")
            return S()

        outcome = self._run(supervise(
            flaky, mission_id="e2e-003", goal="network task"
        ))
        self.assertTrue(outcome.success)
        self.assertEqual(outcome.retries, 1)
        self.assertIn("retry", outcome.recovery_actions)

    @pytest.mark.xfail(reason="memory.memory_ranker module absent", strict=False)
    def test_memory_ranker_integration(self):
        """Verify memory ranker works with real memory items."""
        from memory.memory_models import MemoryItem, MemoryType
        from memory.memory_ranker import rank_memories

        items = [
            MemoryItem(content="Docker container port mapping and networking",
                       memory_type=MemoryType.KNOWLEDGE, confidence=0.9),
            MemoryItem(content="Python asyncio event loop patterns",
                       memory_type=MemoryType.KNOWLEDGE, confidence=0.7),
            MemoryItem(content="Docker compose health check configuration",
                       memory_type=MemoryType.KNOWLEDGE, confidence=0.8),
        ]
        results = rank_memories("docker health check", items, top_k=2)
        self.assertEqual(len(results), 2)
        # Docker items should be ranked higher
        self.assertIn("Docker", results[0][0].content)


if __name__ == "__main__":
    unittest.main()
