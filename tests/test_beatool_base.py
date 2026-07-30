"""Tests pour BEATool, ToolRegistry et ToolResult."""
import pytest
from pydantic import BaseModel

from tools.base import BEATool
from tools.permissions import PermissionLevel
from tools.result import ToolResult
from tools import registry


# --- Fixtures ---

class EchoTool(BEATool):
    name = "echo"
    description = "Retourne le message reçu"
    permission = PermissionLevel.AUTO

    class InputSchema(BaseModel):
        message: str

    async def execute(self, input, context=None) -> ToolResult:
        return ToolResult.ok(output=input.message)


class FailTool(BEATool):
    name = "fail_tool"
    description = "Échoue toujours"

    class InputSchema(BaseModel):
        pass

    async def execute(self, input, context=None) -> ToolResult:
        raise RuntimeError("intentional failure")


@pytest.fixture(autouse=True)
def clean_registry():
    registry.reset()
    yield
    registry.reset()


# --- Tests ---

@pytest.mark.asyncio
async def test_echo_tool_success():
    tool = EchoTool()
    result = await tool({"message": "bonjour"})
    assert result.success
    assert result.output == "bonjour"


@pytest.mark.asyncio
async def test_tool_validation_error():
    tool = EchoTool()
    result = await tool({})  # message manquant
    assert not result.success
    assert "validation" in result.error.lower()


@pytest.mark.asyncio
async def test_tool_exception_caught():
    tool = FailTool()
    result = await tool({})
    assert not result.success
    assert "intentional failure" in result.error


def test_registry_register_and_get():
    registry.register(EchoTool())
    tool = registry.get("echo")
    assert tool is not None
    assert tool.name == "echo"


def test_registry_get_unknown_returns_none():
    assert registry.get("nonexistent") is None


def test_registry_get_or_raise_raises():
    with pytest.raises(KeyError, match="nonexistent"):
        registry.get_or_raise("nonexistent")


def test_registry_list_schemas():
    registry.register(EchoTool())
    schemas = registry.list_schemas()
    assert len(schemas) == 1
    assert schemas[0]["name"] == "echo"
    assert "input_schema" in schemas[0]


@pytest.mark.asyncio
async def test_registry_dispatch():
    registry.register(EchoTool())
    result = await registry.dispatch("echo", {"message": "test"})
    assert result.success
    assert result.output == "test"


@pytest.mark.asyncio
async def test_registry_dispatch_unknown_tool():
    result = await registry.dispatch("ghost", {})
    assert not result.success
    assert "Unknown tool" in result.error


def test_tool_result_ok():
    r = ToolResult.ok(output=42, source="test")
    assert r.success
    assert r.output == 42
    assert r.metadata["source"] == "test"


def test_tool_result_fail():
    r = ToolResult.fail("oops", code=500)
    assert not r.success
    assert r.error == "oops"
    assert r.metadata["code"] == 500
