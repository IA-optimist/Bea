"""Tests for the wiring layer : runners, planners, approval bridge."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from core.autonomy import (
    AutonomyDaemon,
    Budget,
    PlannedAction,
    StopContext,
    cancel_pending_choices_older_than,
    chain_planner,
    composite_runner,
    learner_aware_planner,
    objective_engine_planner,
    request_strategy_choice,
    reset_event_bus,
    reset_multi_choice_store,
    reset_outcome_learner,
    static_planner,
    static_response_runner,
)
from core.autonomy.approval_bridge import StrategyChoice
from core.autonomy.daemon import ActionResult
from core.autonomy.event_bus import EventBus
from core.autonomy.learning import OutcomeLearner


class TestStaticHelpers(unittest.TestCase):
    def test_static_response_runner_success(self):
        r = static_response_runner(success=True, output={"x": 1})
        result = r(PlannedAction(name="a"))
        self.assertTrue(result.success)
        self.assertEqual(result.output, {"x": 1})

    def test_static_response_runner_failure(self):
        r = static_response_runner(success=False)
        result = r(PlannedAction(name="a"))
        self.assertFalse(result.success)

    def test_static_planner_returns_same_action(self):
        action = PlannedAction(name="x", description="y")
        p = static_planner(action)
        self.assertIs(p("any-objective", StopContext()), action)


class TestCompositeRunner(unittest.TestCase):
    def test_first_success_wins(self):
        runner = composite_runner(
            static_response_runner(success=False),
            static_response_runner(success=True, output="ok"),
        )
        result = runner(PlannedAction(name="a"))
        self.assertTrue(result.success)
        self.assertEqual(result.output, "ok")

    def test_all_fail_returns_failure(self):
        runner = composite_runner(
            static_response_runner(success=False),
            static_response_runner(success=False),
        )
        self.assertFalse(runner(PlannedAction(name="a")).success)

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            composite_runner()

    def test_runner_exception_falls_through(self):
        def crashing(_a):
            raise RuntimeError("bad")

        runner = composite_runner(
            crashing,
            static_response_runner(success=True, output="recovered"),
        )
        result = runner(PlannedAction(name="a"))
        self.assertTrue(result.success)
        self.assertEqual(result.output, "recovered")


def _none_planner(_obj, _ctx):
    return None


class TestChainPlanner(unittest.TestCase):
    def test_first_non_none_wins(self):
        action = PlannedAction(name="x")
        chained = chain_planner(_none_planner, static_planner(action))
        self.assertIs(chained("o", StopContext()), action)

    def test_all_none_returns_none(self):
        chained = chain_planner(_none_planner, _none_planner)
        self.assertIsNone(chained("o", StopContext()))

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            chain_planner()

    def test_planner_exception_skipped(self):
        def crashing(_o, _c):
            raise RuntimeError("bad")
        action = PlannedAction(name="ok")
        chained = chain_planner(crashing, static_planner(action))
        self.assertIs(chained("o", StopContext()), action)


class TestObjectiveEnginePlanner(unittest.TestCase):
    def test_no_active_objectives_returns_none(self):
        eng = MagicMock()
        eng.get_next_best_action.return_value = {"action_type": "no_active_objectives"}
        p = objective_engine_planner(eng)
        self.assertIsNone(p("o", StopContext()))

    def test_returns_planned_action_with_payload(self):
        eng = MagicMock()
        eng.get_next_best_action.return_value = {
            "action_type": "scan",
            "rationale": "scan target",
            "confidence": 0.8,
            "objective_id": "obj-1",
            "node_id": "n-1",
            "required_tools": ["nmap"],
            "suggested_agent": "scout",
            "requires_human_approval": False,
        }
        p = objective_engine_planner(eng)
        action = p("o", StopContext())
        self.assertIsNotNone(action)
        self.assertEqual(action.name, "scan")
        self.assertEqual(action.payload["objective_id"], "obj-1")
        self.assertEqual(action.payload["confidence"], 0.8)

    def test_engine_exception_returns_none(self):
        eng = MagicMock()
        eng.get_next_best_action.side_effect = RuntimeError("broken")
        p = objective_engine_planner(eng)
        self.assertIsNone(p("o", StopContext()))


class TestLearnerAwarePlanner(unittest.TestCase):
    def setUp(self):
        reset_event_bus()
        reset_outcome_learner()

    def test_high_score_passes_through(self):
        bus = EventBus()
        learner = OutcomeLearner(bus=bus)
        # Seed many successes for "scan"
        for _ in range(10):
            bus.publish("autonomy.iteration.completed", {"action": "scan"})

        action = PlannedAction(name="scan", description="ok")
        wrapped = learner_aware_planner(static_planner(action), learner, min_score=0.3)
        result = wrapped("o", StopContext())
        self.assertNotIn("downgraded", result.payload)

    def test_low_score_marks_downgraded(self):
        bus = EventBus()
        learner = OutcomeLearner(bus=bus)
        for _ in range(10):
            bus.publish("autonomy.iteration.failed", {"action": "flaky"})

        action = PlannedAction(name="flaky", description="risky")
        wrapped = learner_aware_planner(static_planner(action), learner, min_score=0.5)
        result = wrapped("o", StopContext())
        self.assertTrue(result.payload.get("downgraded"))
        self.assertIn("low-score", result.description)

    def test_passes_through_none(self):
        learner = OutcomeLearner(bus=EventBus())
        wrapped = learner_aware_planner(_none_planner, learner)
        self.assertIsNone(wrapped("o", StopContext()))


class TestApprovalBridge(unittest.TestCase):
    def setUp(self):
        reset_event_bus()
        reset_multi_choice_store()

    def test_request_strategy_choice_creates_decision(self):
        d = request_strategy_choice(
            name="rotate",
            question="Which rotation strategy?",
            strategies=[
                StrategyChoice(label="canary", description="10% first", risk_level="low"),
                StrategyChoice(label="big-bang", description="all at once", risk_level="high"),
            ],
            timeout_s=60.0,
            mirror_to_approval_queue=False,
        )
        self.assertEqual(d.status, "pending")
        self.assertEqual(len(d.choices), 2)
        self.assertEqual(d.metadata["max_risk_level"], "high")

    def test_request_with_empty_strategies_raises(self):
        with self.assertRaises(ValueError):
            request_strategy_choice(
                name="x",
                question="?",
                strategies=[],
                mirror_to_approval_queue=False,
            )

    def test_strategy_metadata_preserved(self):
        d = request_strategy_choice(
            name="a",
            question="?",
            strategies=[
                StrategyChoice(
                    label="opt-a",
                    description="d",
                    risk_level="medium",
                    estimated_cost_usd=0.5,
                    estimated_duration_s=120,
                    rollback_plan="git revert",
                ),
            ],
            mirror_to_approval_queue=False,
        )
        self.assertEqual(d.choices[0].metadata["risk_level"], "medium")
        self.assertEqual(d.choices[0].metadata["estimated_cost_usd"], 0.5)
        self.assertEqual(d.choices[0].metadata["rollback_plan"], "git revert")

    def test_cancel_old_pending_decisions(self):
        request_strategy_choice(
            name="old",
            question="?",
            strategies=[StrategyChoice(label="a", description="d")],
            mirror_to_approval_queue=False,
        )
        # Sweep with cutoff -1s (in the future) → all pending get cancelled
        cancelled = cancel_pending_choices_older_than(seconds=-1)
        self.assertGreaterEqual(cancelled, 1)


class TestDaemonWithStaticHelpers(unittest.TestCase):
    """End-to-end : daemon with static planner + runner."""

    def setUp(self):
        reset_event_bus()

    def test_daemon_runs_with_static_helpers(self):
        action = PlannedAction(name="step", description="do")
        d = AutonomyDaemon(
            objective="test",
            planner=static_planner(action),
            action_runner=static_response_runner(success=True, output="ok"),
            mission_budget=Budget(max_tokens=100, max_usd=1.0, max_seconds=10),
        )
        history = d.run_forever(max_iters=3, sleep_s=0)
        self.assertEqual(len(history), 3)
        self.assertTrue(all(r.success for r in history))


if __name__ == "__main__":
    unittest.main()
