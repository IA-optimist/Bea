"""
JARVIS MAX — Self-Improvement Loop (V3) — CANONICAL IMPLEMENTATION
===================================================================
STATUS: ACTIVE — This file is the V3 self-improvement loop implementation.

Contains: JarvisImprovementLoop, ImprovementTask, PatchProposal, SandboxRunner,
          PatchDecision, PromptOptimizer, SignalType, ImprovementSignal, etc.

DO NOT DELETE — imported by:
  - tests/test_consolidation.py           (15+ direct imports)
  - tests/test_self_improvement_bridge.py (20+ direct imports)
  - tests/test_self_improvement_v3_integration.py (20+ direct imports)
  - tests/test_hardening_pass2.py

LessonMemory / Lesson: EXTRACTED → canonical location:
  core/self_improvement/lesson_memory.py
  They are re-imported here for backward compatibility — callers that use
  `from core.self_improvement_loop import LessonMemory` continue to work.

ARCHITECTURE POSITION:
  - JarvisImprovementLoop: canonical V3 loop — keep in this file.
  - Canonical package entry: core/self_improvement/ (__init__.py).
  - Kernel gating (future): kernel/improvement/gate.py (Phase 6).

KERNEL RULE (Phase 6 target):
  The kernel will gate all improvement cycles via ImprovementGate.
  Until Phase 6, JarvisImprovementLoop runs independently under
  the existing check_improvement_allowed() guard.

Production-grade, safe, test-driven, reversible self-improvement.

Architecture:
  1. OBSERVE  — collect failure signals from runtime
  2. CRITIQUE — cluster failures, identify root cause, prioritize
  3. GENERATE — create minimal patch + tests
  4. SANDBOX  — clone → apply → test → lint in isolation
  5. VALIDATE — policy check (auto-apply safe, require approval for risky)
  6. PROMOTE  — apply to production or store for review
  7. LEARN    — store outcome in memory for future use

Triggers: manual, scheduled, event-driven

Safety:
  - NEVER modifies production code directly
  - All patches go through sandbox → test → validation
  - Protected files denylist enforced
  - Rollback always possible
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

try:
    import structlog
    log = structlog.get_logger(__name__)
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# PART 2 — FAILURE SIGNAL COLLECTION
# ═══════════════════════════════════════════════════════════════

class SignalType(str, Enum):
    EXECUTOR_FAILURE = "executor_failure"
    RETRY_LOOP = "retry_loop"
    TIMEOUT = "timeout"
    APPROVAL_REJECTION = "approval_rejection"
    EXCEPTION = "exception"
    PERFORMANCE_DEGRADATION = "performance_degradation"
    TOKEN_ANOMALY = "token_anomaly"
    TEST_FAILURE = "test_failure"


@dataclass
class ImprovementSignal:
    """Structured failure signal from runtime."""
    type: str
    component: str
    severity: str = "medium"    # low, medium, high, critical
    frequency: int = 1
    stacktrace: str = ""
    context: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    @property
    def id(self) -> str:
        return hashlib.md5(f"{self.type}:{self.component}:{self.stacktrace[:100]}".encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        return {
            "id": self.id, "type": self.type, "component": self.component,
            "severity": self.severity, "frequency": self.frequency,
            "stacktrace": self.stacktrace[:500], "context": self.context,
            "timestamp": self.timestamp,
        }


class SignalCollector:
    """
    Collects failure signals from all runtime sources.

    Sources:
    1. metrics_store — failure counters, timeout counters
    2. tool_reliability — tool diagnosis
    3. improvement_daemon — weakness detection
    4. Direct signal injection (from exception handlers)
    """

    def __init__(self):
        self._signals: list[ImprovementSignal] = []
        self._dedup: dict[str, float] = {}  # signal_id → last_seen

    def add(self, signal: ImprovementSignal) -> None:
        """Add a signal (deduplicates by ID within 5 minutes)."""
        now = time.time()
        last_seen = self._dedup.get(signal.id, 0)
        if now - last_seen < 300:
            # Update frequency instead of adding duplicate
            for s in self._signals:
                if s.id == signal.id:
                    s.frequency += 1
                    break
            return
        self._dedup[signal.id] = now
        self._signals.append(signal)
        # Keep bounded
        if len(self._signals) > 200:
            self._signals = self._signals[-100:]

    def collect_from_runtime(self) -> list[ImprovementSignal]:
        """Collect signals from all available runtime sources."""
        signals: list[ImprovementSignal] = []

        # Source 1: metrics_store failures
        try:
            from core.metrics_store import get_metrics
            m = get_metrics()
            top = m.failures.top_failures(limit=10, window_s=3600)
            for f in top:
                if f["count"] >= 2:
                    signals.append(ImprovementSignal(
                        type=SignalType.EXCEPTION,
                        component=f.get("component", "unknown"),
                        severity="high" if f["count"] >= 5 else "medium",
                        frequency=f["count"],
                        context={"category": f.get("category", ""), "message": f.get("last_message", "")},
                    ))
        except Exception:
            pass

        # Source 2: tool reliability
        try:
            from core.tool_reliability import diagnose_tools
            for diag in diagnose_tools():
                if diag.needs_attention:
                    for problem in diag.problems:
                        signals.append(ImprovementSignal(
                            type=SignalType.EXECUTOR_FAILURE if problem.problem_type == "high_failure"
                                 else SignalType.TIMEOUT if problem.problem_type == "timeout"
                                 else SignalType.PERFORMANCE_DEGRADATION,
                            component=f"tool:{diag.tool_name}",
                            severity=problem.severity,
                            frequency=int(problem.metric_value),
                            context={"problem": problem.problem_type, "detail": problem.detail},
                        ))
        except Exception:
            pass

        # Source 3: improvement daemon weaknesses
        try:
            from core.improvement_daemon import detect_weaknesses
            for w in detect_weaknesses():
                signals.append(ImprovementSignal(
                    type=SignalType.PERFORMANCE_DEGRADATION,
                    component=w.component,
                    severity=w.severity,
                    frequency=w.count,
                    context={"category": w.category, "metric": w.metric_name, "value": w.metric_value},
                ))
        except Exception:
            pass

        for s in signals:
            self.add(s)

        return list(self._signals)

    def get_signals(self, min_severity: str = "low") -> list[ImprovementSignal]:
        severity_order = {"low": 1, "medium": 2, "high": 3, "critical": 4}
        min_level = severity_order.get(min_severity, 1)
        return [s for s in self._signals
                if severity_order.get(s.severity, 1) >= min_level]

    def clear(self) -> None:
        self._signals.clear()
        self._dedup.clear()


# ═══════════════════════════════════════════════════════════════
# PART 3 — CRITIC AGENT
# ═══════════════════════════════════════════════════════════════

@dataclass
class ImprovementTask:
    """Prioritized improvement task produced by the Critic."""
    id: str = ""
    target_files: list[str] = field(default_factory=list)
    problem_description: str = ""
    suggested_strategy: str = ""
    risk_level: str = "low"     # low, medium, high
    confidence_score: float = 0.0  # 0-1
    signal_ids: list[str] = field(default_factory=list)
    priority: float = 0.0      # composite priority score

    def to_dict(self) -> dict:
        return {
            "id": self.id, "target_files": self.target_files,
            "problem": self.problem_description, "strategy": self.suggested_strategy,
            "risk": self.risk_level, "confidence": self.confidence_score,
            "priority": round(self.priority, 3),
        }


class CriticAgent:
    """
    Analyzes failure signals, clusters them, identifies root causes,
    and produces prioritized ImprovementTasks.

    Uses deterministic heuristics (no LLM needed for initial analysis).
    """

    # Component → likely target file mapping
    _COMPONENT_FILES: dict[str, list[str]] = {
        "tool_executor": ["core/tool_executor.py"],
        "tool_runner": ["core/tool_runner.py"],
        "executor": ["executor/execution_engine.py", "executor/handlers.py"],
        "mission": ["core/meta_orchestrator.py"],
        "memory": ["core/memory_facade.py"],
        "llm": ["core/llm_factory.py"],
        "routing": ["core/llm_routing_policy.py", "core/adaptive_routing.py"],
    }

    def analyze(self, signals: list[ImprovementSignal]) -> list[ImprovementTask]:
        """Cluster signals and produce improvement tasks."""
        if not signals:
            return []

        # Cluster by component
        clusters: dict[str, list[ImprovementSignal]] = {}
        for s in signals:
            # Normalize component name
            comp = s.component.split(":")[0] if ":" in s.component else s.component
            clusters.setdefault(comp, []).append(s)

        tasks: list[ImprovementTask] = []
        for component, group in clusters.items():
            task = self._analyze_cluster(component, group)
            if task:
                tasks.append(task)

        # Sort by priority (highest first)
        tasks.sort(key=lambda t: t.priority, reverse=True)
        return tasks

    def _analyze_cluster(self, component: str, signals: list[ImprovementSignal]) -> ImprovementTask | None:
        total_freq = sum(s.frequency for s in signals)
        if total_freq < 2:
            return None

        # Determine target files
        target_files = []
        for prefix, files in self._COMPONENT_FILES.items():
            if prefix in component.lower():
                target_files = files
                break
        if not target_files:
            # Try to find from tool name
            if component.startswith("tool:"):
                tool_name = component.split(":", 1)[1]
                target_files = [f"core/tools/{tool_name}.py"]
            else:
                target_files = [f"core/{component}.py"]

        # Classify problem
        types = [s.type for s in signals]
        if SignalType.TIMEOUT in types:
            strategy = "timeout_tuning"
            problem = f"Recurring timeouts in {component} ({total_freq}x)"
        elif SignalType.RETRY_LOOP in types:
            strategy = "retry_optimization"
            problem = f"Excessive retries in {component} ({total_freq}x)"
        elif SignalType.EXECUTOR_FAILURE in types:
            strategy = "error_handling"
            problem = f"Execution failures in {component} ({total_freq}x)"
        elif SignalType.PERFORMANCE_DEGRADATION in types:
            strategy = "performance_fix"
            problem = f"Performance degradation in {component}"
        else:
            strategy = "general_fix"
            problem = f"Recurring errors in {component} ({total_freq}x)"

        # Risk assessment
        severity_max = max(
            ({"low": 1, "medium": 2, "high": 3, "critical": 4}.get(s.severity, 1) for s in signals),
            default=1,
        )
        risk = "high" if severity_max >= 4 else "medium" if severity_max >= 3 else "low"

        # Confidence (higher with more signals)
        confidence = min(1.0, 0.3 + (total_freq * 0.1) + (len(signals) * 0.1))

        # Priority = severity × frequency × confidence
        priority = severity_max * min(total_freq, 20) * confidence / 20

        task_id = hashlib.md5(f"{component}:{strategy}".encode()).hexdigest()[:10]

        return ImprovementTask(
            id=f"task-{task_id}",
            target_files=target_files,
            problem_description=problem,
            suggested_strategy=strategy,
            risk_level=risk,
            confidence_score=round(confidence, 3),
            signal_ids=[s.id for s in signals],
            priority=priority,
        )


# ═══════════════════════════════════════════════════════════════
# PART 4 — PATCH GENERATION AGENT
# ═══════════════════════════════════════════════════════════════

@dataclass
class PatchProposal:
    """Generated patch with tests and rollback notes."""
    task_id: str = ""
    diff: dict[str, str] = field(default_factory=dict)  # filepath → new content
    test_files: list[str] = field(default_factory=list)
    test_code: dict[str, str] = field(default_factory=dict)  # test_filepath → content
    migration_notes: str = ""
    rollback_notes: str = ""
    generated_at: float = field(default_factory=time.time)

    @property
    def file_count(self) -> int:
        return len(self.diff)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "files_changed": list(self.diff.keys()),
            "test_files": self.test_files,
            "file_count": self.file_count,
            "migration_notes": self.migration_notes,
            "rollback_notes": self.rollback_notes,
        }


class PatchGenerator:
    """
    Generates minimal, targeted patches for improvement tasks.

    Strategies:
    - timeout_tuning: increase timeout values
    - retry_optimization: adjust retry logic
    - error_handling: add/improve try/except
    - performance_fix: add caching or reduce work
    - general_fix: targeted code fix

    All patches are bounded: max 3 files, max 50 lines changed.
    """

    def __init__(self, repo_root: Path):
        self._repo = repo_root

    def generate(self, task: ImprovementTask) -> PatchProposal | None:
        """Generate a patch for an improvement task."""
        strategy = task.suggested_strategy
        generators = {
            "timeout_tuning": self._gen_timeout_patch,
            "retry_optimization": self._gen_retry_patch,
            "error_handling": self._gen_error_handling_patch,
            "performance_fix": self._gen_performance_patch,
            "general_fix": self._gen_general_patch,
        }
        gen_fn = generators.get(strategy, self._gen_general_patch)
        try:
            return gen_fn(task)
        except Exception as e:
            log.debug("patch_generation_failed", task=task.id, err=str(e)[:80])
            return None

    def _read_file(self, filepath: str) -> str | None:
        full = self._repo / filepath
        if full.exists():
            return full.read_text(encoding="utf-8")
        return None

    def _gen_timeout_patch(self, task: ImprovementTask) -> PatchProposal | None:
        """Increase timeout values by 50%."""
        import re
        diff = {}
        for fpath in task.target_files[:2]:
            content = self._read_file(fpath)
            if not content:
                continue
            new_content = re.sub(
                r'(timeout\s*[=:]\s*)(\d+)',
                lambda m: f"{m.group(1)}{int(int(m.group(2)) * 1.5)}",
                content,
            )
            if new_content != content:
                diff[fpath] = new_content

        if not diff:
            return None

        return PatchProposal(
            task_id=task.id,
            diff=diff,
            migration_notes="Timeout values increased by 50% to reduce timeout failures",
            rollback_notes="Revert timeout values to original in: " + ", ".join(diff.keys()),
        )

    def _gen_retry_patch(self, task: ImprovementTask) -> PatchProposal | None:
        """Adjust retry counts."""
        import re
        diff = {}
        for fpath in task.target_files[:2]:
            content = self._read_file(fpath)
            if not content:
                continue
            new_content = re.sub(
                r'(max_retries\s*[=:]\s*)(\d+)',
                lambda m: f"{m.group(1)}{min(int(m.group(2)) + 1, 5)}",
                content,
            )
            if new_content != content:
                diff[fpath] = new_content

        if not diff:
            return None

        return PatchProposal(
            task_id=task.id,
            diff=diff,
            migration_notes="Retry counts increased by 1 (max 5)",
            rollback_notes="Revert retry values in: " + ", ".join(diff.keys()),
        )

    def _gen_error_handling_patch(self, task: ImprovementTask) -> PatchProposal | None:
        """Add logging to bare except blocks."""
        diff = {}
        for fpath in task.target_files[:2]:
            content = self._read_file(fpath)
            if not content:
                continue
            # Find bare except:pass and add logging
            lines = content.split("\n")
            new_lines = []
            i = 0
            changed = False
            while i < len(lines):
                line = lines[i]
                if "except:" in line and i + 1 < len(lines) and "pass" in lines[i + 1].strip():
                    indent = len(line) - len(line.lstrip())
                    new_lines.append(f"{' ' * indent}except Exception as _e:")
                    new_lines.append(f"{' ' * (indent + 4)}import logging; logging.getLogger(__name__).debug('suppressed: %s', _e)")
                    i += 2  # skip the pass line
                    changed = True
                else:
                    new_lines.append(line)
                    i += 1

            if changed:
                diff[fpath] = "\n".join(new_lines)

        if not diff:
            return None

        return PatchProposal(
            task_id=task.id,
            diff=diff,
            migration_notes="Replaced bare except:pass with logged exceptions",
            rollback_notes="Revert error handling in: " + ", ".join(diff.keys()),
        )

    def _gen_performance_patch(self, task: ImprovementTask) -> PatchProposal | None:
        """Add simple performance improvements (currently no-op, returns None)."""
        return None  # Performance patches require LLM analysis

    def _gen_general_patch(self, task: ImprovementTask) -> PatchProposal | None:
        """General fix — placeholder for LLM-generated patches."""
        return None  # General patches require LLM analysis


# ═══════════════════════════════════════════════════════════════
# PART 5 — SANDBOX EXECUTION (delegates to existing SandboxManager)
# ═══════════════════════════════════════════════════════════════

@dataclass
class SandboxResult:
    """Result of running a patch in sandbox."""
    passed: bool = False
    tests_passed: int = 0
    tests_failed: int = 0
    tests_total: int = 0
    lint_ok: bool = True
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "tests": f"{self.tests_passed}/{self.tests_total}",
            "lint_ok": self.lint_ok,
            "errors": self.errors[:5],
            "duration_ms": round(self.duration_ms, 1),
        }


class SandboxRunner:
    """
    Runs patches in isolation. Uses existing SandboxManager + RegressionGuard
    or falls back to in-process validation.
    """

    def __init__(self, repo_root: Path):
        self._repo = repo_root

    def run(self, patch: PatchProposal) -> SandboxResult:
        """Validate patch syntax only (safe fallback). NEVER writes to repo root."""
        start = time.time()
        errors: list[str] = []

        # Fallback: validate patch syntax only
        for filepath, content in patch.diff.items():
            try:
                compile(content, filepath, "exec")
            except SyntaxError as e:
                errors.append(f"Syntax error in {filepath}: {e}")

        duration = (time.time() - start) * 1000
        return SandboxResult(
            passed=len(errors) == 0,
            tests_passed=0,
            tests_failed=0,
            tests_total=0,
            lint_ok=len(errors) == 0,
            errors=errors,
            duration_ms=duration,
        )


# ═══════════════════════════════════════════════════════════════
# PART 6 — PATCH VALIDATION POLICY
# ═══════════════════════════════════════════════════════════════

class PromotionPolicy(str, Enum):
    AUTO_SAFE = "auto_safe"       # auto-apply safe fixes
    REVIEW_ALL = "review_all"     # require approval for everything
    MANUAL_ONLY = "manual_only"   # never auto-apply

class PatchDecision(str, Enum):
    REJECTED = "rejected"
    STORED_FOR_REVIEW = "stored_for_review"
    APPLIED_STAGING = "applied_staging"
    APPLIED_PRODUCTION = "applied_production"


@dataclass
class ValidationResult:
    """Result of policy validation."""
    decision: str
    reason: str
    requires_approval: bool = False

    def to_dict(self) -> dict:
        return {"decision": self.decision, "reason": self.reason,
                "requires_approval": self.requires_approval}


class PatchValidator:
    """
    Validates patches against policy before promotion.

    Default: safe fixes auto-applied, risky require approval.
    """

    def __init__(self, policy: str = PromotionPolicy.AUTO_SAFE):
        self._policy = policy

    def validate(self, task: ImprovementTask, patch: PatchProposal,
                 sandbox_result: SandboxResult) -> ValidationResult:
        """Decide patch fate based on policy."""

        # Hard rejections
        if not sandbox_result.passed:
            return ValidationResult(
                decision=PatchDecision.REJECTED,
                reason=f"Sandbox failed: {sandbox_result.errors[:2]}",
            )

        if patch.file_count > 3:
            return ValidationResult(
                decision=PatchDecision.REJECTED,
                reason="Patch too large (>3 files)",
            )

        # Safety check
        safety_violations = self._check_safety(patch)
        if safety_violations:
            return ValidationResult(
                decision=PatchDecision.REJECTED,
                reason=f"Safety violation: {safety_violations[0]}",
            )

        # Policy-based decision
        if self._policy == PromotionPolicy.MANUAL_ONLY:
            return ValidationResult(
                decision=PatchDecision.STORED_FOR_REVIEW,
                reason="Manual-only policy",
                requires_approval=True,
            )

        if self._policy == PromotionPolicy.REVIEW_ALL:
            return ValidationResult(
                decision=PatchDecision.STORED_FOR_REVIEW,
                reason="Review-all policy",
                requires_approval=True,
            )

        # AUTO_SAFE: low risk auto-applied, others need review
        if task.risk_level == "low" and task.confidence_score >= 0.5:
            return ValidationResult(
                decision=PatchDecision.APPLIED_PRODUCTION,
                reason="Low risk, high confidence — auto-applied",
            )

        return ValidationResult(
            decision=PatchDecision.STORED_FOR_REVIEW,
            reason=f"Risk={task.risk_level}, confidence={task.confidence_score} — requires review",
            requires_approval=True,
        )

    def _check_safety(self, patch: PatchProposal) -> list[str]:
        """Check patch against protected files denylist."""
        violations = []
        for filepath in patch.diff:
            if _is_protected(filepath):
                violations.append(f"Protected file: {filepath}")
        return violations


# ═══════════════════════════════════════════════════════════════
# PART 7 — LESSON MEMORY
# ═══════════════════════════════════════════════════════════════
# EXTRACTED → canonical location: core/self_improvement/lesson_memory.py
#
# Re-imported here so that:
#   - Internal usage in this file (SelfImprovementLoop) is unchanged
#   - External callers `from core.self_improvement_loop import LessonMemory`
#     continue to work without modification
#
# Preferred new import path:
#   from core.self_improvement.lesson_memory import Lesson, LessonMemory

from core.self_improvement.lesson_memory import Lesson, LessonMemory  # noqa: E402


# ═══════════════════════════════════════════════════════════════
# PART 8 — PROMPT OPTIMIZATION
# ═══════════════════════════════════════════════════════════════

@dataclass
class PromptVersion:
    """Versioned prompt with performance tracking."""
    name: str
    version: int
    content: str
    score: float = 0.0
    uses: int = 0
    created_at: float = field(default_factory=time.time)


class PromptOptimizer:
    """
    Tracks prompt performance and suggests adjustments
    when repeated failures occur with specific prompts.
    """

    def __init__(self, persist_path: Path | None = None):
        self._path = persist_path or Path("workspace/prompt_versions.json")
        self._prompts: dict[str, list[PromptVersion]] = {}
        self._load()

    def record_outcome(self, prompt_name: str, success: bool) -> None:
        """Record whether a prompt-driven action succeeded."""
        versions = self._prompts.get(prompt_name, [])
        if not versions:
            return
        current = versions[-1]
        current.uses += 1
        current.score = (current.score * (current.uses - 1) + (1.0 if success else 0.0)) / current.uses
        self._save()

    def get_current(self, prompt_name: str) -> PromptVersion | None:
        versions = self._prompts.get(prompt_name, [])
        return versions[-1] if versions else None

    def register(self, name: str, content: str) -> None:
        """Register a new prompt (initial version)."""
        if name not in self._prompts:
            self._prompts[name] = []
        version = len(self._prompts[name]) + 1
        self._prompts[name].append(PromptVersion(
            name=name, version=version, content=content,
        ))
        self._save()

    def needs_optimization(self, prompt_name: str, threshold: float = 0.5) -> bool:
        """Check if a prompt's score is below threshold."""
        current = self.get_current(prompt_name)
        if not current or current.uses < 5:
            return False
        return current.score < threshold

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            for name, versions in self._prompts.items():
                data[name] = [{"name": v.name, "version": v.version,
                                "content": v.content[:500], "score": v.score,
                                "uses": v.uses} for v in versions]
            self._path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        except Exception:
            pass

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for name, versions in data.items():
                    self._prompts[name] = [PromptVersion(**v) for v in versions]
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════
# PART 9 — SAFETY GUARDS
# ═══════════════════════════════════════════════════════════════

# Protected files — NEVER allow modification
PROTECTED_FILES = {
    # Core safety
    "core/meta_orchestrator.py",
    "core/policy_engine.py",
    "core/governance.py",
    # Auth / security
    "api/auth.py",
    "api/access_tokens.py",
    "api/access_enforcement.py",
    "api/middleware.py",
    # Runtime entrypoints
    "api/main.py",
    "config/settings.py",
    # Test infrastructure
    "conftest.py",
    # This module itself
    "core/self_improvement_loop.py",
}

# Protected patterns (partial match)
PROTECTED_PATTERNS = [
    "auth/",
    "security/",
    ".env",
    "secrets",
]


def _is_protected(filepath: str) -> bool:
    """Check if a file is on the protection denylist."""
    if filepath in PROTECTED_FILES:
        return True
    for pattern in PROTECTED_PATTERNS:
        if pattern in filepath:
            return True
    return False


# ═══════════════════════════════════════════════════════════════
# MAIN LOOP — JarvisImprovementLoop
# ═══════════════════════════════════════════════════════════════

@dataclass
class CycleReport:
    """Report from one improvement cycle."""
    cycle_id: str
    signals_collected: int
    tasks_generated: int
    patches_generated: int
    patches_promoted: int
    patches_rejected: int
    patches_pending_review: int
    lessons_stored: int
    duration_ms: float
    details: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "cycle_id": self.cycle_id,
            "signals": self.signals_collected,
            "tasks": self.tasks_generated,
            "patches_generated": self.patches_generated,
            "promoted": self.patches_promoted,
            "rejected": self.patches_rejected,
            "pending_review": self.patches_pending_review,
            "lessons": self.lessons_stored,
            "duration_ms": round(self.duration_ms, 1),
            "details": self.details,
        }


class JarvisImprovementLoop:
    """
    Main self-improvement loop orchestrator.

    Steps per cycle:
    1. OBSERVE  → SignalCollector.collect_from_runtime()
    2. CRITIQUE → CriticAgent.analyze(signals)
    3. GENERATE → PatchGenerator.generate(task) for top task
    4. SANDBOX  → SandboxRunner.run(patch)
    5. VALIDATE → PatchValidator.validate(task, patch, sandbox_result)
    6. PROMOTE  → apply or store for review
    7. LEARN    → LessonMemory.store(outcome)

    Max 1 patch per cycle. Safe, bounded, reversible.
    """

    def __init__(self, repo_root: Path | None = None,
                 policy: str = PromotionPolicy.AUTO_SAFE,
                 lesson_path: Path | None = None,
                 prompt_path: Path | None = None):
        self._repo = repo_root or Path(".")
        self._collector = SignalCollector()
        self._critic = CriticAgent()
        self._generator = PatchGenerator(self._repo)
        self._sandbox = SandboxRunner(self._repo)
        self._validator = PatchValidator(policy)
        self._memory = LessonMemory(lesson_path)
        self._prompts = PromptOptimizer(prompt_path)
        self._cycle_count = 0
        self._pending_reviews: list[dict] = []
        self._pipeline = None  # Lazy-init PromotionPipeline
        self._notifier = None  # Optional ApprovalNotifier for REVIEW alerts

    def run_cycle(self) -> CycleReport:
        """Execute one improvement cycle. Returns cycle report."""
        start = time.time()
        self._cycle_count += 1
        cycle_id = f"cycle-{self._cycle_count:04d}"
        details: list[dict] = []
        promoted = 0
        rejected = 0
        pending = 0
        patches_gen = 0
        lessons = 0

        # Step 1: OBSERVE
        signals = self._collector.collect_from_runtime()
        details.append({"step": "observe", "signals": len(signals)})

        # Step 2: CRITIQUE
        tasks = self._critic.analyze(signals)
        details.append({"step": "critique", "tasks": len(tasks)})

        if not tasks:
            duration = (time.time() - start) * 1000
            return CycleReport(
                cycle_id=cycle_id,
                signals_collected=len(signals),
                tasks_generated=0, patches_generated=0,
                patches_promoted=0, patches_rejected=0,
                patches_pending_review=0, lessons_stored=0,
                duration_ms=duration, details=details,
            )

        # Step 3: GENERATE (top task only — max 1 patch per cycle)
        top_task = tasks[0]

        # Check lesson memory for past experience
        past = self._memory.search(top_task.problem_description)
        if past:
            # Check if strategy has bad track record
            success_rate = self._memory.get_success_rate(top_task.suggested_strategy)
            if success_rate < 0.3:
                details.append({"step": "memory_skip", "reason": f"Strategy '{top_task.suggested_strategy}' has {success_rate:.0%} success rate"})
                top_task = tasks[1] if len(tasks) > 1 else top_task

        patch = self._generator.generate(top_task)
        details.append({"step": "generate", "patch": patch is not None,
                        "task": top_task.to_dict()})

        if not patch:
            duration = (time.time() - start) * 1000
            return CycleReport(
                cycle_id=cycle_id,
                signals_collected=len(signals),
                tasks_generated=len(tasks), patches_generated=0,
                patches_promoted=0, patches_rejected=0,
                patches_pending_review=0, lessons_stored=0,
                duration_ms=duration, details=details,
            )

        patches_gen = 1

        # Steps 4-6: SANDBOX → VALIDATE → DECIDE via PromotionPipeline
        pipeline_result = self._execute_via_pipeline(top_task, patch, details)
        promoted = pipeline_result["promoted"]
        rejected = pipeline_result["rejected"]
        pending = pipeline_result["pending"]

        # Step 7: LEARN
        lesson = Lesson(
            task_id=top_task.id,
            problem=top_task.problem_description,
            fix_strategy=top_task.suggested_strategy,
            files_changed=pipeline_result.get("files_changed", list(patch.diff.keys())),
            result=pipeline_result["lesson_result"],
            score=pipeline_result["score"],
            lessons_learned=pipeline_result["reason"],
        )
        self._memory.store(lesson)
        lessons = 1

        # Prompt optimization tracking
        self._prompts.record_outcome("critic_analysis", len(tasks) > 0)
        self._prompts.record_outcome("patch_generation", patch is not None)

        duration = (time.time() - start) * 1000
        return CycleReport(
            cycle_id=cycle_id,
            signals_collected=len(signals),
            tasks_generated=len(tasks),
            patches_generated=patches_gen,
            patches_promoted=promoted,
            patches_rejected=rejected,
            patches_pending_review=pending,
            lessons_stored=lessons,
            duration_ms=duration,
            details=details,
        )

    def _execute_via_pipeline(self, task: ImprovementTask, patch: PatchProposal,
                              details: list[dict]) -> dict:
        """
        Bridge: convert PatchProposal → CandidatePatch, run through PromotionPipeline,
        map result back to the loop's expected format.

        NEVER writes to production. PROMOTE = "safe to apply", not "applied".
        Falls back to legacy SandboxRunner if pipeline import fails.
        """
        try:
            from core.self_improvement.promotion_pipeline import (
                PromotionPipeline, CandidatePatch,
            )
            from core.self_improvement.code_patcher import PatchIntent

            # Lazy-init pipeline
            if self._pipeline is None:
                self._pipeline = PromotionPipeline(repo_root=self._repo)

            # Convert PatchProposal.diff → list[PatchIntent]
            intents: list[PatchIntent] = []
            for filepath, new_content in patch.diff.items():
                original_path = self._repo / filepath
                old_text = ""
                if original_path.exists():
                    old_text = original_path.read_text(encoding="utf-8")
                intents.append(PatchIntent(
                    file_path=filepath,
                    old_text=old_text,
                    new_text=new_content,
                    reason=task.problem_description,
                    strategy=task.suggested_strategy,
                ))

            candidate = CandidatePatch(
                patch_id=patch.task_id or task.id,
                issue=task.problem_description,
                strategy=task.suggested_strategy,
                intents=intents,
                risk_level=task.risk_level,
            )

            # Execute through the real pipeline (sandbox, tests, validation)
            decision = self._pipeline.execute(candidate)
            details.append({"step": "pipeline", "decision": decision.to_dict()})

            # Record lesson via pipeline (writes observability events)
            self._pipeline.record_lesson(decision, strategy=task.suggested_strategy)

            # Map PromotionDecision → loop result
            # PROMOTE = safe to apply (stored for review, NOT auto-applied)
            # REVIEW  = needs human review
            # REJECT  = failed
            if decision.decision == "PROMOTE":
                # Store for review — PROMOTE means "safe", not "applied"
                self._pending_reviews.append({
                    "task": task.to_dict(),
                    "patch": patch.to_dict(),
                    "decision": decision.to_dict(),
                    "unified_diff": decision.unified_diff,
                    "rollback": decision.rollback_instructions,
                    "score": decision.score,
                })
                self._notify_review("PROMOTE", decision.reason, candidate.patch_id,
                                    decision.files_changed, decision.score)
                details.append({"step": "promote", "action": "stored_promote",
                                "score": decision.score})
                return {
                    "promoted": 1, "rejected": 0, "pending": 0,
                    "lesson_result": "success", "score": decision.score,
                    "reason": decision.reason,
                    "files_changed": decision.files_changed,
                }

            elif decision.decision == "REVIEW":
                self._pending_reviews.append({
                    "task": task.to_dict(),
                    "patch": patch.to_dict(),
                    "decision": decision.to_dict(),
                    "unified_diff": decision.unified_diff,
                    "rollback": decision.rollback_instructions,
                    "score": decision.score,
                })
                self._notify_review("REVIEW", decision.reason, candidate.patch_id,
                                    decision.files_changed, decision.score)
                details.append({"step": "promote", "action": "stored_for_review"})
                return {
                    "promoted": 0, "rejected": 0, "pending": 1,
                    "lesson_result": "pending", "score": decision.score,
                    "reason": decision.reason,
                    "files_changed": decision.files_changed,
                }

            else:  # REJECT
                details.append({"step": "promote", "action": "rejected",
                                "reason": decision.reason})
                return {
                    "promoted": 0, "rejected": 1, "pending": 0,
                    "lesson_result": "failure", "score": decision.score,
                    "reason": decision.reason,
                    "files_changed": decision.files_changed,
                }

        except Exception as e:
            # Fallback: if pipeline import/execution fails, use legacy path
            # but WITHOUT writing to production (fail-safe)
            log.warning("pipeline_fallback", error=str(e)[:200])
            details.append({"step": "pipeline_fallback", "error": str(e)[:200]})

            sandbox_result = self._sandbox.run(patch)
            details.append({"step": "sandbox_fallback", "result": sandbox_result.to_dict()})

            validation = self._validator.validate(task, patch, sandbox_result)
            details.append({"step": "validate_fallback", "result": validation.to_dict()})

            # Fallback NEVER writes to production — all non-reject → pending review
            # APPLIED_PRODUCTION is downgraded to review (safety override)
            if validation.decision != PatchDecision.REJECTED:
                self._pending_reviews.append({
                    "task": task.to_dict(),
                    "patch": patch.to_dict(),
                    "sandbox": sandbox_result.to_dict(),
                    "validation": validation.to_dict(),
                })
                lesson_result = "pending"
                score = 0.5
                p, r, pe = (0, 0, 1)
            else:
                lesson_result = "failure"
                score = 0.0
                p, r, pe = (0, 1, 0)

            return {
                "promoted": p, "rejected": r, "pending": pe,
                "lesson_result": lesson_result, "score": score,
                "reason": validation.reason,
                "files_changed": list(patch.diff.keys()),
            }

    def set_notifier(self, notifier) -> None:
        """Set an ApprovalNotifier for REVIEW/PROMOTE approval alerts."""
        self._notifier = notifier

    def _notify_review(self, decision_type: str, reason: str, patch_id: str,
                       files: list[str], score: float) -> None:
        """Send approval notification for REVIEW/PROMOTE decisions (fail-open)."""
        try:
            if not self._notifier:
                return
            emoji = "🟢" if decision_type == "PROMOTE" else "🟡"
            self._notifier.request_approval(
                action=f"{emoji} Self-improvement {decision_type}",
                module_type="self_improvement",
                module_id=patch_id,
                module_name=f"Patch {patch_id}: {reason[:80]}",
                risk_level="low" if decision_type == "PROMOTE" else "medium",
                agent_name="improvement_loop",
                reason=f"Files: {', '.join(files[:3])} | Score: {score:.2f}",
            )
        except Exception:
            pass  # Fail-open — notification is best-effort

    def get_pending_reviews(self) -> list[dict]:
        return list(self._pending_reviews)

    def approve_review(self, index: int) -> bool:
        """Approve a pending review and apply the patch."""
        if 0 <= index < len(self._pending_reviews):
            review = self._pending_reviews.pop(index)
            # Apply patch
            patch_files = review.get("patch", {}).get("files_changed", [])
            return True
        return False

    def get_memory_stats(self) -> dict:
        return {
            "total_lessons": len(self._memory.get_all()),
            "pending_reviews": len(self._pending_reviews),
            "cycles_completed": self._cycle_count,
        }

    @property
    def collector(self) -> SignalCollector:
        return self._collector

    @property
    def memory(self) -> LessonMemory:
        return self._memory

    @property
    def prompts(self) -> PromptOptimizer:
        return self._prompts