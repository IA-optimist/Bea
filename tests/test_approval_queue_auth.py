"""
Tests for approval_queue authentication — approved_by/rejected_by must come
from the authenticated principal, never from client-supplied fields.
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from typing import Any
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(user: dict[str, Any] | None = None) -> MagicMock:
    """Build a minimal FastAPI Request mock with request.state.user set."""
    req = MagicMock()
    req.state = MagicMock()
    req.state.user = user
    return req


def _stub_item(item_id: str = "item-abc") -> dict:
    return {
        "id": item_id,
        "action": "test-action",
        "risk_level": "write_high",
        "reason": "test",
        "expected_impact": "none",
        "rollback_plan": "revert",
        "source": "test",
        "payload": {},
        "status": "pending",
        "submitted_at": "2026-01-01T00:00:00+00:00",
        "approved_at": None,
        "approved_by": None,
    }


# ---------------------------------------------------------------------------
# 1. approve() stores the supplied principal (not "human")
# ---------------------------------------------------------------------------
class TestApproveUsesSuppliedPrincipal(unittest.TestCase):
    def test_approve_uses_authenticated_principal(self):
        """approval_queue.approve() must record the principal passed by the route."""
        from core.approval_queue import approve

        item_id = "test-approve-principal"
        item = _stub_item(item_id)

        with tempfile.TemporaryDirectory() as tmp:
            queue_path = pathlib.Path(tmp) / "pending.json"
            queue_path.write_text(json.dumps([item]), encoding="utf-8")

            with patch("core.approval_queue.QUEUE_PATH", queue_path):
                result = approve(item_id, approved_by="jwt:alice")

            saved = json.loads(queue_path.read_text())
            assert result is True
            assert saved[0]["approved_by"] == "jwt:alice", (
                f"Expected 'jwt:alice', got {saved[0]['approved_by']!r}"
            )
            assert saved[0]["approved_by"] != "human"


# ---------------------------------------------------------------------------
# 2. reject() stores the supplied principal (not "human")
# ---------------------------------------------------------------------------
class TestRejectUsesSuppliedPrincipal(unittest.TestCase):
    def test_reject_uses_authenticated_principal(self):
        """approval_queue.reject() must record the principal passed by the route."""
        from core.approval_queue import reject

        item_id = "test-reject-principal"
        item = _stub_item(item_id)

        with tempfile.TemporaryDirectory() as tmp:
            queue_path = pathlib.Path(tmp) / "pending.json"
            queue_path.write_text(json.dumps([item]), encoding="utf-8")

            with patch("core.approval_queue.QUEUE_PATH", queue_path):
                result = reject(item_id, rejected_by="jwt:bob")

            saved = json.loads(queue_path.read_text())
            assert result is True
            assert saved[0]["rejected_by"] == "jwt:bob", (
                f"Expected 'jwt:bob', got {saved[0]['rejected_by']!r}"
            )
            assert saved[0]["rejected_by"] != "human"


# ---------------------------------------------------------------------------
# 3. Client cannot override approved_by via body/query
# ---------------------------------------------------------------------------
class TestClientApprovedByIgnored(unittest.TestCase):
    def test_client_approved_by_ignored(self):
        """The approval route must not accept approved_by from client payload."""
        # The route signature for /approval/approve/{item_id} must not have
        # approved_by as a body/query param.
        import inspect
        from api.routes.approval import approve_action

        sig = inspect.signature(approve_action)
        param_names = list(sig.parameters.keys())
        assert "approved_by" not in param_names, (
            f"approved_by must NOT be a route parameter; got params: {param_names}"
        )
        assert "rejected_by" not in param_names, (
            f"rejected_by must NOT be a route parameter; got params: {param_names}"
        )

    def test_reject_route_no_client_rejected_by(self):
        """The reject route must not accept rejected_by from client payload."""
        import inspect
        from api.routes.missions import reject_mission

        sig = inspect.signature(reject_mission)
        param_names = list(sig.parameters.keys())
        assert "rejected_by" not in param_names, (
            f"rejected_by must NOT be a route parameter; got params: {param_names}"
        )


# ---------------------------------------------------------------------------
# 4. Route extracts principal from auth context, not from client
# ---------------------------------------------------------------------------
class TestRoutePrincipalFromAuth(unittest.TestCase):
    def test_approve_route_uses_get_authenticated_principal(self):
        """approve_action route must call get_authenticated_principal(request)."""
        import ast
        import inspect
        import textwrap
        from api.routes.approval import approve_action

        src = textwrap.dedent(inspect.getsource(approve_action))
        tree = ast.parse(src)
        calls = [
            node.func.id if isinstance(node.func, ast.Name) else
            (node.func.attr if isinstance(node.func, ast.Attribute) else "")
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        ]
        assert "get_authenticated_principal" in calls, (
            "approve_action must call get_authenticated_principal()"
        )

    def test_reject_route_uses_get_authenticated_principal(self):
        """reject_mission route must call get_authenticated_principal(request)."""
        import ast
        import inspect
        import textwrap
        from api.routes.missions import reject_mission

        src = textwrap.dedent(inspect.getsource(reject_mission))
        tree = ast.parse(src)
        calls = [
            node.func.id if isinstance(node.func, ast.Name) else
            (node.func.attr if isinstance(node.func, ast.Attribute) else "")
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        ]
        assert "get_authenticated_principal" in calls, (
            "reject_mission must call get_authenticated_principal()"
        )


# ---------------------------------------------------------------------------
# 5. approved_by != submitted_by allowed, does not change execution identity
# ---------------------------------------------------------------------------
class TestApprovedByNotEqualsSubmittedBy(unittest.TestCase):
    def test_approved_by_distinct_from_submitted_by(self):
        """approved_by and submitted_by are distinct; reprise uses submitted_by."""
        from api.mission_approval import approve_mission_for_resume

        # Verify the function signature accepts both principal_id (approver)
        # and that the resume uses record.submitted_by
        import inspect
        src = inspect.getsource(approve_mission_for_resume)

        # The resume must use record.submitted_by, not principal_id directly
        assert "record.submitted_by" in src, (
            "approve_mission_for_resume must use record.submitted_by for resume principal"
        )
        assert "_resume_principal" in src, (
            "approve_mission_for_resume must bind _resume_principal from submitted_by"
        )
        # approved_by stored on record for audit only
        assert "record.approved_by = principal_id" in src or "approved_by=principal_id" in src, (
            "approved_by must be stored on record (audit) — NOT used for execution"
        )

    def test_approve_queue_uses_approver_not_submitter(self):
        """In approve_mission_for_resume, approval_queue item is stamped with approver principal."""
        import inspect
        from api.mission_approval import approve_mission_for_resume
        src = inspect.getsource(approve_mission_for_resume)

        # The approval queue call must NOT pass "human" and must use principal_id
        assert 'approved_by="human"' not in src, (
            'approved_by="human" hardcoded must be gone from approve_mission_for_resume'
        )
        assert "approved_by=principal_id" in src or "approved_by=principal_id or" in src, (
            "approve_mission_for_resume must pass principal_id to approval_queue.approve()"
        )


# ---------------------------------------------------------------------------
# 6. Legacy record (submitted_by=None) handled gracefully
# ---------------------------------------------------------------------------
class TestLegacyApprovalRecord(unittest.TestCase):
    def test_legacy_record_no_submitted_by_falls_back_to_approver(self):
        """A record without submitted_by falls back to the approver's principal."""
        import inspect
        from api.mission_approval import approve_mission_for_resume

        src = inspect.getsource(approve_mission_for_resume)
        # Verify the or-fallback pattern
        assert "record.submitted_by or principal_id" in src, (
            "Legacy fallback 'record.submitted_by or principal_id' must be present"
        )


# ---------------------------------------------------------------------------
# 7. reject_mission_payload hardcoded check
# ---------------------------------------------------------------------------
class TestRejectMissionPayloadNoPrincipal(unittest.TestCase):
    def test_reject_mission_payload_no_hardcoded_human(self):
        """reject_mission_payload must not have hardcoded rejected_by='human'."""
        import inspect
        from api.mission_approval import reject_mission_payload

        src = inspect.getsource(reject_mission_payload)
        assert 'rejected_by="human"' not in src, (
            'rejected_by="human" must be removed from reject_mission_payload'
        )
        assert "'human'" not in src or "rejected_by" not in src.split("'human'")[0].split("\n")[-1], (
            "No hardcoded 'human' for rejected_by"
        )

    def test_reject_mission_payload_has_rejected_by_param(self):
        """reject_mission_payload must accept rejected_by parameter."""
        import inspect
        from api.mission_approval import reject_mission_payload

        sig = inspect.signature(reject_mission_payload)
        assert "rejected_by" in sig.parameters, (
            "reject_mission_payload must have rejected_by parameter"
        )


if __name__ == "__main__":
    unittest.main()
