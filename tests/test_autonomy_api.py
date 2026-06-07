"""Tests for /api/v3/autonomy/* endpoints.

These tests use FastAPI TestClient against a minimal app that mounts
ONLY the autonomy router and a permissive auth dependency. The full
api/main.py app is too heavy + would fail without DB/Redis.
"""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

import unittest.mock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.autonomy import (
    Choice,
    get_multi_choice_store,
    reset_event_bus,
    reset_multi_choice_store,
)
from core.autonomy import multi_choice as _mc_module


def _build_app():
    """Minimal app : autonomy router + auth bypass."""
    app = FastAPI()
    # Override require_auth before importing the router
    from api import _deps
    original = _deps.require_auth

    def _bypass_auth():
        return {"username": "test", "scopes": []}

    _deps.require_auth = _bypass_auth
    try:
        # Re-import the router with the patched dependency
        import importlib
        import api.routes.autonomy as autonomy_module
        importlib.reload(autonomy_module)
        app.include_router(autonomy_module.router)
    finally:
        _deps.require_auth = original
    return app


class TestAutonomyAPIStatus(unittest.TestCase):
    def setUp(self):
        reset_event_bus()
        reset_multi_choice_store()
        # Redirect MultiChoiceStore persistence to a tmpdir so tests don't
        # see stale decisions from a previous suite.
        self._tmp = tempfile.TemporaryDirectory()
        self._patch = unittest.mock.patch.object(
            _mc_module, "_STORE_PATH",
            Path(self._tmp.name) / "decisions.json",
        )
        self._patch.start()
        os.environ["BEA_AUTONOMY_USE_REAL"] = "0"
        os.environ.pop("BEA_AUTONOMY_PAUSED", None)
        self.app = _build_app()
        self.client = TestClient(self.app)

    def tearDown(self):
        try:
            self._patch.stop()
            self._tmp.cleanup()
        except Exception:
            pass

    def test_status_when_not_running(self):
        r = self.client.get("/api/v3/autonomy/status")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["running"])
        self.assertEqual(body["history_count"], 0)
        self.assertIn("budget", body)
        self.assertIn("event_bus_stats", body)

    def test_decisions_empty_initially(self):
        r = self.client.get("/api/v3/autonomy/decisions")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_answer_unknown_decision_returns_404(self):
        r = self.client.post(
            "/api/v3/autonomy/decisions/does-not-exist/answer",
            json={"selected_index": 0},
        )
        self.assertEqual(r.status_code, 404)


class TestAutonomyAPILifecycle(unittest.TestCase):
    """Smoke tests for /start + /stop with safe defaults."""

    def setUp(self):
        reset_event_bus()
        reset_multi_choice_store()
        # Force safe mode (event_bus_runner) so tests don't poke real orchestrator
        os.environ["BEA_AUTONOMY_USE_REAL"] = "0"
        os.environ.pop("BEA_AUTONOMY_PAUSED", None)
        self.app = _build_app()
        self.client = TestClient(self.app)

    def tearDown(self):
        try:
            self.client.post("/api/v3/autonomy/stop", json={"reason": "test_teardown"})
        except Exception:
            pass
        try:
            self._patch.stop()
            self._tmp.cleanup()
        except Exception:
            pass

    def test_start_returns_started_in_safe_mode(self):
        r = self.client.post(
            "/api/v3/autonomy/start",
            json={
                "objective": "test-objective",
                "max_iters": 2,
                "sleep_s": 0,
                "max_seconds": 30,
                "max_tokens": 1000,
                "max_usd": 0.1,
            },
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "started")
        self.assertEqual(body["objective"], "test-objective")
        self.assertEqual(body["mode"], "safe")

    def test_double_start_returns_409(self):
        # First start
        self.client.post(
            "/api/v3/autonomy/start",
            json={"objective": "first", "max_iters": 100, "sleep_s": 1},
        )
        # Second start without force
        r = self.client.post(
            "/api/v3/autonomy/start",
            json={"objective": "second", "max_iters": 1},
        )
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["detail"]["error"], "daemon_already_running")

    def test_force_replaces_running_daemon(self):
        self.client.post(
            "/api/v3/autonomy/start",
            json={"objective": "first", "max_iters": 100, "sleep_s": 1},
        )
        r = self.client.post(
            "/api/v3/autonomy/start",
            json={
                "objective": "second",
                "max_iters": 1,
                "force": True,
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["objective"], "second")

    def test_stop_when_not_running(self):
        r = self.client.post("/api/v3/autonomy/stop", json={"reason": "no-op"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "not_running")

    def test_stop_after_start_returns_summary(self):
        self.client.post(
            "/api/v3/autonomy/start",
            json={
                "objective": "test",
                "max_iters": 3,
                "sleep_s": 0,
            },
        )
        # Let the loop tick a couple times
        time.sleep(0.5)
        r = self.client.post("/api/v3/autonomy/stop", json={"reason": "test_done"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn(body["status"], ("stopped", "stop_signal_sent", "not_running"))


class TestAutonomyAPIDecisions(unittest.TestCase):
    def setUp(self):
        reset_event_bus()
        reset_multi_choice_store()
        # Redirect MultiChoiceStore persistence to a tmpdir so tests don't
        # see stale decisions from a previous suite.
        self._tmp = tempfile.TemporaryDirectory()
        self._patch = unittest.mock.patch.object(
            _mc_module, "_STORE_PATH",
            Path(self._tmp.name) / "decisions.json",
        )
        self._patch.start()
        os.environ["BEA_AUTONOMY_USE_REAL"] = "0"
        self.app = _build_app()
        self.client = TestClient(self.app)

    def tearDown(self):
        try:
            self._patch.stop()
            self._tmp.cleanup()
        except Exception:
            pass

    def test_pending_decision_listed(self):
        store = get_multi_choice_store()
        d = store.create(
            name="test",
            question="?",
            choices=[Choice(index=0, label="a"), Choice(index=1, label="b")],
        )
        r = self.client.get("/api/v3/autonomy/decisions")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["decision_id"], d.decision_id)

    def test_answer_resolves_decision(self):
        store = get_multi_choice_store()
        d = store.create(
            name="test",
            question="?",
            choices=[Choice(index=0, label="a"), Choice(index=1, label="b")],
        )
        r = self.client.post(
            f"/api/v3/autonomy/decisions/{d.decision_id}/answer",
            json={"selected_index": 1},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "answered")
        self.assertEqual(body["selected_index"], 1)

    def test_answer_invalid_index_returns_400(self):
        store = get_multi_choice_store()
        d = store.create(
            name="test",
            question="?",
            choices=[Choice(index=0, label="a")],
        )
        r = self.client.post(
            f"/api/v3/autonomy/decisions/{d.decision_id}/answer",
            json={"selected_index": 99},
        )
        # 99 is rejected by Pydantic schema (le=99 -> 99 ok, but out of choices range)
        # Either 400 from Pydantic or our store ValueError
        self.assertIn(r.status_code, (400, 422))


if __name__ == "__main__":
    unittest.main()
