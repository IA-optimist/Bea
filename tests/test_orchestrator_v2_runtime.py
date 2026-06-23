from __future__ import annotations

import pytest

from core.orchestrator_v2 import OrchestratorV2
from config.settings import get_settings


def test_get_inner_does_not_raise_module_not_found():
    """Regression: OrchestratorV2 must not crash on a missing legacy module."""
    v2 = OrchestratorV2(get_settings())
    inner = v2._get_inner()
    assert inner is not None
    assert type(inner).__name__ == "BeaOrchestrator"
