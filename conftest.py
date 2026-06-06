"""
conftest.py â€” JarvisMax test configuration.

1. Pre-imports core.state so that test files using
   sys.modules.setdefault("core.state", MagicMock()) cannot overwrite it.
2. Ensures a fresh event loop for each test (pytest-asyncio asyncio_mode=auto
   closes loops after async tests, breaking sync tests that call
   asyncio.get_event_loop().run_until_complete()).
3. Sets JARVIS_SKIP_IMPROVEMENT_GATE=1 for the full test session so that
   kernel.improvement.gate bypasses security checks. This replaces the
   old reset_daemon_state() side-effect that permanently set this env var
   mid-test, which could cause cross-test contamination.
4. Marks tests requiring live infrastructure (Qdrant, live server, real LLM key)
   with pytest.mark.integration or pytest.mark.infra. These are skipped by default
   in CI and in unit-test runs. Pass --run-infra-tests to include them.

Usage:
    pytest                            # unit tests only (fast, no infra)
    pytest --run-infra-tests          # include integration/infra tests
    pytest tests/smoke/ --run-infra-tests  # smoke tests against live stack
    pytest -m "not integration"       # explicitly exclude integration tests
"""
import asyncio
import os
import pytest

# Bypass improvement gate security check for all tests â€” prevents dependency
# on security layer availability (qdrant, structlog) inside test environments.
# DISABLED FOR SECURITY TESTS: # os.environ.setdefault("JARVIS_SKIP_IMPROVEMENT_GATE", "1")

# â”€â”€ Test auth token â€” acceptÃ© par api/_deps._check_auth â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# La plupart des tests API envoient "Authorization: Bearer test". On aligne
# JARVIS_API_TOKEN pour qu'ils passent sans monkeypatch individuel.
# Tests qui utilisent un autre token (ex. "Bearer t" dans test_mcp_registry)
# configurent leur propre override via monkeypatch.setenv / setattr.
os.environ.setdefault("JARVIS_API_TOKEN", "test")

# â”€â”€ Pre-load key modules so test-level mocks cannot overwrite them â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Tests that do sys.modules.setdefault("some.module", MagicMock()) can only
# install their mock if the real module is NOT already in sys.modules.
# By importing here (conftest is collected before test files), we protect them.
for _preload in [
    "core.state",
    "langchain_core",
    "langchain_core.language_models",
    "langchain_core.language_models.chat_models",
    "langchain_core.messages",
    "langchain_core.prompts",
    "langchain_core.outputs",
    "langchain_core.callbacks",
    "langchain_core.callbacks.manager",
    "fastapi",
    "fastapi.responses",
    "structlog",
]:
    try:
        __import__(_preload)
    except Exception:
        pass  # If missing, tests that need it will handle it themselves


# â”€â”€ Integration test CI gate â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Tests decorated with @pytest.mark.integration or @pytest.mark.infra require
# a live stack (Qdrant, running server, real LLM API key). They are skipped
# by default. Pass --run-infra-tests to include them.
#
# Marker semantics:
#   integration â€” requires a running Jarvis Max server + LLM key
#   infra       â€” requires any external infrastructure (Qdrant, Postgres, etc.)
#
# How to mark a test:
#   @pytest.mark.integration
#   def test_mission_e2e(): ...
#
#   @pytest.mark.infra
#   def test_qdrant_connection(): ...


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-infra-tests",
        action="store_true",
        default=False,
        help="Include integration and infra tests that require a live stack.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: marks tests that require a running Jarvis Max server and LLM key",
    )
    config.addinivalue_line(
        "markers",
        "infra: marks tests that require live external infrastructure (Qdrant, Postgres, etc.)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--run-infra-tests", default=False):
        return  # All tests run
    skip_infra = pytest.mark.skip(reason="requires live infra â€” run with --run-infra-tests")
    for item in items:
        if item.get_closest_marker("integration") or item.get_closest_marker("infra"):
            item.add_marker(skip_infra)


@pytest.fixture(autouse=True)
def _ensure_event_loop():
    """Create a fresh event loop before each sync test if none is running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    yield
    # Do not close here â€” let pytest-asyncio manage its own loops.
    # Only clean up loops we created (i.e., not the pytest-asyncio-managed ones).
