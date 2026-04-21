"""
Unit tests for core.approval_queue.

Covers the submit → approve/reject lifecycle, auto-approval of low-risk
actions, deduplication, and persistence across load() calls.

Uses tmp_path to redirect the queue file per-test, avoiding pollution
of the real workspace/approval_queue/pending.json.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import core.approval_queue as aq


class TestApprovalQueue(unittest.TestCase):
    def setUp(self):
        # Redirect the queue file to a fresh tmpdir path per test
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self._queue_path = Path(self._tmp.name) / "pending.json"
        self._patch = patch.object(aq, "QUEUE_PATH", self._queue_path)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def _submit(self, action="test action", risk=aq.RiskLevel.WRITE_HIGH, reason="r"):
        return aq.submit_for_approval(
            action=action,
            risk_level=risk,
            reason=reason,
            expected_impact="none",
            rollback_plan="revert",
            source="test",
        )

    def test_auto_approve_read(self):
        r = self._submit(risk=aq.RiskLevel.READ)
        self.assertTrue(r["approved"])
        self.assertTrue(r["auto"])
        self.assertIsNone(r["item_id"])

    def test_auto_approve_write_low(self):
        r = self._submit(risk=aq.RiskLevel.WRITE_LOW)
        self.assertTrue(r["approved"])
        self.assertTrue(r["auto"])

    def test_write_high_requires_approval(self):
        r = self._submit(risk=aq.RiskLevel.WRITE_HIGH)
        self.assertFalse(r["approved"])
        self.assertTrue(r["pending"])
        self.assertIsNotNone(r["item_id"])

    def test_infra_requires_approval(self):
        r = self._submit(risk=aq.RiskLevel.INFRA)
        self.assertTrue(r["pending"])

    def test_delete_requires_approval(self):
        r = self._submit(risk=aq.RiskLevel.DELETE)
        self.assertTrue(r["pending"])

    def test_deploy_requires_approval(self):
        r = self._submit(risk=aq.RiskLevel.DEPLOY)
        self.assertTrue(r["pending"])

    def test_approve_existing_item(self):
        r = self._submit()
        item_id = r["item_id"]
        self.assertTrue(aq.approve(item_id, approved_by="unit-test"))
        self.assertTrue(aq.is_approved(item_id))

    def test_approve_unknown_item(self):
        self.assertFalse(aq.approve("does-not-exist"))

    def test_reject_existing_item(self):
        r = self._submit()
        item_id = r["item_id"]
        self.assertTrue(aq.reject(item_id, rejected_by="unit-test"))
        # Rejected is not approved
        self.assertFalse(aq.is_approved(item_id))

    def test_get_pending_only_returns_pending(self):
        r1 = self._submit(action="a1")
        r2 = self._submit(action="a2")
        aq.approve(r1["item_id"])
        pending = aq.get_pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["id"], r2["item_id"])

    def test_dedup_same_action_risk(self):
        r1 = self._submit(action="same-action", risk=aq.RiskLevel.WRITE_HIGH)
        r2 = self._submit(action="same-action", risk=aq.RiskLevel.WRITE_HIGH)
        # Second submission with same action+risk returns the FIRST item_id
        self.assertEqual(r1["item_id"], r2["item_id"])

    def test_persistence_across_calls(self):
        r = self._submit(action="persist-check")
        # Simulate a fresh process by calling _load() directly
        items = aq._load()
        ids = [i["id"] for i in items]
        self.assertIn(r["item_id"], ids)


if __name__ == "__main__":
    unittest.main()
