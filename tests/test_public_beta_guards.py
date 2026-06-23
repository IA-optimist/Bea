"""
tests/test_public_beta_guards.py — Public beta guard contracts.

Validates:
  1. Stub routes (voice, browser) are NOT mounted when ENABLE_STUB_ROUTES is absent/false.
  2. HexStrike V2 is marked not-ready (__ready__ = False).
  3. DevinAgent has MATURITY = "experimental".
  4. OrchestratorV2 has a MATURITY label.
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
