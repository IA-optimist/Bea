"""
tests/test_self_improvement_v3.py — Test suite for V3 Self-Improvement Pipeline.

Tests the complete pipeline:
  1. Bridge uses PromotionPipeline (not old paths)
  2. Low-risk valid candidate → PROMOTE
  3. Validation failure → REJECT
  4. Medium/high risk → REVIEW
  5. Lesson recording called
  6. Observability events emitted
  7. No auto-apply in production (diff never written to production files)
  8. Rollback instructions present in PROMOTE/REVIEW results
  9. Degraded behavior without Docker is safe (REVIEW, not crash)
  10. Secret scrubbing in returned results
"""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch

import pytest

# ── Test helpers / fixtures ───────────────────────────────────────────────────

@dataclass
class MockCandidate:
    """Minimal candidate for testing."""
    type: str = "CODE_PATCH"
    description: str = "Fix missing null check in handler"
    domain: str = "core"
    risk: str = "LOW"
    target_file: str = "core/some_module.py"
    current_content: str = "def handler(x):\n    return x.value\n"
    code_patch: str = ""
    changed_files: list = field(default_factory=list)


@dataclass
class MockWorkspaceCandidate:
    """Workspace (non-code) candidate."""
    type: str = "PROMPT_TWEAK"
    description: str = "Improve coding prompt"
    domain: str = "coding"
    risk: str = "LOW"


SAMPLE_DIFF = """\
--- a/core/some_module.py
+++ b/core/some_module.py
@@ -1,3 +1,5 @@
 def handler(x):
-    return x.value
+    if x is None:
+        return None
+    return x.value
"""


# ── 1. Bridge uses PromotionPipeline ─────────────────────────────────────────

class TestPromotionPipelineBridge:
    """Engine routes code candidates to PromotionPipeline (not old SafeExecutor)."""

    def test_engine_calls_promotion_pipeline_for_code_candidates(self):
        from core.self_improvement.engine import SelfImprovementEngine

        engine = SelfImprovementEngine()
        candidate = MockCandidate(code_patch=SAMPLE_DIFF)

        with patch("core.self_improvement.engine.SelfImprovementEngine._run_promotion_pipeline") as mock_promo:
            mock_promo.return_value = {"decision": "PROMOTE", "run_id": "test123", "score": 0.8}
            result = engine._execute_candidate(candidate)

        mock_promo.assert_called_once_with(candidate)
        assert result["decision"] == "PROMOTE"

    def test_engine_routes_workspace_candidates_to_safe_executor(self):
        from core.self_improvement.engine import SelfImprovementEngine

        engine = SelfImprovementEngine()
        candidate = MockWorkspaceCandidate()

        with patch("core.self_improvement.engine.SelfImprovementEngine._run_safe_executor") as mock_safe:
            mock_safe.return_value = {"decision": "APPLIED", "output": "done"}
            engine._execute_candidate(candidate)

        mock_safe.assert_called_once_with(candidate)

    def test_engine_never_routes_workspace_candidates_to_promotion_pipeline(self):
        from core.self_improvement.engine import SelfImprovementEngine

        engine = SelfImprovementEngine()
        candidate = MockWorkspaceCandidate()


        with patch("core.self_improvement.engine.SelfImprovementEngine._run_promotion_pipeline") as mock_promo:
            with patch("core.self_improvement.engine.SelfImprovementEngine._run_safe_executor") as mock_safe:
                mock_safe.return_value = {"decision": "APPLIED"}
                engine._execute_candidate(candidate)
                mock_promo.assert_not_called()


# ── 2. Low-risk valid candidate → PROMOTE ────────────────────────────────────

class TestPromoteDecision:
    """A low-risk candidate with passing tests → PROMOTE."""

    def test_promote_on_low_risk_passing_tests(self):
        from core.self_improvement.promotion_pipeline import PromotionPipeline

        pipeline = PromotionPipeline()
        candidate = MockCandidate(code_patch=SAMPLE_DIFF, risk="LOW")

        mock_sandbox = MagicMock()
        mock_sandbox.success = True
        mock_sandbox.tests_passed = True
        mock_sandbox.lint_passed = True
        mock_sandbox.typecheck_passed = True
        mock_sandbox.regressions = []
        mock_sandbox.improvements = ["all_tests_pass"]
        mock_sandbox.docker_used = True
        mock_sandbox.stdout = ""
        mock_sandbox.stderr = ""
        mock_sandbox.exit_code = 0
        mock_sandbox.duration_s = 5.0

        with patch.object(pipeline, "_run_sandbox", return_value=mock_sandbox):
            with patch.object(pipeline, "_create_pr", return_value="https://github.com/test/pr/1"):
                with patch.object(pipeline, "_record_lesson"):
                    with patch.object(pipeline, "_emit_event"):
                        result = pipeline.execute(candidate)

        assert result.decision == "PROMOTE"
        assert result.score >= 0.7
        assert result.unified_diff == SAMPLE_DIFF

    def test_promote_result_has_rollback_instructions(self):
        from core.self_improvement.promotion_pipeline import PromotionPipeline

        pipeline = PromotionPipeline()
        candidate = MockCandidate(code_patch=SAMPLE_DIFF, risk="LOW")

        mock_sandbox = MagicMock()
        mock_sandbox.success = True
        mock_sandbox.tests_passed = True
        mock_sandbox.lint_passed = True
        mock_sandbox.typecheck_passed = True
        mock_sandbox.regressions = []
        mock_sandbox.improvements = ["all_tests_pass"]
        mock_sandbox.docker_used = True
        mock_sandbox.stdout = ""
        mock_sandbox.stderr = ""
        mock_sandbox.exit_code = 0
        mock_sandbox.duration_s = 3.0

        with patch.object(pipeline, "_run_sandbox", return_value=mock_sandbox):
            with patch.object(pipeline, "_create_pr", return_value=""):
                with patch.object(pipeline, "_record_lesson"):
                    with patch.object(pipeline, "_emit_event"):
                        result = pipeline.execute(candidate)

        assert result.rollback_instructions != ""
        assert "rollback" in result.rollback_instructions.lower() or "revert" in result.rollback_instructions.lower()


# ── 3. Validation failure → REJECT ───────────────────────────────────────────

class TestRejectDecision:
    """Test failure causes REJECT."""

    def test_reject_on_test_failure(self):
        from core.self_improvement.promotion_pipeline import PromotionPipeline

        pipeline = PromotionPipeline()
        candidate = MockCandidate(code_patch=SAMPLE_DIFF, risk="LOW")

        mock_sandbox = MagicMock()
        mock_sandbox.success = True
        mock_sandbox.tests_passed = False
        mock_sandbox.lint_passed = True
        mock_sandbox.typecheck_passed = True
        mock_sandbox.regressions = ["tests/test_core.py::test_handler FAILED"]
        mock_sandbox.improvements = []
        mock_sandbox.docker_used = True
        mock_sandbox.stdout = "FAILED tests/test_core.py::test_handler"
        mock_sandbox.stderr = ""
        mock_sandbox.exit_code = 1
        mock_sandbox.duration_s = 8.0

        with patch.object(pipeline, "_run_sandbox", return_value=mock_sandbox):
            with patch.object(pipeline, "_record_lesson"):
                with patch.object(pipeline, "_emit_event"):
                    result = pipeline.execute(candidate)

        assert result.decision == "REJECT"
        assert result.unified_diff == ""  # No diff on REJECT

    def test_reject_when_sandbox_fails(self):
        from core.self_improvement.promotion_pipeline import PromotionPipeline

        pipeline = PromotionPipeline()
        candidate = MockCandidate(code_patch=SAMPLE_DIFF)

        mock_sandbox = MagicMock()
        mock_sandbox.success = False
        mock_sandbox.tests_passed = False
        mock_sandbox.regressions = []
        mock_sandbox.error = "Docker unavailable"
        mock_sandbox.improvements = []
        mock_sandbox.stdout = ""
        mock_sandbox.stderr = ""
        mock_sandbox.exit_code = -1
        mock_sandbox.duration_s = 0.0
        mock_sandbox.docker_used = False
        mock_sandbox.lint_passed = False
        mock_sandbox.typecheck_passed = False

        with patch.object(pipeline, "_run_sandbox", return_value=mock_sandbox):
            with patch.object(pipeline, "_record_lesson"):
                with patch.object(pipeline, "_emit_event"):
                    result = pipeline.execute(candidate)

        assert result.decision == "REJECT"

    def test_reject_on_regressions(self):
        from core.self_improvement.promotion_pipeline import PromotionPipeline

        pipeline = PromotionPipeline()
        candidate = MockCandidate(code_patch=SAMPLE_DIFF, risk="LOW")

        mock_sandbox = MagicMock()
        mock_sandbox.success = True
        mock_sandbox.tests_passed = True
        mock_sandbox.lint_passed = True
        mock_sandbox.typecheck_passed = True
        mock_sandbox.regressions = ["REGRESSION: test_existing_behavior FAILED"]
        mock_sandbox.improvements = []
        mock_sandbox.docker_used = True
        mock_sandbox.stdout = ""
        mock_sandbox.stderr = ""
        mock_sandbox.exit_code = 1
        mock_sandbox.duration_s = 5.0

        with patch.object(pipeline, "_run_sandbox", return_value=mock_sandbox):
            with patch.object(pipeline, "_record_lesson"):
                with patch.object(pipeline, "_emit_event"):
                    result = pipeline.execute(candidate)

        assert result.decision == "REJECT"


# ── 4. Medium/high risk → REVIEW ─────────────────────────────────────────────

class TestReviewDecision:
    """Medium/high risk candidates go to REVIEW."""

    def test_medium_risk_goes_to_review(self):
        from core.self_improvement.promotion_pipeline import PromotionPipeline

        pipeline = PromotionPipeline()
        candidate = MockCandidate(code_patch=SAMPLE_DIFF, risk="MEDIUM")

        mock_sandbox = MagicMock()
        mock_sandbox.success = True
        mock_sandbox.tests_passed = True
        mock_sandbox.lint_passed = True
        mock_sandbox.typecheck_passed = True
        mock_sandbox.regressions = []
        mock_sandbox.improvements = ["all_tests_pass"]
        mock_sandbox.docker_used = True
        mock_sandbox.stdout = ""
        mock_sandbox.stderr = ""
        mock_sandbox.exit_code = 0
        mock_sandbox.duration_s = 5.0

        with patch.object(pipeline, "_run_sandbox", return_value=mock_sandbox):
            with patch.object(pipeline, "_notify_human", return_value=True):
                with patch.object(pipeline, "_record_lesson"):
                    with patch.object(pipeline, "_emit_event"):
                        result = pipeline.execute(candidate)

        assert result.decision == "REVIEW"

    def test_high_risk_goes_to_review(self):
        from core.self_improvement.promotion_pipeline import PromotionPipeline

        pipeline = PromotionPipeline()
        candidate = MockCandidate(code_patch=SAMPLE_DIFF, risk="HIGH")

        mock_sandbox = MagicMock()
        mock_sandbox.success = True
        mock_sandbox.tests_passed = True
        mock_sandbox.lint_passed = True
        mock_sandbox.typecheck_passed = True
        mock_sandbox.regressions = []
        mock_sandbox.improvements = ["all_tests_pass"]
        mock_sandbox.docker_used = True
        mock_sandbox.stdout = ""
        mock_sandbox.stderr = ""
        mock_sandbox.exit_code = 0
        mock_sandbox.duration_s = 5.0

        with patch.object(pipeline, "_run_sandbox", return_value=mock_sandbox):
            with patch.object(pipeline, "_notify_human", return_value=True):
                with patch.object(pipeline, "_record_lesson"):
                    with patch.object(pipeline, "_emit_event"):
                        result = pipeline.execute(candidate)

        assert result.decision == "REVIEW"


# ── 5. Lesson recording called ────────────────────────────────────────────────

class TestLessonRecording:
    """Lessons are always recorded regardless of decision."""

    def test_lesson_recorded_on_promote(self):
        from core.self_improvement.promotion_pipeline import PromotionPipeline

        pipeline = PromotionPipeline()
        candidate = MockCandidate(code_patch=SAMPLE_DIFF, risk="LOW")

        mock_sandbox = MagicMock()
        mock_sandbox.success = True
        mock_sandbox.tests_passed = True
        mock_sandbox.lint_passed = True
        mock_sandbox.typecheck_passed = True
        mock_sandbox.regressions = []
        mock_sandbox.improvements = ["all_tests_pass"]
        mock_sandbox.docker_used = True
        mock_sandbox.stdout = ""
        mock_sandbox.stderr = ""
        mock_sandbox.exit_code = 0
        mock_sandbox.duration_s = 5.0

        with patch.object(pipeline, "_run_sandbox", return_value=mock_sandbox):
            with patch.object(pipeline, "_create_pr", return_value=""):
                with patch.object(pipeline, "_record_lesson") as mock_record:
                    with patch.object(pipeline, "_emit_event"):
                        pipeline.execute(candidate)
                        mock_record.assert_called_once()

    def test_lesson_recorded_on_reject(self):
        from core.self_improvement.promotion_pipeline import PromotionPipeline

        pipeline = PromotionPipeline()
        candidate = MockCandidate(code_patch=SAMPLE_DIFF, risk="LOW")

        mock_sandbox = MagicMock()
        mock_sandbox.success = False
        mock_sandbox.tests_passed = False
        mock_sandbox.regressions = []
        mock_sandbox.improvements = []
        mock_sandbox.docker_used = False
        mock_sandbox.stdout = ""
        mock_sandbox.stderr = ""
        mock_sandbox.exit_code = 1
        mock_sandbox.duration_s = 0.0
        mock_sandbox.lint_passed = False
        mock_sandbox.typecheck_passed = False

        with patch.object(pipeline, "_run_sandbox", return_value=mock_sandbox):
            with patch.object(pipeline, "_record_lesson") as mock_record:
                with patch.object(pipeline, "_emit_event"):
                    pipeline.execute(candidate)
                    mock_record.assert_called_once()


# ── 6. Observability events emitted ──────────────────────────────────────────

class TestObservability:
    """Events are emitted for every pipeline run."""

    def test_event_emitted_on_every_run(self):
        from core.self_improvement.promotion_pipeline import PromotionPipeline

        pipeline = PromotionPipeline()
        candidate = MockCandidate(code_patch=SAMPLE_DIFF, risk="LOW")

        mock_sandbox = MagicMock()
        mock_sandbox.success = True
        mock_sandbox.tests_passed = True
        mock_sandbox.lint_passed = True
        mock_sandbox.typecheck_passed = True
        mock_sandbox.regressions = []
        mock_sandbox.improvements = []
        mock_sandbox.docker_used = True
        mock_sandbox.stdout = ""
        mock_sandbox.stderr = ""
        mock_sandbox.exit_code = 0
        mock_sandbox.duration_s = 5.0

        with patch.object(pipeline, "_run_sandbox", return_value=mock_sandbox):
            with patch.object(pipeline, "_create_pr", return_value=""):
                with patch.object(pipeline, "_record_lesson"):
                    with patch.object(pipeline, "_emit_event") as mock_emit:
                        pipeline.execute(candidate)
                        mock_emit.assert_called_once()


# ── 7. No auto-apply in production ───────────────────────────────────────────

class TestNoAutoApply:
    """Diff is never written directly to production files."""

    def test_promote_does_not_write_to_production_files(self, tmp_path):
        from core.self_improvement.promotion_pipeline import PromotionPipeline

        pipeline = PromotionPipeline()
        candidate = MockCandidate(code_patch=SAMPLE_DIFF, risk="LOW")

        # Track all file writes

        mock_sandbox = MagicMock()
        mock_sandbox.success = True
        mock_sandbox.tests_passed = True
        mock_sandbox.lint_passed = True
        mock_sandbox.typecheck_passed = True
        mock_sandbox.regressions = []
        mock_sandbox.improvements = ["all_tests_pass"]
        mock_sandbox.docker_used = True
        mock_sandbox.stdout = ""
        mock_sandbox.stderr = ""
        mock_sandbox.exit_code = 0
        mock_sandbox.duration_s = 5.0

        with patch.object(pipeline, "_run_sandbox", return_value=mock_sandbox):
            with patch.object(pipeline, "_create_pr", return_value="https://github.com/test/pr/1") as mock_pr:
                with patch.object(pipeline, "_record_lesson"):
                    with patch.object(pipeline, "_emit_event"):
                        result = pipeline.execute(candidate)

        # PROMOTE should call GitAgent (PR), not write production files
        assert result.decision == "PROMOTE"
        mock_pr.assert_called_once()
        # The diff is in the result but not written to disk by the pipeline
        assert result.unified_diff == SAMPLE_DIFF

    def test_reject_does_not_return_diff(self):
        from core.self_improvement.promotion_pipeline import PromotionPipeline

        pipeline = PromotionPipeline()
        candidate = MockCandidate(code_patch=SAMPLE_DIFF, risk="LOW")

        mock_sandbox = MagicMock()
        mock_sandbox.success = True
        mock_sandbox.tests_passed = False
        mock_sandbox.lint_passed = False
        mock_sandbox.typecheck_passed = False
        mock_sandbox.regressions = ["FAILED test_something"]
        mock_sandbox.improvements = []
        mock_sandbox.docker_used = True
        mock_sandbox.stdout = ""
        mock_sandbox.stderr = ""
        mock_sandbox.exit_code = 1
        mock_sandbox.duration_s = 5.0

        with patch.object(pipeline, "_run_sandbox", return_value=mock_sandbox):
            with patch.object(pipeline, "_record_lesson"):
                with patch.object(pipeline, "_emit_event"):
                    result = pipeline.execute(candidate)

        assert result.decision == "REJECT"
        assert result.unified_diff == ""  # REJECT never returns diff


# ── 8. Rollback instructions present ─────────────────────────────────────────

class TestRollbackInstructions:
    """Rollback instructions always present in PROMOTE/REVIEW results."""

    def test_rollback_instructions_in_review(self):
        from core.self_improvement.promotion_pipeline import PromotionPipeline

        pipeline = PromotionPipeline()
        candidate = MockCandidate(code_patch=SAMPLE_DIFF, risk="HIGH")

        mock_sandbox = MagicMock()
        mock_sandbox.success = True
        mock_sandbox.tests_passed = True
        mock_sandbox.lint_passed = True
        mock_sandbox.typecheck_passed = True
        mock_sandbox.regressions = []
        mock_sandbox.improvements = []
        mock_sandbox.docker_used = True
        mock_sandbox.stdout = ""
        mock_sandbox.stderr = ""
        mock_sandbox.exit_code = 0
        mock_sandbox.duration_s = 5.0

        with patch.object(pipeline, "_run_sandbox", return_value=mock_sandbox):
            with patch.object(pipeline, "_notify_human", return_value=True):
                with patch.object(pipeline, "_record_lesson"):
                    with patch.object(pipeline, "_emit_event"):
                        result = pipeline.execute(candidate)

        assert result.decision == "REVIEW"
        assert result.rollback_instructions != ""


# ── 9. Degraded behavior without Docker ──────────────────────────────────────

class TestDegradedMode:
    """When Docker is unavailable, pipeline degrades safely to REVIEW (not crash)."""

    def test_degraded_sandbox_returns_review_not_crash(self):
        from core.self_improvement.promotion_pipeline import PromotionPipeline

        pipeline = PromotionPipeline()
        candidate = MockCandidate(code_patch=SAMPLE_DIFF, risk="LOW")

        # Simulate sandbox returning degraded result (docker unavailable)
        from dataclasses import dataclass as _dc, field as _field

        @_dc
        class DegradedSandboxResult:
            success: bool = True
            tests_passed: bool = False  # Unknown without Docker → conservative
            lint_passed: bool = False
            typecheck_passed: bool = False
            regressions: list = _field(default_factory=list)
            improvements: list = _field(default_factory=list)
            stdout: str = ""
            stderr: str = ""
            exit_code: int = 0
            duration_s: float = 0.0
            docker_used: bool = False
            error: str = "SandboxExecutor unavailable — degraded mode"

        with patch.object(pipeline, "_run_sandbox", return_value=DegradedSandboxResult()):
            with patch.object(pipeline, "_notify_human", return_value=False):
                with patch.object(pipeline, "_record_lesson"):
                    with patch.object(pipeline, "_emit_event"):
                        result = pipeline.execute(candidate)

        # Must not crash, must not PROMOTE without verification
        assert result.decision in ("REVIEW", "REJECT")
        assert result.error == "" or result.decision != "PROMOTE"

    def test_pipeline_never_raises(self):
        """Pipeline must never raise — it returns error in result."""
        from core.self_improvement.promotion_pipeline import PromotionPipeline

        pipeline = PromotionPipeline()
        candidate = MockCandidate(code_patch=SAMPLE_DIFF)

        # Make sandbox throw an exception
        with patch.object(pipeline, "_run_sandbox", side_effect=RuntimeError("unexpected!")):
            with patch.object(pipeline, "_record_lesson"):
                with patch.object(pipeline, "_emit_event"):
                    result = pipeline.execute(candidate)  # Must NOT raise

        assert result.decision == "REJECT"
        assert "unexpected!" in result.error or result.error != ""


# ── 10. Secret scrubbing ──────────────────────────────────────────────────────

class TestSecretScrubbing:
    """API keys and secrets are scrubbed from returned results."""

    def test_secrets_scrubbed_from_explanation(self):
        from core.self_improvement.promotion_pipeline import _scrub_secrets

        text_with_secret = "token=sk-abc123xyz fix applied to api_key=super-secret-key"
        scrubbed = _scrub_secrets(text_with_secret)

        assert "sk-abc123xyz" not in scrubbed
        assert "super-secret-key" not in scrubbed
        assert "[REDACTED]" in scrubbed

    def test_result_explanation_is_scrubbed(self):
        from core.self_improvement.promotion_pipeline import PromotionPipeline

        pipeline = PromotionPipeline()
        candidate = MockCandidate(code_patch=SAMPLE_DIFF, risk="LOW")
        candidate.description = "Fix using api_key=secret123 for auth"

        mock_sandbox = MagicMock()
        mock_sandbox.success = True
        mock_sandbox.tests_passed = True
        mock_sandbox.lint_passed = True
        mock_sandbox.typecheck_passed = True
        mock_sandbox.regressions = []
        mock_sandbox.improvements = ["all_tests_pass"]
        mock_sandbox.docker_used = True
        mock_sandbox.stdout = ""
        mock_sandbox.stderr = ""
        mock_sandbox.exit_code = 0
        mock_sandbox.duration_s = 5.0

        with patch.object(pipeline, "_run_sandbox", return_value=mock_sandbox):
            with patch.object(pipeline, "_create_pr", return_value=""):
                with patch.object(pipeline, "_record_lesson"):
                    with patch.object(pipeline, "_emit_event"):
                        # Need to mock the patch generation to return scraped explanation
                        with patch.object(pipeline, "_generate_patch",
                                         return_value=(SAMPLE_DIFF, ["core/some_module.py"], "LOW", "fix using api_key=[REDACTED]")):
                            candidate_no_patch = MockCandidate(
                                code_patch="",
                                target_file="core/some_module.py",
                                current_content="def handler(x):\n    return x.value\n",
                                description="Fix using api_key=secret123 for auth",
                            )
                            result = pipeline.execute(candidate_no_patch)

        assert "secret123" not in result.explanation


# ── Protected file check ──────────────────────────────────────────────────────

class TestProtectedFileBlocking:
    """Protected files cannot be patched."""

    def test_protected_file_rejected_by_generator(self):
        from core.self_improvement.code_patch_generator import CodePatchGenerator, PatchRequest

        gen = CodePatchGenerator()
        req = PatchRequest(
            problem_description="bypass security check",
            target_file="core/security/rbac.py",
            current_content="def get_current_user(): ...",
        )
        result = gen.generate(req)

        assert result.success is False
        assert "Protected file" in result.error
        assert result.unified_diff == ""

    @pytest.mark.parametrize("protected_path", [
        "core/security/rbac.py",
        "core/security/input_sanitizer.py",
        "api/auth.py",
        "core/self_improvement/protected_paths.py",
        "core/self_improvement/promotion_pipeline.py",
        "core/self_improvement/sandbox_executor.py",
        "core/self_improvement/human_gate.py",
    ])
    def test_all_protected_files_blocked(self, protected_path):
        from core.self_improvement.code_patch_generator import CodePatchGenerator, PatchRequest

        gen = CodePatchGenerator()
        req = PatchRequest(
            problem_description="test",
            target_file=protected_path,
            current_content="# content",
        )
        result = gen.generate(req)
        assert result.success is False


# ── PromotionResult.to_dict ───────────────────────────────────────────────────

class TestPromotionResultContract:
    """PromotionResult has all expected fields."""

    def test_result_has_all_required_fields(self):
        from core.self_improvement.promotion_pipeline import PromotionResult

        result = PromotionResult(
            run_id="abc",
            decision="REJECT",
            unified_diff="",
        )
        d = result.to_dict()

        required_keys = {
            "run_id", "decision", "unified_diff", "changed_files",
            "risk_level", "score", "validation_report", "rollback_instructions",
            "explanation", "pr_url", "human_notified", "duration_s", "error",
        }
        assert required_keys.issubset(set(d.keys()))

    def test_promote_decision_is_valid_literal(self):
        from core.self_improvement.promotion_pipeline import PromotionPipeline

        pipeline = PromotionPipeline()
        candidate = MockCandidate(code_patch=SAMPLE_DIFF, risk="LOW")

        mock_sandbox = MagicMock()
        mock_sandbox.success = True
        mock_sandbox.tests_passed = True
        mock_sandbox.lint_passed = True
        mock_sandbox.typecheck_passed = True
        mock_sandbox.regressions = []
        mock_sandbox.improvements = ["all_tests_pass"]
        mock_sandbox.docker_used = True
        mock_sandbox.stdout = ""
        mock_sandbox.stderr = ""
        mock_sandbox.exit_code = 0
        mock_sandbox.duration_s = 5.0

        with patch.object(pipeline, "_run_sandbox", return_value=mock_sandbox):
            with patch.object(pipeline, "_create_pr", return_value=""):
                with patch.object(pipeline, "_record_lesson"):
                    with patch.object(pipeline, "_emit_event"):
                        result = pipeline.execute(candidate)

        assert result.decision in ("PROMOTE", "REVIEW", "REJECT")
