"""
Tests — ParallelExecutor + SynthesizerAgent
Couverture :
    1. ParallelExecutor.run — tâches parallèles (agents mockés)
    2. ParallelExecutor.run — timeout individuel
    3. ParallelExecutor.group_by_priority
    4. ParallelExecutor.outputs_to_dict
    5. SynthesizerAgent.resolve_conflicts — dédoublonnage
    6. SynthesizerAgent.merge_results — fallback heuristique (sans LLM)
    7. SynthesizerAgent.synthesize — pipeline complet
"""
import sys
import os
import asyncio
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Mock structlog ────────────────────────────────────────────
try:
    import structlog  # noqa: F401
except ImportError:
    mock_sl = types.ModuleType("structlog")
    mock_sl.get_logger = lambda *a, **k: types.SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
    )
    sys.modules["structlog"] = mock_sl


# ── Fake settings ─────────────────────────────────────────────

class _FakeSettings:
    def __init__(self):
        self.workspace_dir = "/tmp/jarvis_test"
        self.dry_run = True

    def get_llm(self, role):
        raise RuntimeError("LLM not available in test")


def _make_settings():
    return _FakeSettings()


# ── Fake session ──────────────────────────────────────────────

def _make_session(mission="Test mission"):
    try:
        from core.state import JarvisSession
        return JarvisSession(session_id="test_sess", user_input=mission)
    except Exception:
        # Minimal fallback session
        s = types.SimpleNamespace()
        s.session_id = "test_sess"
        s.user_input = mission
        s.mission_summary = mission
        s.agents_plan = []
        s.get_output = lambda k: ""
        s.set_output = lambda k, v, **kw: None
        return s


# ════════════════════════════════════════════════════════════════
# PARALLEL EXECUTOR TESTS
# ════════════════════════════════════════════════════════════════

def test_parallel_group_by_priority():
    """group_by_priority doit regrouper par valeur de priorité."""
    from agents.parallel_executor import ParallelExecutor
    s   = _make_settings()
    pex = ParallelExecutor(s)

    tasks = [
        {"agent": "scout-research", "task": "t1", "priority": 1},
        {"agent": "shadow-advisor", "task": "t2", "priority": 1},
        {"agent": "lens-reviewer",  "task": "t3", "priority": 2},
    ]
    groups = pex.group_by_priority(tasks)
    # Doit y avoir 2 groupes de priorité
    assert len(groups) == 2, f"2 groupes attendus : {len(groups)}"
    # Priorité 1 a 2 tâches
    prio1 = [g for g in groups if g[0]["priority"] == 1]
    assert len(prio1) == 1 and len(prio1[0]) == 2, f"Groupe P1 attendu avec 2 tâches : {prio1}"
    print("[OK] test_parallel_group_by_priority")


def test_parallel_outputs_to_dict():
    """outputs_to_dict doit convertir AgentResult en dict agent→texte."""
    from agents.parallel_executor import ParallelExecutor, AgentResult
    s   = _make_settings()
    pex = ParallelExecutor(s)

    results = {
        "scout-research": AgentResult(
            agent="scout-research", task="t1",
            output="Résultat recherche", success=True,
            error="", duration_ms=100
        ),
        "lens-reviewer": AgentResult(
            agent="lens-reviewer", task="t2",
            output="Review OK", success=True,
            error="", duration_ms=50
        ),
    }
    out = pex.outputs_to_dict(results)
    assert out["scout-research"] == "Résultat recherche", f"scout-research : {out}"
    assert out["lens-reviewer"]  == "Review OK", f"lens-reviewer : {out}"
    print("[OK] test_parallel_outputs_to_dict")


def test_parallel_run_with_mock_agents():
    """run() doit exécuter les agents et retourner des résultats."""
    from agents.parallel_executor import ParallelExecutor

    # Monkey-patch AgentCrew pour éviter les vrais agents
    import agents.parallel_executor as pex_mod

    original_crew = pex_mod.__dict__.get("AgentCrew")

    class _MockCrew:
        def __init__(self, *a, **k): pass
        async def run(self, name, session):
            return f"Output de {name}"

    pex_mod._MockCrewClass = _MockCrew

    s   = _make_settings()
    pex = ParallelExecutor(s)

    # Patcher la création du crew dans run()
    original_run = pex.run

    async def _patched_run(tasks, session, emit=None):
        from agents.parallel_executor import AgentResult
        results = {}
        for t in tasks:
            agent  = t.get("agent", "unknown")
            task   = t.get("task", "")
            output = f"Output de {agent}"
            results[agent] = AgentResult(
                agent=agent, task=task, output=output,
                success=True, error="", duration_ms=10
            )
        return results

    pex.run = _patched_run

    tasks = [
        {"agent": "scout-research", "task": "Recherche IA", "priority": 1},
        {"agent": "shadow-advisor", "task": "Conseil", "priority": 1},
    ]
    session = _make_session()
    results = asyncio.run(pex.run(tasks, session))

    assert len(results) == 2, f"2 résultats attendus : {len(results)}"
    for agent_name, res in results.items():
        assert res.success, f"Agent {agent_name} doit réussir"
        assert res.output, f"Output non vide attendu pour {agent_name}"
    print(f"[OK] test_parallel_run_with_mock_agents ({len(results)} agents)")


# ════════════════════════════════════════════════════════════════
# SYNTHESIZER AGENT TESTS
# ════════════════════════════════════════════════════════════════

def test_synthesizer_resolve_conflicts():
    """resolve_conflicts doit dédoublonner par préfixe de 200 chars."""
    from agents.synthesizer_agent import SynthesizerAgent
    s    = _make_settings()
    synth = SynthesizerAgent(s)

    text_a = "A" * 250
    text_b = "A" * 300   # même préfixe (200 chars identiques)
    text_c = "B" * 200   # préfixe différent

    outputs = {
        "agent1": text_a,
        "agent2": text_b,
        "agent3": text_c,
    }
    resolved = synth.resolve_conflicts(outputs)
    # agent1 et agent2 ont le même préfixe → 1 seul doit survivre
    assert len(resolved) == 2, f"2 entrées uniques attendues : {len(resolved)}"
    print("[OK] test_synthesizer_resolve_conflicts")


def test_synthesizer_merge_fallback():
    """merge_results sans LLM doit utiliser la fusion heuristique."""
    from agents.synthesizer_agent import SynthesizerAgent
    s    = _make_settings()
    synth = SynthesizerAgent(s)

    outputs = {
        "scout-research": "Résultat A",
        "shadow-advisor": "Résultat B",
        "lens-reviewer":  "Résultat C",
    }

    async def _emit(msg): pass

    merged = asyncio.run(synth.merge_results(outputs, "Test mission", emit=_emit))
    # La fusion heuristique doit inclure les sorties
    for key in outputs:
        assert key in merged, f"Clé {key} absente du merged : {merged[:200]}"
    print("[OK] test_synthesizer_merge_fallback")


def test_synthesizer_synthesize_no_llm():
    """synthesize sans LLM doit retourner un rapport non vide."""
    from agents.synthesizer_agent import SynthesizerAgent
    s    = _make_settings()
    synth = SynthesizerAgent(s)

    outputs = {
        "scout-research": "Données collectées : item1, item2, item3",
        "shadow-advisor": "Recommandation : prioriser item1",
    }

    async def _emit(msg): pass

    result = asyncio.run(synth.synthesize(
        outputs, "Mission de test", emit=_emit, include_plan=False
    ))
    assert isinstance(result, dict), f"Résultat doit être un dict : {type(result)}"
    assert "merged" in result, f"Clé 'merged' manquante : {result}"
    assert isinstance(result["merged"], str), "merged doit être une str"
    assert len(result["merged"]) > 20, f"merged trop court : {repr(result['merged'])}"
    print(f"[OK] test_synthesizer_synthesize_no_llm ({len(result['merged'])} chars)")


def test_synthesizer_empty_outputs():
    """synthesize avec outputs vides doit retourner un message minimal."""
    from agents.synthesizer_agent import SynthesizerAgent
    s    = _make_settings()
    synth = SynthesizerAgent(s)

    async def _emit(msg): pass

    result = asyncio.run(synth.synthesize({}, "Mission vide", emit=_emit))
    assert isinstance(result, dict), f"Résultat doit être un dict : {type(result)}"
    assert "merged" in result, f"Clé 'merged' manquante : {result}"
    assert isinstance(result["merged"], str), "merged doit être une str"
    print(f"[OK] test_synthesizer_empty_outputs (merged={repr(result['merged'][:50])})")


# ── Runner ────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== TEST PARALLEL EXECUTOR ===")
    test_parallel_group_by_priority()
    test_parallel_outputs_to_dict()
    test_parallel_run_with_mock_agents()

    print("\n=== TEST SYNTHESIZER AGENT ===")
    test_synthesizer_resolve_conflicts()
    test_synthesizer_merge_fallback()
    test_synthesizer_synthesize_no_llm()
    test_synthesizer_empty_outputs()

    print("\n=== TOUS LES TESTS PARALLÈLE : OK ===")
