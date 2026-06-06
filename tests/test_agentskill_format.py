"""Tests pour core.skills.agentskill_format — round-trip réel, sans mock."""
from __future__ import annotations

from core.skills.agentskill_format import (
    from_agentskill,
    propose_skill_from_mission,
    to_agentskill,
)
from core.skills.skill_models import Skill, SkillStep


def _sample() -> Skill:
    return Skill(
        name="Fix API 500",
        description="Diagnostique et corrige une 500 sur un endpoint FastAPI",
        problem_type="api_fix",
        context="quand un endpoint renvoie 500",
        prerequisites=["accès aux logs"],
        tools_used=["read_file", "shell_command"],
        steps=[
            SkillStep(order=1, description="lire les logs", tool="read_file"),
            SkillStep(order=2, description="rejouer la requête", tool="http_get",
                      code_snippet="curl localhost/x"),
        ],
        pitfalls=["ne pas redémarrer en prod"],
        tags=["api", "debug"],
        risk_level="medium",
    )


def test_roundtrip_lossless():
    skill = _sample()
    md = to_agentskill(skill)
    back = from_agentskill(md)
    assert back.name == skill.name
    assert back.problem_type == "api_fix"
    assert back.tags == ["api", "debug"]
    assert len(back.steps) == 2
    assert back.steps[1].tool == "http_get"
    assert back.steps[1].code_snippet == "curl localhost/x"
    assert back.risk_level == "medium"


def test_markdown_is_human_readable():
    md = to_agentskill(_sample())
    assert md.startswith("---")
    assert "name: Fix API 500" in md
    assert "## Procédure" in md
    assert "1. lire les logs (tool: read_file)" in md


def test_parse_external_skill_md_without_data_block():
    external = (
        "---\n"
        "name: External Skill\n"
        "description: un skill venu d'ailleurs\n"
        "tags: [x, y]\n"
        "---\n\n"
        "# External Skill\n\nblah\n"
    )
    s = from_agentskill(external)
    assert s.name == "External Skill"
    assert s.description == "un skill venu d'ailleurs"
    assert s.tags == ["x", "y"]


def test_empty_input():
    s = from_agentskill("")
    assert isinstance(s, Skill)
    assert s.name == ""


def test_propose_skill_from_mission():
    s = propose_skill_from_mission(
        mission_id="m123",
        name="Deploy flow",
        description="déploiement standard",
        steps=[{"description": "build", "tool": "docker_compose_build"},
               "smoke test"],
        tools_used=["docker_compose_build"],
        problem_type="deployment",
        confidence=1.5,  # doit être clampé à 1.0
    )
    assert s.source_mission_id == "m123"
    assert s.confidence == 1.0
    assert len(s.steps) == 2
    assert s.steps[0].tool == "docker_compose_build"
    assert s.steps[1].order == 2
    # round-trip après extraction
    assert from_agentskill(to_agentskill(s)).name == "Deploy flow"
