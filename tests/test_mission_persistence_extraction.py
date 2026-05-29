"""Regression tests for extracting MissionSystem persistence helpers."""

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


def test_mission_persistence_helpers_have_dedicated_module(tmp_path, monkeypatch):
    from pathlib import Path

    from core import db as db_mod

    from core import mission_persistence
    from core.mission_models import MissionResult
    from core.state import MissionStatus

    mission = MissionResult(
        mission_id="m-persist",
        user_input="persist me",
        intent="CREATE",
        status=MissionStatus.DONE,
        final_output="done",
    )
    path = tmp_path / "missions.json"
    logger = types.SimpleNamespace(
        debug=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(db_mod, "get_db", lambda: None)
    mission_persistence.save_missions(path, {mission.mission_id: mission}, 200, logger)
    loaded, use_sqlite = mission_persistence.load_missions(path, logger)

    source = Path("core/mission_system.py").read_text(encoding="utf-8")
    assert loaded["m-persist"].final_output == "done"
    assert use_sqlite is False
    assert callable(mission_persistence.sqlite_upsert_mission)
    assert "SELECT * FROM missions" not in source
    assert "INSERT OR REPLACE INTO missions" not in source
    assert "json.loads(self._path.read_text" not in source
