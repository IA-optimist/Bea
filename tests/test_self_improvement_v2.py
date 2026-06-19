"""tests/test_self_improvement_v2.py — Tests for controlled self-improvement loop."""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import types
if 'structlog' not in sys.modules:
    _sl = types.ModuleType('structlog')
    class _ML:
        def info(self, *a, **k): pass
        def debug(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def error(self, *a, **k): pass
        def bind(self, **k): return self
    _sl.get_logger = lambda *a, **k: _ML()
    sys.modules['structlog'] = _sl


# ── Goal Registry ────────────────────────────────────────────────────────────

class TestGoalRegistry(unittest.TestCase):

    def test_default_goals_exist(self):
        from core.self_improvement.goal_registry import get_goal_registry
        reg = get_goal_registry()
        goals = reg.list_goals()
        self.assertEqual(len(goals), 8)

    def test_goal_evaluation_improvement(self):
        from core.self_improvement.goal_registry import get_goal_registry
        reg = get_goal_registry()
        result = reg.evaluate("reduce_mission_cost", 0.30)
        self.assertTrue(result["improved"])
        self.assertGreater(result["delta"], 0)

    def test_goal_evaluation_regression(self):
        from core.self_improvement.goal_registry import get_goal_registry
        reg = get_goal_registry()
        result = reg.evaluate("reduce_mission_cost", 0.80)
        self.assertFalse(result["improved"])

    def test_reject_vague_goal(self):
        from core.self_improvement.goal_registry import ImprovementGoalRegistry, ImprovementGoal
        reg = ImprovementGoalRegistry()
        with self.assertRaises(ValueError):
            reg.register(ImprovementGoal(
                goal_id="vague",
                description="be better",
                metric_name="",
                baseline_value=0,
                target_direction="up",
            ))

    def test_list_by_importance(self):
        from core.self_improvement.goal_registry import get_goal_registry
        reg = get_goal_registry()
        critical = reg.list_by_importance("CRITICAL")
        self.assertTrue(all(g.importance == "CRITICAL" for g in critical))


# ── Benchmark Suite ──────────────────────────────────────────────────────────

class TestBenchmarkSuite(unittest.TestCase):

    def test_default_benchmarks(self):
        from core.self_improvement.benchmark_suite import get_benchmark_suite
        suite = get_benchmark_suite()
        scenarios = suite.list_scenarios()
        self.assertEqual(len(scenarios), 8)

    def test_evaluate_passing(self):
        from core.self_improvement.benchmark_suite import get_benchmark_suite
        suite = get_benchmark_suite()
        scenario = suite.get_scenario("simple_answer")
        result = suite.evaluate_result(scenario, {
            "status": "DONE",
            "result_envelope": {
                "trace_id": "tr-test",
                "status": "COMPLETED",
                "agent_outputs": [],
                "metrics": {"duration_seconds": 5.0},
            },
        })
        self.assertTrue(result.passed)

    def test_evaluate_missing_trace(self):
        from core.self_improvement.benchmark_suite import get_benchmark_suite
        suite = get_benchmark_suite()
        scenario = suite.get_scenario("trace_continuity")
        result = suite.evaluate_result(scenario, {
            "status": "DONE",
            "result_envelope": {
                "trace_id": "",
                "status": "COMPLETED",
                "agent_outputs": [],
                "metrics": {},
            },
        })
        self.assertFalse(result.passed)
        self.assertIn("trace_id", result.error)


# ── Critic ───────────────────────────────────────────────────────────────────

class TestImprovementCritic(unittest.TestCase):

    def test_accept_clean_experiment(self):
        from core.self_improvement.improvement_loop import ImprovementCritic, ExperimentResult
        critic = ImprovementCritic()
        exp = ExperimentResult(
            experiment_id="e1", candidate_id="c1", hypothesis="test",
            baseline_pass_rate=0.8, candidate_pass_rate=0.9,
            baseline_cost=0.5, candidate_cost=0.45,
            schema_intact=True, trace_intact=True, safety_intact=True,
            improvements=["cost_reduced"], regressions=[],
        )
        review = critic.review(exp)
        self.assertEqual(review.verdict, "ACCEPT")

    def test_reject_schema_violation(self):
        from core.self_improvement.improvement_loop import ImprovementCritic, ExperimentResult
        critic = ImprovementCritic()
        exp = ExperimentResult(
            experiment_id="e2", candidate_id="c2", hypothesis="test",
            schema_intact=False,
        )
        review = critic.review(exp)
        self.assertEqual(review.verdict, "REJECT")
        self.assertTrue(review.security_regression)

    def test_reject_safety_regression(self):
        from core.self_improvement.improvement_loop import ImprovementCritic, ExperimentResult
        critic = ImprovementCritic()
        exp = ExperimentResult(
            experiment_id="e3", candidate_id="c3", hypothesis="test",
            safety_intact=False,
        )
        review = critic.review(exp)
        self.assertEqual(review.verdict, "REJECT")

    def test_flag_cost_inflation(self):
        from core.self_improvement.improvement_loop import ImprovementCritic, ExperimentResult
        critic = ImprovementCritic()
        exp = ExperimentResult(
            experiment_id="e4", candidate_id="c4", hypothesis="test",
            baseline_cost=0.50, candidate_cost=0.70,
            schema_intact=True, trace_intact=True, safety_intact=True,
        )
        review = critic.review(exp)
        self.assertTrue(review.hidden_cost_inflation)


# ── Adoption Gate ────────────────────────────────────────────────────────────

class TestAdoptionGate(unittest.TestCase):

    def _clean_experiment(self):
        from core.self_improvement.improvement_loop import ExperimentResult
        return ExperimentResult(
            experiment_id="e-gate", candidate_id="c-gate", hypothesis="improve config",
            touched_modules=["config/policy.yaml"],
            risk_level="LOW",
            baseline_pass_rate=0.8, candidate_pass_rate=0.9,
            baseline_cost=0.5, candidate_cost=0.45,
            schema_intact=True, trace_intact=True, safety_intact=True,
            improvements=["cost_reduced"], regressions=[],
        )

    def test_auto_adopt_low_risk(self):
        from core.self_improvement.improvement_loop import AdoptionGate, ImprovementCritic
        gate = AdoptionGate()
        critic = ImprovementCritic()
        exp = self._clean_experiment()
        review = critic.review(exp)
        decision = gate.decide(exp, review)
        self.assertEqual(decision.outcome, "APPROVE_FOR_REVIEW")
        self.assertTrue(decision.requires_human_review)
        self.assertTrue(decision.auto_adopt_eligible)

    def test_reject_on_critic_reject(self):
        from core.self_improvement.improvement_loop import AdoptionGate, CriticReview, ExperimentResult
        gate = AdoptionGate()
        exp = ExperimentResult(experiment_id="e", candidate_id="c", hypothesis="bad",
                              schema_intact=False)
        review = CriticReview(candidate_id="c", verdict="REJECT",
                             security_regression=True, concerns=["schema broken"])
        decision = gate.decide(exp, review)
        self.assertEqual(decision.outcome, "REJECT")

    def test_protected_scope_blocks_auto_adopt(self):
        from core.self_improvement.improvement_loop import AdoptionGate, ImprovementCritic, ExperimentResult
        gate = AdoptionGate()
        critic = ImprovementCritic()
        exp = ExperimentResult(
            experiment_id="e", candidate_id="c", hypothesis="test",
            touched_modules=["core/schemas/final_output.py"],
            risk_level="LOW",
            baseline_pass_rate=0.8, candidate_pass_rate=1.0,
            improvements=["better"], regressions=[],
            schema_intact=True, trace_intact=True, safety_intact=True,
        )
        review = critic.review(exp)
        decision = gate.decide(exp, review)
        self.assertNotEqual(decision.outcome, "AUTO_ADOPT")
        self.assertEqual(decision.outcome, "APPROVE_FOR_REVIEW")


# ── Full Loop ────────────────────────────────────────────────────────────────

class TestImprovementLoop(unittest.TestCase):

    def test_full_evaluation_accept(self):
        from core.self_improvement.improvement_loop import get_improvement_loop
        loop = get_improvement_loop()
        decision = loop.evaluate_candidate(
            candidate_id="c-full-1",
            hypothesis="Reduce policy thresholds",
            touched_modules=["config/policy.yaml"],
            risk_level="LOW",
            baseline_report={"pass_rate": 0.8, "total_cost": 0.5},
            candidate_report={
                "pass_rate": 0.9, "total_cost": 0.4,
                "improvements": ["cost"], "regressions": [],
                "schema_intact": True, "trace_intact": True, "safety_intact": True,
            },
        )
        self.assertEqual(decision.outcome, "APPROVE_FOR_REVIEW")

    def test_full_evaluation_reject(self):
        from core.self_improvement.improvement_loop import get_improvement_loop
        loop = get_improvement_loop()
        decision = loop.evaluate_candidate(
            candidate_id="c-full-2",
            hypothesis="Risky schema change",
            touched_modules=["core/schemas/final_output.py"],
            risk_level="HIGH",
            baseline_report={"pass_rate": 0.9, "total_cost": 0.5},
            candidate_report={
                "pass_rate": 0.7, "total_cost": 0.8,
                "improvements": [], "regressions": ["schema"],
                "schema_intact": False, "trace_intact": True, "safety_intact": True,
            },
        )
        self.assertEqual(decision.outcome, "REJECT")

    def test_history_recorded(self):
        from core.self_improvement.improvement_loop import get_improvement_loop
        loop = get_improvement_loop()
        history = loop.get_history()
        self.assertGreater(len(history), 0)

    def test_has_tried_prevents_retry(self):
        from core.self_improvement.improvement_loop import ImprovementLoop
        loop = ImprovementLoop()
        loop.evaluate_candidate(
            candidate_id="c-retry",
            hypothesis="Bad idea",
            touched_modules=[],
            risk_level="LOW",
            baseline_report={"pass_rate": 0.9},
            candidate_report={"pass_rate": 0.5, "schema_intact": False, "safety_intact": True, "trace_intact": True},
        )
        self.assertTrue(loop.has_tried("Bad idea"))


if __name__ == "__main__":
    unittest.main()
