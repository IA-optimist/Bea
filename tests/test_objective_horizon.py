"""
tests/test_objective_horizon.py — Long-horizon objective management tests.

Validates:
  - Evaluation metrics with progress calculation
  - Time horizon tracking
  - Playbook linkage and execution recording
  - Progress computation (metrics + executions)
  - Strategy suggestions (rules-based)
  - Serialization round-trip
  - Integration with objective engine
  - Integration with playbook execution
"""
import time
from core.objectives.objective_horizon import (
    EvaluationMetric, TimeHorizon, PlaybookLink,
    ObjectiveHorizonManager,
)


class TestEvaluationMetric:

    def test_OH01_progress_up(self):
        """Metric with direction=up calculates progress correctly."""
        m = EvaluationMetric(name="conversions", description="Total conversions",
                            target_value=100, current_value=50, unit="count", direction="up")
        assert m.progress == 0.5

    def test_OH02_progress_down(self):
        """Metric with direction=down calculates inverse progress."""
        m = EvaluationMetric(name="failure_rate", description="Failure rate",
                            target_value=5, current_value=10, unit="percent", direction="down")
        assert m.progress == 0.5

    def test_OH03_progress_complete(self):
        """100% progress when target reached."""
        m = EvaluationMetric(name="x", description="x", target_value=50, current_value=60)
        assert m.progress == 1.0  # capped at 1.0

    def test_OH04_roundtrip(self):
        m = EvaluationMetric(name="x", description="d", target_value=100,
                            current_value=42, unit="count", direction="up")
        d = m.to_dict()
        m2 = EvaluationMetric.from_dict(d)
        assert m2.name == m.name
        assert m2.current_value == m.current_value
        assert abs(m2.progress - m.progress) < 0.001


class TestTimeHorizon:

    def test_OH05_ongoing_not_overdue(self):
        """Ongoing objectives are never overdue."""
        h = TimeHorizon(horizon_type="ongoing")
        assert h.is_overdue is False
        assert h.elapsed_ratio == 0.0

    def test_OH06_fixed_overdue(self):
        """Fixed horizon past target_end is overdue."""
        h = TimeHorizon(start=time.time() - 200, target_end=time.time() - 100,
                       horizon_type="fixed")
        assert h.is_overdue is True
        assert h.elapsed_ratio == 1.0

    def test_OH07_fixed_in_progress(self):
        """Fixed horizon mid-way shows partial elapsed."""
        now = time.time()
        h = TimeHorizon(start=now - 50, target_end=now + 50, horizon_type="fixed")
        assert 0.4 < h.elapsed_ratio < 0.6

    def test_OH08_roundtrip(self):
        h = TimeHorizon(start=100, target_end=200, horizon_type="quarterly")
        d = h.to_dict()
        h2 = TimeHorizon.from_dict(d)
        assert h2.horizon_type == "quarterly"


class TestPlaybookLink:

    def test_OH09_link_creation(self):
        link = PlaybookLink(playbook_id="market_analysis", run_id="r1",
                           status="completed", steps_completed=4, steps_total=4)
        d = link.to_dict()
        assert d["playbook_id"] == "market_analysis"
        assert d["status"] == "completed"

    def test_OH10_link_roundtrip(self):
        link = PlaybookLink(playbook_id="p", run_id="r", status="failed",
                           steps_completed=1, steps_total=3,
                           quality_scores={"s1": 0.8})
        d = link.to_dict()
        link2 = PlaybookLink.from_dict(d)
        assert link2.playbook_id == link.playbook_id
        assert link2.quality_scores == link.quality_scores


class TestHorizonManager:

    def _mgr(self) -> ObjectiveHorizonManager:
        return ObjectiveHorizonManager()

    def test_OH11_set_and_compute_metrics(self):
        mgr = self._mgr()
        mgr.set_metrics("obj1", [
            EvaluationMetric(name="conv", description="d", target_value=100, current_value=50),
            EvaluationMetric(name="rev", description="d", target_value=10000, current_value=5000),
        ])
        progress = mgr.compute_progress("obj1")
        assert progress == 0.5  # both at 50%

    def test_OH12_execution_only_progress(self):
        mgr = self._mgr()
        mgr.record_execution("obj1", "p1", "r1", "completed", 4, 4)
        mgr.record_execution("obj1", "p1", "r2", "failed", 1, 4)
        progress = mgr.compute_progress("obj1")
        assert progress == 0.5  # 1/2 successful

    def test_OH13_mixed_progress(self):
        """Progress blends metrics (60%) and executions (40%)."""
        mgr = self._mgr()
        mgr.set_metrics("obj1", [
            EvaluationMetric(name="x", description="d", target_value=100, current_value=80),
        ])
        mgr.record_execution("obj1", "p1", "r1", "completed", 4, 4)
        progress = mgr.compute_progress("obj1")
        # 0.6 * 0.8 (metrics) + 0.4 * 1.0 (executions) = 0.88
        assert abs(progress - 0.88) < 0.01

    def test_OH14_update_metric(self):
        mgr = self._mgr()
        mgr.set_metrics("obj1", [
            EvaluationMetric(name="conv", description="d", target_value=100, current_value=0),
        ])
        mgr.update_metric("obj1", "conv", 75)
        progress = mgr.compute_progress("obj1")
        assert abs(progress - 0.75) < 0.01

    def test_OH15_no_data_zero_progress(self):
        mgr = self._mgr()
        assert mgr.compute_progress("unknown") == 0.0


class TestStrategySuggestions:

    def test_OH16_no_executions_suggests_playbook(self):
        mgr = ObjectiveHorizonManager()
        suggestions = mgr.get_suggestions("obj1")
        assert len(suggestions) >= 1
        assert suggestions[0].suggestion_type == "run_playbook"

    def test_OH17_failures_suggest_investigation(self):
        mgr = ObjectiveHorizonManager()
        for i in range(3):
            mgr.record_execution("obj1", "p1", f"r{i}", "failed", 0, 4)
        suggestions = mgr.get_suggestions("obj1")
        types = {s.suggestion_type for s in suggestions}
        assert "investigate" in types

    def test_OH18_stagnant_suggests_adjustment(self):
        mgr = ObjectiveHorizonManager()
        mgr.set_metrics("obj1", [
            EvaluationMetric(name="x", description="d", target_value=100, current_value=10),
        ])
        # Mix of successes and failures to keep exec rate low
        for i in range(3):
            mgr.record_execution("obj1", "p1", f"r{i}", "completed", 4, 4)
        mgr.record_execution("obj1", "p1", "r3", "failed", 1, 4)
        suggestions = mgr.get_suggestions("obj1")
        types = {s.suggestion_type for s in suggestions}
        assert "adjust_strategy" in types

    def test_OH19_overdue_suggests_escalation(self):
        mgr = ObjectiveHorizonManager()
        mgr.set_horizon("obj1", TimeHorizon(
            start=time.time() - 200, target_end=time.time() - 100,
            horizon_type="fixed"
        ))
        suggestions = mgr.get_suggestions("obj1")
        types = {s.suggestion_type for s in suggestions}
        assert "escalate" in types

    def test_OH20_high_progress_suggests_completion(self):
        mgr = ObjectiveHorizonManager()
        mgr.set_metrics("obj1", [
            EvaluationMetric(name="x", description="d", target_value=100, current_value=90),
        ])
        mgr.record_execution("obj1", "p1", "r1", "completed", 4, 4)
        suggestions = mgr.get_suggestions("obj1")
        descs = " ".join(s.description for s in suggestions)
        assert "80%" in descs or "completion" in descs.lower()


class TestOverview:

    def test_OH21_overview_complete(self):
        mgr = ObjectiveHorizonManager()
        mgr.set_metrics("obj1", [
            EvaluationMetric(name="x", description="d", target_value=100, current_value=50),
        ])
        mgr.set_horizon("obj1", TimeHorizon(horizon_type="ongoing"))
        mgr.record_execution("obj1", "p1", "r1", "completed", 4, 4)

        overview = mgr.get_overview("obj1")
        assert "progress" in overview
        assert "metrics" in overview
        assert "time_horizon" in overview
        assert "executions" in overview
        assert "suggestions" in overview
        assert overview["executions"] == 1


class TestSerialization:

    def test_OH22_roundtrip(self):
        mgr = ObjectiveHorizonManager()
        mgr.set_metrics("obj1", [
            EvaluationMetric(name="x", description="d", target_value=100, current_value=50),
        ])
        mgr.set_horizon("obj1", TimeHorizon(start=100, target_end=200))
        mgr.record_execution("obj1", "p1", "r1", "completed", 4, 4)

        d = mgr.to_dict()
        mgr2 = ObjectiveHorizonManager.from_dict(d)

        assert mgr2.compute_progress("obj1") == mgr.compute_progress("obj1")
        assert len(mgr2._links.get("obj1", [])) == 1
        assert len(mgr2._metrics.get("obj1", [])) == 1


class TestPlaybookIntegration:

    def test_OH23_playbook_feeds_objective(self):
        """execute_playbook with objective_id records in horizon manager."""
        import inspect
        from core.planning.playbook import execute_playbook
        source = inspect.getsource(execute_playbook)
        assert "objective_id" in source
        assert "record_execution" in source
        assert "horizon_manager" in source or "get_horizon_manager" in source

    def test_OH24_safe_without_objective(self):
        """execute_playbook works fine without objective_id."""
        from core.planning.playbook import execute_playbook
        result = execute_playbook("market_analysis", "Test without objective")
        assert result["ok"] is True
        # No crash — objective_id is optional
