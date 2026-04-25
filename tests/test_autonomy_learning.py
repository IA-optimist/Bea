"""Unit tests for core.autonomy.learning."""
from __future__ import annotations

import time
import unittest

from core.autonomy.event_bus import EventBus, reset_event_bus
from core.autonomy.learning import OutcomeLearner, reset_outcome_learner


class TestOutcomeLearner(unittest.TestCase):
    def setUp(self):
        reset_event_bus()
        reset_outcome_learner()
        self.bus = EventBus()
        self.learner = OutcomeLearner(bus=self.bus)

    def test_no_data_returns_neutral_score(self):
        self.assertAlmostEqual(self.learner.score("never-seen"), 0.5)

    def test_records_action_success_and_failure(self):
        self.bus.publish("autonomy.iteration.completed", {"action": "scan"})
        self.bus.publish("autonomy.iteration.completed", {"action": "scan"})
        self.bus.publish("autonomy.iteration.failed", {"action": "scan"})
        # 2 success / 1 fail → score above neutral
        s = self.learner.score("scan")
        self.assertGreater(s, 0.5)

    def test_records_skill_success(self):
        for _ in range(5):
            self.bus.publish("skill.completed", {"skill": "audit"})
        for _ in range(1):
            self.bus.publish("skill.failed", {"skill": "audit"})
        s = self.learner.score("audit")
        self.assertGreater(s, 0.5)

    def test_skill_failure_drives_score_down(self):
        for _ in range(5):
            self.bus.publish("skill.failed", {"skill": "flaky"})
        s = self.learner.score("flaky")
        self.assertLess(s, 0.5)

    def test_recommendation_ranks_candidates(self):
        # nmap : 3 success
        for _ in range(3):
            self.bus.publish("skill.completed", {"skill": "nmap"})
        # nuclei : 1 success / 2 fail
        self.bus.publish("skill.completed", {"skill": "nuclei"})
        for _ in range(2):
            self.bus.publish("skill.failed", {"skill": "nuclei"})

        ranked = self.learner.recommendation(["nmap", "nuclei"], prefix="skill:")
        names = [r[0] for r in ranked]
        self.assertEqual(names[0], "nmap")
        self.assertEqual(names[1], "nuclei")

    def test_snapshot_includes_recorded_actions(self):
        self.bus.publish("skill.completed", {"skill": "x"})
        snap = self.learner.snapshot()
        self.assertIn("skill:x", snap)
        self.assertIn("score", snap["skill:x"])

    def test_event_without_action_or_skill_is_ignored(self):
        # Should not crash, should not record anything
        self.bus.publish("autonomy.iteration.completed", {})
        self.bus.publish("skill.completed", {})
        self.assertEqual(self.learner.snapshot(), {})

    def test_detach_stops_recording(self):
        self.learner.detach()
        self.bus.publish("skill.completed", {"skill": "x"})
        self.assertEqual(self.learner.snapshot(), {})

    def test_score_is_smoothed_for_low_data(self):
        # 1 success → smoothed score is moderate, not 1.0
        self.bus.publish("skill.completed", {"skill": "fresh"})
        s = self.learner.score("fresh")
        self.assertGreater(s, 0.5)
        self.assertLess(s, 0.85)


if __name__ == "__main__":
    unittest.main()
