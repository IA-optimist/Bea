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

def test_agent_output_extraction_has_dedicated_module():
    from api.mission_outputs import extract_agent_outputs

    route_source = Path("api/routes/missions.py").read_text(encoding="utf-8")
    service_source = Path("api/mission_outputs.py").read_text(encoding="utf-8")

    assert callable(extract_agent_outputs)
    assert "def _extract_agent_outputs" not in route_source
    assert "def extract_agent_outputs" in service_source
    assert "from api.mission_outputs import extract_agent_outputs" in route_source

class _FakeMissionRecord:
    status = "DONE"
    created_at = 123.0
    complexity = "high"
    risk_score = 4
    decision_trace = {
        "confidence_score": 0.8,
        "skipped_agents": ["shadow-advisor"],
        "final_output_source": "test",
        "fallback_level_used": 1,
        "approval_reason": "low risk",
        "approval_decision": "auto_approved",
    }

    def to_dict(self):
        return {
            "mission_id": "m-response",
            "final_output": "",
            "plan_summary": "summary text",
            "execution_trace": ["step-a"],
        }


def test_mission_response_assembly_has_dedicated_module(monkeypatch):
    from api import mission_response

    monkeypatch.setattr(
        mission_response,
        "extract_agent_outputs",
        lambda mission_id: {"forge-builder": "built result"},
    )

    data = mission_response.build_mission_response_data("m-response", _FakeMissionRecord())
    route_source = Path("api/routes/missions.py").read_text(encoding="utf-8")
    service_source = Path("api/mission_response.py").read_text(encoding="utf-8")

    assert data["agent_outputs"] == {"forge-builder": "built result"}
    assert data["execution_trace"] == ["step-a"]
    assert data["confidence_score"] == 0.8
    assert data["risk_score"] == 4
    assert callable(mission_response.build_mission_response_data)
    assert "def build_mission_response_data" in service_source
    assert "aggregate_mission_result" not in route_source
    assert "build_safe_final_output" not in route_source
    assert "from api.mission_response import build_mission_response_data" in route_source
