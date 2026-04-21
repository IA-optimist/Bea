"""
tests/smoke/test_e2e_smoke.py — End-to-end smoke test

Purpose:
    Prove that a running Jarvis Max instance can accept a real mission,
    route it through the canonical API path, and produce a terminal result.

Requirements:
    - A running Jarvis Max stack (docker-compose.test.yml or python main.py)
    - At least one real LLM API key in the environment
    - JARVIS_BASE_URL set, or default http://localhost:8000

Usage:
    # Against local dev server:
    OPENAI_API_KEY=sk-... python main.py &
    pytest tests/smoke/test_e2e_smoke.py -v

    # Against Docker test stack:
    docker compose -f docker-compose.test.yml up -d
    pytest tests/smoke/test_e2e_smoke.py -v

This test is NOT mocked. It exercises the real runtime path.
It will fail explicitly if:
  - The server is not running
  - No LLM key is configured
  - Qdrant is unreachable
  - The mission fails to reach a terminal state within the timeout
"""
from __future__ import annotations

import os
import time
import pytest

try:
    import httpx
except ImportError:
    pytest.skip("httpx required: pip install httpx", allow_module_level=True)

# ─── Marker — skipped in CI unless --run-infra-tests is passed ───────────────
# These tests require a running Jarvis Max server + LLM key.
# Run with: pytest tests/smoke/ --run-infra-tests -v
pytestmark = pytest.mark.integration

# ─── Configuration ────────────────────────────────────────────────────────────

BASE_URL: str = os.environ.get("JARVIS_BASE_URL", "http://localhost:8000")
API_TOKEN: str = os.environ.get("JARVIS_API_TOKEN", "")

# Mission timeout: how long to wait for a mission to reach a terminal state.
# Simple 1-sentence LLM task should complete in < 30s on any provider.
# Increase to 120 if running with a slow provider or rate-limited key.
MISSION_TIMEOUT_S: int = int(os.environ.get("JARVIS_SMOKE_TIMEOUT", "60"))
POLL_INTERVAL_S: float = 2.0

TERMINAL_STATES = {"DONE", "FAILED", "CANCELLED", "REJECTED"}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _headers() -> dict:
    if API_TOKEN:
        return {"Authorization": f"Bearer {API_TOKEN}"}
    return {}


def _get(path: str, timeout: float = 10.0) -> httpx.Response:
    return httpx.get(f"{BASE_URL}{path}", headers=_headers(), timeout=timeout)


def _post(path: str, body: dict, timeout: float = 10.0) -> httpx.Response:
    return httpx.post(f"{BASE_URL}{path}", json=body, headers=_headers(), timeout=timeout)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module", autouse=True)
def assert_server_reachable():
    """Fail fast with a clear message if server is not running."""
    try:
        r = httpx.get(f"{BASE_URL}/health", timeout=5.0)
        assert r.status_code < 500, f"/health returned {r.status_code}"
    except httpx.ConnectError:
        pytest.fail(
            f"Cannot connect to Jarvis Max at {BASE_URL}.\n"
            "Start the server first:\n"
            "  python main.py\n"
            "  OR: docker compose -f docker-compose.test.yml up -d"
        )


@pytest.fixture(scope="module", autouse=True)
def assert_llm_key_configured(assert_server_reachable):
    """Fail fast with a clear message if no LLM key is configured."""
    r = _get("/api/v3/system/readiness", timeout=10.0)
    body = r.json()
    data = body.get("data", body)
    probes = data.get("probes", {})

    if not probes.get("llm_key", False):
        pytest.fail(
            "No LLM API key is configured on the running server.\n"
            "Set one of: OPENAI_API_KEY, ANTHROPIC_API_KEY, OPENROUTER_API_KEY\n"
            "Then restart the server and re-run this test."
        )

    if not probes.get("qdrant", False):
        pytest.fail(
            "Qdrant is unreachable from the running server.\n"
            "Start Qdrant: docker run -p 6333:6333 qdrant/qdrant\n"
            "Then restart the server and re-run this test."
        )


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_S1_readiness_probe_returns_200():
    """Readiness probe confirms server is ready to serve missions."""
    r = _get("/api/v3/system/readiness")
    assert r.status_code == 200, (
        f"Readiness probe returned {r.status_code}.\n"
        f"Body: {r.text[:500]}\n"
        "Check RUNBOOK.md section 13 for diagnosis."
    )
    body = r.json()
    data = body.get("data", body)
    assert data.get("ready") is True, f"ready=False: {data}"
    assert data.get("status") == "ready", f"status != ready: {data}"


def test_S2_mission_submit_returns_201():
    """Submitting a mission returns HTTP 201 with a mission_id."""
    r = _post("/api/v3/missions", {"goal": "Return only the number 42."})
    assert r.status_code == 201, (
        f"Mission submission returned {r.status_code}.\n"
        f"Body: {r.text[:500]}"
    )
    body = r.json()
    data = body.get("data", body)
    assert "mission_id" in data, f"No mission_id in response: {data}"
    assert data["mission_id"], "mission_id is empty"


def test_S3_mission_reaches_terminal_state():
    """
    A submitted mission must reach a terminal state (DONE or FAILED) within
    JARVIS_SMOKE_TIMEOUT seconds.

    This is the core E2E proof:
    - POST /api/v3/missions → returns mission_id
    - Poll GET /api/v3/missions/{id} until terminal state
    - Inspect the result

    Failure modes:
    - Stuck in RUNNING/PLANNED: orchestrator or LLM call blocked
    - Reaches FAILED: LLM returned error, check logs for root cause
    - Timeout: system is too slow or mission queue is backed up
    """
    # Submit
    r = _post("/api/v3/missions", {
        "goal": (
            "Complete this task in a single short sentence: "
            "What is 7 multiplied by 6?"
        )
    })
    assert r.status_code == 201, f"Submit failed: {r.status_code} {r.text[:300]}"
    mission_id = r.json().get("data", r.json()).get("mission_id")
    assert mission_id, "No mission_id returned"

    # Poll for terminal state
    deadline = time.monotonic() + MISSION_TIMEOUT_S
    status = "CREATED"
    last_body = {}

    while time.monotonic() < deadline:
        poll = _get(f"/api/v3/missions/{mission_id}", timeout=15.0)
        if poll.status_code == 200:
            last_body = poll.json().get("data", poll.json())
            status = last_body.get("status", status)
            if status in TERMINAL_STATES:
                break
        time.sleep(POLL_INTERVAL_S)

    assert status in TERMINAL_STATES, (
        f"Mission '{mission_id}' did not reach a terminal state within {MISSION_TIMEOUT_S}s.\n"
        f"Last status: {status}\n"
        f"Last body: {str(last_body)[:500]}\n"
        "Check server logs: docker logs jarvis_test_core"
    )

    # We accept DONE or FAILED — both are terminal.
    # FAILED is explicitly reported so the engineer can investigate root cause.
    if status == "FAILED":
        error = last_body.get("error") or last_body.get("result") or "(no error detail)"
        pytest.fail(
            f"Mission reached FAILED state.\n"
            f"mission_id: {mission_id}\n"
            f"error: {error}\n"
            "Most likely cause: LLM API key expired/invalid, or rate limit hit.\n"
            "Check logs for 'llm_call_failed' or 'circuit_breaker_opened'."
        )

    # DONE — verify result exists
    result = last_body.get("result") or last_body.get("final_report") or ""
    assert result, (
        f"Mission reached DONE but result is empty.\n"
        f"Full response: {last_body}"
    )
    assert len(result) > 0, "Result is empty string"

    # Log the result for inspection (visible with pytest -v -s)
    print(f"\n✓ Mission {mission_id} completed.")
    print("  Goal: 'What is 7 multiplied by 6?'")
    print(f"  Result: {result[:200]}")


def test_S4_mission_list_shows_completed_mission():
    """GET /api/v3/missions returns the completed mission in the list."""
    r = _get("/api/v3/missions")
    assert r.status_code == 200, f"Mission list failed: {r.status_code}"
    body = r.json()
    data = body.get("data", body)
    missions = data if isinstance(data, list) else data.get("missions", [])
    assert isinstance(missions, list), f"Expected list, got: {type(missions)}"
    # At minimum, there's the mission we just submitted in S3
    assert len(missions) >= 1, "Mission list is empty after submitting a mission"


def test_S5_health_endpoint_responsive():
    """Basic health endpoint remains responsive after mission processing."""
    r = _get("/health")
    assert r.status_code < 500, f"Health endpoint degraded: {r.status_code}"
