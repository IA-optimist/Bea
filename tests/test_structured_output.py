"""Tests pour core.structured_output — parsing réel, sans mock."""
from __future__ import annotations

from core.structured_output import extract_json, parse_structured


def test_plain_json():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_json_in_code_fence():
    text = 'Voici le résultat:\n```json\n{"status": "ok", "n": 3}\n```\nVoilà.'
    assert extract_json(text) == {"status": "ok", "n": 3}


def test_json_with_surrounding_prose():
    text = 'Bien sûr ! {"plan": ["a", "b"]} — fin.'
    assert extract_json(text) == {"plan": ["a", "b"]}


def test_no_json():
    assert extract_json("pas de json ici") is None
    assert parse_structured("rien")["ok"] is False
    assert parse_structured("rien")["error"] == "no_json_found"


def test_required_keys_ok_and_missing():
    ok = parse_structured('{"x": 1, "y": 2}', required_keys=["x", "y"])
    assert ok["ok"] is True
    miss = parse_structured('{"x": 1}', required_keys=["x", "y"])
    assert miss["ok"] is False and "missing_keys" in miss["error"]


def test_pydantic_validation():
    try:
        from pydantic import BaseModel
    except ImportError:
        return  # pydantic absent : test ignoré
    class Plan(BaseModel):
        title: str
        steps: int
    good = parse_structured('{"title": "x", "steps": 3}', model=Plan)
    assert good["ok"] is True and good["data"]["steps"] == 3
    bad = parse_structured('{"title": "x"}', model=Plan)  # steps manquant
    assert bad["ok"] is False and "validation_failed" in bad["error"]
