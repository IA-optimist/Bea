"""
Tests — Self-Improvement Engine

Coverage:
  K1. Experiment rejection on regression
  K2. Rollback works
  K3. Sandbox isolation works
  K4. Promotion gate blocks dangerous changes
  K5. Lesson memory stores success/failure
  K6. One-experiment-one-hypothesis enforced
  K7. Protected files are blocked
  K8. Improvement loop survives internal errors gracefully
  K9. Safety zone classification
  K10. Evaluation score computation
  K11. Report generation
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═══════════════════════════════════════════════════════════════
# SAFETY ZONES (K7, K9)
# ═══════════════════════════════════════════════════════════════

class TestSafetyZones:

    def test_critical_files_classified(self):
        from core.improvement_loop import classify_file_safety, SafetyZone
        assert classify_file_safety("core/meta_orchestrator.py") == SafetyZone.CRITICAL
        assert classify_file_safety("core/policy_engine.py") == SafetyZone.CRITICAL
        assert classify_file_safety("core/tool_executor.py") == SafetyZone.CRITICAL
        assert classify_file_safety("api/main.py") == SafetyZone.CRITICAL
        assert classify_file_safety("core/auth/token.py") == SafetyZone.CRITICAL

    def test_high_files_classified(self):
        from core.improvement_loop import classify_file_safety, SafetyZone
        assert classify_file_safety("core/memory/store.py") == SafetyZone.HIGH
        assert classify_file_safety("core/orchestrator.py") == SafetyZone.HIGH

    def test_medium_files_classified(self):
        from core.improvement_loop import classify_file_safety, SafetyZone
        assert classify_file_safety("executor/checkpoint.py") == SafetyZone.MEDIUM
        assert classify_file_safety("core/observability_helpers.py") == SafetyZone.MEDIUM

    def test_low_files_classified(self):
        from core.improvement_loop import classify_file_safety, SafetyZone
        assert classify_file_safety("docs/README.md") == SafetyZone.LOW
        assert classify_file_safety("tests/test_foo.py") == SafetyZone.LOW

    def test_unknown_files_default_low(self):
        from core.improvement_loop import classify_file_safety, SafetyZone
        assert classify_file_safety("random/unknown_file.py") == SafetyZone.LOW

    def test_critical_files_blocked(self):
        from core.improvement_loop import check_safety_violations
        violations = check_safety_violations(["core/meta_orchestrator.py"])
        assert len(violations) >= 1
        assert "CRITICAL" in violations[0]

    def test_medium_zone_max_1(self):
        from core.improvement_loop import check_safety_violations
        violations = check_safety_violations([
            "executor/a.py", "executor/b.py"
        ])
        assert any("MEDIUM" in v for v in violations)

    def test_low_zone_max_3(self):
        from core.improvement_loop import check_safety_violations
        violations = check_safety_violations([
            "docs/a.md", "docs/b.md", "docs/c.md", "docs/d.md"
        ])
        assert any("LOW" in v for v in violations)


# ═══════════════════════════════════════════════════════════════
# EXPERIMENT SPEC (K6)
# ═══════════════════════════════════════════════════════════════

class TestExperimentSpec:

    def test_valid_spec_passes(self):
        from core.improvement_loop import ExperimentSpec
        spec = ExperimentSpec(
            hypothesis="Improve error messages",
            files_allowed=["docs/errors.md"],
            target_subsystem="docs",
        )
        assert spec.validate() == []

    def test_missing_hypothesis_fails(self):
        from core.improvement_loop import ExperimentSpec
        spec = ExperimentSpec(files_allowed=["docs/a.md"])
        errors = spec.validate()
        assert any("hypothesis" in e.lower() for e in errors)

    def test_no_files_fails(self):
        from core.improvement_loop import ExperimentSpec
        spec = ExperimentSpec(hypothesis="test")
        errors = spec.validate()
        assert any("files" in e.lower() for e in errors)

    def test_too_many_files_fails(self):
        from core.improvement_loop import ExperimentSpec
        spec = ExperimentSpec(
            hypothesis="test",
            files_allowed=["a.py", "b.py", "c.py", "d.py"],
            max_files=2,
        )
        errors = spec.validate()
        assert any("too many" in e.lower() for e in errors)

    def test_critical_file_in_spec_fails(self):
        from core.improvement_loop import ExperimentSpec
        spec = ExperimentSpec(
            hypothesis="test",
            files_allowed=["core/meta_orchestrator.py"],
        )
        errors = spec.validate()
        assert any("CRITICAL" in e for e in errors)

    def test_one_experiment_one_hypothesis(self):
        """Each spec must have exactly one hypothesis."""
        from core.improvement_loop import ExperimentSpec
        spec = ExperimentSpec(
            hypothesis="A single clear hypothesis",
            files_allowed=["docs/a.md"],
        )
        assert spec.validate() == []
        assert spec.hypothesis  # Not empty


# ═══════════════════════════════════════════════════════════════
# EVALUATION SCORE (K10)
# ═══════════════════════════════════════════════════════════════

class TestEvaluationScore:

    def test_perfect_score(self):
        from core.improvement_loop import EvaluationScore
        score = EvaluationScore(
            test_pass_rate=1.0,
            regression_pass_rate=1.0,
            health_score=1.0,
            no_regression=True,
            safety_score=1.0,
            files_within_budget=True,
        )
        assert score.composite > 0.8
        assert score.passed is True

    def test_regression_kills_score(self):
        from core.improvement_loop import EvaluationScore
        score = EvaluationScore(
            test_pass_rate=1.0,
            regression_pass_rate=1.0,
            no_regression=False,  # Regression!
            safety_score=1.0,
        )
        assert score.composite == 0.0
        assert score.passed is False

    def test_safety_violation_kills_score(self):
        from core.improvement_loop import EvaluationScore
        score = EvaluationScore(
            test_pass_rate=1.0,
            regression_pass_rate=1.0,
            no_regression=True,
            safety_score=0.3,  # Safety violated!
        )
        assert score.composite == 0.0
        assert score.passed is False

    def test_low_test_rate_rejects(self):
        from core.improvement_loop import EvaluationScore
        score = EvaluationScore(
            test_pass_rate=0.5,  # Too low
            regression_pass_rate=1.0,
            no_regression=True,
            safety_score=1.0,
        )
        assert score.passed is False

    def test_low_regression_rate_rejects(self):
        from core.improvement_loop import EvaluationScore
        score = EvaluationScore(
            test_pass_rate=1.0,
            regression_pass_rate=0.8,  # Below 0.95
            no_regression=True,
            safety_score=1.0,
        )
        assert score.passed is False

    def test_file_budget_exceeded_rejects(self):
        from core.improvement_loop import EvaluationScore
        score = EvaluationScore(
            test_pass_rate=1.0,
            regression_pass_rate=1.0,
            no_regression=True,
            safety_score=1.0,
            files_within_budget=False,
        )
        assert score.passed is False


# ═══════════════════════════════════════════════════════════════
# SANDBOX (K2, K3)
# ═══════════════════════════════════════════════════════════════

class TestSandbox:

    def test_create_takes_snapshots(self, tmp_path):
        from core.improvement_loop import SandboxManager
        # Setup: create a "repo" with a file
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "test.py").write_text("original content")

        sm = SandboxManager(repo, tmp_path / "sandbox")
        sm.create("exp-001", ["test.py"])

        # Snapshot exists
        assert sm.get_snapshot("exp-001", "test.py") == "original content"

    def test_rollback_restores_files(self, tmp_path):
        from core.improvement_loop import SandboxManager
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "test.py").write_text("original")

        sm = SandboxManager(repo, tmp_path / "sandbox")
        sm.create("exp-002", ["test.py"])

        # Modify the file (simulate patch)
        (repo / "test.py").write_text("modified")
        assert (repo / "test.py").read_text(encoding="utf-8") == "modified"

        # Rollback
        restored = sm.rollback("exp-002")
        assert "test.py" in restored
        assert (repo / "test.py").read_text(encoding="utf-8") == "original"

    def test_diff_shows_changes(self, tmp_path):
        from core.improvement_loop import SandboxManager
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "test.py").write_text("line1\nline2\n")

        sm = SandboxManager(repo, tmp_path / "sandbox")
        sm.create("exp-003", ["test.py"])

        # Modify
        (repo / "test.py").write_text("line1\nline2_modified\nline3\n")

        diffs = sm.get_diff("exp-003")
        assert "test.py" in diffs
        assert "line2_modified" in diffs["test.py"]

    def test_cleanup_removes_sandbox(self, tmp_path):
        from core.improvement_loop import SandboxManager
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "test.py").write_text("content")

        sm = SandboxManager(repo, tmp_path / "sandbox")
        sandbox_dir = sm.create("exp-004", ["test.py"])
        assert sandbox_dir.exists()

        sm.cleanup("exp-004")
        assert not sandbox_dir.exists()

    def test_list_active_sandboxes(self, tmp_path):
        from core.improvement_loop import SandboxManager
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "a.py").write_text("a")

        sm = SandboxManager(repo, tmp_path / "sandbox")
        sm.create("exp-a", ["a.py"])
        sm.create("exp-b", ["a.py"])

        active = sm.list_active()
        assert "exp-a" in active
        assert "exp-b" in active


# ═══════════════════════════════════════════════════════════════
# LEARNING MEMORY (K5)
# ═══════════════════════════════════════════════════════════════

class TestLearningMemory:

    def test_record_and_retrieve(self, tmp_path):
        from core.improvement_loop import LearningMemory, Lesson
        mem = LearningMemory(tmp_path / "lessons.json")

        mem.record(Lesson(
            experiment_id="e1",
            subsystem="executor",
            outcome="promoted",
            what_worked="Added retry logic",
            confidence=0.8,
        ))
        mem.record(Lesson(
            experiment_id="e2",
            subsystem="executor",
            outcome="rejected",
            what_failed="Removed error handler",
            confidence=0.3,
        ))

        successes = mem.get_successes("executor")
        assert len(successes) == 1
        assert successes[0].what_worked == "Added retry logic"

        failures = mem.get_failures("executor")
        assert len(failures) == 1
        assert failures[0].what_failed == "Removed error handler"

    def test_persistence(self, tmp_path):
        from core.improvement_loop import LearningMemory, Lesson
        path = tmp_path / "lessons.json"

        mem1 = LearningMemory(path)
        mem1.record(Lesson(experiment_id="e1", outcome="promoted",
                           what_worked="test"))

        # Reload
        mem2 = LearningMemory(path)
        assert len(mem2.get_lessons()) == 1

    def test_summary_for_prompt(self, tmp_path):
        from core.improvement_loop import LearningMemory, Lesson
        mem = LearningMemory(tmp_path / "lessons.json")
        mem.record(Lesson(experiment_id="e1", outcome="promoted",
                           what_worked="Fix A", confidence=0.9))
        mem.record(Lesson(experiment_id="e2", outcome="rejected",
                           what_failed="Fix B", what_to_try_next="Try C",
                           confidence=0.2))

        summary = mem.summary_for_prompt()
        assert "Fix A" in summary
        assert "Fix B" in summary
        assert "Try C" in summary


# ═══════════════════════════════════════════════════════════════
# PROMOTION GATE (K1, K4)
# ═══════════════════════════════════════════════════════════════

class TestPromotionGate:

    def test_regression_blocks_promotion(self):
        """K1: Experiment with more failures than baseline is rejected."""
        from core.improvement_loop import RegressionGuard, ExperimentSpec
        guard = RegressionGuard(Path("."))
        spec = ExperimentSpec(
            hypothesis="test",
            files_allowed=["docs/a.md"],
        )
        baseline = {"passed": 100, "failed": 2}
        candidate = {"passed": 98, "failed": 4}  # More failures!

        evaluation = guard.evaluate(spec, baseline, candidate)
        assert not evaluation.no_regression
        assert not evaluation.passed

    def test_critical_file_blocks_promotion(self):
        """K4: Experiment touching critical file is auto-blocked."""
        from core.improvement_loop import RegressionGuard, ExperimentSpec
        guard = RegressionGuard(Path("."))
        spec = ExperimentSpec(
            hypothesis="test",
            files_allowed=["core/policy_engine.py"],  # CRITICAL!
        )
        baseline = {"passed": 100, "failed": 0}
        candidate = {"passed": 100, "failed": 0}

        evaluation = guard.evaluate(spec, baseline, candidate)
        assert evaluation.safety_score == 0.0
        assert not evaluation.passed

    def test_improvement_promotes(self):
        """Experiment that improves test results promotes."""
        from core.improvement_loop import RegressionGuard, ExperimentSpec
        guard = RegressionGuard(Path("."))
        spec = ExperimentSpec(
            hypothesis="test",
            files_allowed=["docs/a.md"],
        )
        baseline = {"passed": 95, "failed": 5}
        candidate = {"passed": 98, "failed": 2}  # Fewer failures!

        evaluation = guard.evaluate(spec, baseline, candidate)
        assert evaluation.no_regression
        assert evaluation.passed


# ═══════════════════════════════════════════════════════════════
# ENGINE INTEGRATION (K8)
# ═══════════════════════════════════════════════════════════════

class TestEngineIntegration:

    def test_blocked_experiment_produces_report(self, tmp_path):
        """K8: Engine doesn't crash on blocked experiment."""
        from core.improvement_loop import ImprovementLoop, ExperimentSpec
        engine = ImprovementLoop(tmp_path)

        spec = ExperimentSpec(
            hypothesis="",  # Invalid: empty
            files_allowed=["docs/a.md"],
        )
        report = engine.run_experiment(spec)
        assert report.decision == "blocked"
        assert "hypothesis" in report.reason.lower()

    def test_critical_file_blocked(self, tmp_path):
        """K7: Experiment targeting critical file is blocked."""
        from core.improvement_loop import ImprovementLoop, ExperimentSpec
        engine = ImprovementLoop(tmp_path)

        spec = ExperimentSpec(
            hypothesis="Improve auth",
            files_allowed=["core/auth/token.py"],
        )
        report = engine.run_experiment(spec)
        assert report.decision == "blocked"
        assert "CRITICAL" in report.reason

    def test_error_in_patch_triggers_rollback(self, tmp_path):
        """K8: If patch function throws, files are rolled back."""
        from core.improvement_loop import ImprovementLoop, ExperimentSpec
        repo = tmp_path
        (repo / "safe_file.py").write_text("original")
        (repo / "workspace").mkdir(exist_ok=True)
        (repo / "workspace" / "improvement_reports").mkdir(parents=True, exist_ok=True)

        engine = ImprovementLoop(repo)

        spec = ExperimentSpec(
            hypothesis="test error handling",
            files_allowed=["safe_file.py"],
            regression_tests="nonexistent_tests/",  # Will fail baseline
        )

        def bad_patch(root, s):
            (root / "safe_file.py").write_text("CORRUPTED")
            raise RuntimeError("Patch failed!")

        report = engine.run_experiment(spec, apply_patch=bad_patch)
        # File should be rolled back
        assert (repo / "safe_file.py").read_text(encoding="utf-8") == "original"
        assert report.decision in ("error", "blocked")

    def test_lesson_stored_on_block(self, tmp_path):
        """K5: Even blocked experiments store a lesson."""
        from core.improvement_loop import ImprovementLoop, ExperimentSpec
        engine = ImprovementLoop(tmp_path)

        spec = ExperimentSpec(
            hypothesis="",
            files_allowed=["docs/a.md"],
            target_subsystem="docs",
        )
        engine.run_experiment(spec)

        lessons = engine.memory.get_lessons()
        assert len(lessons) >= 1
        assert lessons[0].outcome == "blocked"


# ═══════════════════════════════════════════════════════════════
# REPORT GENERATION (K11)
# ═══════════════════════════════════════════════════════════════

class TestReportGeneration:

    def test_report_has_json_and_markdown(self):
        from core.improvement_loop import ExperimentReport
        report = ExperimentReport(
            experiment_id="exp-test",
            spec={"hypothesis": "test", "target_subsystem": "docs",
                  "files_allowed": ["docs/a.md"], "risk_class": "low"},
            baseline={"passed": 10, "failed": 0},
            candidate={"passed": 10, "failed": 0},
            evaluation={"composite": 0.9, "passed": True},
            diffs={"docs/a.md": "+added line"},
            decision="promoted",
            reason="All gates passed",
            rollback_instructions="git checkout -- docs/a.md",
            lesson={"outcome": "promoted", "what_worked": "Added docs"},
        )

        json_str = report.to_json()
        data = json.loads(json_str)
        assert data["decision"] == "promoted"

        md_str = report.to_markdown()
        assert "# Experiment Report" in md_str
        assert "promoted" in md_str.lower()
        assert "docs/a.md" in md_str


# ═══════════════════════════════════════════════════════════════
# REGRESSION GUARD PARSER
# ═══════════════════════════════════════════════════════════════

class TestRegressionGuardParser:

    def test_parse_pytest_output(self):
        from core.improvement_loop import RegressionGuard
        result = RegressionGuard._parse_pytest_output(
            "42 passed, 3 failed, 1 error in 5.2s")
        assert result["passed"] == 42
        assert result["failed"] == 3
        assert result["errors"] == 1
        assert result["success"] is False

    def test_parse_all_pass(self):
        from core.improvement_loop import RegressionGuard
        result = RegressionGuard._parse_pytest_output("100 passed in 8.3s")
        assert result["passed"] == 100
        assert result["failed"] == 0
        assert result["success"] is True

    def test_parse_empty_output(self):
        from core.improvement_loop import RegressionGuard
        result = RegressionGuard._parse_pytest_output("")
        assert result["passed"] == 0
        assert result["success"] is False
