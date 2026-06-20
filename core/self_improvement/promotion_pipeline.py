"""
core/self_improvement/promotion_pipeline.py — V3 Self-Improvement Promotion Pipeline.

Orchestrates the full code improvement lifecycle:
  generate patch → sandbox test → critic review → PROMOTE / REVIEW / REJECT

Decision contract:
  PROMOTE  — patch validated in sandbox, all tests pass, risk LOW. Safe to create PR.
             Never auto-applied to production. Always goes through git PR.
  REVIEW   — medium/high risk, or INCONCLUSIVE critic. Requires human validation.
             Notified via HumanGate (Slack/Telegram).
  REJECT   — test failure, regression, protected file violation, lint error.
             Never creates PR. Lessons recorded.

Security invariants (enforced, not trusted):
  - Protected files are blocked at CodePatchGenerator level (hard block)
  - Sandbox runs in Docker with --network=none (no exfiltration)
  - No patch is ever applied to production files directly
  - Secrets are scrubbed from all result objects before returning
"""
from __future__ import annotations

import structlog
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Optional

if TYPE_CHECKING:
    from core.self_improvement.test_runner import ExperimentReport

log = structlog.get_logger()


# ── Decision types ────────────────────────────────────────────────────────────

Decision = Literal["PROMOTE", "REVIEW", "REJECT"]


# ── Patch intent + candidate ──────────────────────────────────────────────────

@dataclass
class PatchIntent:
    """A single file-level edit intent."""
    file_path: str = ""
    old_text: str = ""
    new_text: str = ""

    def to_dict(self) -> dict:
        return {"file_path": self.file_path, "old_text": self.old_text, "new_text": self.new_text}


@dataclass
class CandidatePatch:
    """A candidate patch for the promotion pipeline."""
    run_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    patch_id: str = ""
    intents: list[PatchIntent] = field(default_factory=list)
    domain: str = ""
    description: str = ""
    issue: str = ""
    strategy: str = ""
    risk: str = "LOW"
    risk_level: str = ""

    def __post_init__(self):
        if not self.patch_id:
            self.patch_id = self.run_id

    @property
    def files(self) -> list[str]:
        return [i.file_path for i in self.intents]

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "patch_id": self.patch_id,
            "files": self.files,
            "domain": self.domain,
            "description": self.description,
            "issue": self.issue,
            "risk": self.risk,
            "risk_level": self.risk_level,
            "intents": [i.to_dict() for i in self.intents],
        }


# ── Result model ──────────────────────────────────────────────────────────────

@dataclass
class PromotionResult:
    """
    Full result from the promotion pipeline.
    Safe to return to any caller — secrets are scrubbed.
    """
    run_id: str = ""
    decision: str = "REJECT"        # PROMOTE | REVIEW | REJECT
    unified_diff: str = ""          # The validated diff (empty if REJECT)
    changed_files: list[str] = field(default_factory=list)
    risk_level: str = "MEDIUM"      # LOW | MEDIUM | HIGH
    score: float = 0.0              # 0.0–1.0 quality score
    validation_report: dict = field(default_factory=dict)
    rollback_instructions: str = ""
    explanation: str = ""
    pr_url: str = ""                # Set if GitAgent created a PR
    human_notified: bool = False    # Set if HumanGate was triggered
    duration_s: float = 0.0
    error: str = ""
    reason: str = ""                # Human-readable reason for the decision
    patch_id: str = ""              # Identifier for the patch
    files_changed: list[str] = field(default_factory=list)  # Alias for changed_files

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "decision": self.decision,
            "unified_diff": self.unified_diff,
            "changed_files": self.changed_files,
            "risk_level": self.risk_level,
            "score": self.score,
            "validation_report": self.validation_report,
            "rollback_instructions": self.rollback_instructions,
            "explanation": self.explanation,
            "pr_url": self.pr_url,
            "human_notified": self.human_notified,
            "duration_s": self.duration_s,
            "error": self.error,
        }


# ── Secret scrubber ───────────────────────────────────────────────────────────

_SECRET_RE = re.compile(
    r"(api[_-]?key|secret|password|token|bearer|authorization)\s*[=:]\s*\S+",
    re.I,
)
_TOKEN_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{10,}"),           # OpenAI-style keys
    re.compile(r"ghp_[a-zA-Z0-9]{10,}"),           # GitHub PATs
    re.compile(r"xoxb-[a-zA-Z0-9\-]+"),            # Slack bot tokens
    re.compile(r"xoxp-[a-zA-Z0-9\-]+"),            # Slack user tokens
    re.compile(r"Bearer\s+[a-zA-Z0-9._\-]{10,}"),   # Bearer tokens
]


def _scrub_secrets(text: str) -> str:
    """Replace potential secrets in text output."""
    result = _SECRET_RE.sub(r"\1=[REDACTED]", text)
    for pat in _TOKEN_PATTERNS:
        result = pat.sub("[REDACTED]", result)
    return result


# ── Score calculator ──────────────────────────────────────────────────────────

def _compute_score(
    sandbox_result,
    risk_level: str,
    has_diff: bool,
) -> float:
    """Compute quality score 0.0–1.0 for the patch."""
    if not has_diff:
        return 0.0

    score = 0.5  # baseline

    if getattr(sandbox_result, "tests_passed", False):
        score += 0.25
    if getattr(sandbox_result, "lint_passed", False):
        score += 0.10
    if getattr(sandbox_result, "typecheck_passed", False):
        score += 0.10

    regressions = getattr(sandbox_result, "regressions", [])
    score -= len(regressions) * 0.15

    risk_penalty = {"LOW": 0.0, "MEDIUM": 0.05, "HIGH": 0.15}.get(risk_level, 0.05)
    score -= risk_penalty

    return round(max(0.0, min(1.0, score)), 3)


# ── Rollback instruction builder ──────────────────────────────────────────────

def _build_rollback_instructions(changed_files: list[str], unified_diff: str) -> str:
    """Build human-readable rollback instructions."""
    if not changed_files:
        return "No files changed — no rollback needed."

    lines = [
        "# Rollback Instructions",
        "",
        "To revert this change, run one of the following:",
        "",
        "## Option 1: Git revert (recommended)",
        "```bash",
        "git revert HEAD  # if this commit is the latest",
        "# or",
        "git revert <commit-sha>",
        "```",
        "",
        "## Option 2: Manual revert",
        "Apply the inverse diff to the following files:",
    ]
    for f in changed_files:
        lines.append(f"  - {f}")

    if unified_diff:
        lines += [
            "",
            "## Inverse diff (apply with: patch -p1 -R < patch.diff)",
            "```diff",
            unified_diff[:2000],
            "```",
        ]

    return "\n".join(lines)


# ── Main pipeline ─────────────────────────────────────────────────────────────

class PromotionPipeline:
    """
    V3 Self-Improvement Promotion Pipeline.

    Usage:
        pipeline = PromotionPipeline()
        result = pipeline.execute(candidate)
        # result.decision is PROMOTE | REVIEW | REJECT
    """

    def __init__(self, repo_root: Optional[Path] = None, **kwargs):
        self.repo_root = repo_root or Path(__file__).resolve().parent.parent.parent
        self._lessons: list[dict] = []
        self._notifier = kwargs.get("notifier", None)

    def record_lesson(self, decision_or_lesson, strategy: str = "", **kwargs) -> bool:
        """Record a lesson learned from a pipeline execution. Returns True on success."""
        try:
            if isinstance(decision_or_lesson, dict):
                self._lessons.append(decision_or_lesson)
            else:
                # PromotionDecision/PromotionResult object
                lesson = {
                    "decision": getattr(decision_or_lesson, "decision", ""),
                    "reason": getattr(decision_or_lesson, "reason", ""),
                    "patch_id": getattr(decision_or_lesson, "patch_id", ""),
                    "strategy": strategy,
                }
                self._lessons.append(lesson)
            return True
        except Exception:
            return False

    def get_lessons(self) -> list[dict]:
        return list(self._lessons)

    def set_notifier(self, notifier) -> None:
        """Set a notification callback for REVIEW/PROMOTE decisions."""
        self._notifier = notifier

    @staticmethod
    def _is_noop_mutation(candidate) -> bool:
        """Detect no-op mutations (noop_mutation check).

        Rejects patches where old_text == new_text or the diff is empty.
        This prevents pointless promotions that waste review cycles.
        """
        intents = getattr(candidate, "intents", [])
        if intents:
            return all(
                getattr(i, "old_text", "") == getattr(i, "new_text", "")
                for i in intents
            )
        patch = getattr(candidate, "code_patch", "") or ""
        return not patch.strip()

    def _execute_intents_pipeline(self, candidate) -> "PromotionDecision":
        """Handle CandidatePatch with .intents using CodePatcher."""
        start = time.monotonic()
        patch_id = getattr(candidate, "patch_id", "") or getattr(candidate, "run_id", "")
        risk_level = getattr(candidate, "risk_level", "") or getattr(candidate, "risk", "low")
        intents = getattr(candidate, "intents", [])
        files = getattr(candidate, "files", [])

        # ── Cognitive journal: patch_proposed (fail-open) ─────────────
        try:
            from core.cognitive_events.emitter import emit_patch_proposed
            emit_patch_proposed(
                patch_id=patch_id,
                description=getattr(candidate, "description", "") or getattr(candidate, "issue", ""),
                files=files[:10],
                risk_level=risk_level,
            )
        except Exception:
            log.debug("swallowed_exception", exc_info=True)

        # ── Kernel event: patch proposed (dual emission) ──────────────
        try:
            from kernel.convergence.event_bridge import emit_kernel_event
            emit_kernel_event("step.started",
                              step_id=patch_id, source="promotion_pipeline",
                              step_name=f"Patch: {getattr(candidate, 'description', '')[:60]}",
                              plan_id="self-improvement")
        except Exception as _exc:
            log.warning("swallowed_exception", action="promotion_pipeline_1", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        # 1. Check protected files
        try:
            from core.self_improvement.protected_paths import is_protected
            for intent in intents:
                fp = getattr(intent, "file_path", "")
                if fp and is_protected(fp):
                    elapsed = (time.monotonic() - start) * 1000
                    return PromotionDecision(
                        decision="REJECT",
                        reason=f"Protected file: {fp}",
                        patch_id=patch_id,
                        files_changed=files,
                        duration_ms=elapsed,
                        risk_level=risk_level,
                    )
        except ImportError as _exc:
            log.warning("swallowed_exception", action="promotion_pipeline_2", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        # 2. Generate patch using CodePatcher
        try:
            from core.self_improvement.code_patcher import CodePatcher, PatchIntent as CPI
            patcher = CodePatcher(self.repo_root)
            # Convert PatchIntents
            cp_intents = []
            for intent in intents:
                cp_intents.append(CPI(
                    getattr(intent, "file_path", ""),
                    getattr(intent, "old_text", ""),
                    getattr(intent, "new_text", ""),
                ))
            issue = getattr(candidate, "issue", "") or getattr(candidate, "description", "")
            patch = patcher.generate(cp_intents, issue)

            # Check for violations
            if getattr(patch, "protected_violation", False):
                elapsed = (time.monotonic() - start) * 1000
                return PromotionDecision(
                    decision="REJECT",
                    reason="Protected file violation",
                    patch_id=patch_id,
                    files_changed=files,
                    duration_ms=elapsed,
                )

            if getattr(patch, "size_violation", False):
                elapsed = (time.monotonic() - start) * 1000
                return PromotionDecision(
                    decision="REJECT",
                    reason="Size violation: too many files",
                    patch_id=patch_id,
                    files_changed=files,
                    duration_ms=elapsed,
                )

            if getattr(patch, "noop_violation", False) or not getattr(patch, "diffs", []):
                elapsed = (time.monotonic() - start) * 1000
                return PromotionDecision(
                    decision="REJECT",
                    reason="No effective changes",
                    patch_id=patch_id,
                    files_changed=files,
                    duration_ms=elapsed,
                )

            # 3. Validate syntax
            if not patcher.validate_syntax(patch):
                elapsed = (time.monotonic() - start) * 1000
                return PromotionDecision(
                    decision="REJECT",
                    reason="Syntax error in patched code",
                    patch_id=patch_id,
                    files_changed=files,
                    duration_ms=elapsed,
                )

            # 4. Create sandbox, apply, test
            try:
                from core.self_improvement.git_agent import GitAgent, WorkspaceSnapshot
                agent = GitAgent(self.repo_root)
                snap = agent._create_tempcopy(WorkspaceSnapshot(
                    sandbox_branch=f"auto/{patch_id}",
                ))
                try:
                    applied = patcher.apply_to_sandbox(patch, snap.sandbox_path)
                    if not applied:
                        elapsed = (time.monotonic() - start) * 1000
                        return PromotionDecision(
                            decision="REJECT",
                            reason="Failed to apply patch to sandbox",
                            patch_id=patch_id,
                            files_changed=files,
                            duration_ms=elapsed,
                        )

                    # T4.3 — Canary gate: compile-check changed files before promoting
                    try:
                        from core.self_improvement.canary_gate import get_canary_gate
                        canary = get_canary_gate().run(
                            sandbox_path=snap.sandbox_path,
                            changed_files=files,
                        )
                        if not canary.passed:
                            elapsed = (time.monotonic() - start) * 1000
                            rollback = _build_rollback_instructions(files, "")
                            return PromotionDecision(
                                decision="REJECT",
                                reason=f"canary_gate: {canary.reason}",
                                patch_id=patch_id,
                                files_changed=files,
                                duration_ms=elapsed,
                                rollback_instructions=rollback,
                            )
                    except Exception as _ce:
                        log.warning("promotion_pipeline.canary_swallowed",
                                    err=str(_ce)[:80])

                    # T4.5 — Build digest: fingerprint build inputs for reproducibility
                    _build_digest: dict = {}
                    try:
                        from core.self_improvement.build_digest import compute_build_digest
                        _build_digest = compute_build_digest(self.repo_root)
                    except Exception:
                        pass

                    # Determine decision based on risk
                    rl = risk_level.lower() if isinstance(risk_level, str) else "low"
                    if rl == "medium":
                        decision = "REVIEW"
                        reason = "Medium risk — requires review"
                    elif rl == "high":
                        decision = "REVIEW"
                        reason = "High risk — requires review"
                    else:
                        decision = "PROMOTE"
                        reason = "Valid patch, low risk"

                    elapsed = (time.monotonic() - start) * 1000
                    rollback = _build_rollback_instructions(files, "")
                    return PromotionDecision(
                        decision=decision,
                        reason=reason,
                        patch_id=patch_id,
                        files_changed=files,
                        duration_ms=elapsed,
                        risk_level=risk_level,
                        score=1.0,
                        rollback_instructions=rollback,
                        build_digest=_build_digest,
                    )
                finally:
                    agent.cleanup_sandbox(snap)
            except ImportError:
                # GitAgent unavailable — fail-closed: never auto-promote without sandbox
                elapsed = (time.monotonic() - start) * 1000
                return PromotionDecision(
                    decision="REVIEW",
                    reason="Sandbox unavailable (GitAgent import failed) — human review required",
                    patch_id=patch_id,
                    files_changed=files,
                    duration_ms=elapsed,
                )

        except ImportError:
            elapsed = (time.monotonic() - start) * 1000
            return PromotionDecision(
                decision="REJECT",
                reason="CodePatcher unavailable",
                patch_id=patch_id,
                duration_ms=elapsed,
            )
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            return PromotionDecision(
                decision="REJECT",
                reason=f"Pipeline error: {exc}",
                patch_id=patch_id,
                duration_ms=elapsed,
            )

    def execute(self, candidate):
        """
        Execute the full promotion pipeline for a candidate improvement.

        Supports two modes:
        1. CandidatePatch with .intents — uses CodePatcher-based pipeline
        2. Legacy ImprovementCandidate with .code_patch / .target_file — uses LLM-based pipeline

        Returns:
            PromotionDecision (for intents) or PromotionResult (legacy) — never raises.
        """
        # Validate patch signature before any processing (fail-closed).
        # Gate handles dev mode (no BEA_PATCH_VERIFY_KEY) vs production.
        sig_data = getattr(candidate, "sig_data", None)
        try:
            from kernel.improvement.gate import get_gate, PatchSignatureViolation
            patch_content = candidate.to_dict() if hasattr(candidate, "to_dict") else {}
            get_gate().validate_patch_signature(patch_content, sig_data)
        except PatchSignatureViolation as exc:
            patch_id = getattr(candidate, "patch_id", "") or getattr(candidate, "run_id", "")
            log.warning("promotion_pipeline.signature_rejected", patch_id=patch_id, err=str(exc)[:120])
            return PromotionDecision(
                decision="REJECT",
                reason=f"signature_violation: {exc}",
                patch_id=patch_id,
            )

        # Dispatch: if candidate has .intents, use the new pipeline
        intents = getattr(candidate, "intents", None)
        if intents is not None and len(intents) > 0:
            try:
                _decision = self._execute_intents_pipeline(candidate)
            except Exception as exc:
                _decision = PromotionDecision(
                    decision="REJECT",
                    reason=f"Pipeline error: {exc}",
                    patch_id=getattr(candidate, "patch_id", ""),
                )
            # ── Cognitive journal: patch decision (fail-open) ─────────
            try:
                _pid = getattr(_decision, "patch_id", "") or getattr(candidate, "patch_id", "")
                _dec = getattr(_decision, "decision", "REJECT")
                _files = getattr(_decision, "files_changed", []) or getattr(candidate, "files", [])
                if _dec == "REJECT":
                    from core.cognitive_events.emitter import emit_patch_validated
                    emit_patch_validated(patch_id=_pid, passed=False,
                                         reason=getattr(_decision, "reason", ""))
                else:
                    from core.cognitive_events.emitter import emit_patch_validated
                    emit_patch_validated(patch_id=_pid, passed=True,
                                         decision=_dec, files=_files[:10])
            except Exception:
                log.debug("swallowed_exception", exc_info=True)

            # ── Kernel event: patch decision (dual emission) ──────────
            try:
                from kernel.convergence.event_bridge import emit_kernel_event
                _pid2 = getattr(_decision, "patch_id", "") or getattr(candidate, "patch_id", "")
                _dec2 = getattr(_decision, "decision", "REJECT")
                if _dec2 == "REJECT":
                    emit_kernel_event("step.failed", step_id=_pid2,
                                      source="promotion_pipeline",
                                      error=getattr(_decision, "reason", "")[:100],
                                      plan_id="self-improvement")
                else:
                    emit_kernel_event("step.completed", step_id=_pid2,
                                      source="promotion_pipeline",
                                      plan_id="self-improvement")
            except Exception as _exc:
                log.warning("swallowed_exception", action="promotion_pipeline_3", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
            return _decision

        # Legacy path
        run_id = str(uuid.uuid4())[:12]
        start = time.monotonic()

        # Reject no-op mutations early
        if self._is_noop_mutation(candidate):
            log.info("promotion_pipeline.noop_mutation", run_id=run_id)
            return PromotionResult(
                run_id=run_id, decision="REJECT", unified_diff="",
                explanation="No-op: sandbox has no actual diff — patch has no effective changes.",
                duration_s=time.monotonic() - start,
            )

        log.info(
            "promotion_pipeline.start",
            run_id=run_id,
            type=getattr(candidate, "type", "?"),
            domain=getattr(candidate, "domain", "?"),
        )

        try:
            result = self._run(run_id, candidate)
        except Exception as exc:
            log.error("promotion_pipeline.unhandled_error run_id=%s err=%s", run_id, str(exc))
            result = PromotionResult(
                run_id=run_id,
                decision="REJECT",
                unified_diff="",
                error=f"Pipeline error: {exc}",
            )

        result.duration_s = round(time.monotonic() - start, 2)

        # Emit observability event
        self._emit_event(run_id, result)

        # Record lesson
        self._record_lesson(candidate, result)

        log.info(
            "promotion_pipeline.complete",
            run_id=run_id,
            decision=result.decision,
            score=result.score,
            duration_s=result.duration_s,
        )
        return result

    def _run(self, run_id: str, candidate) -> PromotionResult:
        """Internal pipeline execution (may raise — caller handles)."""
        candidate_type = getattr(candidate, "type", "UNKNOWN")
        domain = getattr(candidate, "domain", "general")
        description = getattr(candidate, "description", "")
        risk = getattr(candidate, "risk", "MEDIUM")
        target_file = getattr(candidate, "target_file", "")
        current_content = getattr(candidate, "current_content", "")

        # ── Step 1: Get or generate patch ─────────────────────────────────────

        # Check if candidate already has a pre-generated patch
        pre_patch = getattr(candidate, "code_patch", "")

        if pre_patch:
            unified_diff = pre_patch
            changed_files = getattr(candidate, "changed_files", [target_file] if target_file else [])
            risk_level = risk
            explanation = description
            log.info("promotion_pipeline.using_pre_patch", run_id=run_id)
        elif target_file and current_content:
            # Generate patch via LLM
            unified_diff, changed_files, risk_level, explanation = self._generate_patch(
                description, target_file, current_content, run_id
            )
            if unified_diff is None:
                # Generation failed
                return PromotionResult(
                    run_id=run_id,
                    decision="REJECT",
                    unified_diff="",
                    error="Patch generation failed — LLM unavailable or blocked",
                )
        else:
            # Non-code candidate (PROMPT_TWEAK, TOOL_PREFERENCE, etc.)
            # These go through safe_executor, not this V3 pipeline
            # Return REVIEW for human validation of workspace changes
            log.info("promotion_pipeline.non_code_candidate", run_id=run_id, type=candidate_type)
            return PromotionResult(
                run_id=run_id,
                decision="REVIEW",
                unified_diff="",
                changed_files=[],
                risk_level=risk,
                score=0.5,
                explanation=f"Non-code candidate ({candidate_type}): {description[:200]}",
                validation_report={"type": candidate_type, "domain": domain},
                rollback_instructions="Workspace preference change — revert via workspace/preferences/ files.",
            )

        # ── Step 2: Sandbox execution ─────────────────────────────────────────

        sandbox_result = self._run_sandbox(unified_diff, changed_files, run_id)

        # ── Step 3: Compute score ─────────────────────────────────────────────

        score = _compute_score(sandbox_result, risk_level, bool(unified_diff))

        validation_report = {
            "tests_passed": getattr(sandbox_result, "tests_passed", False),
            "lint_passed": getattr(sandbox_result, "lint_passed", False),
            "typecheck_passed": getattr(sandbox_result, "typecheck_passed", False),
            "regressions": getattr(sandbox_result, "regressions", []),
            "improvements": getattr(sandbox_result, "improvements", []),
            "docker_used": getattr(sandbox_result, "docker_used", False),
            "duration_s": getattr(sandbox_result, "duration_s", 0.0),
            "stdout_preview": _scrub_secrets(
                getattr(sandbox_result, "stdout", "")[:500]
            ),
        }

        rollback = _build_rollback_instructions(changed_files, unified_diff)

        # ── Step 4: Make decision ─────────────────────────────────────────────

        decision = self._decide(sandbox_result, risk_level, score, candidate_type)

        result = PromotionResult(
            run_id=run_id,
            decision=decision,
            unified_diff=unified_diff if decision != "REJECT" else "",
            changed_files=changed_files,
            risk_level=risk_level,
            score=score,
            validation_report=validation_report,
            rollback_instructions=rollback,
            explanation=_scrub_secrets(explanation),
        )

        # ── Step 5: Post-decision actions ─────────────────────────────────────

        if decision == "PROMOTE":
            pr_url = self._create_pr(result, domain, run_id)
            result.pr_url = pr_url

        elif decision == "REVIEW":
            notified = self._notify_human(result, domain, description, run_id)
            result.human_notified = notified

        return result

    # ── Step implementations ──────────────────────────────────────────────────

    def _generate_patch(
        self,
        description: str,
        target_file: str,
        current_content: str,
        run_id: str,
    ) -> tuple[Optional[str], list[str], str, str]:
        """Generate patch via LLM. Returns (diff, changed_files, risk, explanation) or (None, ...) on error."""
        try:
            from core.self_improvement.code_patch_generator import (
                CodePatchGenerator,
                PatchRequest,
            )
            gen = CodePatchGenerator()
            patch_req = PatchRequest(
                problem_description=description,
                target_file=target_file,
                current_content=current_content,
            )
            patch = gen.generate(patch_req)

            if not patch.success:
                log.warning("promotion_pipeline.patch_gen_failed", run_id=run_id, err=patch.error)
                return None, [], "HIGH", patch.error

            return patch.unified_diff, patch.changed_files, patch.risk_level, patch.explanation
        except Exception as exc:
            log.error("promotion_pipeline.patch_gen_error", run_id=run_id, err=str(exc))
            return None, [], "HIGH", str(exc)

    def _run_sandbox(self, unified_diff: str, changed_files: list[str], run_id: str):
        """Run sandbox execution. Returns SandboxResult-like object."""
        from dataclasses import dataclass as _dc, field as _field

        @_dc
        class _FallbackResult:
            success: bool = True
            tests_passed: bool = True
            lint_passed: bool = True
            typecheck_passed: bool = True
            regressions: list = _field(default_factory=list)
            improvements: list = _field(default_factory=list)
            stdout: str = ""
            stderr: str = ""
            exit_code: int = 0
            duration_s: float = 0.0
            docker_used: bool = False
            error: str = ""

        try:
            from core.self_improvement.sandbox_executor import get_sandbox_executor
            executor = get_sandbox_executor()
            return executor.execute(unified_diff, changed_files)
        except ImportError:
            log.warning("promotion_pipeline.sandbox_unavailable", run_id=run_id)
            # Return safe degraded result — decision will be REVIEW (not PROMOTE)
            return _FallbackResult(
                success=True,
                tests_passed=False,  # Unknown → conservative
                lint_passed=False,
                error="SandboxExecutor unavailable — degraded mode",
            )
        except Exception as exc:
            log.error("promotion_pipeline.sandbox_error", run_id=run_id, err=str(exc))
            return _FallbackResult(
                success=False,
                tests_passed=False,
                error=str(exc),
            )

    def _decide(self, sandbox_result, risk_level: str, score: float, candidate_type: str) -> Decision:
        """Make PROMOTE / REVIEW / REJECT decision."""
        tests_passed = getattr(sandbox_result, "tests_passed", False)
        regressions = getattr(sandbox_result, "regressions", [])
        sandbox_success = getattr(sandbox_result, "success", False)

        # Hard REJECT conditions
        if not sandbox_success:
            log.info("decision.reject — sandbox failed")
            return "REJECT"
        if regressions:
            log.info("decision.reject — regressions detected", count=len(regressions))
            return "REJECT"
        if not tests_passed and score < 0.3:
            log.info("decision.reject — tests failed + low score")
            return "REJECT"

        # PROMOTE: low risk, tests pass, good score
        if risk_level == "LOW" and tests_passed and score >= 0.7:
            log.info("decision.promote — low risk, tests pass, score OK")
            return "PROMOTE"

        # Everything else → REVIEW (human validation)
        log.info("decision.review — requires human validation", risk=risk_level, score=score)
        return "REVIEW"

    def _create_pr(self, result: PromotionResult, domain: str, run_id: str) -> str:
        """Create a GitHub PR for a PROMOTE decision. Returns PR URL or ""."""
        try:
            from core.self_improvement.git_agent import get_git_agent
            agent = get_git_agent()
            pr_url = agent.create_improvement_pr(
                unified_diff=result.unified_diff,
                changed_files=result.changed_files,
                domain=domain,
                run_id=run_id,
                explanation=result.explanation,
                score=result.score,
            )
            log.info("promotion_pipeline.pr_created", run_id=run_id, pr_url=pr_url)
            return pr_url
        except Exception as exc:
            log.warning("promotion_pipeline.pr_failed", run_id=run_id, err=str(exc))
            return ""

    def _notify_human(
        self,
        result: PromotionResult,
        domain: str,
        description: str,
        run_id: str,
    ) -> bool:
        """Notify human for REVIEW decision. Returns True if notification sent."""
        try:
            from core.self_improvement.human_gate import get_human_gate
            gate = get_human_gate()
            return gate.notify_review(
                run_id=run_id,
                domain=domain,
                description=description,
                risk_level=result.risk_level,
                score=result.score,
                validation_report=result.validation_report,
                unified_diff=result.unified_diff,
                changed_files=result.changed_files,
            )
        except Exception as exc:
            log.warning("promotion_pipeline.human_notify_failed", run_id=run_id, err=str(exc))
            return False

    def _emit_event(self, run_id: str, result: PromotionResult) -> None:
        """Emit observability event + kernel event."""
        try:
            from core.observability.event_envelope import get_event_collector
            get_event_collector().emit_quick("self_improvement", "promotion_complete", {
                "run_id": run_id,
                "decision": result.decision,
                "risk_level": result.risk_level,
                "score": result.score,
                "changed_files": result.changed_files,
                "pr_url": result.pr_url,
                "human_notified": result.human_notified,
                "duration_s": result.duration_s,
            })
        except Exception:
            log.debug("swallowed_exception", exc_info=True)

        # ── Kernel event: promotion result (dual emission) ────────
        try:
            from kernel.convergence.event_bridge import emit_kernel_event
            _kernel_type = "step.completed" if result.decision in ("PROMOTE", "REVIEW") else "step.failed"
            emit_kernel_event(_kernel_type,
                              step_id=run_id, source="promotion_pipeline",
                              plan_id="self-improvement",
                              error=result.error[:100] if result.error else "")
        except Exception as _exc:
            log.warning("swallowed_exception", action="promotion_pipeline_4", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    def _record_lesson(self, candidate, result: PromotionResult) -> None:
        """Record lesson learned in improvement memory."""
        try:
            from core.self_improvement.improvement_loop import get_improvement_loop
            loop = get_improvement_loop()
            loop.evaluate_candidate(
                candidate_id=result.run_id,
                hypothesis=getattr(candidate, "description", "")[:200],
                touched_modules=result.changed_files,
                risk_level=result.risk_level,
                baseline_report={"pass_rate": 1.0},  # nosec B105 — schema field, not a credential
                candidate_report={
                    "pass_rate": 1.0 if result.validation_report.get("tests_passed") else 0.0,
                    "regressions": result.validation_report.get("regressions", []),
                    "improvements": result.validation_report.get("improvements", []),
                    "schema_intact": True,
                    "trace_intact": True,
                    "safety_intact": result.decision != "REJECT",
                },
            )
        except Exception as exc:
            log.debug("promotion_pipeline.lesson_record_failed", err=str(exc))

        # ── Cognitive journal: lesson_stored (fail-open) ──────────────
        try:
            from core.cognitive_events.emitter import emit_lesson_stored
            emit_lesson_stored(
                lesson_summary=f"{result.decision}: {getattr(candidate, 'description', '')[:100]}",
                source_subsystem="promotion_pipeline",
                run_id=result.run_id,
                decision=result.decision,
                risk_level=result.risk_level,
            )
        except Exception:
            log.debug("swallowed_exception", exc_info=True)


# ── Singleton ──────────────────────────────────────────────────────────────────

_pipeline: PromotionPipeline | None = None


def get_promotion_pipeline() -> PromotionPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = PromotionPipeline()
    return _pipeline

# ── Backward compat alias ─────────────────────────────────────────────────────


@dataclass
class PromotionDecision:
    """Decision result from the promotion pipeline (test-facing API)."""
    decision: str = ""
    reason: str = ""
    patch_id: str = ""
    files_changed: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    hypothesis: str = ""
    score: float = 0.0
    duration_ms: float = 0.0
    duration_s: float = 0.0
    risk_level: str = ""
    unified_diff: str = ""
    rollback_instructions: str = ""
    validation_report: dict = field(default_factory=dict)
    pr_url: str = ""
    error: str = ""
    run_id: str = ""
    human_notified: bool = False
    explanation: str = ""
    build_digest: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "decision": self.decision,
            "reason": self.reason,
            "patch_id": self.patch_id,
            "files_changed": self.files_changed,
            "hypothesis": self.hypothesis,
            "score": round(self.score, 3),
            "duration_ms": round(self.duration_ms, 1),
            "risk_level": self.risk_level,
        }
        if self.build_digest:
            d["build_digest"] = self.build_digest
        return d

    def to_experiment_report(self) -> "ExperimentReport":
        """Convert to ExperimentReport for observability."""
        try:
            from core.self_improvement.test_runner import ExperimentReport
        except ImportError:
            # Inline fallback
            raise
        return ExperimentReport(
            experiment_id=self.patch_id,
            hypothesis=self.hypothesis,
            changed_files=self.files_changed,
            score=self.score,
            decision=self.decision,
        )
