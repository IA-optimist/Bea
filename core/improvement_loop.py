"""
JARVIS MAX — Hardened Improvement Loop (V3)

Production-safe autonomous improvement cycle:
  observe → detect → hypothesize → sandbox → patch → test → evaluate → promote/reject → learn

Complements the existing self_improvement_engine.py (V2) which handles
strategy mutations. This module adds:
  - ExperimentSpec with safety zone enforcement
  - SandboxManager with file snapshots and rollback
  - RegressionGuard with composite scoring
  - PromotionGate with hard safety checks
  - LearningMemory for persistent lessons
  - Structured reporting (JSON + Markdown)

Safety zones:
  CRITICAL (auto-block): meta_orchestrator, policy_engine, tool_executor core, auth
  HIGH (manual review):  memory schema, orchestrator core, mobile auth
  MEDIUM (1/cycle):      executor internals, observability, planner
  LOW (3/cycle):         dashboards, docs, diagnostics, connectors
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import structlog
_silent_log = __import__("structlog").get_logger(__name__)

log = structlog.get_logger()


# ═══════════════════════════════════════════════════════════════
# SAFETY ZONES
# ═══════════════════════════════════════════════════════════════

class SafetyZone:
    CRITICAL = "critical"
    HIGH     = "high"
    MEDIUM   = "medium"
    LOW      = "low"

_SAFETY_RULES: list[tuple[str, str]] = [
    ("core/meta_orchestrator",     SafetyZone.CRITICAL),
    ("core/policy_engine",         SafetyZone.CRITICAL),
    ("core/tool_executor.py",      SafetyZone.CRITICAL),
    ("core/auth",                  SafetyZone.CRITICAL),
    ("core/safety",                SafetyZone.CRITICAL),
    ("main.py",                    SafetyZone.CRITICAL),
    ("api/main.py",                SafetyZone.CRITICAL),
    ("config/settings.py",         SafetyZone.CRITICAL),
    ("core/memory",                SafetyZone.HIGH),
    ("core/orchestrator.py",       SafetyZone.HIGH),
    ("core/orchestrator_",         SafetyZone.HIGH),
    ("jarvismax_app/lib/services/api_service", SafetyZone.HIGH),
    ("jarvismax_app/lib/services/websocket",   SafetyZone.HIGH),
    ("executor/",                  SafetyZone.MEDIUM),
    ("core/observability",         SafetyZone.MEDIUM),
    ("core/planner",               SafetyZone.MEDIUM),
    ("core/llm_factory",           SafetyZone.MEDIUM),
    ("core/llm_routing",           SafetyZone.MEDIUM),
    ("docs/",                      SafetyZone.LOW),
    ("tests/",                     SafetyZone.LOW),
    ("api/routes/",                SafetyZone.LOW),
]


def classify_file_safety(filepath: str) -> str:
    fp = filepath.replace("\\", "/")
    for pattern, zone in _SAFETY_RULES:
        if pattern in fp:
            return zone
    return SafetyZone.LOW


def check_safety_violations(files: list[str]) -> list[str]:
    violations = []
    zone_counts: dict[str, int] = {}
    for f in files:
        zone = classify_file_safety(f)
        zone_counts[zone] = zone_counts.get(zone, 0) + 1
        if zone == SafetyZone.CRITICAL:
            violations.append(f"CRITICAL file blocked: {f}")
    if zone_counts.get(SafetyZone.MEDIUM, 0) > 1:
        violations.append(f"MEDIUM zone: {zone_counts[SafetyZone.MEDIUM]} files (max 1/cycle)")
    if zone_counts.get(SafetyZone.LOW, 0) > 3:
        violations.append(f"LOW zone: {zone_counts[SafetyZone.LOW]} files (max 3/cycle)")
    return violations


# ═══════════════════════════════════════════════════════════════
# EXPERIMENT SPEC
# ═══════════════════════════════════════════════════════════════

@dataclass
class ExperimentSpec:
    id: str = field(default_factory=lambda: f"exp-{uuid.uuid4().hex[:10]}")
    target_subsystem: str = ""
    target_repo: str = "jarvismax"
    weakness_detected: str = ""
    hypothesis: str = ""
    files_allowed: list[str] = field(default_factory=list)
    expected_gain: str = ""
    risk_class: str = SafetyZone.LOW
    rollback_plan: str = "git checkout -- <files>"
    test_plan: list[str] = field(default_factory=list)
    regression_tests: str = "tests/"
    promotion_threshold: float = 0.0
    max_files: int = 3
    created_at: float = field(default_factory=time.time)

    def validate(self) -> list[str]:
        errors = []
        if not self.hypothesis:
            errors.append("Missing hypothesis")
        if not self.files_allowed:
            errors.append("No files_allowed specified")
        if len(self.files_allowed) > self.max_files:
            errors.append(f"Too many files: {len(self.files_allowed)} > {self.max_files}")
        errors.extend(check_safety_violations(self.files_allowed))
        return errors


# ═══════════════════════════════════════════════════════════════
# EVALUATION SCORE
# ═══════════════════════════════════════════════════════════════

@dataclass
class EvaluationScore:
    test_pass_rate: float = 0.0
    regression_pass_rate: float = 0.0
    health_score: float = 1.0
    no_regression: bool = True
    latency_delta: float = 0.0
    failure_rate_delta: float = 0.0
    safety_score: float = 1.0
    files_within_budget: bool = True

    @property
    def composite(self) -> float:
        if not self.no_regression or self.safety_score < 0.5:
            return 0.0
        if not self.files_within_budget:
            return 0.0
        return round(
            self.test_pass_rate * 0.30 + self.regression_pass_rate * 0.25
            + self.health_score * 0.15 + self.safety_score * 0.20
            + max(0, -self.failure_rate_delta) * 0.10, 4)

    @property
    def passed(self) -> bool:
        return (self.composite > 0.5 and self.no_regression
                and self.safety_score >= 0.9 and self.files_within_budget
                and self.test_pass_rate >= 0.8 and self.regression_pass_rate >= 0.95)


# ═══════════════════════════════════════════════════════════════
# SANDBOX MANAGER
# ═══════════════════════════════════════════════════════════════

class SandboxManager:
    def __init__(self, repo_root: Path, sandbox_root: Path | None = None):
        self.repo_root = Path(repo_root)
        self.sandbox_root = sandbox_root or (self.repo_root / "workspace" / ".sandbox")
        self._snapshots: dict[str, dict[str, str]] = {}

    def create(self, experiment_id: str, files: list[str]) -> Path:
        sandbox_dir = self.sandbox_root / experiment_id
        sandbox_dir.mkdir(parents=True, exist_ok=True)
        snapshots: dict[str, str] = {}
        for f in files:
            src = self.repo_root / f
            if src.exists():
                snapshots[f] = src.read_text(encoding="utf-8")
                dest = sandbox_dir / f
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
        self._snapshots[experiment_id] = snapshots
        (sandbox_dir / "_snapshots.json").write_text(
            json.dumps(snapshots, indent=2), encoding="utf-8")
        log.info("sandbox_created", id=experiment_id, files=len(files))
        return sandbox_dir

    def get_snapshot(self, experiment_id: str, filepath: str) -> str | None:
        return self._snapshots.get(experiment_id, {}).get(filepath)

    def rollback(self, experiment_id: str) -> list[str]:
        snapshots = self._snapshots.get(experiment_id)
        if not snapshots:
            sf = self.sandbox_root / experiment_id / "_snapshots.json"
            if sf.exists():
                snapshots = json.loads(sf.read_text(encoding="utf-8"))
            else:
                return []
        restored = []
        for filepath, content in snapshots.items():
            try:
                (self.repo_root / filepath).write_text(content, encoding="utf-8")
                restored.append(filepath)
            except Exception as e:
                log.error("rollback_failed", file=filepath, err=str(e)[:80])
        log.info("sandbox_rollback", id=experiment_id, restored=len(restored))
        return restored

    def get_diff(self, experiment_id: str) -> dict[str, str]:
        snapshots = self._snapshots.get(experiment_id, {})
        diffs: dict[str, str] = {}
        for filepath, original in snapshots.items():
            cur = self.repo_root / filepath
            current = cur.read_text(encoding="utf-8") if cur.exists() else ""
            if current != original:
                diff = difflib.unified_diff(
                    original.splitlines(keepends=True),
                    current.splitlines(keepends=True),
                    fromfile=f"a/{filepath}", tofile=f"b/{filepath}")
                diffs[filepath] = "".join(diff)
        return diffs

    def cleanup(self, experiment_id: str) -> None:
        d = self.sandbox_root / experiment_id
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        self._snapshots.pop(experiment_id, None)

    def list_active(self) -> list[str]:
        if not self.sandbox_root.exists():
            return []
        return [d.name for d in self.sandbox_root.iterdir()
                if d.is_dir() and not d.name.startswith(".")]


# ═══════════════════════════════════════════════════════════════
# REGRESSION GUARD
# ═══════════════════════════════════════════════════════════════

_DOCKER_SOCKET = "/var/run/docker.sock"


def _si_enabled() -> bool:
    """
    Self-improvement (SI) is disabled by default.

    Requires explicit opt-in: JARVIS_ENABLE_SI=1
    Must NOT be set in production unless the operator has:
      1. Mounted /var/run/docker.sock into the container (required by RegressionGuard)
      2. Accepted the privilege escalation risk that entails
      3. Reviewed the safety zone configuration

    Risk: /var/run/docker.sock access grants container-escape-level privileges.
    Default: DISABLED (fail-closed).
    """
    return os.environ.get("JARVIS_ENABLE_SI", "0").strip().lower() in ("1", "true", "yes")


class RegressionGuard:
    def __init__(self, repo_root: Path, docker_image: str = "jarvismax-jarvis:latest",
                 network: str = "jarvismax_jarvis_net"):
        self.repo_root = repo_root
        self.docker_image = docker_image
        self.network = network
        # Log warning at construction time if SI is not enabled or socket missing.
        # The hard raise happens in run_tests() — evaluate() is pure logic and safe to call always.
        if not _si_enabled():
            log.warning("regression_guard.disabled",
                        reason="JARVIS_ENABLE_SI not set",
                        action="run_tests() will raise if called without enabling SI")
        elif not os.path.exists(_DOCKER_SOCKET):
            log.warning("regression_guard.no_socket",
                        socket=_DOCKER_SOCKET,
                        action="run_tests() will raise if called without Docker socket")
        else:
            log.info("regression_guard.ready",
                     docker_image=docker_image,
                     socket=_DOCKER_SOCKET,
                     warning="Docker socket is mounted — container-level privilege is active")

    def run_tests(self, test_path: str, timeout: int = 120) -> dict:
        # ── SI safety gate — enforced at execution time, not construction ──
        if not _si_enabled():
            raise RuntimeError(
                "RegressionGuard.run_tests() is disabled. "
                "Set JARVIS_ENABLE_SI=1 to enable self-improvement. "
                "WARNING: this requires /var/run/docker.sock mounted and grants Docker privilege."
            )
        if not os.path.exists(_DOCKER_SOCKET):
            raise RuntimeError(
                f"RegressionGuard.run_tests() requires Docker socket at {_DOCKER_SOCKET}. "
                "Mount the Docker socket or disable SI."
            )
        cmd = ["docker", "run", "--rm", "-v", f"{self.repo_root}:/app",
               "-w", "/app", "--network", self.network, "-e", "PYTHONPATH=/app",
               self.docker_image, "python", "-m", "pytest", test_path, "--tb=no", "-q"]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=timeout, cwd=str(self.repo_root))
            output = r.stdout + r.stderr
        except subprocess.TimeoutExpired:
            return {"passed": 0, "failed": 0, "errors": 1, "output": "TIMEOUT", "success": False}
        except Exception as e:
            return {"passed": 0, "failed": 0, "errors": 1, "output": str(e)[:500], "success": False}
        return self._parse_pytest_output(output)

    def evaluate(self, spec: ExperimentSpec, baseline: dict, candidate: dict) -> EvaluationScore:
        b_total = baseline.get("passed", 0) + baseline.get("failed", 0)
        c_total = candidate.get("passed", 0) + candidate.get("failed", 0)
        c_pass_rate = candidate["passed"] / c_total if c_total > 0 else 0
        no_reg = candidate.get("failed", 0) <= baseline.get("failed", 0)
        safety = 0.0 if check_safety_violations(spec.files_allowed) else 1.0
        return EvaluationScore(
            test_pass_rate=c_pass_rate, regression_pass_rate=c_pass_rate,
            no_regression=no_reg,
            failure_rate_delta=candidate.get("failed", 0) - baseline.get("failed", 0),
            safety_score=safety, files_within_budget=len(spec.files_allowed) <= spec.max_files)

    @staticmethod
    def _parse_pytest_output(output: str) -> dict:
        passed = failed = errors = 0
        m = re.search(r'(\d+)\s+passed', output)
        if m: passed = int(m.group(1))
        m = re.search(r'(\d+)\s+failed', output)
        if m: failed = int(m.group(1))
        m = re.search(r'(\d+)\s+error', output)
        if m: errors = int(m.group(1))
        return {"passed": passed, "failed": failed, "errors": errors,
                "output": output[-2000:], "success": failed == 0 and errors == 0 and passed > 0}


# ═══════════════════════════════════════════════════════════════
# LEARNING MEMORY
# ═══════════════════════════════════════════════════════════════

@dataclass
class Lesson:
    id: str = field(default_factory=lambda: f"lesson-{uuid.uuid4().hex[:10]}")
    experiment_id: str = ""
    subsystem: str = ""
    problem: str = ""
    patch_summary: str = ""
    outcome: str = ""
    what_worked: str = ""
    what_failed: str = ""
    what_to_try_next: str = ""
    confidence: float = 0.5
    score_delta: float = 0.0
    files_changed: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


class LearningMemory:
    def __init__(self, persist_path: Path | None = None):
        self._path = persist_path or Path("workspace/.improvement_lessons.json")
        self._lessons: list[Lesson] = []
        self._load()

    def record(self, lesson: Lesson) -> None:
        self._lessons.append(lesson)
        self._save()

    def get_lessons(self, subsystem: str = "", outcome: str = "", limit: int = 20) -> list[Lesson]:
        r = self._lessons
        if subsystem: r = [l for l in r if l.subsystem == subsystem]
        if outcome: r = [l for l in r if l.outcome == outcome]
        return sorted(r, key=lambda l: l.timestamp, reverse=True)[:limit]

    def get_failures(self, subsystem: str = "", limit: int = 10) -> list[Lesson]:
        return self.get_lessons(subsystem=subsystem, outcome="rejected", limit=limit)

    def get_successes(self, subsystem: str = "", limit: int = 10) -> list[Lesson]:
        return self.get_lessons(subsystem=subsystem, outcome="promoted", limit=limit)

    def summary_for_prompt(self, subsystem: str = "") -> str:
        failures = self.get_failures(subsystem=subsystem, limit=5)
        successes = self.get_successes(subsystem=subsystem, limit=5)
        lines = [f"## Improvement Lessons ({len(self._lessons)} total)"]
        if successes:
            lines.append("### What Worked")
            for l in successes:
                lines.append(f"- {l.what_worked} (conf={l.confidence:.1f})")
        if failures:
            lines.append("### What Failed")
            for l in failures:
                lines.append(f"- {l.what_failed} (conf={l.confidence:.1f})")
                if l.what_to_try_next:
                    lines.append(f"  → Try: {l.what_to_try_next}")
        return "\n".join(lines)

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(
                [asdict(l) for l in self._lessons[-200:]], indent=2), encoding="utf-8")
        except Exception as e:
            log.warning("learning_memory_save_failed", err=str(e)[:80])

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._lessons = [Lesson(**d) for d in json.loads(
                    self._path.read_text(encoding="utf-8"))]
            except Exception:
                _silent_log.debug("suppressed_exception", src='improvement_loop.py')


# ═══════════════════════════════════════════════════════════════
# EXPERIMENT REPORT
# ═══════════════════════════════════════════════════════════════

@dataclass
class ExperimentReport:
    experiment_id: str
    spec: dict
    baseline: dict
    candidate: dict
    evaluation: dict
    diffs: dict[str, str]
    decision: str
    reason: str
    rollback_instructions: str
    lesson: dict
    timestamp: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, default=str)

    def to_markdown(self) -> str:
        s = self.spec
        e = self.evaluation
        return (
            f"# Experiment Report: {self.experiment_id}\n"
            f"**Decision:** {self.decision}\n**Reason:** {self.reason}\n\n"
            f"## Hypothesis\n{s.get('hypothesis','N/A')}\n\n"
            f"## Target\n- Subsystem: {s.get('target_subsystem','N/A')}\n"
            f"- Files: {', '.join(s.get('files_allowed',[]))}\n"
            f"- Risk: {s.get('risk_class','N/A')}\n\n"
            f"## Results\n- Baseline: {self.baseline.get('passed',0)} passed, {self.baseline.get('failed',0)} failed\n"
            f"- Candidate: {self.candidate.get('passed',0)} passed, {self.candidate.get('failed',0)} failed\n"
            f"- Composite: {e.get('composite',0):.4f}\n"
            f"- Gate: {'PASSED' if e.get('passed') else 'FAILED'}\n\n"
            f"## Rollback\n```\n{self.rollback_instructions}\n```\n"
        )


# ═══════════════════════════════════════════════════════════════
# IMPROVEMENT ENGINE
# ═══════════════════════════════════════════════════════════════

class ImprovementLoop:
    def __init__(self, repo_root: Path, docker_image: str = "jarvismax-jarvis:latest",
                 network: str = "jarvismax_jarvis_net"):
        self.repo_root = Path(repo_root)
        self.sandbox = SandboxManager(self.repo_root)
        # RegressionGuard raises RuntimeError if JARVIS_ENABLE_SI!=1 or Docker socket absent.
        # Let the exception propagate — callers must handle it or not instantiate ImprovementLoop.
        self.guard = RegressionGuard(self.repo_root, docker_image, network)
        self.memory = LearningMemory(self.repo_root / "workspace" / ".improvement_lessons.json")
        self._reports_dir = self.repo_root / "workspace" / "improvement_reports"
        self._reports_dir.mkdir(parents=True, exist_ok=True)

    def run_experiment(self, spec: ExperimentSpec,
                       apply_patch: callable | None = None) -> ExperimentReport:
        log.info("experiment_start", id=spec.id, hypothesis=spec.hypothesis[:80])

        errors = spec.validate()
        if errors:
            return self._blocked(spec, f"Validation: {'; '.join(errors)}")

        try:
            baseline = self.guard.run_tests(spec.regression_tests)
        except RuntimeError as e:
            return self._error(spec, {}, f"Baseline test execution failed: {e}")
        if not baseline.get("passed") and not baseline.get("failed"):
            return self._blocked(spec, "Baseline returned no results")

        self.sandbox.create(spec.id, spec.files_allowed)

        if apply_patch:
            try:
                patch_desc = apply_patch(self.repo_root, spec)
            except Exception as e:
                self.sandbox.rollback(spec.id)
                return self._error(spec, baseline, f"Patch failed: {e}")
        else:
            patch_desc = "manual"

        candidate = self.guard.run_tests(spec.regression_tests)
        evaluation = self.guard.evaluate(spec, baseline, candidate)
        diffs = self.sandbox.get_diff(spec.id)

        if evaluation.passed and evaluation.composite > spec.promotion_threshold:
            decision, reason = "promoted", f"Score {evaluation.composite:.4f} passed all gates"
            self.sandbox.cleanup(spec.id)
        else:
            decision = "rejected"
            reasons = []
            if not evaluation.no_regression: reasons.append("regression")
            if evaluation.safety_score < 0.9: reasons.append("safety violation")
            if not evaluation.files_within_budget: reasons.append("file budget exceeded")
            if evaluation.test_pass_rate < 0.8: reasons.append(f"test_rate={evaluation.test_pass_rate:.2f}")
            if evaluation.regression_pass_rate < 0.95: reasons.append(f"reg_rate={evaluation.regression_pass_rate:.2f}")
            if evaluation.composite <= spec.promotion_threshold: reasons.append(f"score={evaluation.composite:.4f}")
            reason = "; ".join(reasons) or "gate not passed"
            self.sandbox.rollback(spec.id)

        lesson = Lesson(experiment_id=spec.id, subsystem=spec.target_subsystem,
                        problem=spec.weakness_detected, patch_summary=patch_desc,
                        outcome=decision,
                        what_worked=patch_desc if decision == "promoted" else "",
                        what_failed=reason if decision != "promoted" else "",
                        confidence=min(evaluation.composite + 0.1, 1.0) if decision == "promoted" else 0.3,
                        score_delta=evaluation.composite - spec.promotion_threshold,
                        files_changed=spec.files_allowed)
        self.memory.record(lesson)

        report = ExperimentReport(
            experiment_id=spec.id, spec=asdict(spec), baseline=baseline,
            candidate=candidate, evaluation={"composite": evaluation.composite,
            "passed": evaluation.passed, "test_pass_rate": evaluation.test_pass_rate,
            "regression_pass_rate": evaluation.regression_pass_rate,
            "no_regression": evaluation.no_regression, "safety_score": evaluation.safety_score,
            "failure_rate_delta": evaluation.failure_rate_delta},
            diffs=diffs, decision=decision, reason=reason,
            rollback_instructions=f"cd {self.repo_root} && git checkout -- {' '.join(spec.files_allowed)}",
            lesson=asdict(lesson))
        self._save_report(report)
        return report

    def _blocked(self, spec, reason):
        lesson = Lesson(experiment_id=spec.id, subsystem=spec.target_subsystem,
                        outcome="blocked", what_failed=reason, confidence=0.1)
        self.memory.record(lesson)
        return ExperimentReport(experiment_id=spec.id, spec=asdict(spec),
            baseline={}, candidate={}, evaluation={"composite": 0, "passed": False},
            diffs={}, decision="blocked", reason=reason,
            rollback_instructions="No changes.", lesson=asdict(lesson))

    def _error(self, spec, baseline, reason):
        lesson = Lesson(experiment_id=spec.id, subsystem=spec.target_subsystem,
                        outcome="error", what_failed=reason, confidence=0.1)
        self.memory.record(lesson)
        return ExperimentReport(experiment_id=spec.id, spec=asdict(spec),
            baseline=baseline, candidate={}, evaluation={"composite": 0, "passed": False},
            diffs={}, decision="error", reason=reason,
            rollback_instructions="Rolled back.", lesson=asdict(lesson))

    def _save_report(self, report):
        try:
            (self._reports_dir / f"{report.experiment_id}.json").write_text(
                report.to_json(), encoding="utf-8")
            (self._reports_dir / f"{report.experiment_id}.md").write_text(
                report.to_markdown(), encoding="utf-8")
        except Exception as e:
            log.warning("report_save_failed", err=str(e)[:80])

    def get_learning_summary(self, subsystem: str = "") -> str:
        return self.memory.summary_for_prompt(subsystem)
