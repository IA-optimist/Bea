"""Tests d'intégration des outils builtin."""
import sys

import pytest
from tools import registry
from tools.builtin import register_builtin_tools


@pytest.fixture(autouse=True)
def setup_registry():
    registry.reset()
    register_builtin_tools()
    yield
    registry.reset()


def test_all_builtin_tools_registered():
    names = {t.name for t in registry.list_tools()}
    expected = {"read_file", "write_file", "run_command", "http_get", "http_post", "web_search"}
    assert expected.issubset(names)


def test_schemas_are_valid():
    schemas = registry.list_schemas()
    assert len(schemas) >= 6
    for s in schemas:
        assert "name" in s
        assert "description" in s
        assert "input_schema" in s
        assert "permission" in s


@pytest.mark.asyncio
async def test_dispatch_read_file_missing(tmp_path):
    result = await registry.dispatch("read_file", {"path": str(tmp_path / "ghost.py")})
    assert not result.success
    assert "introuvable" in result.error


@pytest.mark.asyncio
async def test_dispatch_write_then_read(tmp_path):
    path = str(tmp_path / "hello.md")
    write_result = await registry.dispatch("write_file", {"path": path, "content": "# Hello"})
    assert write_result.success

    read_result = await registry.dispatch("read_file", {"path": path})
    assert read_result.success
    assert read_result.output == "# Hello"


@pytest.mark.asyncio
async def test_run_command_echo():
    result = await registry.dispatch("run_command", {"command": "echo béa"})
    assert result.success
    assert "béa" in result.output


@pytest.mark.asyncio
async def test_run_command_timeout():
    command = f'"{sys.executable}" -c "import time; time.sleep(10)"'
    result = await registry.dispatch("run_command", {"command": command, "timeout": 1})
    assert not result.success
    assert "timeout" in result.error.lower()


@pytest.mark.asyncio
async def test_write_file_blocked_critical():
    result = await registry.dispatch(
        "write_file",
        {"path": "config/settings.py", "content": "malicious"}
    )
    assert not result.success
    assert "bloqu" in result.error
