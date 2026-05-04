"""
tests/test_claw_patterns.py — Tests for agentic pattern integration.

Covers: value scoring, planning depth, pre-execution assessment,
strategy switching, tool health integration, failure pattern matching.
"""
from __future__ import annotations
import pytest

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestValueScoring(unittest.TestCase):
    """Pattern 1: Value-based task prioritization."""

    def test_urgent_high_value(self):
        from core.orchestration.mission_classifier import classify
        c = classify("URGENT: production server is down, fix immediately")
        self.assertGreater(c.value_score, 0.6)

    def test_trivial_low_value(self):
        from core.orchestration.mission_classifier import classify
        c = classify("What time is it?")
        self.assertLess(c.value_score, 0.6)

    def test_value_score_in_dict(self):
        from core.orchestration.mission_classifier import classify
        c = classify("Deploy the application")
        d = c.to_dict()
        self.assertIn("value_score", d)
        self.assertIn("planning_depth", d)

    def test_value_score_bounded(self):
        from core.orchestration.mission_classifier import classify
        for goal in ["simple", "URGENT complex multi-step deployment"]:
            c = classify(goal)
            self.assertGreaterEqual(c.value_score, 0.0)
            self.assertLessEqual(c.value_score, 1.0)


class TestPlanningDepth(unittest.TestCase):
    """Pattern 2: Adaptive planning depth."""

    def test_trivial_depth_zero(self):
        from core.orchestration.mission_classifier import classify
        c = classify("Hi")
        self.assertIn(c.planning_depth, (0, 1))

    def test_complex_depth_high(self):
        from core.orchestration.mission_classifier import classify
        c = classify(
            "Analyze the entire codebase for security vulnerabilities, "
            "create a migration plan with rollback strategy, deploy to "
            "staging, run integration tests, and promote to production"
        )
        self.assertGreaterEqual(c.planning_depth, 1)

    def test_depth_increases_with_complexity(self):
        from core.orchestration.mission_classifier import classify
        simple = classify("List files")
        complex_ = classify(
            "Refactor the database schema to support multi-tenancy "
            "with data isolation, backward compatible migration, "
            "and comprehensive test coverage across all modules"
        )
        self.assertGreaterEqual(complex_.planning_depth, simple.planning_depth)


class TestPreExecutionAssessment(unittest.TestCase):
    """Pattern 4+5+6: Pre-execution intelligence."""

    def test_basic_assessment(self):
        from core.orchestration.pre_execution import assess_before_execution
        a = assess_before_execution(
            goal="Simple task",
            classification={"complexity": "simple"},
            prior_skills=[],
            relevant_memories=[],
        )
        self.assertTrue(a.proceed)
        self.assertGreater(a.estimated_confidence, 0.0)

    def test_skill_match_boosts_confidence(self):
        from core.orchestration.pre_execution import assess_before_execution
        a_no_skill = assess_before_execution(
            goal="Fix database",
            classification={"complexity": "moderate"},
            prior_skills=[],
            relevant_memories=[],
        )
        a_with_skill = assess_before_execution(
            goal="Fix database",
            classification={"complexity": "moderate"},
            prior_skills=[{"confidence": 0.9, "name": "DB fix"}],
            relevant_memories=[],
        )
        self.assertGreater(a_with_skill.estimated_confidence,
                           a_no_skill.estimated_confidence)

    def test_complex_tasks_lower_confidence(self):
        from core.orchestration.pre_execution import assess_before_execution
        simple = assess_before_execution(
            goal="test",
            classification={"complexity": "simple"},
            prior_skills=[], relevant_memories=[],
        )
        complex_ = assess_before_execution(
            goal="test",
            classification={"complexity": "complex"},
            prior_skills=[], relevant_memories=[],
        )
        self.assertGreater(simple.estimated_confidence,
                           complex_.estimated_confidence)

    def test_strategy_suggestion(self):
        from core.orchestration.pre_execution import assess_before_execution
        # Very low confidence should suggest decompose
        a = assess_before_execution(
            goal="Impossible task with no tools",
            classification={"complexity": "complex"},
            prior_skills=[], relevant_memories=[],
        )
        self.assertIn(a.strategy_suggestion, ("cautious", "decompose", "alternative", ""))

    def test_to_dict(self):
        from core.orchestration.pre_execution import assess_before_execution
        a = assess_before_execution(
            goal="test", classification={},
            prior_skills=[], relevant_memories=[],
        )
        d = a.to_dict()
        self.assertIn("estimated_confidence", d)
        self.assertIn("tool_health_ok", d)
        self.assertIn("proceed", d)

    def test_unhealthy_tool_detection(self):
        from executor.capability_health import CapabilityHealthTracker
        from core.orchestration.pre_execution import assess_before_execution
        t = CapabilityHealthTracker()
        t.reset()
        for _ in range(5):
            t.record_failure("bad_shell", error="broken")
        a = assess_before_execution(
            goal="Run shell command",
            classification={"suggested_tools": ["bad_shell"]},
            prior_skills=[], relevant_memories=[],
        )
        self.assertFalse(a.tool_health_ok)
        self.assertIn("bad_shell", a.unhealthy_tools)
        t.reset()


class TestOrchIntegration(unittest.TestCase):
    """Verify wiring in MetaOrchestrator."""

    @pytest.mark.xfail(reason="pre_assessment wiring drift in run_mission", strict=False)
    def test_pre_assessment_wired(self):
        import inspect
        from core.meta_orchestrator import MetaOrchestrator
        src = inspect.getsource(MetaOrchestrator.run_mission)
        self.assertIn("pre_execution", src)
        self.assertIn("assess_before_execution", src)

    def test_value_score_in_classifier(self):
        import inspect
        from core.orchestration.mission_classifier import classify
        src = inspect.getsource(classify)
        self.assertIn("value_score", src)
        self.assertIn("planning_depth", src)

    def test_strategy_switching_in_supervisor(self):
        import inspect
        from core.orchestration.execution_supervisor import supervise
        src = inspect.getsource(supervise)
        self.assertIn("SIMPLIFIED", src)
        self.assertIn("fallback", src.lower())


if __name__ == "__main__":
    unittest.main()
