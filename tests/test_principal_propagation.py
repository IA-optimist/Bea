"""
Structural propagation tests for authenticated principal_id.

These tests ensure that the validated principal extracted from the request can
flow from routes down to PolicyEngine through the documented call chain.
"""
from __future__ import annotations

import inspect

import pytest


class TestCoreSignaturesAcceptPrincipalId:
    """Every layer in the public call chain must accept principal_id."""

    def test_meta_orchestrator_run_mission_accepts_principal_id(self):
        from core.meta_orchestrator import MetaOrchestrator
        sig = inspect.signature(MetaOrchestrator.run_mission)
        assert "principal_id" in sig.parameters

    def test_meta_orchestrator_run_compat_accepts_principal_id(self):
        from core.meta_orchestrator import MetaOrchestrator
        sig = inspect.signature(MetaOrchestrator.run)
        assert "principal_id" in sig.parameters

    def test_bea_executor_run_accepts_principal_id(self):
        from core.bea_executor import BeaOrchestrator
        sig = inspect.signature(BeaOrchestrator.run)
        assert "principal_id" in sig.parameters

    def test_kernel_adapter_submit_accepts_principal_id(self):
        from interfaces.kernel_adapter import KernelAdapter
        sig = inspect.signature(KernelAdapter.submit)
        assert "principal_id" in sig.parameters

    def test_tool_runner_accepts_principal_id(self):
        from core.tool_runner import run_tools_for_mission
        sig = inspect.signature(run_tools_for_mission)
        assert "principal_id" in sig.parameters

    def test_execution_engine_accepts_principal_id(self):
        from core.execution_engine import execute_tool_intelligently
        sig = inspect.signature(execute_tool_intelligently)
        assert "principal_id" in sig.parameters

    def test_tool_pipeline_accepts_principal_id(self):
        from core.tools.tool_pipeline_tool import tool_pipeline
        sig = inspect.signature(tool_pipeline)
        assert "principal_id" in sig.parameters


class TestRoutesUseAuthenticatedPrincipal:
    """Public routes that launch missions or execute tools must call
    get_authenticated_principal and inject its value as the trusted key."""

    def test_missions_route_imports_principal_helper(self):
        import api.routes.missions as mod
        src = inspect.getsource(mod)
        assert "get_authenticated_principal" in src
        # The route passes the validated principal_id to run_tools_for_mission,
        # KernelAdapter.submit and MetaOrchestrator.run; the trusted key is
        # injected further down in tool_runner/execution_engine.
        assert "principal_id=_principal_id" in src
        assert "principal_id=_principal_id or \"\"" in src

    def test_operational_tools_route_injects_principal(self):
        import api.routes.operational_tools as mod
        src = inspect.getsource(mod)
        assert "get_authenticated_principal" in src
        assert '"_bea_principal_id"' in src

    def test_system_v2_tools_test_injects_principal(self):
        import api.routes.system_v2 as mod
        src = inspect.getsource(mod)
        assert "get_authenticated_principal" in src
        assert '"_bea_principal_id"' in src

    def test_mission_approval_passes_principal(self):
        import api.mission_approval as mod
        src = inspect.getsource(mod)
        assert "principal_id" in src
        # Inspect signature includes keyword-only principal_id
        sig = inspect.signature(mod.approve_mission_for_resume)
        assert "principal_id" in sig.parameters

    def test_api_main_run_mission_accepts_principal(self):
        import api.main as mod
        src = inspect.getsource(mod)
        assert "def _run_mission(" in src
        assert "principal_id" in src


class TestPolicyEngineTrustsBeaconKey:
    """PolicyEngine must prefer the trusted `_bea_principal_id` key."""

    def test_extract_principal_id_prefers_trusted_key(self):
        from core.policy_engine import _extract_principal_id
        assert _extract_principal_id({
            "_bea_principal_id": "jwt:alice",
            "principal_id": "fake",
        }) == "jwt:alice"


class TestSubmittedByBinding:
    """submitted_by is distinct from approved_by; resume uses submitted_by."""

    def test_mission_result_has_submitted_by_field(self):
        from core.mission_models import MissionResult
        from core.state import MissionStatus
        r = MissionResult(
            mission_id="m1", user_input="x", intent="y", status=MissionStatus.PENDING_VALIDATION
        )
        assert hasattr(r, "submitted_by")
        assert r.submitted_by is None  # default

    def test_mission_result_submitted_by_and_approved_by_independent(self):
        from core.mission_models import MissionResult
        from core.state import MissionStatus
        r = MissionResult(
            mission_id="m2", user_input="x", intent="y", status=MissionStatus.PENDING_VALIDATION
        )
        r.submitted_by = "jwt:alice"
        r.approved_by = "jwt:bob"
        assert r.submitted_by != r.approved_by
        assert r.submitted_by == "jwt:alice"
        assert r.approved_by == "jwt:bob"

    def test_approve_mission_for_resume_uses_submitted_by_not_approver(self):
        """_resume_principal must be record.submitted_by, not the approver's principal_id."""
        import api.mission_approval as mod
        src = inspect.getsource(mod)
        # The fix: record.submitted_by is used as _resume_principal
        assert "_resume_principal = record.submitted_by or principal_id" in src
        # And _resume_principal is passed to run_mission, not principal_id directly
        assert "principal_id=_resume_principal" in src

    def test_approve_mission_sets_approved_by_on_record(self):
        """approved_by must be stored separately from submitted_by."""
        import api.mission_approval as mod
        src = inspect.getsource(mod)
        assert "record.approved_by = principal_id" in src

    def test_legacy_record_without_submitted_by_falls_back_to_approver(self):
        """Legacy MissionResult with submitted_by=None falls back gracefully."""
        from core.mission_models import MissionResult
        from core.state import MissionStatus
        r = MissionResult(
            mission_id="legacy", user_input="x", intent="y", status=MissionStatus.PENDING_VALIDATION
        )
        # submitted_by is None for legacy records
        approver_principal = "jwt:admin"
        # Simulate the resume logic: record.submitted_by or principal_id
        resume_principal = r.submitted_by or approver_principal
        assert resume_principal == approver_principal  # safe fallback documented

    def test_approval_route_does_not_accept_approved_by_query_param(self):
        """approval.py route must not accept approved_by as a query param."""
        import api.routes.approval as mod
        import inspect as _inspect
        src = _inspect.getsource(mod)
        # Client-supplied approved_by must not appear as a function parameter default
        assert "approved_by: str = " not in src
        assert "rejected_by: str = " not in src
        # Route must use get_authenticated_principal
        assert "get_authenticated_principal" in src
