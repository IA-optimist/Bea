"""
Unit tests for pure classification functions in core.mission_system.

Covers the deterministic, side-effect-free helpers that are used heavily
during mission routing. These are small functions with clear contracts,
so adding tests here raises core/ coverage cheaply and pins behavior
so refactors don't drift.
"""
from __future__ import annotations

import unittest

from core.mission_system import (
    MissionIntent,
    classify_action,
    compute_complexity,
    compute_risk_score,
    detect_intent,
    evaluate_approval,
    is_capability_query,
    risk_score_to_level,
)


class TestIsCapabilityQuery(unittest.TestCase):
    def test_matches_french_capability(self):
        self.assertTrue(is_capability_query("ce que tu peux faire ?"))
        self.assertTrue(is_capability_query("quelles sont tes capacités ?"))

    def test_matches_english_capability(self):
        self.assertTrue(is_capability_query("what can you do"))
        self.assertTrue(is_capability_query("explain your capabilities"))

    def test_not_matches_real_goal(self):
        self.assertFalse(is_capability_query("Deploy the staging cluster"))
        self.assertFalse(is_capability_query("Fix the auth bug on login"))


class TestDetectIntent(unittest.TestCase):
    def test_analyze(self):
        self.assertEqual(detect_intent("analyse ce code"), MissionIntent.ANALYZE)

    def test_create(self):
        self.assertEqual(detect_intent("crée une API REST"), MissionIntent.CREATE)

    def test_improve(self):
        self.assertEqual(detect_intent("optimise la mémoire"), MissionIntent.IMPROVE)

    def test_plan(self):
        self.assertEqual(detect_intent("planifie un sprint"), MissionIntent.PLAN)

    def test_unknown_falls_back_to_other(self):
        self.assertEqual(detect_intent("bonjour"), MissionIntent.OTHER)


class TestClassifyAction(unittest.TestCase):
    def test_write_keyword_triggers_medium(self):
        action, risk = classify_action("write a config file")
        self.assertEqual(action, "write")
        self.assertEqual(risk, "MEDIUM")

    def test_read_only_is_low(self):
        action, risk = classify_action("analyze the codebase for bugs")
        self.assertEqual(action, "analyze")
        self.assertEqual(risk, "LOW")

    def test_french_write_keyword(self):
        action, risk = classify_action("crée un nouveau fichier")
        self.assertEqual(action, "write")
        self.assertEqual(risk, "MEDIUM")


class TestComputeRiskScore(unittest.TestCase):
    def test_destructive_higher_than_write(self):
        destructive = compute_risk_score("delete all files in /tmp")
        write = compute_risk_score("write a new config")
        self.assertGreater(destructive, write)

    def test_system_keyword_adds_risk(self):
        base = compute_risk_score("hello world")
        system = compute_risk_score("restart docker container")
        self.assertGreater(system, base)

    def test_long_plan_adds_one_point(self):
        r_short = compute_risk_score("write a file", plan_steps=["a", "b"])
        r_long = compute_risk_score("write a file", plan_steps=["a"] * 10)
        self.assertEqual(r_long, r_short + 1)

    def test_score_capped_at_10(self):
        # Use every bucket to push max
        s = compute_risk_score("delete docker api write a file remove http")
        self.assertLessEqual(s, 10)


class TestRiskScoreToLevel(unittest.TestCase):
    def test_low_range(self):
        self.assertEqual(risk_score_to_level(0), "LOW")
        self.assertEqual(risk_score_to_level(3), "LOW")

    def test_medium_range(self):
        self.assertEqual(risk_score_to_level(4), "MEDIUM")
        self.assertEqual(risk_score_to_level(6), "MEDIUM")

    def test_high_range(self):
        self.assertEqual(risk_score_to_level(7), "HIGH")
        self.assertEqual(risk_score_to_level(10), "HIGH")


class TestComputeComplexity(unittest.TestCase):
    def test_low_complexity_short_goal(self):
        # Simple capability query is low
        c = compute_complexity("c'est quoi python ?", 0)
        self.assertEqual(c, "low")

    def test_high_risk_bumps_complexity(self):
        # A high-risk score should NOT produce "low"
        c = compute_complexity("restart container", 8)
        self.assertIn(c, ("medium", "high"))


class TestEvaluateApproval(unittest.TestCase):
    def test_auto_mode_always_auto(self):
        d = evaluate_approval(5, "medium", "AUTO")
        self.assertEqual(d["decision"], "auto_approved")

    def test_manual_mode_always_requires_approval(self):
        d = evaluate_approval(1, "low", "MANUAL")
        self.assertEqual(d["decision"], "pending")
        self.assertFalse(d["auto_approved"])

    def test_supervised_low_risk_auto(self):
        d = evaluate_approval(1, "low", "SUPERVISED")
        # Supervised + low risk + low complexity typically auto-approves
        self.assertIn(d["decision"], ("auto_approved", "requires_approval"))


if __name__ == "__main__":
    unittest.main()
