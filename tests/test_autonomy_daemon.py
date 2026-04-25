"""Unit tests for core.autonomy.daemon + stop_conditions."""
from __future__ import annotations

import os
import time
import unittest

from core.autonomy.budget import Budget, BudgetTracker, reset_budget_tracker
from core.autonomy.daemon import (
    ActionResult,
    AutonomyDaemon,
    PlannedAction,
)
from core.autonomy.event_bus import EventBus, reset_event_bus
from core.autonomy.stop_conditions import (
    all_of,
    always_false,
    always_true,
    any_of,
    confidence_condition,
    consecutive_failures_condition,
    default_mission_policy,
    iteration_condition,
    StopContext,
    timeout_condition,
)


class TestStopConditions(unittest.TestCase):
    def test_timeout_triggers(self):
        cond = timeout_condition(0.05)
        ctx = StopContext()
        time.sleep(0.1)
        self.assertTrue(cond(ctx))

    def test_iteration_triggers(self):
        cond = iteration_condition(3)
        ctx = StopContext(iteration=3)
        self.assertTrue(cond(ctx))
        ctx2 = StopContext(iteration=2)
        self.assertFalse(cond(ctx2))

    def test_confidence_triggers(self):
        cond = confidence_condition(0.5)
        self.assertTrue(cond(StopContext(confidence=0.4)))
        self.assertFalse(cond(StopContext(confidence=0.6)))

    def test_failures_triggers(self):
        cond = consecutive_failures_condition(3)
        self.assertTrue(cond(StopContext(consecutive_failures=3)))
        self.assertFalse(cond(StopContext(consecutive_failures=2)))

    def test_any_of_triggers_when_first_true(self):
        cond = any_of(always_true(), always_false())
        self.assertTrue(cond(StopContext()))

    def test_all_of_triggers_only_when_all_true(self):
        c1 = all_of(always_true(), always_true())
        c2 = all_of(always_true(), always_false())
        self.assertTrue(c1(StopContext()))
        self.assertFalse(c2(StopContext()))

    def test_default_policy_combines(self):
        # Triggered by iteration limit
        cond = default_mission_policy(max_iterations=2, max_seconds=0)
        self.assertTrue(cond(StopContext(iteration=3)))


class TestAutonomyDaemon(unittest.TestCase):
    def setUp(self):
        reset_event_bus()
        reset_budget_tracker()
        self.bus = EventBus()
        self.budget = BudgetTracker(daily_budget=Budget())  # unlimited daily
        os.environ.pop("JARVIS_AUTONOMY_PAUSED", None)

    def _make_daemon(self, **kw) -> AutonomyDaemon:
        defaults = {
            "objective": "test-goal",
            "bus": self.bus,
            "budget": self.budget,
            "mission_id": kw.pop("mission_id", "test-loop"),
            "mission_budget": kw.pop(
                "mission_budget",
                Budget(max_tokens=10_000, max_usd=1.0, max_seconds=60, max_consecutive_failures=2),
            ),
        }
        defaults.update(kw)
        return AutonomyDaemon(**defaults)

    def test_run_once_succeeds_with_default_planner(self):
        d = self._make_daemon()
        r = d.run_once()
        self.assertIsNotNone(r)
        self.assertTrue(r.success)
        self.assertEqual(d.context.iteration, 1)

    def test_run_once_halts_on_empty_objective(self):
        d = self._make_daemon(objective="")
        self.assertIsNone(d.run_once())

    def test_stop_policy_halts_loop(self):
        d = self._make_daemon(stop_policy=always_true())
        self.assertIsNone(d.run_once())

    def test_paused_via_env_halts(self):
        os.environ["JARVIS_AUTONOMY_PAUSED"] = "1"
        d = self._make_daemon()
        self.assertIsNone(d.run_once())
        os.environ.pop("JARVIS_AUTONOMY_PAUSED")

    def test_run_forever_respects_max_iters(self):
        d = self._make_daemon()
        history = d.run_forever(max_iters=3, sleep_s=0)
        self.assertEqual(len(history), 3)

    def test_failed_action_increments_consecutive(self):
        def runner(action):
            return ActionResult(success=False, error="boom")
        d = self._make_daemon(action_runner=runner)
        d.run_once()
        d.run_once()
        # Third should halt because policy says max_consecutive_failures=2
        d.run_once()
        # Either halted (None) or executed but tripped budget
        # Either way the daemon stops here
        self.assertGreaterEqual(d.context.consecutive_failures, 2)

    def test_success_resets_failure_counter(self):
        results_iter = iter([
            ActionResult(success=False),
            ActionResult(success=True, confidence=0.9),
            ActionResult(success=False),
        ])

        def runner(_a):
            return next(results_iter)

        d = self._make_daemon(action_runner=runner)
        d.run_once()
        self.assertEqual(d.context.consecutive_failures, 1)
        d.run_once()
        self.assertEqual(d.context.consecutive_failures, 0)
        d.run_once()
        self.assertEqual(d.context.consecutive_failures, 1)

    def test_publishes_lifecycle_events(self):
        captured = []
        self.bus.subscribe("autonomy.*", lambda e: captured.append(e.topic))
        d = self._make_daemon()
        d.run_once()
        self.assertIn("autonomy.iteration.started", captured)
        self.assertIn("autonomy.iteration.completed", captured)

    def test_stop_signal_halts_loop(self):
        d = self._make_daemon()
        d.stop()
        self.assertIsNone(d.run_once())

    def test_runner_exception_recorded_as_failure(self):
        def runner(_a):
            raise RuntimeError("crashed")
        d = self._make_daemon(action_runner=runner)
        r = d.run_once()
        self.assertIsNotNone(r)
        self.assertFalse(r.success)
        self.assertIn("crashed", r.error)


if __name__ == "__main__":
    unittest.main()
