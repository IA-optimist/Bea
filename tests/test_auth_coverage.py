from __future__ import annotations

import re

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


def test_public_route_allowlist_is_explicit_and_middleware_is_mounted():
    from api.main import app

    middleware_names = {m.cls.__name__ for m in app.user_middleware}
    assert "AccessEnforcementMiddleware" in middleware_names

    for path in EXPECTED_PUBLIC_PATHS:
        assert is_public_path(path), path

    protected = [route.path for route in app.routes if hasattr(route, "methods") and not is_public_path(route.path)]
    assert protected, "Expected non-public routes to remain protected by the middleware"


def test_route_modules_do_not_use_fail_open_auth_fallbacks():
    import pathlib

    routes_dir = pathlib.Path(__file__).resolve().parents[1] / "api" / "routes"
    offenders: list[str] = []
    for path in routes_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if re.search(r"^\s*_auth\s*=\s*None\b", text, flags=re.MULTILINE):
            offenders.append(str(path))

    assert not offenders, "Fail-open auth fallback still present in:\n" + "\n".join(offenders)


def test_key_admin_routes_are_router_protected():
    from api.routes import extensions, venture

    extensions_deps = getattr(extensions.router, "dependencies", [])
    venture_deps = getattr(venture.router, "dependencies", [])

    assert extensions_deps, "extensions router must keep router-level auth"
    assert venture_deps, "venture router must keep router-level auth"


def test_mobile_metrics_auth_requires_real_credentials():
    import pathlib

    metrics_path = pathlib.Path(__file__).resolve().parents[1] / "api" / "routes" / "metrics_mobile.py"
    text = metrics_path.read_text(encoding="utf-8")

    assert "Always require valid auth" in text
    assert "silent bypass" in text.lower()
    assert "raise HTTPException(401, \"Unauthorized\")" in text
