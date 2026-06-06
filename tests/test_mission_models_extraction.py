"""Regression tests for extracting mission dataclasses from core.mission_system."""

from pathlib import Path
import sys
import types

if "structlog" not in sys.modules:
    _structlog = types.ModuleType("structlog")
    _logger = types.SimpleNamespace(
        debug=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )
    _structlog.get_logger = lambda *args, **kwargs: _logger
    sys.modules["structlog"] = _structlog


def test_mission_models_have_dedicated_module_with_mission_system_compatibility():
    from core import mission_models
    from core import mission_system

    for name in ["MissionStep", "MissionPlan", "MissionResult"]:
        assert getattr(mission_system, name) is getattr(mission_models, name)

    source = Path("core/mission_system.py").read_text(encoding="utf-8")
    assert "class MissionStep" not in source
    assert "class MissionPlan" not in source
    assert "class MissionResult" not in source


def test_mission_result_serialization_still_round_trips():
    from core.mission_models import MissionResult
    from core.state import MissionStatus

    result = MissionResult(
        mission_id="m1",
        user_input="build api",
        intent="CREATE",
        status=MissionStatus.DONE,
        final_output="done",
    )

    restored = MissionResult.from_dict(result.to_dict())

    assert restored.mission_id == "m1"
    assert restored.is_done()
    assert "m1"[:8] in restored.summary_line()
