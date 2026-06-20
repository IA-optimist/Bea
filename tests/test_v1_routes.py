"""tests/test_v1_routes.py — Quick checks for the stable v1 surface."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from api import main

    monkeypatch.setenv("BEA_API_TOKEN", "test-token")
    test_client = TestClient(main.app)
    test_client.headers.update({"Authorization": "Bearer test-token"})
    return test_client


def test_v1_migration_guide_returns_matrix(client) -> None:
    resp = client.get("/api/v1/migration")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    routes = body["data"]["routes"]
    assert any("/api/v1/missions" in r["v1"] for r in routes)
    assert "sunset" in body["data"]


def test_v1_evaluations_returns_placeholder(client, tmp_path: Path) -> None:
    from core.observability import eval_publisher

    original = eval_publisher._DEFAULT_SCORE_FILE
    tmp_file = tmp_path / "eval_scores.json"
    eval_publisher._DEFAULT_SCORE_FILE = tmp_file
    try:
        resp = client.get("/api/v1/evaluations")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["status"] in ("ok", "not_run")
    finally:
        eval_publisher._DEFAULT_SCORE_FILE = original
