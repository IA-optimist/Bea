"""tests/test_research_loop.py — Research loop self-improvement tests."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestExperimentSpec:
    def test_create(self):
        from core.self_improvement.research_loop import ExperimentSpec
        spec = ExperimentSpec(hypothesis="Test hypothesis", subsystem="tools")
        assert len(spec.experiment_id) == 10
        assert spec.risk_level == "LOW"

    def test_to_dict(self):
        from core.self_improvement.research_loop import ExperimentSpec
        spec = ExperimentSpec(hypothesis="Test", target_files=["a.py"])
        d = spec.to_dict()
        assert d["hypothesis"] == "Test"
        assert d["target_files"] == ["a.py"]


class TestBaselineMetrics:
    def test_composite_score(self):
        from core.self_improvement.research_loop import BaselineMetrics
        m = BaselineMetrics(
            test_pass_rate=1.0, test_count=100, test_failures=0,
            mission_success_rate=0.9, tool_success_rate=0.95,
            endpoint_health=True, trace_completeness=0.8,
        )
        score = m.composite_score()
        assert 0.8 < score <= 1.0

    def test_low_score_on_failures(self):
        from core.self_improvement.research_loop import BaselineMetrics
        good = BaselineMetrics(test_pass_rate=1.0, test_count=100,
                                mission_success_rate=0.9)
        bad = BaselineMetrics(test_pass_rate=0.5, test_count=100,
                               test_failures=50, mission_success_rate=0.3)
        assert bad.composite_score() < good.composite_score()


class TestRiskAnalyzer:
    def test_protected_zone_critical(self):
        from core.self_improvement.research_loop import analyze_risk, ExperimentSpec
        spec = ExperimentSpec(target_files=["core/meta_orchestrator.py"])
        assert analyze_risk(spec) == "CRITICAL"

    def test_policy_high(self):
        from core.self_improvement.research_loop import analyze_risk, ExperimentSpec
        spec = ExperimentSpec(subsystem="policy")
        assert analyze_risk(spec) == "HIGH"

    def test_tools_low(self):
        from core.self_improvement.research_loop import analyze_risk, ExperimentSpec
        spec = ExperimentSpec(subsystem="tools")
        assert analyze_risk(spec) == "LOW"

    def test_many_files_medium(self):
        from core.self_improvement.research_loop import analyze_risk, ExperimentSpec
        spec = ExperimentSpec(target_files=[f"f{i}.py" for i in range(10)],
                              subsystem="tools")
        assert analyze_risk(spec) in ("MEDIUM", "HIGH")

    def test_auth_high(self):
        from core.self_improvement.research_loop import analyze_risk, ExperimentSpec
        spec = ExperimentSpec(subsystem="auth")
        assert analyze_risk(spec) == "HIGH"


class TestRegressionGuard:
    def test_no_regression(self):
        from core.self_improvement.research_loop import RegressionGuard, BaselineMetrics
        guard = RegressionGuard()
        baseline = BaselineMetrics(test_pass_rate=0.95, test_failures=5,
                                    endpoint_health=True, mission_success_rate=0.9)
        candidate = BaselineMetrics(test_pass_rate=0.96, test_failures=4,
                                     endpoint_health=True, mission_success_rate=0.92)
        passed, regs = guard.check(baseline, candidate)
        assert passed
        assert len(regs) == 0

    def test_test_regression(self):
        from core.self_improvement.research_loop import RegressionGuard, BaselineMetrics
        guard = RegressionGuard()
        baseline = BaselineMetrics(test_pass_rate=0.95, test_failures=5)
        candidate = BaselineMetrics(test_pass_rate=0.90, test_failures=10)
        passed, regs = guard.check(baseline, candidate)
        assert not passed
        assert len(regs) >= 1

    def test_health_regression(self):
        from core.self_improvement.research_loop import RegressionGuard, BaselineMetrics
        guard = RegressionGuard()
        baseline = BaselineMetrics(endpoint_health=True)
        candidate = BaselineMetrics(endpoint_health=False)
        passed, regs = guard.check(baseline, candidate)
        assert not passed


class TestPromotionGate:
    def test_promote_on_improvement(self):
        from core.self_improvement.research_loop import PromotionGate, ExperimentResult
        gate = PromotionGate()
        result = ExperimentResult(score_delta=0.05, tests_passed=True,
                                   regression_detected=False)
        promote, reason = gate.evaluate(result, "LOW")
        assert promote

    def test_reject_on_regression(self):
        from core.self_improvement.research_loop import PromotionGate, ExperimentResult
        gate = PromotionGate()
        result = ExperimentResult(score_delta=0.05, tests_passed=True,
                                   regression_detected=True)
        promote, reason = gate.evaluate(result, "LOW")
        assert not promote

    def test_reject_on_test_failure(self):
        from core.self_improvement.research_loop import PromotionGate, ExperimentResult
        gate = PromotionGate()
        result = ExperimentResult(score_delta=0.05, tests_passed=False)
        promote, reason = gate.evaluate(result, "LOW")
        assert not promote

    def test_reject_critical(self):
        from core.self_improvement.research_loop import PromotionGate, ExperimentResult
        gate = PromotionGate()
        result = ExperimentResult(score_delta=0.05, tests_passed=True,
                                   regression_detected=False)
        promote, reason = gate.evaluate(result, "CRITICAL")
        assert not promote

    def test_reject_score_decrease(self):
        from core.self_improvement.research_loop import PromotionGate, ExperimentResult
        gate = PromotionGate()
        result = ExperimentResult(score_delta=-0.02, tests_passed=True,
                                   regression_detected=False)
        promote, reason = gate.evaluate(result, "LOW")
        assert not promote


class TestSandboxManager:
    def test_create_cleanup(self, tmp_path):
        from core.self_improvement.research_loop import SandboxManager
        sm = SandboxManager(root=str(tmp_path / "sandbox"))
        # Create a temp file to sandbox
        src = tmp_path / "test.py"
        src.write_text("x = 1")
        path = sm.create("exp1", [str(src)])
        assert os.path.isdir(path)
        assert os.path.exists(os.path.join(path, "test.py"))
        sm.cleanup("exp1")
        assert not os.path.isdir(path)

    def test_list_sandboxes(self, tmp_path):
        from core.self_improvement.research_loop import SandboxManager
        sm = SandboxManager(root=str(tmp_path / "sandbox"))
        assert sm.list_sandboxes() == []
        os.makedirs(str(tmp_path / "sandbox" / "exp1"))
        assert "exp1" in sm.list_sandboxes()


class TestRollbackManager:
    def test_create_and_rollback(self, tmp_path):
        from core.self_improvement.research_loop import RollbackManager
        rm = RollbackManager(root=str(tmp_path / "rollbacks"))
        # Create a file, save rollback point, modify, rollback
        src = tmp_path / "target.py"
        src.write_text("original")
        rm.create_rollback_point("exp1", [str(src)])
        src.write_text("modified")
        assert src.read_text(encoding="utf-8") == "modified"
        ok, msg = rm.rollback("exp1")
        assert ok
        assert src.read_text(encoding="utf-8") == "original"

    def test_rollback_missing(self, tmp_path):
        from core.self_improvement.research_loop import RollbackManager
        rm = RollbackManager(root=str(tmp_path / "rollbacks"))
        ok, msg = rm.rollback("nonexistent")
        assert not ok


class TestResearchLoopStats:
    def test_stats_empty(self):
        from core.self_improvement.research_loop import ResearchLoop
        loop = ResearchLoop()
        stats = loop.stats()
        assert stats["total_experiments"] == 0
        assert stats["promoted"] == 0

    def test_history_empty(self):
        from core.self_improvement.research_loop import ResearchLoop
        loop = ResearchLoop()
        assert loop.get_history() == []


class TestProtectedZones:
    def test_protected_files(self):
        from core.self_improvement.research_loop import PROTECTED_ZONES
        assert "core/meta_orchestrator.py" in PROTECTED_ZONES
        assert "core/tool_executor.py" in PROTECTED_ZONES
        assert "api/main.py" in PROTECTED_ZONES
        assert "main.py" in PROTECTED_ZONES


class TestReportGeneration:
    def test_generate(self, tmp_path, monkeypatch):
        import core.self_improvement.research_loop as rl
        monkeypatch.setattr(rl, "REPORT_DIR", str(tmp_path))
        from core.self_improvement.research_loop import generate_report, ExperimentResult
        result = ExperimentResult(
            experiment_id="test123",
            spec={"hypothesis": "Test", "subsystem": "tools"},
            baseline={"test_pass_rate": 0.95},
            candidate={"test_pass_rate": 0.97},
            baseline_score=0.85,
            candidate_score=0.87,
            score_delta=0.02,
            tests_passed=True,
            promoted=True,
            lessons=["Worked well"],
        )
        path = generate_report(result)
        assert os.path.exists(path)
        content = open(path, encoding="utf-8").read()
        assert "Test" in content
        assert "PROMOTED" in content
