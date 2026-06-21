"""Tests for core.repo_map.repo_map_service."""
from __future__ import annotations

import pytest

from core.memory.memory_item import MemoryItemType
from core.memory.operational_memory import OperationalMemoryStore
from core.repo_map.repo_map_service import RepoMapService


@pytest.fixture
def fixture_repo(tmp_path):
    (tmp_path / "api").mkdir()
    (tmp_path / "tests" / "api").mkdir(parents=True)
    (tmp_path / "api" / "routes.py").write_text(
        "from fastapi import APIRouter\n\nrouter = APIRouter()\n"
        "@router.get('/health')\ndef health():\n    return {'ok': True}\n"
    )
    (tmp_path / "tests" / "api" / "test_routes.py").write_text(
        "def test_health():\n    assert True\n"
    )
    return tmp_path


@pytest.fixture
def service(fixture_repo):
    store = OperationalMemoryStore(db_path=":memory:")
    return RepoMapService(root=fixture_repo, store=store, max_files=100)


def test_repo_map_service_persist(service, fixture_repo):
    report = service.persist()
    assert report["files"] >= 2
    assert report["repo_facts_stored"] >= 1
    assert report["test_maps_stored"] >= 1

    facts = service.store.search(type=MemoryItemType.REPO_FACT)
    assert any("routes.py" in f.title for f in facts)

    maps = service.store.search(type=MemoryItemType.TEST_MAP)
    assert any("routes.py" in m.title for m in maps)


def test_find_tests_for_file(service, fixture_repo):
    service.persist()
    tests = service.find_tests_for_file("api/routes.py")
    assert "tests/api/test_routes.py" in tests


def test_find_symbols_for_file(service):
    service.persist()
    symbols = service.find_symbols_for_file("api/routes.py")
    names = [s.name for s in symbols]
    assert "health" in names


def test_render_returns_text(service):
    service.persist()
    text = service.render()
    assert "Repo map" in text
    assert "api/routes.py" in text
