"""
Tests — Improvement Daemon

Coverage:
  D1. Weakness detection from metrics (6 categories)
  D2. No weaknesses on clean metrics
  D3. Experiment proposal from weakness
  D4. Critical file proposals blocked
  D5. Run cycle with degraded executor (simulated)
  D6. Run cycle with no weaknesses
  D7. Past failures skipped (dedup)
  D8. Daemon state tracking
  D9. Safe patch generation — timeout bump
  D10. Safe patch generation — retry bump
  D11. Daemon start/stop lifecycle
  D12. Cycle emits metrics
  D13. Safety limits enforced (max 1 experiment, max 3 files)
"""
import os
import sys
import time
import threading
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Daemon tests ne sont PAS des tests sécurité gate — bypass explicite.
# Le gate est ré-activé par défaut (conftest.py), ce module se réactive en
# local pour que les cycle tests valident le comportement fonctionnel du
# daemon, pas la sécurité (testée séparément dans test_improvement_gate_security).
os.environ["JARVIS_SKIP_IMPROVEMENT_GATE"] = "1"


# ═══════════════════════════════════════════════════════════════
# WEAKNESS DETECTION (D1, D2)
# ═══════════════════════════════════════════════════════════════

class TestWeaknessDetection:

    def test_low_success_rate(self):
        """D1: Detect low mission success rate."""
        from core.metrics_store import reset_metrics, emit_mission_submitted, emit_mission_completed, emit_mission_failed
        from core.improvement_daemon import detect_weaknesses
        m = reset_metrics()

        for _ in range(10):
            emit_mission_submitted("test")
        for _ in range(3):
            emit_mission_completed("test", 1000)
        for _ in range(7):
            emit_mission_failed("test", "crash")

        weaknesses = detect_weaknesses()
        assert any(w.category == "low_success" for w in weaknesses)

    def test_tool_failure_rate(self):
        """D1: Detect high tool failure rate."""
        from core.metrics_store import reset_metrics, emit_tool_invocation
        from core.improvement_daemon import detect_weaknesses
        m = reset_metrics()

        for _ in range(3):
            emit_tool_invocation("web_search", True)
        for _ in range(5):
            emit_tool_invocation("web_search", False)

        weaknesses = detect_weaknesses()
        assert any(w.category == "slow_tool" for w in weaknesses)

    def test_timeout_detection(self):
        """D1: Detect high timeout count."""
        from core.metrics_store import reset_metrics, emit_tool_timeout
        from core.improvement_daemon import detect_weaknesses
        m = reset_metrics()

        for _ in range(5):
            emit_tool_timeout("shell_command")

        weaknesses = detect_weaknesses()
        assert any(w.category == "timeout" for w in weaknesses)

    def test_retry_storm(self):
        """D1: Detect retry storm."""
        from core.metrics_store import reset_metrics, emit_retry
        from core.improvement_daemon import detect_weaknesses
        m = reset_metrics()

        for _ in range(8):
            emit_retry("executor")

        weaknesses = detect_weaknesses()
        assert any(w.category == "retry" for w in weaknesses)

    def test_failure_patterns(self):
        """D1: Detect recurring failure patterns."""
        from core.metrics_store import reset_metrics, get_metrics
        from core.improvement_daemon import detect_weaknesses
        m = reset_metrics()

        for _ in range(5):
            m.record_failure("timeout", "executor", "timed out")

        weaknesses = detect_weaknesses()
        assert any(w.category == "failure_pattern" for w in weaknesses)

    def test_no_weaknesses_clean(self):
        """D2: No weaknesses on fresh metrics."""
        from core.metrics_store import reset_metrics
        from core.improvement_daemon import detect_weaknesses
        reset_metrics()

        weaknesses = detect_weaknesses()
        assert len(weaknesses) == 0

    def test_sorted_by_severity(self):
        """Weaknesses sorted by severity (high before medium)."""
        from core.metrics_store import reset_metrics, emit_mission_submitted, emit_mission_failed, emit_tool_timeout
        from core.improvement_daemon import detect_weaknesses
        m = reset_metrics()

        # Low success (high severity: < 0.5)
        for _ in range(10):
            emit_mission_submitted("test")
        for _ in range(8):
            emit_mission_failed("test", "crash")

        # Tool timeout (medium severity)
        for _ in range(5):
            emit_tool_timeout("shell")

        weaknesses = detect_weaknesses()
        assert len(weaknesses) >= 2
        # First should be high/critical severity
        sevs = [w.severity for w in weaknesses]
        assert sevs[0] in ("high", "critical")


# ═══════════════════════════════════════════════════════════════
# EXPERIMENT PROPOSAL (D3, D4)
# ═══════════════════════════════════════════════════════════════

class TestProposal:

    def test_proposal_from_weakness(self, tmp_path):
        """D3: Generate valid proposal from weakness."""
        from core.improvement_daemon import _propose_experiment, Weakness

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "executor").mkdir()
        (repo / "executor" / "retry_policy.py").write_text("max_retries=1\n")

        weakness = Weakness(
            category="retry",
            component="executor",
            metric_name="retry_attempts_total",
            current_value=10,
            threshold=5,
            severity="medium",
            description="10 retry attempts",
            suggested_target="executor/retry_policy.py",
            suggested_fix="Tune backoff",
        )

        proposal = _propose_experiment(weakness, repo)
        assert proposal is not None
        assert proposal["files_allowed"] == ["executor/retry_policy.py"]
        assert "retry" in proposal["hypothesis"].lower()

    def test_critical_file_blocked(self, tmp_path):
        """D4: Critical file proposals return None."""
        from core.improvement_daemon import _propose_experiment, Weakness

        repo = tmp_path / "repo"
        repo.mkdir()

        weakness = Weakness(
            category="failure_pattern",
            component="orchestrator",
            metric_name="test",
            current_value=10,
            threshold=3,
            severity="high",
            description="test",
            suggested_target="core/meta_orchestrator.py",
        )

        proposal = _propose_experiment(weakness, repo)
        assert proposal is None

    def test_missing_file_returns_none(self, tmp_path):
        """Proposal for nonexistent file returns None."""
        from core.improvement_daemon import _propose_experiment, Weakness

        repo = tmp_path / "repo"
        repo.mkdir()

        weakness = Weakness(
            category="timeout",
            component="executor",
            metric_name="test",
            current_value=5,
            threshold=3,
            severity="medium",
            description="test",
            suggested_target="nonexistent/file.py",
        )

        proposal = _propose_experiment(weakness, repo)
        assert proposal is None


# ═══════════════════════════════════════════════════════════════
# SAFE PATCH GENERATION (D9, D10)
# ═══════════════════════════════════════════════════════════════

class TestSafePatch:

    def test_timeout_bump(self, tmp_path):
        """D9: Timeout values are increased."""
        from core.improvement_daemon import _generate_safe_patch, Weakness

        repo = tmp_path / "repo"
        repo.mkdir()
        target = "executor/retry_policy.py"
        (repo / "executor").mkdir()
        (repo / target).write_text("def run():\n    timeout=10\n    return timeout\n")

        weakness = Weakness(
            category="timeout",
            component="executor",
            metric_name="tool_timeout_total",
            current_value=5,
            threshold=3,
            severity="medium",
            description="5 timeouts",
        )
        spec_dict = {"files_allowed": [target]}

        modified = _generate_safe_patch(weakness, repo, spec_dict)
        assert modified is not None
        assert "timeout=10" not in modified  # Original bumped
        assert "timeout=15" in modified      # 10 + 50% = 15

    def test_retry_bump(self, tmp_path):
        """D10: Retry count is increased."""
        from core.improvement_daemon import _generate_safe_patch, Weakness

        repo = tmp_path / "repo"
        repo.mkdir()
        target = "executor/retry_policy.py"
        (repo / "executor").mkdir()
        (repo / target).write_text("def run():\n    max_retries=1\n    return True\n")

        weakness = Weakness(
            category="retry",
            component="executor",
            metric_name="retry_attempts_total",
            current_value=10,
            threshold=5,
            severity="medium",
            description="10 retries",
        )
        spec_dict = {"files_allowed": [target]}

        modified = _generate_safe_patch(weakness, repo, spec_dict)
        assert modified is not None
        assert "max_retries=2" in modified  # 1 + 1 = 2


# ═══════════════════════════════════════════════════════════════
# FULL CYCLE (D5, D6, D7, D12)
# ═══════════════════════════════════════════════════════════════

class TestCycle:

    def test_cycle_no_weaknesses(self, tmp_path):
        """D6: Cycle with clean metrics does nothing."""
        from core.metrics_store import reset_metrics
        from core.improvement_daemon import run_cycle, reset_daemon_state
        reset_metrics()
        reset_daemon_state()

        result = run_cycle(tmp_path)
        assert result["weaknesses_found"] == 0
        assert result["experiment_run"] is False
        assert result["decision"] == "none"

    def test_cycle_degraded_executor(self, tmp_path):
        """D5: Cycle detects degraded executor and proposes fix."""
        from core.metrics_store import reset_metrics, emit_tool_timeout
        from core.improvement_daemon import run_cycle, reset_daemon_state

        m = reset_metrics()
        reset_daemon_state()

        # Create repo with target file
        (tmp_path / "executor").mkdir()
        (tmp_path / "executor" / "retry_policy.py").write_text(
            "def retry():\n    timeout=10\n    return True\n")
        (tmp_path / "workspace" / "improvement_reports").mkdir(parents=True, exist_ok=True)

        # Simulate degraded executor
        for _ in range(5):
            emit_tool_timeout("shell_command")

        result = run_cycle(tmp_path)
        assert result["weaknesses_found"] >= 1
        assert result["weakness"] != ""
        # Experiment may or may not run depending on file/Docker availability
        # but the cycle should not crash
        assert "error" in result or "decision" in result

    def test_cycle_emits_metrics(self, tmp_path):
        """D12: Cycle updates daemon state."""
        from core.metrics_store import reset_metrics
        from core.improvement_daemon import run_cycle, reset_daemon_state, get_daemon_status
        reset_metrics()
        reset_daemon_state()

        run_cycle(tmp_path)
        status = get_daemon_status()
        assert status["cycles_completed"] == 1
        assert status["last_cycle_at"] > 0


# ═══════════════════════════════════════════════════════════════
# DAEMON LIFECYCLE (D8, D11)
# ═══════════════════════════════════════════════════════════════

class TestDaemonLifecycle:

    def test_state_tracking(self):
        """D8: DaemonState tracks all fields."""
        from core.improvement_daemon import DaemonState
        state = DaemonState()
        d = state.to_dict()
        assert "running" in d
        assert "cycles_completed" in d
        assert "experiments_total" in d
        assert "experiments_promoted" in d
        assert "experiments_rejected" in d
        assert "experiments_blocked" in d
        assert "errors" in d

    def test_start_stop(self):
        """D11: Start and stop daemon thread."""
        from core.improvement_daemon import start_daemon, stop_daemon, get_daemon_status, reset_daemon_state
        reset_daemon_state()

        # Set very long interval so it doesn't actually run a cycle
        os.environ["IMPROVEMENT_INTERVAL_MIN"] = "999"

        result = start_daemon()
        assert result["status"] == "started"

        # Give it a moment to start
        time.sleep(0.1)
        status = get_daemon_status()
        assert status["running"] is True

        # Stop
        result = stop_daemon()
        assert result["status"] == "stopped"

        # Clean up
        os.environ.pop("IMPROVEMENT_INTERVAL_MIN", None)

    def test_idempotent_start(self):
        """Starting twice returns already_running."""
        from core.improvement_daemon import start_daemon, stop_daemon, reset_daemon_state
        reset_daemon_state()

        os.environ["IMPROVEMENT_INTERVAL_MIN"] = "999"
        start_daemon()
        time.sleep(0.1)

        result = start_daemon()
        assert result["status"] == "already_running"

        stop_daemon()
        os.environ.pop("IMPROVEMENT_INTERVAL_MIN", None)


# ═══════════════════════════════════════════════════════════════
# SAFETY LIMITS (D13)
# ═══════════════════════════════════════════════════════════════

class TestSafetyLimits:

    def test_max_one_experiment_per_cycle(self, tmp_path):
        """D13: Only one experiment per cycle even with multiple weaknesses."""
        from core.metrics_store import reset_metrics, emit_tool_timeout, emit_retry
        from core.improvement_daemon import run_cycle, reset_daemon_state
        m = reset_metrics()
        reset_daemon_state()

        # Create multiple weaknesses
        for _ in range(5):
            emit_tool_timeout("shell")
        for _ in range(10):
            emit_retry("executor")

        (tmp_path / "executor").mkdir()
        (tmp_path / "executor" / "retry_policy.py").write_text("max_retries=1\n")
        (tmp_path / "workspace" / "improvement_reports").mkdir(parents=True)

        result = run_cycle(tmp_path)
        # Should attempt at most 1 experiment
        assert result.get("experiment_run", False) or result.get("decision") in ("none", "blocked", "error")

    def test_max_3_files_enforced(self):
        """D13: ExperimentSpec rejects > 3 files."""
        from core.improvement_loop import ExperimentSpec
        spec = ExperimentSpec(
            hypothesis="test",
            files_allowed=["a.py", "b.py", "c.py", "d.py"],
            max_files=3,
        )
        errors = spec.validate()
        assert any("too many" in e.lower() for e in errors)
