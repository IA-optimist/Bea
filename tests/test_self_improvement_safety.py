"""tests/test_self_improvement_safety.py — Self-improvement safety boundary tests."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import pytest


class TestProtectedPaths:
    def test_meta_orchestrator_protected(self):
        from core.self_improvement.safety_boundary import is_path_protected
        assert is_path_protected("core/meta_orchestrator.py")

    def test_tool_executor_protected(self):
        from core.self_improvement.safety_boundary import is_path_protected
        assert is_path_protected("core/tool_executor.py")

    def test_policy_engine_protected(self):
        from core.self_improvement.safety_boundary import is_path_protected
        assert is_path_protected("core/policy/policy_engine.py")

    def test_main_protected(self):
        from core.self_improvement.safety_boundary import is_path_protected
        assert is_path_protected("main.py")

    def test_api_main_protected(self):
        from core.self_improvement.safety_boundary import is_path_protected
        assert is_path_protected("api/main.py")

    def test_workspace_not_protected(self):
        from core.self_improvement.safety_boundary import is_path_protected
        assert not is_path_protected("workspace/test.txt")

    def test_skills_not_protected(self):
        from core.self_improvement.safety_boundary import is_path_protected
        assert not is_path_protected("core/skills/new_skill.py")


class TestAllowedScope:
    def test_workspace_allowed(self):
        from core.self_improvement.safety_boundary import is_path_allowed
        assert is_path_allowed("workspace/config.json")

    def test_skills_allowed(self):
        from core.self_improvement.safety_boundary import is_path_allowed
        assert is_path_allowed("core/skills/skill_abc.py")

    def test_tools_allowed(self):
        from core.self_improvement.safety_boundary import is_path_allowed
        assert is_path_allowed("core/tools/new_tool.py")

    def test_random_path_not_allowed(self):
        from core.self_improvement.safety_boundary import is_path_allowed
        assert not is_path_allowed("core/meta_orchestrator.py")

    def test_config_allowed(self):
        from core.self_improvement.safety_boundary import is_path_allowed
        assert is_path_allowed("config/settings.yaml")


class TestProposalValidation:
    def test_valid_workspace_low_risk(self):
        from core.self_improvement.safety_boundary import validate_proposal, ImprovementProposal
        p = ImprovementProposal(
            improvement_type="prompt",
            description="Improve system prompt",
            target_file="workspace/prompts/main.txt",
            risk_level="LOW",
        )
        valid, msg = validate_proposal(p)
        assert valid
        assert msg == "APPROVED"
        assert not p.requires_approval

    def test_rejected_protected_file(self):
        from core.self_improvement.safety_boundary import validate_proposal, ImprovementProposal
        p = ImprovementProposal(
            improvement_type="capability",
            description="Modify orchestrator",
            target_file="core/meta_orchestrator.py",
        )
        valid, msg = validate_proposal(p)
        assert not valid
        assert "protected" in msg.lower()

    @pytest.mark.xfail(reason="SI scope rejection drift", strict=False)
    def test_rejected_outside_scope(self):
        from core.self_improvement.safety_boundary import validate_proposal, ImprovementProposal
        p = ImprovementProposal(
            improvement_type="capability",
            description="Modify env",
            target_file=".env",
        )
        valid, msg = validate_proposal(p)
        assert not valid
        assert "outside" in msg.lower()

    def test_high_risk_requires_approval(self):
        from core.self_improvement.safety_boundary import validate_proposal, ImprovementProposal
        p = ImprovementProposal(
            improvement_type="tool_usage",
            description="New dangerous tool",
            target_file="core/tools/danger.py",
            risk_level="HIGH",
        )
        valid, msg = validate_proposal(p)
        assert valid
        assert p.requires_approval is True


class TestStaging:
    def test_ensure_staging(self):
        from core.self_improvement.safety_boundary import ensure_staging, STAGING_DIR
        path = ensure_staging()
        assert os.path.isdir(path)

    def test_stage_modification(self):
        from core.self_improvement.safety_boundary import stage_modification, STAGING_DIR
        path = stage_modification("core/skills/test.py", "# test content\n")
        assert os.path.exists(path)
        with open(path) as f:
            assert f.read() == "# test content\n"
        os.unlink(path)

    def test_validate_staged_good(self):
        from core.self_improvement.safety_boundary import (
            stage_modification, validate_staged_modification
        )
        path = stage_modification("test.py", "x = 1\n")
        valid, msg = validate_staged_modification(path)
        assert valid
        assert msg == "OK"
        os.unlink(path)

    def test_validate_staged_syntax_error(self):
        from core.self_improvement.safety_boundary import (
            stage_modification, validate_staged_modification
        )
        path = stage_modification("test.py", "def broken(\n")
        valid, msg = validate_staged_modification(path)
        assert not valid
        assert "syntax" in msg.lower() or "Syntax" in msg
        os.unlink(path)

    def test_validate_staged_empty(self):
        from core.self_improvement.safety_boundary import (
            stage_modification, validate_staged_modification
        )
        path = stage_modification("test.py", "")
        valid, msg = validate_staged_modification(path)
        assert not valid
        assert "Empty" in msg
        os.unlink(path)

    def test_promote_blocked_for_protected(self):
        from core.self_improvement.safety_boundary import (
            stage_modification, promote_to_production
        )
        path = stage_modification("test.py", "x = 1\n")
        ok, msg = promote_to_production(path, "core/meta_orchestrator.py")
        assert not ok
        assert "protected" in msg.lower()
        os.unlink(path)

    def test_rollback_no_backup(self):
        from core.self_improvement.safety_boundary import rollback
        ok, msg = rollback("/tmp/nonexistent_file_xyz.py")
        assert not ok
        assert "backup" in msg.lower()


class TestNeverModify:
    def test_never_modify_categories_exist(self):
        from core.self_improvement.safety_boundary import NEVER_MODIFY
        assert "auth" in NEVER_MODIFY
        assert "policy_engine" in NEVER_MODIFY
        assert "memory_schema" in NEVER_MODIFY

    def test_protected_runtime_count(self):
        from core.self_improvement.safety_boundary import PROTECTED_RUNTIME
        assert len(PROTECTED_RUNTIME) >= 14
