"""Regression tests for extracting MetaOrchestrator state compatibility."""
from pathlib import Path
import sys
import types


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


def test_meta_orchestrator_state_has_dedicated_module_with_compatibility():
    _install_structlog_stub()
    from core import meta_orchestrator as meta
    from core import meta_orchestrator_state as state

    assert meta.MissionContext is state.MissionContext
    assert meta._VALID_TRANSITIONS is state._VALID_TRANSITIONS
    assert meta._KERNEL_STATE_AVAILABLE is state._KERNEL_STATE_AVAILABLE
    assert meta._get_kernel_sm is state._get_kernel_sm

    source = Path("core/meta_orchestrator.py").read_text(encoding="utf-8")
    assert "class MissionContext" not in source
    assert "from dataclasses import dataclass, field" not in source


def test_meta_orchestrator_state_exports_created_transition():
    _install_structlog_stub()
    from core.meta_orchestrator_state import MissionStatus, _VALID_TRANSITIONS

    assert MissionStatus.PLANNED in _VALID_TRANSITIONS[MissionStatus.CREATED]
    assert MissionStatus.FAILED in _VALID_TRANSITIONS[MissionStatus.CREATED]
