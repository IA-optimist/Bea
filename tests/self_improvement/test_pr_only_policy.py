"""Self-improvement PR-only policy tests."""
from __future__ import annotations

from types import SimpleNamespace

from core.self_improvement.promotion_pipeline import CandidatePatch, PatchIntent, PromotionPipeline
from core.self_improvement.protected_paths import is_protected


def test_protected_paths_block_kernel_files() -> None:
    assert is_protected("kernel/improvement/gate.py")
    assert is_protected("core/security/secret_vault.py")
    assert is_protected("api/auth.py")
    assert is_protected(".env")


def test_self_improvement_guardrails_are_protected() -> None:
    assert is_protected("core/self_improvement/promotion_pipeline.py")
    assert is_protected("core/self_improvement/protected_paths.py")
    assert is_protected("core/self_improvement/patch_signature.py")
    assert is_protected("core/self_improvement/git_agent.py")
    assert is_protected("core/self_improvement/sandbox_executor.py")
    assert is_protected("scripts/validate_local.py")
    assert is_protected(".github/workflows/ci.yml")
    assert is_protected("deploy/something.yml")
    assert is_protected("api/auth.py")
    assert is_protected("kernel/runtime/boot.py")


def test_non_protected_paths_are_allowed() -> None:
    assert not is_protected("core/coding_agent/repo_map.py")
    assert not is_protected("business/automation/opportunity_scanner.py")
    assert not is_protected("core/coding_agent/new_helper.py")


def test_pipeline_rejects_protected_file_intent() -> None:
    candidate = CandidatePatch(
        patch_id="test-protected",
        intents=[PatchIntent(file_path="kernel/improvement/gate.py", old_text="x", new_text="y")],
    )
    pipeline = PromotionPipeline()
    decision = pipeline._execute_intents_pipeline(candidate)

    assert decision.decision == "REJECT"
    assert "Protected file" in decision.reason


def test_pipeline_rejects_auth_file_intent() -> None:
    candidate = CandidatePatch(
        patch_id="test-auth",
        intents=[PatchIntent(file_path="api/auth.py", old_text="x", new_text="y")],
    )
    pipeline = PromotionPipeline()
    decision = pipeline._execute_intents_pipeline(candidate)

    assert decision.decision == "REJECT"
    assert "Protected file" in decision.reason


def test_pr_only_policy_does_not_auto_merge_protected_paths() -> None:
    risky = CandidatePatch(
        patch_id="risky",
        intents=[PatchIntent(file_path="core/security/secret_policy.py", old_text="x", new_text="y")],
    )
    pipeline = PromotionPipeline()
    decision = pipeline._execute_intents_pipeline(risky)

    assert decision.decision != "PROMOTE"


def test_unsigned_patch_cannot_promote_in_merge_mode(monkeypatch) -> None:
    monkeypatch.setenv("BEA_IMPROVEMENT_MODE", "merge")
    monkeypatch.delenv("BEA_PATCH_VERIFY_KEY", raising=False)
    pipeline = PromotionPipeline()
    sandbox_result = SimpleNamespace(success=True, tests_passed=True, regressions=[])
    candidate = CandidatePatch(
        patch_id="unsigned",
        intents=[PatchIntent(file_path="core/coding_agent/repo_map.py", old_text="x", new_text="y")],
    )

    decision = pipeline._decide(sandbox_result, "LOW", 0.95, "CODE_PATCH", candidate=candidate)

    assert decision != "PROMOTE"


def test_protected_patch_cannot_promote_at_decision_stage(monkeypatch) -> None:
    monkeypatch.setenv("BEA_IMPROVEMENT_MODE", "merge")
    pipeline = PromotionPipeline()
    sandbox_result = SimpleNamespace(success=True, tests_passed=True, regressions=[])
    candidate = CandidatePatch(
        patch_id="protected",
        intents=[PatchIntent(file_path="core/self_improvement/protected_paths.py", old_text="x", new_text="y")],
    )

    decision = pipeline._decide(sandbox_result, "LOW", 0.95, "CODE_PATCH", candidate=candidate)

    assert decision in ("REVIEW", "REJECT")


def test_legacy_changed_files_protected_patch_cannot_promote(monkeypatch) -> None:
    monkeypatch.delenv("BEA_IMPROVEMENT_MODE", raising=False)
    monkeypatch.delenv("BEA_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("BEA_REQUIRE_PATCH_SIGNATURE", raising=False)
    pipeline = PromotionPipeline()
    sandbox_result = SimpleNamespace(success=True, tests_passed=True, regressions=[])
    candidate = SimpleNamespace(changed_files=["kernel/runtime/boot.py"])

    decision = pipeline._decide(sandbox_result, "LOW", 0.95, "CODE_PATCH", candidate=candidate)

    assert decision in ("REVIEW", "REJECT")
