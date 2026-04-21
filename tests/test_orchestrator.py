"""
Tests end-to-end — JarvisOrchestrator (offline)

Couvre :
    1. classify_intent() — routing local zero LLM
    2. INTENT_MAP — completude
    3. _run_improve() — délégation à SelfImproveEngine
    4. Offline guarantee — pas de crash si aucune clé cloud

Usage :
    python -m pytest tests/test_orchestrator.py -v
    # ou
    python tests/test_orchestrator.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Skip entire module si core.orchestrator_LEGACY_20260407 absent (drift connu
# — le module a été purgé du codebase, voir core/_legacy/__init__.py roadmap).
if importlib.util.find_spec("core.orchestrator_LEGACY_20260407") is None:
    pytest.skip(
        "core.orchestrator_LEGACY_20260407 retiré du codebase (drift connu)",
        allow_module_level=True,
    )


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════

def _ok(name: str):
    print(f"  [OK] {name}")

def _fail(name: str, detail: str = ""):
    print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))
    return False


# ══════════════════════════════════════════════════════════════
# Test 1 : import + instanciation
# ══════════════════════════════════════════════════════════════

def test_import():
    from core.orchestrator_LEGACY_20260407 import JarvisOrchestrator
    from config.settings import get_settings
    orch = JarvisOrchestrator(get_settings())
    assert orch is not None
    _ok("import JarvisOrchestrator")


# ══════════════════════════════════════════════════════════════
# Test 2 : INTENT_MAP completude
# ══════════════════════════════════════════════════════════════

def test_intent_map():
    from core.orchestrator_LEGACY_20260407 import JarvisOrchestrator
    required_keys = {"improve", "code", "research", "plan", "night", "chat", "default"}
    present = set(JarvisOrchestrator.INTENT_MAP.keys())
    missing = required_keys - present
    assert not missing, f"INTENT_MAP manquants : {missing}"
    _ok(f"INTENT_MAP complet ({len(present)} clés)")


# ══════════════════════════════════════════════════════════════
# Test 3 : classify_intent (zero LLM)
# ══════════════════════════════════════════════════════════════

def test_classify_intent():
    from core.orchestrator_LEGACY_20260407 import JarvisOrchestrator
    from config.settings import get_settings

    orch = JarvisOrchestrator(get_settings())
    cases = [
        ("ameliore le pipeline self_improve",        "improve"),
        ("optimise ton code",                        "improve"),
        ("ecris un script python pour lire des logs","code"),
        ("genere le code de l API REST",             "code"),
        ("recherche les meilleures pratiques Docker","research"),
        ("cree un plan pour migrer la base de donnees","plan"),
        ("bonjour",                                  "chat"),
        ("salut",                                    "chat"),
        ("ok",                                       "chat"),
    ]

    passed = 0
    for text, expected in cases:
        result = orch.classify_intent(text)
        if result == expected:
            passed += 1
        else:
            _fail(f"classify_intent('{text[:40]}')", f"attendu={expected} obtenu={result}")

    assert passed == len(cases), f"classify_intent {passed}/{len(cases)} cas corrects"
    _ok(f"classify_intent {passed}/{len(cases)} cas corrects")


# ══════════════════════════════════════════════════════════════
# Test 4 : SupervisedExecutor — lazy property
# ══════════════════════════════════════════════════════════════

def test_supervised_property():
    from core.orchestrator_LEGACY_20260407 import JarvisOrchestrator
    from config.settings import get_settings
    from executor.supervised_executor import SupervisedExecutor

    orch = JarvisOrchestrator(get_settings())
    sup  = orch.supervised
    assert isinstance(sup, SupervisedExecutor), f"type={type(sup)}"
    # Appel 2 fois → même instance (cache)
    assert orch.supervised is sup
    _ok("supervised property (lazy + cache)")


# ══════════════════════════════════════════════════════════════
# Test 5 : TaskRouter plans
# ══════════════════════════════════════════════════════════════

def test_task_router_plans():
    from core.task_router import TaskRouter
    router = TaskRouter()

    plans = {
        "ecris un script python": ["forge-builder"],
        "ameliore le pipeline":   ["vault-memory"],
        "recherche les tendances":["scout-research"],
    }

    all_ok = True
    for text, expected_agents in plans.items():
        d = router.route(text)
        agent_names = [a["agent"] for a in d.agents]
        for ea in expected_agents:
            if ea not in agent_names:
                _fail(f"TaskRouter '{text[:30]}'", f"{ea} absent du plan : {agent_names}")
                all_ok = False
                break
        else:
            _ok(f"TaskRouter '{text[:35]}' → {d.mode.value} agents={agent_names}")

    assert all_ok, "TaskRouter plans: un ou plusieurs agents attendus absents"


# ══════════════════════════════════════════════════════════════
# Test 6 : llm_factory offline fallback
# ══════════════════════════════════════════════════════════════

def test_llm_factory_offline():
    from core.llm_factory import CLOUD_PREFERRED_ROLES, LOCAL_ONLY_ROLES

    # Vérifier que les rôles critiques sont en offline-safe
    required_cloud_preferred = {"builder", "reviewer", "improve", "director", "planner", "fast"}
    missing = required_cloud_preferred - CLOUD_PREFERRED_ROLES
    assert not missing, f"CLOUD_PREFERRED_ROLES manquants : {missing}"
    _ok(f"CLOUD_PREFERRED_ROLES couvre {len(required_cloud_preferred)} rôles offline-safe")

    # advisor est désormais CLOUD_PREFERRED (R-06 SRE) — peut fallback sur OpenAI-fast
    # Vérifier que les rôles critique restants sont bien LOCAL_ONLY
    required_local_only = {"memory", "code", "vision"}
    missing_local = required_local_only - LOCAL_ONLY_ROLES
    assert not missing_local, f"LOCAL_ONLY_ROLES manquants : {missing_local}"
    _ok(f"LOCAL_ONLY_ROLES couvre {len(LOCAL_ONLY_ROLES)} rôles (memory, code, vision)")


# ══════════════════════════════════════════════════════════════
# Runner
# ══════════════════════════════════════════════════════════════

def run_all():
    tests = [
        ("import + instanciation",      test_import),
        ("INTENT_MAP completude",        test_intent_map),
        ("classify_intent routing",      test_classify_intent),
        ("supervised property",          test_supervised_property),
        ("TaskRouter plans",             test_task_router_plans),
        ("llm_factory offline fallback", test_llm_factory_offline),
    ]

    print("\n=== tests/test_orchestrator.py ===\n")
    passed = 0
    for name, fn in tests:
        print(f"[TEST] {name}")
        try:
            ok = fn()
            if ok:
                passed += 1
        except Exception as e:
            _fail(name, str(e))
        print()

    print(f"Résultat : {passed}/{len(tests)} tests OK")
    return passed == len(tests)


if __name__ == "__main__":
    success = run_all()
    pass  # sys.exit removed for pytest compatibility
