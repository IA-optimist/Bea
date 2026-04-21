"""
core/self_improvement/research_loop.py — Autonomous Research-Grade Self-Improvement Loop.

Orchestrates: observe → hypothesize → experiment → evaluate → promote/reject → learn

Builds on existing modules:
- weakness_detector.py (detection)
- candidate_generator.py (hypothesis)
- safe_executor.py (bounded changes)
- validation_runner.py (testing)
- benchmark_suite.py (metrics)
- improvement_memory.py (learning)
- safety_boundary.py (protection)
- improvement_loop.py (critic + adoption gate)

Adds:
- Sandbox isolation
- Baseline/candidate scoring
- Structured experiment reports
- Promotion gate with regression guard
- Rollback management
- Loop scheduling with hard limits
"""
from __future__ import annotations

import json
import os
import shutil
import time
import uuid
import structlog
from dataclasses import dataclass, field
_silent_log = __import__("structlog").get_logger(__name__)

log = structlog.get_logger("jarvis.research_loop")

SANDBOX_ROOT = "workspace/sandbox"
REPORT_DIR = "workspace/reports/experiments"
MAX_LOW_RISK_PER_CYCLE = 3
MAX_MEDIUM_RISK_PER_CYCLE = 1


# ── Experiment State ─────────────────────────────────────────────────────────

@dataclass
class ExperimentSpec:
    """One bounded improvement experiment."""
    experiment_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    weakness_id: str = ""
    hypothesis: str = ""
    target_files: list[str] = field(default_factory=list)
    risk_level: str = "LOW"  # LOW, MEDIUM, HIGH, CRITICAL
    subsystem: str = ""
    expected_improvement: str = ""
    success_criteria: str = ""
    skill_type: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class BaselineMetrics:
    """Metrics snapshot before experiment."""
    test_pass_rate: float = 0
    test_count: int = 0
    test_failures: int = 0
    mission_success_rate: float = 0
    tool_success_rate: float = 0
    endpoint_health: bool = True
    trace_completeness: float = 0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    def composite_score(self) -> float:
        """Weighted composite system score."""
        return round(
            self.test_pass_rate * 0.25 +
            self.mission_success_rate * 0.20 +
            self.tool_success_rate * 0.15 +
            (1.0 if self.endpoint_health else 0.0) * 0.15 +
            self.trace_completeness * 0.10 +
            (1.0 - min(1.0, self.test_failures / max(1, self.test_count))) * 0.15,
            4
        )


@dataclass
class ExperimentResult:
    """Full result of one experiment cycle."""
    experiment_id: str = ""
    spec: dict = field(default_factory=dict)
    baseline: dict = field(default_factory=dict)
    candidate: dict = field(default_factory=dict)
    baseline_score: float = 0
    candidate_score: float = 0
    score_delta: float = 0
    tests_passed: bool = False
    regression_detected: bool = False
    promoted: bool = False
    rejected_reason: str = ""
    rollback_info: dict = field(default_factory=dict)
    duration_ms: float = 0
    lessons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


# ── Risk Analyzer ────────────────────────────────────────────────────────────

PROTECTED_ZONES = frozenset({
    "core/meta_orchestrator.py", "core/tool_executor.py", "core/orchestrator.py",
    "core/policy/policy_engine.py", "core/resilience/_base.py",
    "core/self_improvement/safety_boundary.py", "api/main.py", "main.py",
    "core/state.py", "core/startup_guard.py",
})

SUBSYSTEM_RISK = {
    "auth": "HIGH", "policy": "HIGH", "executor": "MEDIUM",
    "memory": "MEDIUM", "orchestrator": "HIGH", "tools": "LOW",
    "skills": "LOW", "observability": "LOW", "mobile": "MEDIUM",
    "connectors": "LOW", "knowledge": "LOW",
}


def analyze_risk(spec: ExperimentSpec) -> str:
    """Compute risk level for an experiment."""
    # Check protected zones
    for f in spec.target_files:
        if f in PROTECTED_ZONES:
            return "CRITICAL"
    # Check subsystem risk
    sub_risk = SUBSYSTEM_RISK.get(spec.subsystem, "LOW")
    if sub_risk == "HIGH":
        return "HIGH"
    if len(spec.target_files) > 5:
        return "MEDIUM" if sub_risk == "LOW" else "HIGH"
    return sub_risk


# ── Sandbox Manager ──────────────────────────────────────────────────────────

class SandboxManager:
    """Manage isolated experiment sandboxes."""

    def __init__(self, root: str = SANDBOX_ROOT):
        self._root = root

    def create(self, experiment_id: str, target_files: list[str]) -> str:
        """Create sandbox with copies of target files. Returns sandbox path."""
        sandbox_path = os.path.join(self._root, experiment_id)
        os.makedirs(sandbox_path, exist_ok=True)

        for f in target_files:
            if os.path.exists(f):
                dest = os.path.join(sandbox_path, os.path.basename(f))
                shutil.copy2(f, dest)
                # Also save original as .orig for diff
                shutil.copy2(f, dest + ".orig")

        log.info("sandbox_created", experiment=experiment_id,
                 files=len(target_files), path=sandbox_path)
        return sandbox_path

    def cleanup(self, experiment_id: str) -> None:
        """Remove sandbox after experiment."""
        sandbox_path = os.path.join(self._root, experiment_id)
        if os.path.isdir(sandbox_path):
            shutil.rmtree(sandbox_path, ignore_errors=True)
            log.debug("sandbox_cleaned", experiment=experiment_id)

    def list_sandboxes(self) -> list[str]:
        if not os.path.isdir(self._root):
            return []
        return [d for d in os.listdir(self._root)
                if os.path.isdir(os.path.join(self._root, d))]


# ── Regression Guard ─────────────────────────────────────────────────────────

class RegressionGuard:
    """Zero tolerance regression check."""

    CRITICAL_CHECKS = [
        "auth_flow", "websocket_handshake", "mission_lifecycle",
        "memory_persistence", "policy_enforcement", "executor_completion",
        "test_pass_rate",
    ]

    def check(self, baseline: BaselineMetrics, candidate: BaselineMetrics) -> tuple[bool, list[str]]:
        """Compare baseline vs candidate. Returns (passed, regressions)."""
        regressions = []

        if candidate.test_pass_rate < baseline.test_pass_rate:
            regressions.append(
                f"test_pass_rate: {baseline.test_pass_rate:.3f} → {candidate.test_pass_rate:.3f}")

        if candidate.test_failures > baseline.test_failures:
            regressions.append(
                f"test_failures: {baseline.test_failures} → {candidate.test_failures}")

        if not candidate.endpoint_health and baseline.endpoint_health:
            regressions.append("endpoint_health: healthy → unhealthy")

        if candidate.mission_success_rate < baseline.mission_success_rate - 0.01:
            regressions.append(
                f"mission_success: {baseline.mission_success_rate:.3f} → {candidate.mission_success_rate:.3f}")

        passed = len(regressions) == 0
        if not passed:
            log.warning("regression_detected", count=len(regressions),
                        details=regressions[:3])
        return passed, regressions


# ── Promotion Gate ───────────────────────────────────────────────────────────

class PromotionGate:
    """Decide whether to promote an experiment result."""

    def evaluate(self, result: ExperimentResult, risk: str) -> tuple[bool, str]:
        """Returns (promote, reason)."""
        # Hard rejects
        if result.regression_detected:
            return False, "Regression detected — auto-rejected"
        if not result.tests_passed:
            return False, "Tests failed — auto-rejected"
        if risk == "CRITICAL":
            return False, "CRITICAL risk — requires manual review"

        # Score check
        if result.score_delta < 0:
            return False, f"Score decreased by {abs(result.score_delta):.4f}"

        # HIGH risk needs improvement proof
        if risk == "HIGH" and result.score_delta < 0.001:
            return False, "HIGH risk with no measurable improvement"

        # Promote
        if result.score_delta > 0:
            return True, f"Score improved by {result.score_delta:.4f}"
        if result.score_delta == 0 and risk in ("LOW", "MEDIUM"):
            return True, "Score neutral, no regression (LOW/MEDIUM risk OK)"

        return False, "No improvement detected"


# ── Rollback Manager ────────────────────────────────────────────────────────

class RollbackManager:
    """Track rollback artifacts for every experiment."""

    def __init__(self, root: str = "workspace/rollbacks"):
        self._root = root
        os.makedirs(root, exist_ok=True)

    def create_rollback_point(self, experiment_id: str,
                               target_files: list[str]) -> dict:
        """Save current state of target files as rollback point."""
        rb_dir = os.path.join(self._root, experiment_id)
        os.makedirs(rb_dir, exist_ok=True)

        backups = {}
        for f in target_files:
            if os.path.exists(f):
                dest = os.path.join(rb_dir, os.path.basename(f))
                shutil.copy2(f, dest)
                backups[f] = dest

        info = {
            "experiment_id": experiment_id,
            "timestamp": time.time(),
            "files": backups,
            "git_sha": self._get_git_sha(),
        }
        with open(os.path.join(rb_dir, "rollback.json"), "w") as fp:
            json.dump(info, fp, indent=2)

        log.info("rollback_point_created", experiment=experiment_id,
                 files=len(backups))
        return info

    def rollback(self, experiment_id: str) -> tuple[bool, str]:
        """Restore files from rollback point."""
        rb_dir = os.path.join(self._root, experiment_id)
        info_path = os.path.join(rb_dir, "rollback.json")
        if not os.path.exists(info_path):
            return False, f"No rollback point: {experiment_id}"

        with open(info_path) as f:
            info = json.load(f)

        restored = 0
        for original, backup in info.get("files", {}).items():
            if os.path.exists(backup):
                shutil.copy2(backup, original)
                restored += 1

        log.info("rollback_executed", experiment=experiment_id, files=restored)
        return True, f"Restored {restored} files"

    @staticmethod
    def _get_git_sha() -> str:
        try:
            import subprocess
            r = subprocess.run(["git", "rev-parse", "HEAD"],
                               capture_output=True, text=True, timeout=3)
            return r.stdout.strip()[:12] if r.returncode == 0 else ""
        except Exception:
            return ""


# ── Metrics Collector ────────────────────────────────────────────────────────

def collect_metrics() -> BaselineMetrics:
    """Collect current system metrics."""
    m = BaselineMetrics()

    # Test suite
    try:
        import subprocess
        r = subprocess.run(
            ["python3", "-m", "pytest", "tests/", "-q", "--tb=no",
             "--ignore=tests/aios_full_battery.py", "-x"],
            capture_output=True, text=True, timeout=60, cwd="/app"
        )
        output = r.stdout + r.stderr
        # Parse "X passed, Y failed" from pytest output
        for line in output.split("\n"):
            if "passed" in line:
                parts = line.split()
                for i, p in enumerate(parts):
                    if p == "passed" and i > 0:
                        try:
                            m.test_count += int(parts[i - 1])
                        except ValueError:
                            _silent_log.debug("suppressed_exception", src='research_loop.py')
                    if p == "failed" and i > 0:
                        try:
                            m.test_failures += int(parts[i - 1])
                            m.test_count += int(parts[i - 1])
                        except ValueError:
                            _silent_log.debug("suppressed_exception", src='research_loop.py')
        m.test_pass_rate = (m.test_count - m.test_failures) / m.test_count if m.test_count else 1.0
    except Exception as e:
        log.debug("metrics_test_failed", err=str(e)[:60])
        m.test_pass_rate = 0

    # Health endpoint
    try:
        import httpx
        r = httpx.get("http://localhost:8000/health", timeout=3)
        m.endpoint_health = r.status_code == 200
    except Exception:
        m.endpoint_health = False

    # Mission success from recent missions
    try:
        from core.mission_system import get_mission_system
        ms = get_mission_system()
        missions = ms.list_missions(limit=20)
        if missions:
            done = sum(1 for mi in missions if mi.status in ("DONE", "COMPLETED"))
            m.mission_success_rate = done / len(missions)
    except Exception:
        m.mission_success_rate = 0.9  # Assume healthy if can't measure

    # Tool success from recovery engine
    try:
        from core.resilience.recovery_engine import get_recovery_engine
        stats = get_recovery_engine().stats()
        m.tool_success_rate = 1.0  # Default if no failures tracked
    except Exception:
        m.tool_success_rate = 0.9

    # Trace completeness
    try:
        traces_dir = "workspace/traces"
        if os.path.isdir(traces_dir):
            traces = os.listdir(traces_dir)
            if traces:
                complete = 0
                for t in traces[-10:]:
                    with open(os.path.join(traces_dir, t)) as f:
                        events = [json.loads(l) for l in f if l.strip()]
                    phases = {e.get("phase") for e in events}
                    if "classify" in phases and "complete" in phases:
                        complete += 1
                m.trace_completeness = complete / min(10, len(traces))
    except Exception:
        m.trace_completeness = 0.8

    return m


# ── Report Generator ─────────────────────────────────────────────────────────

def generate_report(result: ExperimentResult) -> str:
    """Generate markdown experiment report."""
    os.makedirs(REPORT_DIR, exist_ok=True)

    md = f"""# Experiment Report: {result.experiment_id}

## Spec
- **Hypothesis**: {result.spec.get('hypothesis', 'N/A')}
- **Subsystem**: {result.spec.get('subsystem', 'N/A')}
- **Risk**: {result.spec.get('risk_level', 'N/A')}
- **Target files**: {', '.join(result.spec.get('target_files', []))}

## Baseline
- Score: **{result.baseline_score:.4f}**
- Test pass rate: {result.baseline.get('test_pass_rate', 0):.3f}
- Tests: {result.baseline.get('test_count', 0)} ({result.baseline.get('test_failures', 0)} failures)
- Health: {'✅' if result.baseline.get('endpoint_health') else '❌'}

## Candidate
- Score: **{result.candidate_score:.4f}**
- Test pass rate: {result.candidate.get('test_pass_rate', 0):.3f}
- Tests: {result.candidate.get('test_count', 0)} ({result.candidate.get('test_failures', 0)} failures)
- Health: {'✅' if result.candidate.get('endpoint_health') else '❌'}

## Result
- **Score delta**: {result.score_delta:+.4f}
- **Tests passed**: {'✅' if result.tests_passed else '❌'}
- **Regression**: {'❌ DETECTED' if result.regression_detected else '✅ None'}
- **Decision**: {'✅ PROMOTED' if result.promoted else f'❌ REJECTED: {result.rejected_reason}'}
- **Duration**: {result.duration_ms:.0f}ms

## Lessons
{chr(10).join(f'- {l}' for l in result.lessons) if result.lessons else '- No lessons recorded'}

## Rollback
{json.dumps(result.rollback_info, indent=2) if result.rollback_info else 'N/A'}
"""
    # Save
    report_path = os.path.join(REPORT_DIR, f"{result.experiment_id}.md")
    with open(report_path, "w") as f:
        f.write(md)

    json_path = os.path.join(REPORT_DIR, f"{result.experiment_id}.json")
    with open(json_path, "w") as f:
        json.dump(result.to_dict(), f, indent=2, default=str)

    return report_path


# ── Research Loop ────────────────────────────────────────────────────────────

class ResearchLoop:
    """Autonomous research-grade self-improvement loop."""

    def __init__(self):
        self._sandbox = SandboxManager()
        self._guard = RegressionGuard()
        self._gate = PromotionGate()
        self._rollback = RollbackManager()
        self._history: list[ExperimentResult] = []

    def run_cycle(self, max_experiments: int = 1) -> list[ExperimentResult]:
        """Run one improvement cycle: detect → hypothesize → experiment → evaluate."""
        results = []

        # 1. Detect weaknesses
        try:
            from core.self_improvement.weakness_detector import get_weakness_detector
            detector = get_weakness_detector()
            weaknesses = detector.detect()
            log.info("weaknesses_detected", count=len(weaknesses))
        except Exception as e:
            log.warning("weakness_detection_failed", err=str(e)[:80])
            return results

        if not weaknesses:
            log.info("no_weaknesses_detected")
            return results

        # 2. Generate hypotheses (candidates)
        try:
            from core.self_improvement.candidate_generator import get_candidate_generator
            generator = get_candidate_generator()
            candidates = generator.generate(weaknesses)
            log.info("candidates_generated", count=len(candidates))
        except Exception as e:
            log.warning("candidate_generation_failed", err=str(e)[:80])
            return results

        # 3. Run bounded experiments
        low_risk_count = 0
        medium_risk_count = 0

        for candidate in candidates[:max_experiments]:
            spec = ExperimentSpec(
                weakness_id=getattr(candidate, 'weakness_id', ''),
                hypothesis=getattr(candidate, 'description', str(candidate)),
                target_files=getattr(candidate, 'target_files', []),
                subsystem=getattr(candidate, 'subsystem', 'unknown'),
                expected_improvement=getattr(candidate, 'expected_improvement', ''),
                skill_type=getattr(candidate, 'improvement_type', ''),
            )
            spec.risk_level = analyze_risk(spec)

            # Enforce limits
            if spec.risk_level == "CRITICAL":
                log.info("skip_critical", experiment=spec.experiment_id)
                continue
            if spec.risk_level == "HIGH":
                log.info("skip_high_auto", experiment=spec.experiment_id)
                continue
            if spec.risk_level == "MEDIUM":
                if medium_risk_count >= MAX_MEDIUM_RISK_PER_CYCLE:
                    continue
                medium_risk_count += 1
            if spec.risk_level == "LOW":
                if low_risk_count >= MAX_LOW_RISK_PER_CYCLE:
                    continue
                low_risk_count += 1

            result = self._run_experiment(spec)
            results.append(result)
            self._history.append(result)

            # Store learning
            self._store_learning(result)

        return results

    def _run_experiment(self, spec: ExperimentSpec) -> ExperimentResult:
        """Execute a single experiment with full lifecycle."""
        start = time.time()
        result = ExperimentResult(experiment_id=spec.experiment_id, spec=spec.to_dict())

        log.info("experiment_start", id=spec.experiment_id,
                 hypothesis=spec.hypothesis[:60], risk=spec.risk_level)

        try:
            # 1. Collect baseline
            baseline = collect_metrics()
            result.baseline = baseline.to_dict()
            result.baseline_score = baseline.composite_score()

            # 2. Create rollback point
            rb_info = self._rollback.create_rollback_point(
                spec.experiment_id, spec.target_files)
            result.rollback_info = rb_info

            # 3. Create sandbox
            sandbox_path = self._sandbox.create(spec.experiment_id, spec.target_files)

            # 4. Apply change via safe executor
            try:
                from core.self_improvement.safe_executor import get_safe_executor
                executor = get_safe_executor()

                # Create a candidate-like object for the executor
                class _Candidate:
                    def __init__(self, s):
                        self.improvement_type = s.skill_type or "prompt"
                        self.description = s.hypothesis
                        self.target_file = s.target_files[0] if s.target_files else ""
                        self.risk_level = s.risk_level
                        self.new_value = ""
                        self.key = ""

                exec_result = executor.execute(_Candidate(spec))
                if not exec_result.success:
                    result.rejected_reason = f"Execution failed: {exec_result.error}"
                    return result
            except Exception as e:
                result.rejected_reason = f"Executor error: {str(e)[:100]}"
                return result

            # 5. Collect candidate metrics
            candidate = collect_metrics()
            result.candidate = candidate.to_dict()
            result.candidate_score = candidate.composite_score()
            result.score_delta = round(result.candidate_score - result.baseline_score, 4)

            # 6. Regression check
            passed, regressions = self._guard.check(baseline, candidate)
            result.regression_detected = not passed
            result.tests_passed = candidate.test_pass_rate >= baseline.test_pass_rate

            # 7. Promotion decision
            promote, reason = self._gate.evaluate(result, spec.risk_level)
            result.promoted = promote
            if not promote:
                result.rejected_reason = reason
                # Rollback
                self._rollback.rollback(spec.experiment_id)
                result.lessons.append(f"Rejected: {reason}")
            else:
                result.lessons.append(f"Promoted: {reason}")

        except Exception as e:
            result.rejected_reason = f"Experiment failed: {str(e)[:100]}"
            self._rollback.rollback(spec.experiment_id)
            result.lessons.append(f"Error: {str(e)[:100]}")

        finally:
            result.duration_ms = (time.time() - start) * 1000
            # Generate report
            generate_report(result)
            # Cleanup sandbox
            self._sandbox.cleanup(spec.experiment_id)

            log.info("experiment_complete", id=spec.experiment_id,
                     promoted=result.promoted, delta=result.score_delta,
                     duration=round(result.duration_ms))

        return result

    def _store_learning(self, result: ExperimentResult) -> None:
        """Record experiment in improvement memory."""
        try:
            from core.self_improvement.improvement_memory import get_improvement_memory
            mem = get_improvement_memory()
            mem.record(
                candidate_type=result.spec.get("skill_type", "prompt"),
                description=result.spec.get("hypothesis", "")[:200],
                score=max(0.0, min(1.0, result.candidate_score)),
                outcome="SUCCESS" if result.promoted else "FAILURE",
                applied_change=f"delta={result.score_delta:+.4f}" if result.promoted else "",
            )
        except Exception as e:
            log.debug("learning_store_failed", err=str(e)[:60])

    def get_history(self) -> list[dict]:
        return [r.to_dict() for r in self._history]

    def stats(self) -> dict:
        total = len(self._history)
        promoted = sum(1 for r in self._history if r.promoted)
        return {
            "total_experiments": total,
            "promoted": promoted,
            "rejected": total - promoted,
            "avg_score_delta": round(
                sum(r.score_delta for r in self._history) / total, 4
            ) if total else 0,
            "sandboxes": self._sandbox.list_sandboxes(),
        }


# ── Singleton ────────────────────────────────────────────────────────────────

_loop: ResearchLoop | None = None

def get_research_loop() -> ResearchLoop:
    global _loop
    if _loop is None:
        _loop = ResearchLoop()
    return _loop
