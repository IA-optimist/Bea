"""Self-improvement PR-only policy tests."""
from __future__ import annotations

from core.self_improvement.promotion_pipeline import CandidatePatch, PatchIntent, PromotionPipeline
from core.self_improvement.protected_paths import is_protected


def test_protected_paths_block_kernel_files() -> None:
    assert is_protected("kernel/improvement/gate.py")
    assert is_protected("core/security/secret_vault.py")
    assert is_protected("api/auth.py")
    assert is_protected(".env")


def test_non_protected_paths_are_allowed() -> None:
    assert not is_protected("core/coding_agent/repo_map.py")
    assert not is_protected("business/automation/opportunity_scanner.py")


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
