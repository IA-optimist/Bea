"""
conftest.py - BeaMax test configuration.

1. Pre-imports core.state so test files cannot replace it with a mock.
2. Ensures a fresh event loop for each sync test if none is running.
3. Marks tests requiring live infrastructure with integration/infra.
4. Marks stale or drifted tests as quarantine so they stay out of the
   blocking suite.
"""

from __future__ import annotations

import asyncio
import os
import re

import pytest

os.environ.setdefault("BEA_API_TOKEN", "test")

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
        pass


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
        "integration: marks tests that require a running Bea Max server and LLM key",
    )
    config.addinivalue_line(
        "markers",
        "infra: marks tests that require live external infrastructure (Qdrant, Postgres, etc.)",
    )
    config.addinivalue_line(
        "markers",
        "quarantine: marks stale or drifted tests kept out of the blocking suite",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--run-infra-tests", default=False):
        return

    skip_infra = pytest.mark.skip(reason="requires live infra -- run with --run-infra-tests")
    quarantine_reason = pytest.mark.skip(reason="quarantined stale test")
    quarantine_patterns = re.compile(
        r"(stale|drift|removed files?|phantom|deprecated|legacy compat|module not implemented|not implemented yet|moved)",
        re.IGNORECASE,
    )

    for item in items:
        if item.get_closest_marker("integration") or item.get_closest_marker("infra"):
            item.add_marker(skip_infra)
            continue

        marker = item.get_closest_marker("skip") or item.get_closest_marker("xfail")
        if marker:
            reason = str(marker.kwargs.get("reason", ""))
            if quarantine_patterns.search(reason):
                item.add_marker(pytest.mark.quarantine)
                item.add_marker(quarantine_reason)


@pytest.fixture(autouse=True)
def _ensure_event_loop():
    """Create a fresh event loop before each sync test if none is running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    yield
