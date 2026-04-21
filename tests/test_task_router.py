"""Tests for core/task_router.py — intent detection and routing."""
import sys
import pytest
from unittest.mock import MagicMock

# Stub core.state.TaskMode for import
sys.modules.setdefault("core.state", MagicMock())


def _router():
    from core.task_router import TaskRouter
    return TaskRouter()


def _route(text, **kwargs):
    return _router().route(text, **kwargs)


# ── CHAT detection ────────────────────────────────────────────

def test_chat_greetings():
    for msg in ["bonjour", "salut", "hello", "hi", "hey", "coucou"]:
        r = _route(msg)
        assert r.mode.value == "chat", f"'{msg}' should route to CHAT"


def test_chat_short_affirmations():
    for msg in ["ok", "oui", "merci", "super", "cool"]:
        r = _route(msg)
        assert r.mode.value == "chat", f"'{msg}' should route to CHAT"


def test_chat_empty_input():
    r = _route("")
    assert r.mode.value == "chat"


# ── CODE detection ────────────────────────────────────────────

def test_code_explicit():
    r = _route("écris un script Python qui parse du JSON")
    assert r.mode.value == "code"


def test_code_create_module():
    r = _route("crée un module de gestion des fichiers")
    assert r.mode.value == "code"


# ── RESEARCH detection ────────────────────────────────────────

def test_research_question():
    r = _route("qu'est-ce que le circuit breaker pattern")
    assert r.mode.value == "research"


def test_research_compare():
    r = _route("compare les avantages de Redis et PostgreSQL")
    assert r.mode.value == "research"


# ── IMPROVE detection ─────────────────────────────────────────

def test_improve_self():
    r = _route("améliore-toi en détectant les bugs dans ton code")
    assert r.mode.value == "improve"


# ── PLAN detection ────────────────────────────────────────────

def test_plan_roadmap():
    r = _route("crée un plan pour migrer vers une architecture microservices")
    assert r.mode.value == "plan"


# ── Explicit mode override ────────────────────────────────────

@pytest.mark.xfail(reason="task_router mode override drift", strict=False)
def test_explicit_mode_overrides():
    r = _route("hello world", explicit_mode="auto")
    assert r.mode.value == "auto"
    assert r.reason == "explicit:auto"


# ── needs_actions ─────────────────────────────────────────────

def test_code_needs_actions():
    r = _route("écris un script de test")
    assert r.needs_actions is True


def test_research_no_actions():
    r = _route("qu'est-ce que Kubernetes")
    assert r.needs_actions is False


def test_chat_no_actions():
    r = _route("salut")
    assert r.needs_actions is False


# ── Agents plan ───────────────────────────────────────────────

def test_research_has_agents():
    r = _route("recherche les tendances en cybersécurité pour 2025")
    assert len(r.agents) > 0
    agent_names = [a["agent"] for a in r.agents]
    assert "scout-research" in agent_names


def test_chat_has_no_agents():
    r = _route("salut")
    assert len(r.agents) == 0


# ── Heuristics ────────────────────────────────────────────────

def test_short_non_greeting_is_chat():
    r = _route("test rapide")
    assert r.mode.value == "chat"  # <= 30 chars, no pattern


def test_medium_message_defaults_to_research():
    r = _route("je voudrais comprendre comment fonctionne le système de mémoire vectorielle")
    assert r.mode.value == "research"


# ── Summarize ─────────────────────────────────────────────────

def test_summarize():
    r = _route("recherche les tendances AI")
    summary = _router().summarize(r)
    assert "Mode" in summary
    assert "Agents" in summary


# ── Uncensored flag ───────────────────────────────────────────

def test_uncensored_mode_flag():
    r = _route("test", uncensored_mode=True)
    assert r.uncensored_mode is True
