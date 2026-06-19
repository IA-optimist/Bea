"""Explicit public route allowlist tests."""
from __future__ import annotations

import pytest

from api.access_enforcement import is_public_path


EXPECTED_PUBLIC_PATHS = {
    "/",
    "/health",
    "/api/v2/health",
    "/api/v3/system/readiness",
    "/auth/login",
    "/auth/token",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/app.html",
}


@pytest.mark.parametrize("path", EXPECTED_PUBLIC_PATHS)
def test_public_path_allowlist(path: str) -> None:
    assert is_public_path(path), f"{path} should be public"


@pytest.mark.parametrize(
    "path",
    [
        "/api/v2/missions",
        "/api/v3/extensions",
        "/api/v3/venture/hypotheses",
        "/api/v2/learning",
        "/api/v1/missions",
    ],
)
def test_sensitive_routes_are_not_public(path: str) -> None:
    assert not is_public_path(path), f"{path} should be protected"


def test_allowlist_is_explicit_and_stable() -> None:
    assert len(EXPECTED_PUBLIC_PATHS) >= 8, "Allowlist must remain explicit"
