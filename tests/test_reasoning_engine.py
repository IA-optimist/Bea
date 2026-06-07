"""
tests/test_reasoning_engine.py — Reasoning Engine Tests

Validates practical intelligence improvements:
- Problem framing accuracy
- Prioritization correctness
- Output shape selection
- Self-critique sensitivity
- Repo-aware reasoning
- Judgment signal computation
- Integrated reasoning pre-pass
"""
import unittest
import sys
import os
import pytest
pytestmark = pytest.mark.integration


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestProblemFraming(unittest.TestCase):
    """Phase 1: Does Bea correctly identify what actually matters?"""

    def test_RE01_direct_question_complexity(self):
        """Direct questions should be classified as direct_answer."""
        from core.orchestration.reasoning_engine import frame_problem
        frame = frame_problem("What is the current API version?")
        self.assertEqual(frame.complexity_class, "direct_answer")

    def test_RE02_bug_fix_complexity(self):
        """Bug reports should be classified as small_fix."""
        from core.orchestration.reasoning_engine import frame_problem
        frame = frame_problem("Fix the 404 error on the /api/health endpoint")
        self.assertEqual(frame.complexity_class, "small_fix")

    def test_RE03_investigation_complexity(self):
        """Analysis tasks should be classified as investigation."""
        from core.orchestration.reasoning_engine import frame_problem
        frame = frame_problem("Analyze why the test suite is slow and diagnose the bottleneck")
        self.assertEqual(frame.complexity_class, "investigation")

    def test_RE04_multi_step_complexity(self):
        """Complex tasks with multiple verbs should be multi_step."""
        from core.orchestration.reasoning_engine import frame_problem
        frame = frame_problem(
            "Build a new authentication system, implement JWT tokens, "
            "design the database schema, and deploy to production"
        )
        self.assertEqual(frame.complexity_class, "multi_step")

    def test_RE05_bottleneck_from_prior_failures(self):
        """Prior failures should be the strongest bottleneck signal."""
        from core.orchestration.reasoning_engine import frame_problem
        frame = frame_problem(
            "Deploy the API",
            prior_failures=["Deployment failed: Docker image too large"]
        )
        self.assertIn("failed before", frame.likely_bottleneck)

    def test_RE06_essential_vs_optional_decomposition(self):
        """Tasks with explicit optional markers should be split correctly."""
        from core.orchestration.reasoning_engine import frame_problem
        frame = frame_problem(
            "Fix the login bug. Optional: add rate limiting. Never delete the user table."
        )
        self.assertTrue(len(frame.essential) >= 1)
        self.assertTrue(len(frame.optional) >= 1)
        self.assertTrue(len(frame.do_not_do) >= 1)

    def test_RE07_smallest_next_move_for_direct(self):
        """Direct answer tasks should have simple next move."""
        from core.orchestration.reasoning_engine import frame_problem
        frame = frame_problem("What is Python?")
        self.assertEqual(frame.smallest_next_move, "Answer the question directly")

    def test_RE08_real_problem_strips_noise(self):
        """Noise like 'please' and 'can you' should be removed."""
        from core.orchestration.reasoning_engine import frame_problem
        frame = frame_problem("Please can you fix the database connection issue")
        self.assertNotIn("please", frame.real_problem.lower())

    def test_RE09_true_objective_for_code_tasks(self):
        """Code tasks should have working code as objective."""
        from core.orchestration.reasoning_engine import frame_problem
        frame = frame_problem(
            "Fix the auth bug",
            classification={"task_type": "code"}
        )
        self.assertIn("code", frame.true_objective.lower())

    def test_RE10_frame_to_dict(self):
        """Frame should serialize to dict."""
        from core.orchestration.reasoning_engine import frame_problem
        frame = frame_problem("Test task")
        d = frame.to_dict()
        self.assertIn("real_problem", d)
        self.assertIn("likely_bottleneck", d)
        self.assertIn("smallest_next_move", d)

    def test_RE11_frame_to_prompt_context(self):
        """Frame should produce concise prompt injection."""
        from core.orchestration.reasoning_engine import frame_problem
        frame = frame_problem("Fix the 404 error")
        ctx = frame.to_prompt_context()
        self.assertIn("PROBLEM:", ctx)
        self.assertIn("OBJECTIVE:", ctx)
        self.assertIn("BOTTLENECK:", ctx)


class TestPrioritization(unittest.TestCase):
    """Phase 2: Does Bea prioritize correctly?"""

    def test_RE12_crash_is_critical(self):
        """Crashes should be critical blockers."""
        from core.orchestration.reasoning_engine import prioritize_issues
        result = prioritize_issues(["Application crash on startup"])
        self.assertEqual(result[0].priority.value, "critical_blocker")

    def test_RE13_auth_failure_is_critical(self):
        """Auth failures should be critical blockers."""
        from core.orchestration.reasoning_engine import prioritize_issues
        result = prioritize_issues(["401 Unauthorized on API endpoint"])
        self.assertEqual(result[0].priority.value, "critical_blocker")

    def test_RE14_style_is_noise(self):
        """Style issues should be noise."""
        from core.orchestration.reasoning_engine import prioritize_issues
        result = prioritize_issues(["Whitespace formatting inconsistency"])
        self.assertEqual(result[0].priority.value, "noise")

    def test_RE15_sorted_by_leverage(self):
        """Issues should be sorted by leverage, highest first."""
        from core.orchestration.reasoning_engine import prioritize_issues
        result = prioritize_issues([
            "Missing type hint on helper function",
            "Application crash on startup",
            "Slow performance on dashboard",
        ])
        self.assertEqual(result[0].priority.value, "critical_blocker")
        self.assertGreater(result[0].leverage, result[-1].leverage)

    def test_RE16_goal_relevance_boost(self):
        """Issues related to current goal should get priority boost."""
        from core.orchestration.reasoning_engine import prioritize_issues
        result = prioritize_issues(
            ["Database connection timeout", "Dashboard color mismatch"],
            goal="Fix the database connection issue"
        )
        self.assertGreater(result[0].leverage, result[1].leverage)
        self.assertIn("database", result[0].description.lower())

    def test_RE17_empty_issues(self):
        """Empty issue list should return empty."""
        from core.orchestration.reasoning_engine import prioritize_issues
        result = prioritize_issues([])
        self.assertEqual(result, [])


class TestOutputShapeSelection(unittest.TestCase):
    """Phase 3: Does Bea pick the right response format?"""

    def test_RE18_question_gets_direct_answer(self):
        """Questions should get direct answers."""
        from core.orchestration.reasoning_engine import select_output_shape, frame_problem
        frame = frame_problem("What is the API version?")
        shape = select_output_shape("What is the API version?", frame)
        self.assertEqual(shape.value, "direct_answer")

    def test_RE19_bug_gets_patch(self):
        """Bug fix requests should get patches."""
        from core.orchestration.reasoning_engine import select_output_shape, frame_problem
        frame = frame_problem("Fix the 404 bug in login")
        shape = select_output_shape("Fix the 404 bug in login", frame)
        self.assertEqual(shape.value, "patch")

    def test_RE20_analysis_gets_report(self):
        """Analysis requests should get reports."""
        from core.orchestration.reasoning_engine import select_output_shape, frame_problem
        frame = frame_problem("Analyze the test coverage and review gaps")
        shape = select_output_shape("Analyze the test coverage and review gaps", frame)
        self.assertEqual(shape.value, "report")

    def test_RE21_build_gets_plan(self):
        """Complex build requests should get plans."""
        from core.orchestration.reasoning_engine import select_output_shape, frame_problem
        frame = frame_problem("Build a new payment system with Stripe integration and deploy it")
        shape = select_output_shape("Build a new payment system with Stripe integration and deploy it", frame)
        self.assertEqual(shape.value, "plan")

    def test_RE22_diagnosis_for_why_questions(self):
        """'Why' questions about bugs should get diagnosis."""
        from core.orchestration.reasoning_engine import select_output_shape, frame_problem
        frame = frame_problem("Why does the auth endpoint return 401?")
        shape = select_output_shape("Why does the auth endpoint return 401?", frame)
        self.assertIn(shape.value, ("diagnosis", "direct_answer"))


class TestSelfCritique(unittest.TestCase):
    """Phase 4: Does Bea detect weak outputs?"""

    def test_RE23_empty_output_is_weak(self):
        """Empty output should be flagged as weak."""
        from core.orchestration.reasoning_engine import critique_output
        result = critique_output("Fix the bug", "")
        self.assertTrue(result.is_weak)
        self.assertEqual(result.overall_score, 0.0)

    def test_RE24_generic_output_detected(self):
        """Generic filler text should score low on specificity."""
        from core.orchestration.reasoning_engine import critique_output
        result = critique_output(
            "Fix the database connection timeout in store.py",
            "In general, there are many ways to fix database issues. "
            "It is important to consider best practices. Typically you should check configuration."
        )
        self.assertLess(result.specificity_score, 0.5)

    def test_RE25_specific_output_scores_high(self):
        """Specific output with concrete details should score well."""
        from core.orchestration.reasoning_engine import critique_output
        result = critique_output(
            "Fix the database connection timeout in store.py",
            "Fixed `memory/store.py` line 105: changed timeout from 2s to 10s.\n"
            "```python\n_qdrant_kwargs['timeout'] = 10\n```\n"
            "The database connection was timing out because the default 2s timeout "
            "is too short for initial Qdrant collection creation."
        )
        self.assertGreater(result.specificity_score, 0.3)
        self.assertGreater(result.usability_score, 0.4)

    def test_RE26_overcomplicated_detected(self):
        """Short task with huge output should be flagged."""
        from core.orchestration.reasoning_engine import critique_output
        long_output = "## Section 1\n" + "blah " * 800 + "\n## Section 2\n" + "stuff " * 800
        result = critique_output("What is 2+2?", long_output)
        self.assertTrue(any("overcomplicated" in w.lower() for w in result.weaknesses))

    def test_RE27_error_output_detected(self):
        """Error messages masquerading as results should be caught."""
        from core.orchestration.reasoning_engine import critique_output
        result = critique_output(
            "Build the API",
            "Traceback (most recent call last):\nError: unable to import module\nFailed to start"
        )
        self.assertTrue(any("error" in w.lower() for w in result.weaknesses))

    def test_RE28_critique_to_dict(self):
        """Critique should serialize properly."""
        from core.orchestration.reasoning_engine import critique_output
        result = critique_output("Test", "Result text here")
        d = result.to_dict()
        self.assertIn("is_weak", d)
        self.assertIn("overall", d)
        self.assertIn("specificity", d)

    def test_RE29_bottleneck_coverage_check(self):
        """Output should address the identified bottleneck."""
        from core.orchestration.reasoning_engine import (
            critique_output, ProblemFrame,
        )
        frame = ProblemFrame(
            real_problem="Auth failure",
            true_objective="Working auth",
            likely_bottleneck="JWT token validation is broken",
            essential=["Fix JWT"], optional=[], do_not_do=[],
            smallest_next_move="Check JWT", complexity_class="small_fix",
        )
        result = critique_output(
            "Fix the auth system",
            "Updated the CSS colors on the login page for better visibility.",
            frame=frame,
        )
        self.assertTrue(any("bottleneck" in w.lower() for w in result.weaknesses))


class TestRepoAwareness(unittest.TestCase):
    """Phase 5: Does Bea reason about the codebase?"""

    def test_RE30_kernel_risk_detection(self):
        """Changes to kernel should be high risk."""
        from core.orchestration.reasoning_engine import assess_repo_context
        awareness = assess_repo_context(
            "Modify the kernel contracts",
            proposed_files=["kernel/contracts/core.py"]
        )
        self.assertEqual(awareness.risk_level, "high")

    def test_RE31_api_layer_detection(self):
        """API tasks should target api layer."""
        from core.orchestration.reasoning_engine import assess_repo_context
        awareness = assess_repo_context("Add a new REST endpoint for user profiles")
        self.assertEqual(awareness.target_layer, "api")

    def test_RE32_memory_layer_detection(self):
        """Memory tasks should target memory layer."""
        from core.orchestration.reasoning_engine import assess_repo_context
        awareness = assess_repo_context("Fix the RAG embedding search")
        self.assertEqual(awareness.target_layer, "memory")

    def test_RE33_fail_open_pattern_included(self):
        """Core layer changes should include fail-open pattern."""
        from core.orchestration.reasoning_engine import assess_repo_context
        awareness = assess_repo_context("Improve the planning engine")
        self.assertTrue(any("fail-open" in p.lower() for p in awareness.existing_patterns))

    def test_RE34_anti_patterns_present(self):
        """Anti-patterns should always be provided."""
        from core.orchestration.reasoning_engine import assess_repo_context
        awareness = assess_repo_context("Any code change")
        self.assertTrue(len(awareness.anti_patterns) >= 1)

    def test_RE35_delete_is_high_risk(self):
        """Delete operations should be high risk."""
        from core.orchestration.reasoning_engine import assess_repo_context
        awareness = assess_repo_context("Delete the old authentication module")
        self.assertEqual(awareness.risk_level, "high")


class TestJudgmentSignals(unittest.TestCase):
    """Phase 6: Are judgment signals computed correctly?"""

    def test_RE36_zero_retries_is_good(self):
        """Zero retries = first choice correct."""
        from core.orchestration.reasoning_engine import (
            compute_judgment_signals, ProblemFrame, CritiqueResult,
        )
        frame = ProblemFrame(
            real_problem="test", true_objective="test",
            likely_bottleneck="none", essential=[], optional=[],
            do_not_do=[], smallest_next_move="test",
            complexity_class="small_fix", confidence=0.8,
        )
        critique = CritiqueResult(
            is_weak=False, weaknesses=[], improvement_suggestion="",
            specificity_score=0.8, completeness_score=0.9,
            usability_score=0.8, overall_score=0.83,
        )
        signals = compute_judgment_signals(frame, critique, retries=0)
        self.assertTrue(signals.first_choice_correct)
        self.assertEqual(signals.unnecessary_steps, 0)

    def test_RE37_retries_signal_problems(self):
        """Multiple retries indicate poor first judgment."""
        from core.orchestration.reasoning_engine import (
            compute_judgment_signals, ProblemFrame, CritiqueResult,
        )
        frame = ProblemFrame(
            real_problem="test", true_objective="test",
            likely_bottleneck="none", essential=[], optional=[],
            do_not_do=[], smallest_next_move="test",
            complexity_class="small_fix",
        )
        critique = CritiqueResult(
            is_weak=True, weaknesses=["generic"], improvement_suggestion="be specific",
            specificity_score=0.3, completeness_score=0.4,
            usability_score=0.3, overall_score=0.33,
        )
        signals = compute_judgment_signals(frame, critique, retries=3)
        self.assertFalse(signals.first_choice_correct)
        self.assertEqual(signals.retries_needed, 3)
        self.assertGreater(signals.unnecessary_steps, 0)


class TestIntegratedReasoning(unittest.TestCase):
    """Full reasoning pre-pass integration."""

    def test_RE38_reason_returns_complete_result(self):
        """reason() should return all components."""
        from core.orchestration.reasoning_engine import reason
        result = reason("Fix the auth bug in api/auth.py")
        self.assertIsNotNone(result.frame)
        self.assertIsNotNone(result.output_shape)
        self.assertIsNotNone(result.enriched_goal)
        self.assertGreater(len(result.enriched_goal), len("Fix the auth bug in api/auth.py"))

    def test_RE39_reason_includes_repo_context_for_code(self):
        """Code tasks should include repo awareness."""
        from core.orchestration.reasoning_engine import reason
        result = reason("Fix the bug in the kernel module")
        self.assertIsNotNone(result.repo_awareness)

    def test_RE40_reason_to_dict(self):
        """ReasoningResult should serialize."""
        from core.orchestration.reasoning_engine import reason
        result = reason("Analyze the system performance")
        d = result.to_dict()
        self.assertIn("frame", d)
        self.assertIn("output_shape", d)
        self.assertIn("reasoning_ms", d)

    def test_RE41_reason_prompt_injection(self):
        """Prompt injection should be concise and useful."""
        from core.orchestration.reasoning_engine import reason
        result = reason("Fix the database timeout error")
        injection = result.to_prompt_injection()
        self.assertIn("PROBLEM:", injection)
        self.assertIn("OUTPUT FORMAT:", injection)

    def test_RE42_reason_performance(self):
        """Reasoning pre-pass should be fast (<100ms without LLM)."""
        import time
        from core.orchestration.reasoning_engine import reason
        t0 = time.time()
        reason("Complex task with many requirements and multiple steps to implement")
        elapsed_ms = (time.time() - t0) * 1000
        self.assertLess(elapsed_ms, 100, f"Reasoning took {elapsed_ms:.0f}ms — too slow")

    def test_RE43_bottleneck_identification(self):
        """Should correctly identify bottleneck type."""
        from core.orchestration.reasoning_engine import frame_problem
        # External dependency
        frame = frame_problem("Call the external API to fetch user data")
        self.assertIn("external", frame.likely_bottleneck.lower())
        # Permission
        frame2 = frame_problem("Grant access to the admin dashboard")
        self.assertIn("access", frame2.likely_bottleneck.lower())

    def test_RE44_do_not_do_preserved(self):
        """Explicit 'do not' instructions should be preserved."""
        from core.orchestration.reasoning_engine import frame_problem
        frame = frame_problem("Improve the code. Never delete the database. Avoid breaking changes.")
        combined = " ".join(frame.do_not_do).lower()
        self.assertTrue("delete" in combined or "break" in combined)

    def test_RE45_prioritize_to_dict(self):
        """Prioritized issues should serialize."""
        from core.orchestration.reasoning_engine import prioritize_issues
        result = prioritize_issues(["Crash on startup", "Missing docstring"])
        for item in result:
            d = item.to_dict()
            self.assertIn("priority", d)
            self.assertIn("leverage", d)


if __name__ == "__main__":
    unittest.main()
