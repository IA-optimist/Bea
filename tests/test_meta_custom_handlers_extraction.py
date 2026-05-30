"""Regression tests for extracting MetaOrchestrator custom handler methods."""
import sys
import types

import pytest


class _StructlogStub(types.SimpleNamespace):
    def get_logger(self, *_args, **_kwargs):
        return types.SimpleNamespace(
            debug=lambda *_a, **_k: None,
            info=lambda *_a, **_k: None,
            warning=lambda *_a, **_k: None,
            error=lambda *_a, **_k: None,
        )


def _install_structlog_stub():
    sys.modules.setdefault("structlog", _StructlogStub())


@pytest.mark.asyncio
async def test_custom_mission_handlers_live_in_mixin_with_meta_compatibility():
    _install_structlog_stub()
    from core import meta_orchestrator as meta
    from core.meta_custom_handlers import CustomMissionHandlerMixin

    assert issubclass(meta.MetaOrchestrator, CustomMissionHandlerMixin)

    source = open("core/meta_orchestrator.py", encoding="utf-8").read()
    assert "def register_mission_handler" not in source
    assert "def dispatch_custom_mission" not in source

    class Harness(CustomMissionHandlerMixin):
        def __init__(self):
            self._custom_handlers = {}

    async def handler(mission, context):
        return {"mission": mission, "context": context}

    harness = Harness()
    harness.register_mission_handler("demo", handler)
    result = await harness.dispatch_custom_mission("demo", {"x": 1}, {"y": 2})
    assert result == {"mission": {"x": 1}, "context": {"y": 2}}

    with pytest.raises(KeyError):
        await harness.dispatch_custom_mission("missing", {}, {})
