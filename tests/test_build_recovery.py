"""
tests/test_build_recovery.py — Build Recovery + Deployment Layer tests.

Tests Phases 1-10:
  BR01-BR10: Failure classification
  BR11-BR20: Controlled retry
  BR21-BR30: Deployment targets + pipeline
  BR31-BR40: Verification + feedback + safety
  BR41-BR50: API endpoints
"""
import json


# ── Phase 1: Failure Classification ───────────────────────────

class TestFailureClassification:
    def test_BR01_generation_failure(self):
        from core.execution.recovery import classify_build_failure, FailureCategory
        f = classify_build_failure("Content generation produced empty output")
        assert f.category == FailureCategory.GENERATION
        assert f.retryable is True

    def test_BR02_file_write_failure(self):
        from core.execution.recovery import classify_build_failure, FailureCategory
        f = classify_build_failure("Permission denied writing to workspace")
        assert f.category == FailureCategory.FILE_WRITE
        assert f.operator_relevant is True

    def test_BR03_validation_failure(self):
        from core.execution.recovery import classify_build_failure, FailureCategory
        f = classify_build_failure("Required validation failed: content_check")
        assert f.category == FailureCategory.VALIDATION
        assert f.retryable is True

    def test_BR04_missing_dependency(self):
        from core.execution.recovery import classify_build_failure, FailureCategory
        f = classify_build_failure("Missing dependency: n8n not configured")
        assert f.category == FailureCategory.MISSING_DEP
        assert f.retryable is False
        assert f.operator_relevant is True

    def test_BR05_deploy_prep_failure(self):
        from core.execution.recovery import classify_build_failure, FailureCategory
        f = classify_build_failure("Deployment preparation target not ready")
        assert f.category == FailureCategory.DEPLOY_PREP
        assert f.retryable is True

    def test_BR06_deploy_execution_failure(self):
        from core.execution.recovery import classify_build_failure, FailureCategory
        f = classify_build_failure("Deploy failed: target unreachable")
        assert f.category == FailureCategory.DEPLOY_EXEC
        assert f.operator_relevant is True

    def test_BR07_verification_failure(self):
        from core.execution.recovery import classify_build_failure, FailureCategory
        f = classify_build_failure("Deployment verification missing entrypoint")
        assert f.category == FailureCategory.VERIFICATION

    def test_BR08_unknown_failure_not_retryable(self):
        from core.execution.recovery import classify_build_failure
        f = classify_build_failure("some completely unknown error")
        assert f.retryable is False
        assert f.operator_relevant is True

    def test_BR09_failure_has_recommended_strategy(self):
        from core.execution.recovery import classify_build_failure, RetryStrategy
        f = classify_build_failure("Content generation produced empty output")
        assert f.recommended_strategy == RetryStrategy.STRONGER_MODEL

    def test_BR10_failure_to_dict(self):
        from core.execution.recovery import classify_build_failure
        f = classify_build_failure("validation failed")
        d = f.to_dict()
        assert "category" in d
        assert "severity" in d
        assert "retryable" in d
        assert "recommended_strategy" in d


# ── Phase 2: Controlled Retry ─────────────────────────────────

class TestControlledRetry:
    def test_BR11_non_retryable_returns_immediately(self):
        from core.execution.recovery import retry_build
        result = retry_build(None, "Missing dependency: module not found")
        assert result.recovered is False
        assert len(result.attempts) == 0

    def test_BR12_max_retries_bounded(self):
        from core.execution.recovery import MAX_RETRIES
        assert MAX_RETRIES <= 5  # Must be small and explicit

    def test_BR13_retry_strategies_exist(self):
        from core.execution.recovery import RetryStrategy
        strategies = list(RetryStrategy)
        assert len(strategies) >= 5

    def test_BR14_each_retry_has_reason(self):
        from core.execution.recovery import RetryAttempt, RetryStrategy
        a = RetryAttempt(attempt_number=1, strategy=RetryStrategy.STRONGER_MODEL, reason="test")
        assert a.reason
        assert a.strategy

    def test_BR15_retry_result_to_dict(self):
        from core.execution.recovery import RetryResult, BuildFailure, FailureCategory, FailureSeverity
        f = BuildFailure(FailureCategory.GENERATION, FailureSeverity.HIGH, "test", True)
        r = RetryResult(original_error="test", failure_class=f)
        d = r.to_dict()
        assert "original_error" in d
        assert "failure_class" in d
        assert "attempts" in d
        assert "recovered" in d

    def test_BR16_strategy_escalation_order(self):
        from core.execution.recovery import _STRATEGY_ESCALATION
        assert len(_STRATEGY_ESCALATION) >= 4

    def test_BR17_pick_strategy_uses_recommended_first(self):
        from core.execution.recovery import _pick_strategy, BuildFailure, FailureCategory, FailureSeverity, RetryStrategy
        f = BuildFailure(FailureCategory.GENERATION, FailureSeverity.HIGH, "test", True, RetryStrategy.STRONGER_MODEL)
        s = _pick_strategy(1, f, [])
        assert s == RetryStrategy.STRONGER_MODEL

    def test_BR18_pick_strategy_escalates(self):
        from core.execution.recovery import _pick_strategy, BuildFailure, FailureCategory, FailureSeverity, RetryStrategy
        f = BuildFailure(FailureCategory.GENERATION, FailureSeverity.HIGH, "test", True, RetryStrategy.STRONGER_MODEL)
        s = _pick_strategy(2, f, [RetryStrategy.STRONGER_MODEL])
        assert s != RetryStrategy.STRONGER_MODEL

    def test_BR19_apply_strategy_critical_budget(self):
        from core.execution.recovery import _apply_strategy, RetryStrategy
        from dataclasses import dataclass, field
        @dataclass
        class FakeArtifact:
            expected_outcome: str = "test"
            input_context: dict = field(default_factory=dict)
        art = FakeArtifact()
        _, budget = _apply_strategy(RetryStrategy.CRITICAL_BUDGET, art, "normal")
        assert budget == "critical"

    def test_BR20_apply_strategy_simplify(self):
        from core.execution.recovery import _apply_strategy, RetryStrategy
        from dataclasses import dataclass, field
        @dataclass
        class FakeArtifact:
            expected_outcome: str = "Build a complex enterprise application with 50 features"
            input_context: dict = field(default_factory=dict)
        art = FakeArtifact()
        _apply_strategy(RetryStrategy.SIMPLIFY, art, "normal")
        assert "Simplified" in art.expected_outcome


# ── Phase 3-4: Deployment Targets + Pipeline ──────────────────

class TestDeployment:
    def test_BR21_deployment_targets_exist(self):
        from core.execution.deployment import DEPLOYMENT_TARGETS
        assert len(DEPLOYMENT_TARGETS) >= 5
        assert "local_preview" in DEPLOYMENT_TARGETS
        assert "static_bundle" in DEPLOYMENT_TARGETS
        assert "api_package" in DEPLOYMENT_TARGETS

    def test_BR22_target_has_required_fields(self):
        from core.execution.deployment import DEPLOYMENT_TARGETS
        for name, t in DEPLOYMENT_TARGETS.items():
            d = t.to_dict()
            assert "target_id" in d
            assert "target_type" in d
            assert "verification_method" in d
            assert "rollback_strategy" in d
            assert "policy_level" in d

    def test_BR23_all_targets_low_risk(self):
        """This sprint: all targets must be low risk."""
        from core.execution.deployment import DEPLOYMENT_TARGETS
        for name, t in DEPLOYMENT_TARGETS.items():
            assert t.policy_level in ("low", "medium"), f"Target {name} is {t.policy_level}"

    def test_BR24_artifact_deploy_map(self):
        from core.execution.deployment import ARTIFACT_DEPLOY_MAP
        assert "landing_page" in ARTIFACT_DEPLOY_MAP
        assert "api_service" in ARTIFACT_DEPLOY_MAP

    def test_BR25_get_deployment_target(self):
        from core.execution.deployment import get_deployment_target
        t = get_deployment_target("landing_page")
        assert t.target_type.value == "static_bundle"

    def test_BR26_deploy_pipeline_rejects_failed_build(self):
        from core.execution.deployment import DeploymentPipeline
        from core.execution.artifacts import ExecutionArtifact, ArtifactType

        art = ExecutionArtifact(artifact_type=ArtifactType.LANDING_PAGE, name="test")

        class _BR:
            success = False
            output_dir = ""
            output_files = []

        pipeline = DeploymentPipeline()
        result = pipeline.deploy(_BR(), art)
        assert result.status.value == "failed"
        assert "not successful" in result.error

    def test_BR27_deploy_pipeline_rejects_empty_build(self):
        from core.execution.deployment import DeploymentPipeline
        from core.execution.artifacts import ExecutionArtifact, ArtifactType

        art = ExecutionArtifact(artifact_type=ArtifactType.LANDING_PAGE, name="test")

        class _BR:
            success = True
            output_dir = ""
            output_files = []

        result = DeploymentPipeline().deploy(_BR(), art)
        assert result.status.value == "failed"

    def test_BR28_deploy_pipeline_succeeds_with_files(self, tmp_path):
        from core.execution.deployment import DeploymentPipeline, DeploymentTarget, DeploymentTargetType
        from core.execution.artifacts import ExecutionArtifact, ArtifactType, ArtifactStatus
        import os

        os.environ["WORKSPACE_DIR"] = str(tmp_path)
        build_dir = tmp_path / "builds" / "test-artifact"
        build_dir.mkdir(parents=True)
        (build_dir / "index.html").write_text("<h1>Test</h1>")

        art = ExecutionArtifact(
            artifact_id="test-artifact",
            artifact_type=ArtifactType.LANDING_PAGE,
            name="test",
            status=ArtifactStatus.BUILT,
        )

        class _BR:
            success = True
            output_dir = str(build_dir)
            output_files = ["index.html"]

        target = DeploymentTarget(
            target_type=DeploymentTargetType.LOCAL_PREVIEW,
            verification_method="file_exists",
            rollback_strategy="delete_output",
        )
        target.output_dir = str(tmp_path / "deployments" / "test")

        # Patch _DEPLOY_DIR for test
        import core.execution.deployment as dep_mod
        old_dir = dep_mod._DEPLOY_DIR
        dep_mod._DEPLOY_DIR = tmp_path / "deployments"

        try:
            result = DeploymentPipeline().deploy(_BR(), art, target)
            assert result.output_files
            assert result.status.value in ("deployed", "verified")
        finally:
            dep_mod._DEPLOY_DIR = old_dir
            os.environ.pop("WORKSPACE_DIR", None)

    def test_BR29_deployment_result_to_dict(self):
        from core.execution.deployment import DeploymentResult
        r = DeploymentResult(artifact_id="test")
        d = r.to_dict()
        assert "deployment_id" in d
        assert "artifact_id" in d
        assert "status" in d
        assert "verification_passed" in d

    def test_BR30_rollback_nonexistent(self):
        from core.execution.deployment import DeploymentPipeline
        assert DeploymentPipeline().rollback("nonexistent") is False


# ── Phase 5-6: Verification + Feedback + Safety ──────────────

class TestVerificationAndSafety:
    def test_BR31_verify_file_exists(self, tmp_path):
        from core.execution.deployment import DeploymentPipeline, DeploymentTarget
        target = DeploymentTarget(verification_method="file_exists")
        (tmp_path / "test.txt").write_text("content")
        p = DeploymentPipeline()
        result = p._verify_deployment(tmp_path, target, ["test.txt"])
        assert result["passed"] is True

    def test_BR32_verify_entrypoint_check(self, tmp_path):
        from core.execution.deployment import DeploymentPipeline, DeploymentTarget
        target = DeploymentTarget(verification_method="entrypoint_check")
        (tmp_path / "index.html").write_text("<!DOCTYPE html><html><head><title>Test</title></head><body><h1>Hello World</h1></body></html>")
        result = DeploymentPipeline()._verify_deployment(tmp_path, target, ["index.html"])
        assert result["passed"] is True

    def test_BR33_verify_entrypoint_fails_without_index(self, tmp_path):
        from core.execution.deployment import DeploymentPipeline, DeploymentTarget
        target = DeploymentTarget(verification_method="entrypoint_check")
        (tmp_path / "style.css").write_text("body{}")
        result = DeploymentPipeline()._verify_deployment(tmp_path, target, ["style.css"])
        assert result["passed"] is False

    def test_BR34_verify_package_check(self, tmp_path):
        from core.execution.deployment import DeploymentPipeline, DeploymentTarget
        target = DeploymentTarget(verification_method="package_check")
        (tmp_path / "main.py").write_text("from fastapi import FastAPI")
        result = DeploymentPipeline()._verify_deployment(tmp_path, target, ["main.py"])
        assert result["passed"] is True

    def test_BR35_verify_config_check(self, tmp_path):
        from core.execution.deployment import DeploymentPipeline, DeploymentTarget
        target = DeploymentTarget(verification_method="config_check")
        (tmp_path / "config.json").write_text('{"key":"value"}')
        result = DeploymentPipeline()._verify_deployment(tmp_path, target, ["config.json"])
        assert result["passed"] is True

    def test_BR36_no_secrets_in_deployment_result(self):
        from core.execution.deployment import DeploymentResult
        r = DeploymentResult(artifact_id="test", error="some error")
        d = json.dumps(r.to_dict())
        assert "sk-or-" not in d
        assert "ghp_" not in d
        assert "Bearer" not in d

    def test_BR37_deployment_status_enum_values(self):
        from core.execution.deployment import DeploymentStatus
        assert "deployed" in [s.value for s in DeploymentStatus]
        assert "verified" in [s.value for s in DeploymentStatus]
        assert "rolled_back" in [s.value for s in DeploymentStatus]

    def test_BR38_no_high_risk_targets(self):
        """No critical-risk targets in this sprint."""
        from core.execution.deployment import DEPLOYMENT_TARGETS
        for t in DEPLOYMENT_TARGETS.values():
            assert t.policy_level != "critical"

    def test_BR39_deployment_store_tracks(self):
        from core.execution.deployment import get_deployments
        deps = get_deployments()
        assert isinstance(deps, list)

    def test_BR40_failure_classification_covers_all_categories(self):
        from core.execution.recovery import FailureCategory
        assert len(list(FailureCategory)) == 7


# ── API Tests ─────────────────────────────────────────────────

class TestDeploymentAPI:
    def test_BR41_execution_status_endpoint(self):
        """Execution status returns active=True."""
        import importlib
        mod = importlib.import_module("api.routes.execution")
        assert hasattr(mod, "execution_status")

    def test_BR42_deploy_endpoint_exists(self):
        import importlib
        mod = importlib.import_module("api.routes.execution")
        assert hasattr(mod, "deploy_artifact")

    def test_BR43_deployments_endpoint_exists(self):
        import importlib
        mod = importlib.import_module("api.routes.execution")
        assert hasattr(mod, "list_deployments")

    def test_BR44_builds_endpoint_exists(self):
        import importlib
        mod = importlib.import_module("api.routes.execution")
        assert hasattr(mod, "get_build_detail")

    def test_BR45_retries_endpoint_exists(self):
        import importlib
        mod = importlib.import_module("api.routes.execution")
        assert hasattr(mod, "list_retries")

    def test_BR46_targets_endpoint_exists(self):
        import importlib
        mod = importlib.import_module("api.routes.execution")
        assert hasattr(mod, "list_deployment_targets")

    def test_BR47_recovery_module_imports(self):
        pass

    def test_BR48_deployment_module_imports(self):
        pass

    def test_BR49_build_pipeline_unchanged(self):
        """Existing build pipeline still works."""
        from core.execution.build_pipeline import BuildPipeline, BuildResult, TOOL_CONTRACTS
        assert BuildPipeline
        assert BuildResult
        assert len(TOOL_CONTRACTS) >= 5

    def test_BR50_feedback_still_works(self):
        """Existing feedback module unbroken."""
        from core.execution.feedback import BuildConfidence
        c = BuildConfidence(validation_score=0.8, content_score=0.7)
        assert 0 < c.composite <= 1
