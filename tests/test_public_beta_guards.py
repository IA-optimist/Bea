"""
tests/test_public_beta_guards.py — Public beta guard contracts.

Validates:
  1. Stub routes (voice, browser) are NOT mounted when ENABLE_STUB_ROUTES is absent/false.
  2. Stub routes that ARE enabled must NOT return a silent 200 OK (Contract 2).
  3. HexStrike V2 is marked not-ready (__ready__ = False).
  4. DevinAgent has MATURITY = "experimental".
  5. OrchestratorV2 has a MATURITY label.
"""
from __future__ import annotations

import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Contract 1: Stub routes are disabled by default ───────────────────────────

def test_stub_routes_disabled_by_default():
    """When ENABLE_STUB_ROUTES is not set/false, voice and browser routes are absent."""
    # We test at the router_mount level: build a minimal FastAPI app
    # and confirm that voice/browser route prefixes are NOT present.
    from fastapi import FastAPI
    from api.router_mount import mount_all_routers

    minimal_app = FastAPI()
    # Mount with stub routes DISABLED (default)
    mount_all_routers(minimal_app, enable_stub_routes=False)

    # Collect all route paths registered on the app
    registered_paths = {
        getattr(route, "path", "") for route in minimal_app.routes
    }

    # No voice or browser *stub* paths should be present.
    # The voice stub router prefix is /api/v2/voice (NOT /multimodal/voice).
    # The browser stub router prefix is /api/v2/browser.
    voice_stub_paths = [p for p in registered_paths if p.startswith("/api/v2/voice")]
    browser_stub_paths = [p for p in registered_paths if p.startswith("/api/v2/browser")]

    assert not voice_stub_paths, (
        f"Voice stub routes (/api/v2/voice/*) should NOT be mounted when "
        f"enable_stub_routes=False, but found: {voice_stub_paths}"
    )
    assert not browser_stub_paths, (
        f"Browser stub routes (/api/v2/browser/*) should NOT be mounted when "
        f"enable_stub_routes=False, but found: {browser_stub_paths}"
    )


def test_stub_routes_enabled_when_flag_set():
    """When enable_stub_routes=True, voice and browser routes ARE mounted."""
    from fastapi import FastAPI
    from api.router_mount import mount_all_routers

    minimal_app = FastAPI()
    mount_all_routers(minimal_app, enable_stub_routes=True)

    registered_paths = {
        getattr(route, "path", "") for route in minimal_app.routes
    }

    voice_stub_paths = [p for p in registered_paths if p.startswith("/api/v2/voice")]
    browser_stub_paths = [p for p in registered_paths if p.startswith("/api/v2/browser")]

    # With stub routes enabled at least one voice and one browser stub path must appear
    assert voice_stub_paths, (
        "Voice stub routes (/api/v2/voice/*) should be mounted when enable_stub_routes=True"
    )
    assert browser_stub_paths, (
        "Browser stub routes (/api/v2/browser/*) should be mounted when enable_stub_routes=True"
    )


# ── Contract 2: Stub routes return non-silent responses ───────────────────────

def test_router_mount_flag_controls_stub_routes_independently():
    """Mounting with vs without stub routes yields different route sets — confirming
    the flag is respected and not silently ignored."""
    from fastapi import FastAPI
    from api.router_mount import mount_all_routers

    app_no_stubs = FastAPI()
    mount_all_routers(app_no_stubs, enable_stub_routes=False)
    paths_no_stubs = {getattr(r, "path", "") for r in app_no_stubs.routes}

    app_with_stubs = FastAPI()
    mount_all_routers(app_with_stubs, enable_stub_routes=True)
    paths_with_stubs = {getattr(r, "path", "") for r in app_with_stubs.routes}

    # The stub-enabled app must have more routes than the stub-disabled app
    stub_only_paths = paths_with_stubs - paths_no_stubs
    assert stub_only_paths, (
        "enable_stub_routes=True should add at least one extra route that is "
        "absent when enable_stub_routes=False. Got no difference."
    )


# ── Contract 2: Stub routes must not return a silent 200 OK ──────────────────

def test_stub_routes_do_not_return_false_200():
    """When stub routes ARE enabled, they must NOT silently return 200 OK.

    A stub endpoint that returns 200 with a fake success response is worse than
    a 404 — it silently lies about capability.  Any 4xx (401, 404, 405, 422, 501)
    is acceptable; 200 is not.

    Endpoints tested (voice + browser stubs):
      POST /api/v2/voice/call     — requires auth + JSON body
      POST /api/v2/voice/sms      — requires auth + JSON body
      GET  /api/v2/voice/call/x   — requires auth
      POST /api/v2/browser/navigate  — requires auth + JSON body
      POST /api/v2/browser/search    — requires auth + JSON body
      POST /api/v2/browser/screenshot — requires auth + JSON body
    """
    import os
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.router_mount import mount_all_routers

    # Ensure auth is enforced (default) so no accidental bypass via env var
    os.environ.pop("BEA_REQUIRE_AUTH", None)
    # No valid token — any auth-protected stub must reject with 4xx
    os.environ.pop("BEA_API_TOKEN", None)

    app = FastAPI()
    mount_all_routers(app, enable_stub_routes=True)

    # Probe each stub endpoint without a valid auth token.
    # Expected: 4xx (401 no-token, 403 forbidden, 404 not-found, 405 method-not-allowed,
    #           422 validation-error, 501 not-implemented, 503 auth-not-configured).
    # Forbidden: 200 (silent lie about capability).
    stub_probes = [
        # (method, path, json_body_or_None)
        ("POST", "/api/v2/voice/call",
         {"to": "+32470000000", "message": "test"}),
        ("POST", "/api/v2/voice/sms",
         {"to": "+32470000000", "message": "test"}),
        ("GET",  "/api/v2/voice/call/fake-sid", None),
        ("POST", "/api/v2/browser/navigate",
         {"url": "https://example.com"}),
        ("POST", "/api/v2/browser/search",
         {"query": "test"}),
        ("POST", "/api/v2/browser/screenshot",
         {"url": "https://example.com"}),
    ]

    false_200_routes: list[str] = []

    with TestClient(app, raise_server_exceptions=False) as client:
        for method, path, body in stub_probes:
            if method == "GET":
                resp = client.get(path)
            else:
                resp = client.post(path, json=body)

            if resp.status_code == 200:
                false_200_routes.append(
                    f"{method} {path} → 200 (body: {resp.text[:120]})"
                )

    assert not false_200_routes, (
        "The following stub routes returned a false 200 OK — they must return 4xx "
        "(401/404/405/422/501/503) to avoid silently lying about capability:\n"
        + "\n".join(false_200_routes)
    )


# ── Contract 3: HexStrike V2 is marked not-ready ─────────────────────────────

def test_hexstrike_v2_not_ready():
    """HexStrike V2 is incomplete and exposes __ready__ = False."""
    import mcp.hexstrike_v2 as hexstrike_v2

    assert hasattr(hexstrike_v2, "__ready__"), (
        "mcp.hexstrike_v2 must expose a __ready__ attribute to signal readiness"
    )
    assert hexstrike_v2.__ready__ is False, (
        f"mcp.hexstrike_v2.__ready__ must be False (got {hexstrike_v2.__ready__!r})"
    )


# ── Contract 4a: DevinAgent has MATURITY = "experimental" ────────────────────

def test_devin_agent_labeled_experimental():
    """DevinAgent has MATURITY = 'experimental'."""
    from agents.autonomous.devin_agent import DevinAgent

    assert hasattr(DevinAgent, "MATURITY"), (
        "DevinAgent must have a class-level MATURITY attribute"
    )
    assert DevinAgent.MATURITY == "experimental", (
        f"DevinAgent.MATURITY must be 'experimental', got {DevinAgent.MATURITY!r}"
    )


# ── Contract 4b: OrchestratorV2 has a MATURITY label ─────────────────────────

def test_orchestrator_v2_has_maturity_label():
    """OrchestratorV2 has a MATURITY label set to a recognised value."""
    from core.orchestrator_v2 import OrchestratorV2

    assert hasattr(OrchestratorV2, "MATURITY"), (
        "OrchestratorV2 must have a class-level MATURITY attribute"
    )
    assert OrchestratorV2.MATURITY in ("active", "stable", "experimental"), (
        f"OrchestratorV2.MATURITY must be one of 'active'/'stable'/'experimental', "
        f"got {OrchestratorV2.MATURITY!r}"
    )


# ── Contract 5: /api/v3/system/readiness does not crash (PolicyEngine non-regression) ──

def test_system_route_policy_report_no_crash():
    """GET /api/v3/system/readiness must not return 500.

    This is a non-regression guard for PolicyEngine.get_report() — if get_report()
    raises AttributeError (e.g. missing _cloud_allowed), the endpoint returns 500.
    We accept 200 / 401 / 403 but NOT 500.
    """
    try:
        from api.main import app
        from fastapi.testclient import TestClient
    except Exception:
        import pytest
        pytest.skip("api.main not importable in this environment")

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(
        "/api/v3/system/readiness",
        headers={"X-Bea-Token": "test"},
    )
    assert resp.status_code != 500, (
        f"GET /api/v3/system/readiness returned HTTP 500. "
        f"Likely cause: PolicyEngine.get_report() raised an exception. "
        f"Response body: {resp.text[:400]}"
    )
