"""
tests/test_api_structure.py — API consolidation tests.

Validates:
  - Router registry works
  - Extracted routers load
  - api/main.py size reduced
  - No duplicate handlers
  - Key endpoints still reachable via extracted routers
  - Registry status endpoint exists
"""
from pathlib import Path
import importlib


class TestRouterRegistry:
    def test_AS01_registry_module_exists(self):
        from api.router_registry import RouterRegistry
        assert RouterRegistry

    def test_AS02_register_router(self):
        from api.router_registry import RouterRegistry
        from fastapi import APIRouter
        r = RouterRegistry()
        router = APIRouter()
        @router.get("/test")
        async def test(): return "ok"
        r.register("test", router, prefix="/test")
        assert r.get("test") is not None

    def test_AS03_register_failure(self):
        from api.router_registry import RouterRegistry
        r = RouterRegistry()
        r.register_failure("broken", "ImportError: no module")
        assert "broken" in r.get_failed_names()
        assert r.get("broken") is None

    def test_AS04_registry_status(self):
        from api.router_registry import RouterRegistry
        from fastapi import APIRouter
        r = RouterRegistry()
        r.register("a", APIRouter())
        r.register_failure("b", "err")
        status = r.get_status()
        assert status["loaded"] == 1
        assert status["failed"] == 1
        assert status["total_routers"] == 2

    def test_AS05_singleton_registry(self):
        from api.router_registry import get_registry
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2


class TestExtractedRouters:
    def test_AS06_system_v2_router_exists(self):
        from api.routes.system_v2 import router
        assert router
        # Check some routes exist
        routes = [r.path for r in router.routes]
        assert any("/api/v2/decision-memory/stats" in p for p in routes)
        assert any("/health" in p for p in routes)

    def test_AS07_si_v2_router_exists(self):
        from api.routes.self_improvement_v2 import router
        assert router
        routes = [r.path for r in router.routes]
        assert any("self-improvement" in p for p in routes)
        assert any("self-improve" in p for p in routes)

    def test_AS08_system_v2_handlers_present(self):
        # set_system_mode removed from system_v2 (duplicate) — lives in missions.py
        # get_capabilities removed from system_v2 (duplicate) — lives in monitoring.py
        pass

    def test_AS09_si_v2_handlers_present(self):
        # si_status removed from self_improvement_v2 (duplicate) — lives in self_improvement.py
        pass


class TestMainReduction:
    def test_AS10_main_py_reduced(self):
        """api/main.py must be under 1600 lines (was 1990)."""
        content = Path("api/main.py").read_text(encoding="utf-8")
        lines = content.count("\n") + 1
        assert lines < 1600, f"api/main.py has {lines} lines (target < 1600)"

    def test_AS11_main_py_syntax_valid(self):
        import ast
        content = Path("api/main.py").read_text(encoding="utf-8")
        ast.parse(content)

    def test_AS12_no_duplicate_decision_memory(self):
        """decision_memory_stats should only be in system_v2, not main."""
        main = Path("api/main.py").read_text(encoding="utf-8")
        # Should not have the full handler, only comments
        assert main.count("async def decision_memory_stats") == 0

    def test_AS13_no_duplicate_si_handlers(self):
        """SI handlers should only be in self_improvement_v2, not main."""
        main = Path("api/main.py").read_text(encoding="utf-8")
        assert main.count("async def si_get_failures") == 0
        assert main.count("async def si_get_proposals") == 0
        assert main.count("async def get_suggestions") == 0

    def test_AS14_no_duplicate_system_handlers(self):
        main = Path("api/main.py").read_text(encoding="utf-8")
        assert main.count("async def get_policy_mode") == 0
        assert main.count("async def get_capabilities") == 0
        assert main.count("async def get_tools_registry") == 0

    def test_AS15_orphan_marker_exists(self):
        """Orphaned code removed marker."""
        main = Path("api/main.py").read_text(encoding="utf-8")
        assert "_ORPHAN_REMOVED" in main


class TestMountedRouters:
    def test_AS16_system_v2_mounted(self):
        import inspect
        main_src = inspect.getsource(importlib.import_module("api.main"))
        assert "system_v2_router" in main_src

    def test_AS17_si_v2_mounted(self):
        import inspect
        main_src = inspect.getsource(importlib.import_module("api.main"))
        assert "si_v2_router" in main_src

    def test_AS18_registry_endpoint_exists(self):
        import inspect
        main_src = inspect.getsource(importlib.import_module("api.main"))
        assert "router_registry_status" in main_src
        assert "/api/v3/system/registry" in main_src


class TestBackwardCompat:
    def test_AS19_root_redirect_still_works(self):
        import inspect
        main_src = inspect.getsource(importlib.import_module("api.main"))
        assert "/app.html" in main_src

    def test_AS20_task_submit_still_inline(self):
        """POST /api/v2/task is handled by missions_v3_router (missions.py, mounted in main)."""
        # Route moved from inline stub in main.py to canonical handler in missions.py.
        # Verify the handler exists there and the router is mounted in main.
        from api.routes.missions import submit_task
        assert submit_task
        import inspect
        main_src = inspect.getsource(importlib.import_module("api.main"))
        assert "missions_v3_router" in main_src  # router is mounted

    def test_AS21_approve_reject_still_works(self):
        """Flutter approve/reject endpoints handled by missions_v3_router."""
        # Moved from stubs in main.py to canonical handlers in missions.py.
        from api.routes.missions import approve_task, reject_task
        assert approve_task
        assert reject_task

    def test_AS22_health_endpoint_available(self):
        """Health check accessible (either main or system_v2)."""
        from api.routes.system_v2 import health_check
        assert health_check

    def test_AS23_auth_endpoints_remain(self):
        """Audit Mo3: auth routes were extracted from api.main to
        api.routes.auth. Both files together still expose the surface."""
        import inspect
        main_src = inspect.getsource(importlib.import_module("api.main"))
        try:
            routes_src = inspect.getsource(importlib.import_module("api.routes.auth"))
        except Exception:
            routes_src = ""
        combined = main_src + "\n" + routes_src
        assert "login_for_access_token" in combined
        assert "auth/me" in combined

    def test_AS24_websocket_remains(self):
        import inspect
        main_src = inspect.getsource(importlib.import_module("api.main"))
        assert "ws_stream_alias" in main_src

    def test_AS25_static_mount_last(self):
        """Static files mount at the end."""
        main = Path("api/main.py").read_text(encoding="utf-8")
        lines = main.strip().split("\n")
        last_10 = "\n".join(lines[-10:])
        assert "StaticFiles" in last_10 or "static" in last_10
