"""
Live proof: two experiments through the ImprovementLoop.
  1. REJECTED: patch that introduces a regression
  2. PROMOTED: safe patch that improves code without regression
"""
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.improvement_loop import (
    ImprovementLoop, ExperimentSpec,
)


class TestLiveProof:
    """End-to-end proof with real sandbox, real rollback, real lessons."""

    def _make_engine(self, tmp_path):
        # Create a mini "repo" with a test file
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "workspace" / "improvement_reports").mkdir(parents=True)
        # A real Python file we'll experiment on
        (repo / "utils.py").write_text(
            'def add(a, b):\n    return a + b\n\n'
            'def greet(name):\n    return f"Hello {name}"\n'
        )
        return ImprovementLoop(repo), repo

    # ── EXPERIMENT 1: REJECTED (regression detected) ──────────

    def test_rejected_experiment_regression(self, tmp_path):
        """
        Patch introduces a bug (breaks add function).
        Engine must: detect regression → reject → rollback → store lesson.
        """
        engine, repo = self._make_engine(tmp_path)

        spec = ExperimentSpec(
            hypothesis="Optimize add() by removing type check",
            files_allowed=["utils.py"],
            target_subsystem="utils",
            weakness_detected="add() is slow",
        )

        def bad_patch(root, s):
            # Introduce a bug: add returns wrong result
            (root / "utils.py").write_text(
                'def add(a, b):\n    return a - b  # BUG!\n\n'
                'def greet(name):\n    return f"Hello {name}"\n'
            )
            return "Changed + to - in add()"

        # Override run_tests to simulate real pytest results

        call_count = [0]
        def mock_run_tests(test_path, timeout=120):
            call_count[0] += 1
            if call_count[0] == 1:
                # Baseline: all good
                return {"passed": 50, "failed": 0, "errors": 0, "success": True}
            else:
                # After patch: regression!
                return {"passed": 45, "failed": 5, "errors": 0, "success": False}

        engine.guard.run_tests = mock_run_tests

        report = engine.run_experiment(spec, apply_patch=bad_patch)

        # ── ASSERTIONS ──
        assert report.decision == "rejected", f"Expected rejected, got {report.decision}"
        assert "regression" in report.reason.lower(), f"Reason should mention regression: {report.reason}"

        # File must be rolled back to original
        content = (repo / "utils.py").read_text(encoding="utf-8")
        assert "return a + b" in content, "File not rolled back!"
        assert "return a - b" not in content, "Bug still present after rollback!"

        # Lesson stored
        lessons = engine.memory.get_lessons()
        assert len(lessons) >= 1
        assert lessons[0].outcome == "rejected"
        assert lessons[0].experiment_id == spec.id

        # Report is valid JSON
        data = json.loads(report.to_json())
        assert data["decision"] == "rejected"
        assert data["baseline"]["passed"] == 50
        assert data["candidate"]["failed"] == 5

        print(f"\n✗ REJECTED: {report.reason}")
        print("  Rollback: confirmed (original restored)")
        print(f"  Lesson: {lessons[0].what_failed[:80]}")

    # ── EXPERIMENT 2: PROMOTED (safe improvement) ─────────────

    def test_promoted_experiment_safe(self, tmp_path):
        """
        Patch adds a docstring (zero-risk improvement).
        Engine must: verify no regression → promote → store lesson → cleanup sandbox.
        """
        engine, repo = self._make_engine(tmp_path)

        spec = ExperimentSpec(
            hypothesis="Add docstrings to improve code documentation",
            files_allowed=["utils.py"],
            target_subsystem="utils",
            weakness_detected="Missing docstrings reduce maintainability",
        )

        def safe_patch(root, s):
            (root / "utils.py").write_text(
                '"""Utility functions for BeaMax."""\n\n'
                'def add(a, b):\n    """Add two numbers."""\n    return a + b\n\n'
                'def greet(name):\n    """Greet someone by name."""\n    return f"Hello {name}"\n'
            )
            return "Added module docstring + function docstrings"

        # Both baseline and candidate pass identically (no regression)
        def mock_run_tests(test_path, timeout=120):
            return {"passed": 50, "failed": 0, "errors": 0, "success": True}

        engine.guard.run_tests = mock_run_tests

        report = engine.run_experiment(spec, apply_patch=safe_patch)

        # ── ASSERTIONS ──
        assert report.decision == "promoted", f"Expected promoted, got {report.decision}: {report.reason}"

        # File should contain the improvement (NOT rolled back)
        content = (repo / "utils.py").read_text(encoding="utf-8")
        assert '"""Utility functions for BeaMax."""' in content
        assert '"""Add two numbers."""' in content

        # Lesson stored as success
        lessons = engine.memory.get_lessons()
        promoted = [l for l in lessons if l.outcome == "promoted"]
        assert len(promoted) >= 1
        assert promoted[0].what_worked == "Added module docstring + function docstrings"

        # Sandbox cleaned up after promotion
        assert spec.id not in engine.sandbox.list_active()

        # Report is valid
        data = json.loads(report.to_json())
        assert data["decision"] == "promoted"
        assert data["evaluation"]["passed"] is True
        assert data["evaluation"]["no_regression"] is True

        print(f"\n✓ PROMOTED: {report.reason}")
        print(f"  Score: {data['evaluation']['composite']}")
        print(f"  Lesson: {promoted[0].what_worked}")

    # ── EXPERIMENT 3: BLOCKED (critical file) ─────────────────

    def test_blocked_critical_file(self, tmp_path):
        """Attempt to modify meta_orchestrator → auto-blocked before any test runs."""
        engine, repo = self._make_engine(tmp_path)

        spec = ExperimentSpec(
            hypothesis="Optimize orchestrator loop",
            files_allowed=["core/meta_orchestrator.py"],
            target_subsystem="orchestrator",
        )

        report = engine.run_experiment(spec)
        assert report.decision == "blocked"
        assert "CRITICAL" in report.reason

        print(f"\n⛔ BLOCKED: {report.reason}")

    # ── EXPERIMENT 4: Error recovery ──────────────────────────

    def test_error_recovery_rollback(self, tmp_path):
        """Patch function crashes → engine rolls back and reports error."""
        engine, repo = self._make_engine(tmp_path)

        spec = ExperimentSpec(
            hypothesis="Test crash recovery",
            files_allowed=["utils.py"],
            target_subsystem="utils",
        )

        original = (repo / "utils.py").read_text(encoding="utf-8")

        def crashing_patch(root, s):
            (root / "utils.py").write_text("CORRUPTED")
            raise RuntimeError("LLM returned garbage")

        def mock_run_tests(test_path, timeout=120):
            return {"passed": 50, "failed": 0, "errors": 0, "success": True}

        engine.guard.run_tests = mock_run_tests

        report = engine.run_experiment(spec, apply_patch=crashing_patch)

        assert report.decision == "error"
        assert (repo / "utils.py").read_text(encoding="utf-8") == original, "File not restored after crash!"

        print(f"\n🔄 ERROR RECOVERED: {report.reason}")
        print("  File restored: ✓")
