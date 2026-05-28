"""Regression tests for extracting mission route schemas."""

from pathlib import Path


def test_mission_route_schemas_have_dedicated_module():
    from api import schemas_missions as schemas

    expected = {
        "TaskRequest",
        "ModeRequest",
        "TriggerRequest",
        "AbortRequest",
        "MissionSubmitRequest",
        "ApproveRequest",
    }

    for name in expected:
        assert hasattr(schemas, name)

    route_source = Path("api/routes/missions.py").read_text(encoding="utf-8")
    schema_source = Path("api/schemas_missions.py").read_text(encoding="utf-8")

    for name in expected:
        assert f"class {name}" not in route_source
        assert f"class {name}" in schema_source

    assert "from api.schemas_missions import" in route_source
