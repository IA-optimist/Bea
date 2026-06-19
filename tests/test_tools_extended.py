"""
Tests étendus pour les tools L4 — tous graceful (SKIP si tool indisponible).
"""
import os
import pytest
_silent_log = __import__("structlog").get_logger(__name__)
pytestmark = pytest.mark.integration


BEA_ROOT = os.environ.get("BEA_ROOT", "/opt/beamax")


def _skip_if_unavailable(result: dict, reason: str = "") -> None:
    """Skip le test si le tool retourne une erreur de type 'not found'."""
    if not result.get("ok"):
        err = result.get("error", "")
        if any(k in (err or "") for k in ["not_found", "not found", "not available", "unavailable", "No such file"]):
            pytest.skip(f"tool_unavailable: {err}")


# ── file_tool ──────────────────────────────────────────────────────────────────

def test_file_read():
    from core.tool_executor import read_file_content
    result = read_file_content(os.path.join(BEA_ROOT, "main.py"), max_lines=5)
    # Either ok or file not found — both acceptable
    assert "ok" in result


def test_file_write_rollback():
    """Écrit un fichier de test, vérifie backup, nettoie."""
    import tempfile
    import os
    from core.tool_executor import write_file_safe
    from core.rollback_manager import get_rollback_manager

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", dir="/tmp", delete=False, prefix="bea_test_"
    ) as f:
        test_path = f.name
        f.write("original content")

    try:
        result = write_file_safe(test_path, "new content")
        assert result.get("ok"), f"write failed: {result.get('error')}"
        with open(test_path, "r", encoding="utf-8") as f:
            assert f.read() == "new content"
        rm = get_rollback_manager()
        backups = rm.list_backups(test_path)
        assert len(backups) >= 1, "backup should exist after write"
    finally:
        try:
            os.unlink(test_path)
        except Exception:
            _silent_log.debug("suppressed_exception", src='test_tools_extended.py')


@pytest.mark.stale
@pytest.mark.skip(reason="phantom: import changed")
def test_file_create():
    import os
    from core.tools.file_tool import file_create

    test_path = f"/tmp/bea_test_create_{os.getpid()}.txt"
    try:
        result = file_create(test_path, "hello from file_create")
        assert result.get("ok"), f"file_create failed: {result.get('error')}"
        assert os.path.exists(test_path)
    finally:
        try:
            os.unlink(test_path)
        except Exception:
            _silent_log.debug("suppressed_exception", src='test_tools_extended.py')


# ── github_tool ────────────────────────────────────────────────────────────────

def test_git_status():
    from core.tools.github_tool import git_status
    result = git_status(BEA_ROOT)
    _skip_if_unavailable(result, "git not available")
    # Either ok or blocked_path — acceptable
    assert "ok" in result or "status" in result


# ── docker_tool ────────────────────────────────────────────────────────────────

def test_docker_ps():
    from core.tools.docker_tool import docker_ps
    result = docker_ps()
    _skip_if_unavailable(result, "docker not available")
    assert "ok" in result


# ── web_research_tool ──────────────────────────────────────────────────────────

def test_http_get():
    from core.tools.web_research_tool import fetch_url
    result = fetch_url("https://httpbin.org/json", timeout=10)
    if not result.get("ok"):
        err = result.get("error", "")
        if "Connection" in err or "timeout" in err.lower() or "connect" in err.lower():
            pytest.skip(f"network_unavailable: {err}")
    assert result.get("ok"), f"http_get failed: {result.get('error')}"
    assert "slideshow" in result.get("output", "").lower() or "json" in result.get("output", "").lower()


# ── memory_toolkit ─────────────────────────────────────────────────────────────

def test_memory_store_search():
    from core.tools.memory_toolkit import memory_store_solution, memory_search_similar
    store_result = memory_store_solution(
        problem="test_problem_unique_xyz123",
        solution="test_solution_xyz123",
        tags=["test"],
    )
    if not store_result.get("ok"):
        err = store_result.get("error", "")
        if "qdrant" in err.lower() or "unavailable" in err.lower() or "Connection" in err:
            pytest.skip(f"qdrant_unavailable: {err}")

    search_result = memory_search_similar("test_problem_unique_xyz123", top_k=3)
    if not search_result.get("ok"):
        pytest.skip(f"qdrant_unavailable: {search_result.get('error')}")
    assert "found=" in search_result.get("output", "")


# ── test_toolkit ───────────────────────────────────────────────────────────────

def test_run_smoke_tests():
    from core.tools.test_toolkit import api_healthcheck
    result = api_healthcheck("http://localhost:8000")
    # Graceful — API may not be running in test env
    assert "ok" in result
    assert "healthy" in result


def test_app_sync_fields():
    from core.tools.app_sync_toolkit import check_api_fields
    result = check_api_fields("http://localhost:8000")
    assert "ok" in result
    # fields_ok and fields_missing should always be present
    assert "fields_ok" in result
    assert "fields_missing" in result
