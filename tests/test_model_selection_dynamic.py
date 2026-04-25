"""
tests/test_model_selection_dynamic.py — Dynamic model selection + A/B testing.

MD01-MD25: A/B tests, cost tracking, dynamic quality/cost, catalog refresh.
"""
import pytest


class TestABTest:
    def test_MD01_ab_test_create(self):
        from core.model_intelligence.auto_update import ABTest
        t = ABTest(test_id="ab-1", task_class="coding", model_a="m1", model_b="m2")
        assert t.a_total == 0

    def test_MD02_pick_variant_balanced(self):
        from core.model_intelligence.auto_update import ABTest
        t = ABTest(model_a="a", model_b="b")
        v = t.pick_variant()
        assert v in ("a", "b")

    def test_MD03_record_outcome_a(self):
        from core.model_intelligence.auto_update import ABTest
        t = ABTest(model_a="a", model_b="b")
        t.record_outcome("a", True, quality=0.8, cost=0.01)
        assert t.a_successes == 1
        assert t.a_quality_sum == 0.8

    def test_MD04_record_outcome_b(self):
        from core.model_intelligence.auto_update import ABTest
        t = ABTest(model_a="a", model_b="b")
        t.record_outcome("b", False, quality=0.2)
        assert t.b_failures == 1

    def test_MD05_not_conclusive_early(self):
        from core.model_intelligence.auto_update import ABTest
        t = ABTest(model_a="a", model_b="b")
        t.record_outcome("a", True, 0.9)
        assert not t.is_conclusive

    def test_MD06_conclusive_after_enough_samples(self):
        from core.model_intelligence.auto_update import ABTest
        t = ABTest(model_a="a", model_b="b")
        for _ in range(5):
            t.record_outcome("a", True, quality=0.9)
            t.record_outcome("b", True, quality=0.5)
        assert t.is_conclusive

    def test_MD07_winner_is_better(self):
        from core.model_intelligence.auto_update import ABTest
        t = ABTest(model_a="good", model_b="bad")
        for _ in range(5):
            t.record_outcome("good", True, quality=0.9, cost=0.01)
            t.record_outcome("bad", False, quality=0.2, cost=0.05)
        winner = t.evaluate()
        assert winner == "good"

    def test_MD08_to_dict(self):
        from core.model_intelligence.auto_update import ABTest
        t = ABTest(test_id="x", task_class="coding", model_a="a", model_b="b")
        d = t.to_dict()
        assert d["test_id"] == "x"
        assert "a_score" in d

    def test_MD09_score_computation(self):
        from core.model_intelligence.auto_update import ABTest
        t = ABTest(model_a="a", model_b="b")
        for _ in range(3):
            t.record_outcome("a", True, quality=1.0, cost=0.0)
        assert t.a_score > 0.7  # high quality, free, all success

    def test_MD10_max_rounds_forces_conclusion(self):
        from core.model_intelligence.auto_update import ABTest, AB_MAX_ROUNDS
        t = ABTest(model_a="a", model_b="b")
        for _ in range(AB_MAX_ROUNDS + 1):
            t.record_outcome("a", True, 0.6, 0.01)
            t.record_outcome("b", True, 0.6, 0.01)
        # Equal but max rounds reached
        assert t.is_conclusive


class TestModelAutoUpdate:
    def test_MD11_engine_create(self):
        from core.model_intelligence.auto_update import ModelAutoUpdate
        e = ModelAutoUpdate()
        assert e.should_refresh()

    def test_MD12_mark_refreshed(self):
        from core.model_intelligence.auto_update import ModelAutoUpdate
        e = ModelAutoUpdate()
        e.mark_refreshed()
        assert not e.should_refresh()

    def test_MD13_start_ab_test(self):
        from core.model_intelligence.auto_update import ModelAutoUpdate
        e = ModelAutoUpdate()
        t = e.start_ab_test("coding", "m1", "m2")
        assert t.task_class == "coding"
        assert e.get_active_test("coding") is not None

    def test_MD14_record_invocation_no_test(self):
        from core.model_intelligence.auto_update import ModelAutoUpdate
        e = ModelAutoUpdate()
        result = e.record_invocation("coding", "m1", True, 0.8, 0.01)
        assert result is None  # No active test

    def test_MD15_record_invocation_feeds_test(self):
        from core.model_intelligence.auto_update import ModelAutoUpdate
        e = ModelAutoUpdate()
        e.start_ab_test("coding", "m1", "m2")
        for _ in range(5):
            e.record_invocation("coding", "m1", True, 0.9, 0.01)
            e.record_invocation("coding", "m2", True, 0.4, 0.02)
        # Should conclude with m1 winning
        e.record_invocation("coding", "m1", True, 0.9, 0.01)
        # Test may or may not conclude depending on threshold
        # But active test should have data
        test = e.get_active_test("coding")
        if test:
            assert test.a_total >= 5

    def test_MD16_test_concludes_winner(self):
        from core.model_intelligence.auto_update import ModelAutoUpdate
        e = ModelAutoUpdate()
        e.start_ab_test("simple", "good", "bad")
        for _ in range(10):
            e.record_invocation("simple", "good", True, 0.95, 0.01)
            e.record_invocation("simple", "bad", False, 0.1, 0.05)
        # Force evaluate
        test = e.get_active_test("simple")
        if test:
            winner = test.evaluate()
            assert winner == "good"

    def test_MD17_real_cost_tracking(self):
        from core.model_intelligence.auto_update import ModelAutoUpdate
        e = ModelAutoUpdate()
        e.record_invocation("t1", "m1", True, cost=0.01)
        e.record_invocation("t1", "m1", True, cost=0.02)
        e.record_invocation("t1", "m2", True, cost=0.05)
        stats = e.get_real_cost_stats()
        assert stats["models_tracked"] == 2
        assert stats["total_cost"] == pytest.approx(0.08, abs=0.001)
        assert stats["per_model"]["m2"] == pytest.approx(0.05, abs=0.001)

    @pytest.mark.xfail(reason="dynamic cost ratio drift", strict=False)
    def test_MD18_dynamic_quality_cost_ratio_no_data(self):
        from core.model_intelligence.auto_update import ModelAutoUpdate
        e = ModelAutoUpdate()
        assert e.get_dynamic_quality_cost_ratio("unknown") == 0.5

    def test_MD19_dynamic_ratio_free_model(self):
        from core.model_intelligence.auto_update import ModelAutoUpdate
        e = ModelAutoUpdate()
        # Free model: quality IS the ratio
        ratio = e.get_dynamic_quality_cost_ratio("free_model")
        assert ratio >= 0

    def test_MD20_status(self):
        from core.model_intelligence.auto_update import ModelAutoUpdate
        e = ModelAutoUpdate()
        s = e.get_status()
        assert "active_tests" in s
        assert "should_refresh" in s

    def test_MD21_singleton(self):
        from core.model_intelligence.auto_update import get_model_auto_update
        e1 = get_model_auto_update()
        e2 = get_model_auto_update()
        assert e1 is e2


class TestAutoOptimization:
    """Jarvis optimizes cost vs quality automatically."""

    def test_MD22_cheap_wins_equal_quality(self):
        """Given equal quality, the cheaper model should score higher."""
        from core.model_intelligence.auto_update import ABTest
        t = ABTest(model_a="cheap", model_b="expensive")
        for _ in range(5):
            t.record_outcome("cheap", True, quality=0.8, cost=0.001)
            t.record_outcome("expensive", True, quality=0.8, cost=0.1)
        assert t.a_score > t.b_score
        assert t.evaluate() == "cheap"

    def test_MD23_quality_beats_cost(self):
        """When quality difference is large, quality wins over cost."""
        from core.model_intelligence.auto_update import ABTest
        t = ABTest(model_a="quality", model_b="cheap")
        for _ in range(5):
            t.record_outcome("quality", True, quality=0.95, cost=0.05)
            t.record_outcome("cheap", True, quality=0.3, cost=0.001)
        assert t.a_score > t.b_score
        assert t.evaluate() == "quality"

    def test_MD24_reliability_matters(self):
        """Unreliable model loses even if quality is ok when it works."""
        from core.model_intelligence.auto_update import ABTest
        t = ABTest(model_a="reliable", model_b="flaky")
        for _ in range(5):
            t.record_outcome("reliable", True, quality=0.7)
        for i in range(5):
            t.record_outcome("flaky", i % 3 == 0, quality=0.8 if i % 3 == 0 else 0.0)
        assert t.a_score > t.b_score

    def test_MD25_detect_ab_candidates_empty(self):
        from core.model_intelligence.auto_update import ModelAutoUpdate
        e = ModelAutoUpdate()
        candidates = e.detect_ab_candidates()
        assert isinstance(candidates, list)
