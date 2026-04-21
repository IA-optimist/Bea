"""Tests du pipeline guard — garantie final_output non vide."""
import pytest
from api.pipeline_guard import build_safe_final_output

def _ao(name, result):
    return {"agent_name": name, "result": result}


def test_valid_output():
    """final_output explicite → retourné tel quel."""
    out = build_safe_final_output("Bonjour, je suis Jarvis.", [], "m1")
    assert out == "Bonjour, je suis Jarvis."


def test_synthesis_from_agents():
    """final_output vide → synthèse depuis agent_outputs."""
    aos = [_ao("scout", "Résultat de recherche"), _ao("lens", "Analyse terminée")]
    out = build_safe_final_output("", aos, "m2")
    assert "scout" in out
    assert "Résultat de recherche" in out
    assert out.strip() != ""


def test_fallback_when_agents_empty():
    """final_output vide + agent_outputs vide → fallback message."""
    out = build_safe_final_output("", [], "m3")
    assert out.strip() != ""
    assert len(out) > 10


def test_agent_returns_empty_string():
    """Agent retourne "" → synthèse ignore, fallback activé."""
    aos = [_ao("agent1", ""), _ao("agent2", "   ")]
    out = build_safe_final_output("", aos, "m4")
    assert out.strip() != ""


def test_agent_outputs_none_fields():
    """Agent avec result=None → ignoré proprement."""
    aos = [{"agent_name": "a", "result": None}, {"agent_name": "b", "result": "Réponse valide"}]
    out = build_safe_final_output(None, aos, "m5")
    assert "Réponse valide" in out


def test_exception_in_chain():
    """Même si agent_outputs contient des objets malformés → pas de crash."""
    aos = [{"broken": True}, None, _ao("good", "OK")]
    try:
        out = build_safe_final_output("", aos, "m6")
        assert out.strip() != ""
    except Exception as e:
        pytest.fail(f"Pipeline guard crashed: {e}")
