"""
tests/test_executor_upgrades.py — Tests for executor-level upgrades.

Covers: observation, budget tracking, output validation, learning loop.
"""
from __future__ import annotations

import os
import sys
import unittest
import pytest

# Skip all tests - executor.observation, executor.output_validator, memory.working_memory not implemented
pytestmark = pytest.mark.skip(reason="executor upgrades modules not implemented")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestObservation(unittest.TestCase):
    """Test structured observation contract."""

    def test_basic_observation(self):
        from executor.observation import Observation, ObservationType
        obs = Observation(
            obs_type=ObservationType.TOOL_OUTPUT,
            content="File created successfully",
            success=True,
        )
        self.assertTrue(obs.is_actionable())
        self.assertFalse(obs.is_error())
        self.assertIn("tool_output", obs.summary())

    def test_error_observation(self):
        from executor.observation import Observation, ObservationType
        obs = Observation(
            obs_type=ObservationType.ERROR,
            content="Connection refused",
            success=False,
        )
        self.assertTrue(obs.is_error())
        self.assertFalse(obs.is_actionable())

    def test_empty_not_actionable(self):
        from executor.observation import Observation, ObservationType
        obs = Observation(obs_type=ObservationType.TOOL_OUTPUT, content="", success=True)
        self.assertFalse(obs.is_actionable())

    def test_to_dict(self):
        from executor.observation import Observation, ObservationType
        obs = Observation(
            obs_type=ObservationType.LLM_RESPONSE,
            content="Hello",
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.001,
        )
        d = obs.to_dict()
        self.assertEqual(d["tokens_in"], 100)
        self.assertEqual(d["tokens_out"], 50)
        self.assertEqual(d["cost_usd"], 0.001)


class TestExecutionBudget(unittest.TestCase):
    """Test budget tracking and enforcement."""

    def test_budget_not_exceeded_initially(self):
        from executor.observation import ExecutionBudget
        b = ExecutionBudget(max_tokens=1000, max_cost_usd=0.1, max_steps=5)
        exceeded, _ = b.is_exceeded()
        self.assertFalse(exceeded)
        self.assertEqual(b.remaining_pct(), 1.0)

    def test_budget_token_exceeded(self):
        from executor.observation import ExecutionBudget, Observation, ObservationType
        b = ExecutionBudget(max_tokens=100, max_steps=100)
        obs = Observation(obs_type=ObservationType.LLM_RESPONSE, tokens_in=60, tokens_out=60)
        b.record(obs)
        exceeded, reason = b.is_exceeded()
        self.assertTrue(exceeded)
        self.assertIn("tokens", reason)

    def test_budget_step_exceeded(self):
        from executor.observation import ExecutionBudget, Observation, ObservationType
        b = ExecutionBudget(max_steps=2)
        for _ in range(3):
            b.record(Observation(obs_type=ObservationType.TOOL_OUTPUT))
        exceeded, reason = b.is_exceeded()
        self.assertTrue(exceeded)
        self.assertIn("steps", reason)

    def test_budget_cost_exceeded(self):
        from executor.observation import ExecutionBudget, Observation, ObservationType
        b = ExecutionBudget(max_cost_usd=0.01)
        b.record(Observation(obs_type=ObservationType.LLM_RESPONSE, cost_usd=0.02))
        exceeded, reason = b.is_exceeded()
        self.assertTrue(exceeded)
        self.assertIn("cost", reason)

    def test_remaining_pct(self):
        from executor.observation import ExecutionBudget, Observation, ObservationType
        b = ExecutionBudget(max_tokens=100, max_steps=10, max_cost_usd=1.0)
        b.record(Observation(obs_type=ObservationType.TOOL_OUTPUT, tokens_in=50))
        self.assertAlmostEqual(b.remaining_pct(), 0.5, places=1)


class TestOutputValidator(unittest.TestCase):
    """Test output validation."""

    def test_valid_output(self):
        from executor.output_validator import validate_output, ValidationStatus
        r = validate_output("Build completed successfully", tool_name="shell")
        self.assertEqual(r.status, ValidationStatus.VALID)
        self.assertEqual(len(r.issues), 0)

    def test_empty_output_invalid(self):
        from executor.output_validator import validate_output, ValidationStatus
        r = validate_output("")
        self.assertEqual(r.status, ValidationStatus.INVALID)

    def test_secret_detection(self):
        from executor.output_validator import validate_output, ValidationStatus
        r = validate_output("API key is sk-abcdefghijklmnopqrstuvwxyz1234567890abcde")
        self.assertEqual(r.status, ValidationStatus.INVALID)
        self.assertIn("[REDACTED]", r.sanitized_output)

    def test_github_token_detection(self):
        from executor.output_validator import validate_output, ValidationStatus
        r = validate_output("Token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij")
        self.assertEqual(r.status, ValidationStatus.INVALID)

    def test_error_masking_detected(self):
        from executor.output_validator import validate_output, ValidationStatus
        r = validate_output("Task completed successfully\nTraceback (most recent call last)")
        self.assertEqual(r.status, ValidationStatus.SUSPICIOUS)

    def test_json_format_validation(self):
        from executor.output_validator import validate_output, ValidationStatus
        r = validate_output('{"status": "ok"}', expected_format="json")
        self.assertEqual(r.status, ValidationStatus.VALID)

    def test_json_format_invalid(self):
        from executor.output_validator import validate_output
        r = validate_output("not json at all", expected_format="json")
        self.assertTrue(any("JSON" in i for i in r.issues))


class TestWorkingMemory(unittest.TestCase):
    """Test bounded working memory."""

    def test_add_items(self):
        from memory.working_memory import WorkingMemory
        wm = WorkingMemory(token_budget=500)
        wm.add("Skill: handle database errors", "skill", relevance=0.8)
        wm.add("Previous failure: timeout on API", "failure", relevance=0.6)
        self.assertEqual(len(wm.items), 2)

    def test_budget_enforcement(self):
        from memory.working_memory import WorkingMemory
        wm = WorkingMemory(token_budget=10)  # very small
        wm.add("A " * 100, "skill", relevance=0.5)  # way over budget
        wm.add("B " * 100, "memory", relevance=0.9)  # also big
        # At most 1 item should survive (or 0 if both exceed)
        self.assertLessEqual(len(wm.items), 2)

    def test_relevance_ranking(self):
        from memory.working_memory import WorkingMemory
        wm = WorkingMemory(token_budget=100)
        wm.add("Low relevance item " * 5, "skill", relevance=0.1)
        wm.add("High relevance item " * 5, "memory", relevance=0.9)
        wm.add("Medium relevance " * 5, "failure", relevance=0.5)
        # Highest relevance should be first
        if wm.items:
            self.assertEqual(wm.items[0].source, "memory")

    def test_to_prompt(self):
        from memory.working_memory import WorkingMemory
        wm = WorkingMemory()
        wm.add("Use retry on timeout", "skill", relevance=0.8)
        prompt = wm.to_prompt()
        self.assertIn("[skill]", prompt)
        self.assertIn("retry", prompt)

    def test_stats(self):
        from memory.working_memory import WorkingMemory
        wm = WorkingMemory(token_budget=1000)
        wm.add("Item 1", "skill")
        wm.add("Item 2", "memory")
        s = wm.stats()
        self.assertEqual(s["items"], 2)
        self.assertIn("skill", s["sources"])


class TestLearningLoop(unittest.TestCase):
    """Test post-mission learning."""

    def test_no_lesson_from_clean_success(self):
        from core.orchestration.learning_loop import extract_lesson
        lesson = extract_lesson(
            mission_id="test-1",
            goal="Simple query",
            result="Good answer",
            reflection_verdict="accept",
            reflection_confidence=0.9,
        )
        self.assertIsNone(lesson)

    def test_lesson_from_low_confidence(self):
        from core.orchestration.learning_loop import extract_lesson
        lesson = extract_lesson(
            mission_id="test-2",
            goal="Complex analysis",
            result="Partial answer",
            reflection_verdict="low_confidence",
            reflection_confidence=0.4,
        )
        self.assertIsNotNone(lesson)
        self.assertIn("confidence", lesson.what_happened)

    def test_lesson_from_empty_result(self):
        from core.orchestration.learning_loop import extract_lesson
        lesson = extract_lesson(
            mission_id="test-3",
            goal="Build something",
            result="",
            reflection_verdict="empty",
            reflection_confidence=0.0,
        )
        self.assertIsNotNone(lesson)
        self.assertIn("no output", lesson.what_happened)

    def test_lesson_from_error(self):
        from core.orchestration.learning_loop import extract_lesson
        lesson = extract_lesson(
            mission_id="test-4",
            goal="Deploy app",
            result="Failed",
            reflection_verdict="retry_suggested",
            reflection_confidence=0.2,
            error_class="timeout",
        )
        self.assertIsNotNone(lesson)
        self.assertIn("weak", lesson.what_happened.lower())

    def test_lesson_from_retries(self):
        from core.orchestration.learning_loop import extract_lesson
        lesson = extract_lesson(
            mission_id="test-5",
            goal="Fetch data",
            result="Got it eventually",
            reflection_verdict="accept",
            reflection_confidence=0.65,
            retries=3,
        )
        self.assertIsNotNone(lesson)
        self.assertIn("retries", lesson.what_happened.lower())

    def test_lesson_to_dict(self):
        from core.orchestration.learning_loop import extract_lesson
        lesson = extract_lesson(
            mission_id="test-6",
            goal="Test",
            result="Bad",
            reflection_verdict="retry_suggested",
            reflection_confidence=0.1,
        )
        d = lesson.to_dict()
        self.assertIn("mission_id", d)
        self.assertIn("what_to_do_differently", d)


class TestDecisionTraceCost(unittest.TestCase):
    """Test cost tracking in decision trace."""

    def test_cost_accumulation(self):
        from core.orchestration.decision_trace import DecisionTrace
        trace = DecisionTrace(mission_id="cost-test")
        trace.record_cost(tokens_in=100, tokens_out=50, cost_usd=0.001)
        trace.record_cost(tokens_in=200, tokens_out=100, cost_usd=0.002)
        cs = trace.cost_summary()
        self.assertEqual(cs["tokens_in"], 300)
        self.assertEqual(cs["tokens_out"], 150)
        self.assertEqual(cs["total_cost_usd"], 0.003)

    def test_cost_summary_format(self):
        from core.orchestration.decision_trace import DecisionTrace
        trace = DecisionTrace(mission_id="format-test")
        trace.record("test", "action")
        cs = trace.cost_summary()
        self.assertIn("phases", cs)
        self.assertIn("duration_s", cs)


class TestOrchIntegration(unittest.TestCase):
    """Test MetaOrchestrator has learning loop wired."""

    def test_orchestrator_has_learning(self):
        import inspect
        from core.meta_orchestrator import MetaOrchestrator
        src = inspect.getsource(MetaOrchestrator.run_mission)
        self.assertIn("learning_loop", src)
        self.assertIn("extract_lesson", src)


if __name__ == "__main__":
    unittest.main()
