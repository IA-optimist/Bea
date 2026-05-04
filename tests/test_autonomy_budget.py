"""Unit tests for core.autonomy.budget."""
from __future__ import annotations

import time
import unittest

from core.autonomy.budget import (
    Budget,
    BudgetExceeded,
    BudgetTracker,
    get_budget_tracker,
    reset_budget_tracker,
)


class TestBudgetTracker(unittest.TestCase):
    def setUp(self):
        reset_budget_tracker()
        self.bt = BudgetTracker(daily_budget=Budget(max_tokens=10_000, max_usd=1.0))

    def test_singleton_returns_same(self):
        a = get_budget_tracker()
        b = get_budget_tracker()
        self.assertIs(a, b)

    def test_charge_under_limit_succeeds(self):
        self.bt.start_mission("m1", limits=Budget(max_tokens=1000, max_usd=0.1))
        self.bt.charge("m1", tokens=100, usd=0.01)
        snap = self.bt.snapshot()
        self.assertEqual(snap["missions"]["m1"]["tokens"], 100)

    def test_charge_over_mission_token_limit_raises(self):
        self.bt.start_mission("m1", limits=Budget(max_tokens=500, max_usd=0))
        with self.assertRaises(BudgetExceeded) as ctx:
            self.bt.charge("m1", tokens=600)
        self.assertEqual(ctx.exception.scope, "mission")
        self.assertEqual(ctx.exception.dimension, "tokens")

    def test_charge_over_mission_usd_limit_raises(self):
        self.bt.start_mission("m1", limits=Budget(max_usd=0.5))
        with self.assertRaises(BudgetExceeded) as ctx:
            self.bt.charge("m1", usd=0.6)
        self.assertEqual(ctx.exception.dimension, "usd")

    def test_daily_limit_enforced(self):
        bt = BudgetTracker(daily_budget=Budget(max_tokens=100))
        with self.assertRaises(BudgetExceeded) as ctx:
            bt.charge(tokens=200)
        self.assertEqual(ctx.exception.scope, "daily")

    def test_consecutive_failures_caps(self):
        self.bt.start_mission("m1", limits=Budget(max_consecutive_failures=2))
        self.bt.record_failure("m1")
        self.bt.record_failure("m1")
        with self.assertRaises(BudgetExceeded):
            self.bt.record_failure("m1")

    def test_success_resets_failure_counter(self):
        self.bt.start_mission("m1", limits=Budget(max_consecutive_failures=2))
        self.bt.record_failure("m1")
        self.bt.record_success("m1")
        # Two more failures don't trip because the counter was reset
        self.bt.record_failure("m1")
        self.bt.record_failure("m1")
        with self.assertRaises(BudgetExceeded):
            self.bt.record_failure("m1")

    def test_end_mission_clears_state(self):
        self.bt.start_mission("m1", limits=Budget(max_tokens=100))
        self.bt.charge("m1", tokens=50)
        usage = self.bt.end_mission("m1")
        self.assertIsNotNone(usage)
        self.assertEqual(usage.tokens, 50)
        # After end, no mission state
        self.assertNotIn("m1", self.bt.snapshot()["missions"])

    def test_charge_without_active_mission_only_hits_daily(self):
        self.bt.charge(tokens=10)  # no mission_id
        snap = self.bt.snapshot()
        self.assertEqual(snap["daily"]["tokens"], 10)
        self.assertEqual(snap["missions"], {})

    def test_max_seconds_enforced(self):
        bt = BudgetTracker(daily_budget=Budget())
        bt.start_mission("m1", limits=Budget(max_seconds=0.05))
        time.sleep(0.1)
        with self.assertRaises(BudgetExceeded) as ctx:
            bt.charge("m1", tokens=1)
        self.assertEqual(ctx.exception.dimension, "seconds")

    def test_zero_limits_mean_unlimited(self):
        bt = BudgetTracker(daily_budget=Budget())  # all zero
        bt.start_mission("m1", limits=Budget())
        # Big charges should pass without raising
        bt.charge("m1", tokens=10**9, usd=10**6)


if __name__ == "__main__":
    unittest.main()
