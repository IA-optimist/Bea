"""
Tests — Agent Evaluation Engine

Part 2: Metrics Collection
  E1. EvaluationMetrics has all fields
  E2. Metrics to_dict serializes correctly
  E3. MetricsCollector doesn't crash with empty runtime
  E4. MetricsCollector returns EvaluationMetrics

Part 3: Scoring Model
  E5. Perfect metrics → high score
  E6. Terrible metrics → low score
  E7. Score has 6 dimensions
  E8. Custom weights respected
  E9. DimensionScore weighted calculation

Part 4: Weakness Detection
  E10. Low success rate detected
  E11. Excessive retries detected
  E12. Frequent timeouts detected
  E13. Poor tool selection detected
  E14. High cost detected
  E15. Low autonomy detected
  E16. No weaknesses for good metrics
  E17. Priorities sorted by impact

Part 5: Integration with Improvement Loop
  E18. get_improvement_signals produces signal dicts
  E19. Signal dicts have required fields

Part 6: Evaluation Memory
  E20. Store and retrieve history
  E21. Evolution tracking (improved)
  E22. Evolution tracking (regressed)
  E23. Regression detection
  E24. Trend data
  E25. Persistence survives reload

Part 7: Reporting
  E26. EvaluationReport to_dict
  E27. EvaluationReport summary text
  E28. Summary includes evolution

Part 8: Full Engine
  E29. Full evaluate cycle
  E30. Evaluate from pre-built metrics
  E31. Multiple evaluations track evolution
  E32. Engine trend endpoint
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.evaluation_engine import (
    EvaluationMetrics, MetricsCollector,
    DimensionScore, AgentScore, ScoringModel, WeaknessType, WeaknessDetector,
    EvaluationMemory,
    EvaluationReport, AgentEvaluationEngine,
)


# ═══════════════════════════════════════════════════════════════
# PART 2: METRICS COLLECTION
# ═══════════════════════════════════════════════════════════════

class TestMetricsCollection:

    def test_metrics_fields(self):
        """E1: All fields present."""
        m = EvaluationMetrics()
        assert hasattr(m, "success_rate")
        assert hasattr(m, "retry_rate")
        assert hasattr(m, "timeout_rate")
        assert hasattr(m, "avg_cost_usd")
        assert hasattr(m, "avg_latency_ms")
        assert hasattr(m, "tool_success_rate")
        assert hasattr(m, "approval_rate")
        assert hasattr(m, "patch_success_rate")
        assert hasattr(m, "exception_count")

    def test_metrics_serialization(self):
        """E2: to_dict serializes correctly."""
        m = EvaluationMetrics(success_rate=0.85, retry_rate=0.1,
                              missions_total=20, missions_succeeded=17)
        d = m.to_dict()
        assert d["success_rate"] == 0.85
        assert d["retry_rate"] == 0.1
        assert d["missions_total"] == 20
        assert "collected_at" in d

    def test_collector_no_crash(self):
        """E3: Collector doesn't crash with empty runtime."""
        c = MetricsCollector()
        m = c.collect()
        assert isinstance(m, EvaluationMetrics)

    def test_collector_returns_metrics(self):
        """E4: Collector returns EvaluationMetrics."""
        c = MetricsCollector()
        m = c.collect()
        assert m.success_rate >= 0
        assert m.tool_success_rate >= 0


# ═══════════════════════════════════════════════════════════════
# PART 3: SCORING MODEL
# ═══════════════════════════════════════════════════════════════

class TestScoringModel:

    def test_perfect_metrics(self):
        """E5: Perfect metrics → high score."""
        m = EvaluationMetrics(
            missions_total=100, missions_succeeded=100,
            success_rate=1.0, retry_rate=0.0, timeout_rate=0.0,
            approval_rate=0.0, tool_success_rate=1.0,
            avg_cost_usd=0.005, patch_success_rate=0.8,
        )
        scorer = ScoringModel()
        score = scorer.score(m)
        assert score.overall >= 8.0
        assert len(score.dimensions) == 6

    def test_terrible_metrics(self):
        """E6: Terrible metrics → low score."""
        m = EvaluationMetrics(
            missions_total=50, missions_succeeded=10,
            success_rate=0.2, retry_rate=0.7, timeout_rate=0.5,
            approval_rate=0.8, tool_success_rate=0.3,
            avg_cost_usd=3.0, exception_count=50,
            patch_success_rate=0.1, lessons_total=10,
        )
        scorer = ScoringModel()
        score = scorer.score(m)
        assert score.overall < 4.0

    def test_six_dimensions(self):
        """E7: Score has 6 dimensions."""
        m = EvaluationMetrics(missions_total=10, success_rate=0.8)
        scorer = ScoringModel()
        score = scorer.score(m)
        names = {d.name for d in score.dimensions}
        assert names == {"success_rate", "stability", "reasoning_quality",
                         "cost_efficiency", "tool_accuracy", "autonomy"}

    def test_custom_weights(self):
        """E8: Custom weights respected."""
        custom = {"success_rate": 0.5, "stability": 0.1, "reasoning_quality": 0.1,
                  "cost_efficiency": 0.1, "tool_accuracy": 0.1, "autonomy": 0.1}
        m = EvaluationMetrics(success_rate=1.0, missions_total=10, missions_succeeded=10,
                              tool_success_rate=1.0)
        scorer = ScoringModel(weights=custom)
        score = scorer.score(m)
        # Success rate weighted more → higher overall
        sr_dim = [d for d in score.dimensions if d.name == "success_rate"][0]
        assert sr_dim.weight == 0.5

    def test_dimension_weighted(self):
        """E9: DimensionScore weighted calculation."""
        d = DimensionScore(name="test", value=8.0, weight=0.25)
        assert d.weighted == 2.0


# ═══════════════════════════════════════════════════════════════
# PART 4: WEAKNESS DETECTION
# ═══════════════════════════════════════════════════════════════

class TestWeaknessDetection:

    def _make_score(self, metrics):
        return ScoringModel().score(metrics)

    def test_low_success_rate(self):
        """E10: Low success rate detected."""
        m = EvaluationMetrics(missions_total=20, missions_succeeded=10,
                              success_rate=0.5, tool_success_rate=1.0)
        score = self._make_score(m)
        detector = WeaknessDetector()
        priorities = detector.detect(score, m)
        types = {p.weakness_type for p in priorities}
        assert WeaknessType.FREQUENT_FAILURES in types

    def test_excessive_retries(self):
        """E11: Excessive retries detected."""
        m = EvaluationMetrics(missions_total=10, success_rate=0.9,
                              retry_rate=0.4, tool_success_rate=1.0)
        score = self._make_score(m)
        priorities = WeaknessDetector().detect(score, m)
        types = {p.weakness_type for p in priorities}
        assert WeaknessType.EXCESSIVE_RETRIES in types

    def test_frequent_timeouts(self):
        """E12: Frequent timeouts detected."""
        m = EvaluationMetrics(missions_total=10, success_rate=0.9,
                              timeout_rate=0.2, tool_timeout_count=5,
                              tool_success_rate=1.0)
        score = self._make_score(m)
        priorities = WeaknessDetector().detect(score, m)
        types = {p.weakness_type for p in priorities}
        assert WeaknessType.FREQUENT_TIMEOUTS in types

    def test_poor_tool_selection(self):
        """E13: Poor tool selection detected."""
        m = EvaluationMetrics(missions_total=10, success_rate=0.9,
                              tool_calls_total=20, tool_success_rate=0.6)
        score = self._make_score(m)
        priorities = WeaknessDetector().detect(score, m)
        types = {p.weakness_type for p in priorities}
        assert WeaknessType.POOR_TOOL_SELECTION in types

    def test_high_cost(self):
        """E14: High cost detected."""
        m = EvaluationMetrics(missions_total=10, missions_succeeded=9,
                              success_rate=0.9, avg_cost_usd=2.0,
                              tool_success_rate=1.0)
        score = self._make_score(m)
        priorities = WeaknessDetector().detect(score, m)
        types = {p.weakness_type for p in priorities}
        assert WeaknessType.HIGH_COST in types

    def test_low_autonomy(self):
        """E15: Low autonomy detected."""
        m = EvaluationMetrics(missions_total=20, success_rate=0.9,
                              approval_rate=0.6, tool_success_rate=1.0)
        score = self._make_score(m)
        priorities = WeaknessDetector().detect(score, m)
        types = {p.weakness_type for p in priorities}
        assert WeaknessType.LOW_AUTONOMY in types

    def test_no_weaknesses(self):
        """E16: No weaknesses for good metrics."""
        m = EvaluationMetrics(
            missions_total=50, missions_succeeded=48,
            success_rate=0.96, retry_rate=0.05, timeout_rate=0.02,
            approval_rate=0.1, tool_success_rate=0.95,
            tool_calls_total=100, avg_cost_usd=0.02,
        )
        score = self._make_score(m)
        priorities = WeaknessDetector().detect(score, m)
        assert len(priorities) == 0

    def test_sorted_by_impact(self):
        """E17: Priorities sorted by impact."""
        m = EvaluationMetrics(
            missions_total=20, missions_succeeded=8,
            success_rate=0.4, retry_rate=0.3,
            timeout_rate=0.15, tool_success_rate=0.5,
            tool_calls_total=30, avg_cost_usd=1.5,
        )
        score = self._make_score(m)
        priorities = WeaknessDetector().detect(score, m)
        assert len(priorities) >= 2
        for i in range(len(priorities) - 1):
            assert priorities[i].impact_score >= priorities[i + 1].impact_score


# ═══════════════════════════════════════════════════════════════
# PART 5: INTEGRATION WITH IMPROVEMENT LOOP
# ═══════════════════════════════════════════════════════════════

class TestImprovementIntegration:

    def test_signals_from_priorities(self, tmp_path):
        """E18: get_improvement_signals produces signal dicts."""
        engine = AgentEvaluationEngine(history_path=tmp_path / "hist.json")
        m = EvaluationMetrics(
            missions_total=20, success_rate=0.5, missions_succeeded=10,
            retry_rate=0.4, tool_success_rate=0.6, tool_calls_total=20,
        )
        report = engine.evaluate_from_metrics(m)
        signals = engine.get_improvement_signals(report)
        assert len(signals) > 0

    def test_signal_fields(self, tmp_path):
        """E19: Signal dicts have required fields."""
        engine = AgentEvaluationEngine(history_path=tmp_path / "hist.json")
        m = EvaluationMetrics(
            missions_total=10, success_rate=0.5, missions_succeeded=5,
            tool_success_rate=1.0,
        )
        report = engine.evaluate_from_metrics(m)
        signals = engine.get_improvement_signals(report)
        for s in signals:
            assert "type" in s
            assert "component" in s
            assert "severity" in s
            assert "frequency" in s
            assert "context" in s


# ═══════════════════════════════════════════════════════════════
# PART 6: EVALUATION MEMORY
# ═══════════════════════════════════════════════════════════════

class TestEvaluationMemory:

    def _make_score(self, overall, dims=None):
        if dims is None:
            dims = [DimensionScore(name="success_rate", value=overall, weight=0.25)]
        return AgentScore(overall=overall, dimensions=dims)

    def test_store_retrieve(self, tmp_path):
        """E20: Store and retrieve history."""
        mem = EvaluationMemory(tmp_path / "hist.json")
        score = self._make_score(7.5)
        mem.record(score, [])
        assert mem.get_history_count() == 1

    def test_evolution_improved(self, tmp_path):
        """E21: Evolution tracking (improved)."""
        mem = EvaluationMemory(tmp_path / "hist.json")
        mem.record(self._make_score(6.0), [])
        mem.record(self._make_score(7.5), [])
        evo = mem.get_evolution()
        assert evo["status"] == "ok"
        assert evo["direction"] == "improved"
        assert evo["delta"] == 1.5

    def test_evolution_regressed(self, tmp_path):
        """E22: Evolution tracking (regressed)."""
        mem = EvaluationMemory(tmp_path / "hist.json")
        mem.record(self._make_score(8.0), [])
        mem.record(self._make_score(6.5), [])
        evo = mem.get_evolution()
        assert evo["direction"] == "regressed"
        assert evo["regression_detected"] is True  # delta < -0.5

    def test_regression_detection(self, tmp_path):
        """E23: Regression detection over window."""
        mem = EvaluationMemory(tmp_path / "hist.json")
        for score in [9.0, 8.5, 8.0, 7.5, 7.0]:
            mem.record(self._make_score(score), [])
        assert mem.detect_regression(window=5) is True

    def test_trend_data(self, tmp_path):
        """E24: Trend data."""
        mem = EvaluationMemory(tmp_path / "hist.json")
        for i in range(5):
            mem.record(self._make_score(5.0 + i), [])
        trend = mem.get_trend(last_n=3)
        assert len(trend) == 3
        assert trend[0]["score"] == 7.0
        assert trend[2]["score"] == 9.0

    def test_persistence(self, tmp_path):
        """E25: Persistence survives reload."""
        path = tmp_path / "hist.json"
        mem1 = EvaluationMemory(path)
        mem1.record(self._make_score(7.5), [])
        mem1.record(self._make_score(8.0), [])
        mem2 = EvaluationMemory(path)
        assert mem2.get_history_count() == 2
        evo = mem2.get_evolution()
        assert evo["status"] == "ok"


# ═══════════════════════════════════════════════════════════════
# PART 7: REPORTING
# ═══════════════════════════════════════════════════════════════

class TestReporting:

    def test_report_to_dict(self, tmp_path):
        """E26: Report to_dict has all fields."""
        engine = AgentEvaluationEngine(history_path=tmp_path / "hist.json")
        m = EvaluationMetrics(missions_total=10, success_rate=0.8,
                              missions_succeeded=8, tool_success_rate=0.9)
        report = engine.evaluate_from_metrics(m)
        d = report.to_dict()
        assert "score" in d
        assert "priorities" in d
        assert "evolution" in d
        assert "regression_detected" in d

    def test_summary_text(self, tmp_path):
        """E27: Summary includes score and dimensions."""
        engine = AgentEvaluationEngine(history_path=tmp_path / "hist.json")
        m = EvaluationMetrics(missions_total=20, success_rate=0.7,
                              missions_succeeded=14, missions_failed=6,
                              retry_rate=0.3, tool_success_rate=0.8,
                              tool_calls_total=50)
        report = engine.evaluate_from_metrics(m)
        text = report.summary()
        assert "Agent Score:" in text
        assert "success_rate" in text

    def test_summary_with_evolution(self, tmp_path):
        """E28: Summary includes evolution after 2+ evals."""
        engine = AgentEvaluationEngine(history_path=tmp_path / "hist.json")
        m1 = EvaluationMetrics(missions_total=10, success_rate=0.6,
                               missions_succeeded=6, tool_success_rate=0.9)
        m2 = EvaluationMetrics(missions_total=20, success_rate=0.85,
                               missions_succeeded=17, tool_success_rate=0.95)
        engine.evaluate_from_metrics(m1)
        report = engine.evaluate_from_metrics(m2)
        text = report.summary()
        assert "→" in text  # evolution arrow


# ═══════════════════════════════════════════════════════════════
# PART 8: FULL ENGINE
# ═══════════════════════════════════════════════════════════════

class TestFullEngine:

    def test_full_evaluate(self, tmp_path):
        """E29: Full evaluate cycle."""
        engine = AgentEvaluationEngine(history_path=tmp_path / "hist.json")
        report = engine.evaluate()
        assert isinstance(report, EvaluationReport)
        assert report.score.overall >= 0
        assert isinstance(report.priorities, list)

    def test_evaluate_from_metrics(self, tmp_path):
        """E30: Evaluate from pre-built metrics."""
        engine = AgentEvaluationEngine(history_path=tmp_path / "hist.json")
        m = EvaluationMetrics(
            missions_total=30, missions_succeeded=27,
            success_rate=0.9, retry_rate=0.05,
            timeout_rate=0.02, approval_rate=0.1,
            tool_success_rate=0.95, tool_calls_total=100,
            avg_cost_usd=0.02,
        )
        report = engine.evaluate_from_metrics(m)
        assert report.score.overall >= 7.0
        assert len(report.priorities) == 0  # healthy system

    def test_multiple_evaluations(self, tmp_path):
        """E31: Multiple evaluations track evolution."""
        engine = AgentEvaluationEngine(history_path=tmp_path / "hist.json")
        m1 = EvaluationMetrics(missions_total=10, success_rate=0.5,
                               missions_succeeded=5, tool_success_rate=0.8,
                               tool_calls_total=20)
        m2 = EvaluationMetrics(missions_total=20, success_rate=0.8,
                               missions_succeeded=16, tool_success_rate=0.9,
                               tool_calls_total=40)
        engine.evaluate_from_metrics(m1)
        report2 = engine.evaluate_from_metrics(m2)
        evo = report2.evolution
        assert evo.get("status") == "ok"
        assert evo.get("direction") == "improved"

    def test_trend_endpoint(self, tmp_path):
        """E32: Engine trend returns history."""
        engine = AgentEvaluationEngine(history_path=tmp_path / "hist.json")
        for sr in [0.5, 0.6, 0.7, 0.8]:
            m = EvaluationMetrics(missions_total=10, success_rate=sr,
                                  missions_succeeded=int(sr * 10),
                                  tool_success_rate=0.9)
            engine.evaluate_from_metrics(m)
        trend = engine.get_trend(last_n=4)
        assert len(trend) == 4
        # Scores should be increasing
        assert trend[-1]["score"] > trend[0]["score"]
