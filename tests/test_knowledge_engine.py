"""
Tests du Knowledge & Capability Engine.

5 tests :
  test_pattern_storage    — enregistrement d'une tâche dans knowledge_index
  test_pattern_similarity — détection de similarité via pattern_detector
  test_capability_score_update — mise à jour et calcul des scores par domaine
  test_experience_reuse   — réutilisation d'expérience dans planner.py
  test_memory_cleanup     — nettoyage local KnowledgeMemory

Ces tests sont conçus pour passer sans Qdrant (fail-open) et sans dépendances externes.
"""
from __future__ import annotations

import sys
import os
import pytest
pytestmark = pytest.mark.integration


# Ensure project root is in path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ─── Test 1 : Pattern Storage ────────────────────────────────────────────────

def test_pattern_storage():
    """
    knowledge_index.record_task doit retourner un bool (True si Qdrant dispo,
    False si indisponible) sans lever d'exception.
    """
    from core.knowledge.knowledge_index import record_task

    result = record_task(
        task_type="bug_fix",
        tools_used=["file_search", "replace_in_file"],
        action_sequence=["search error", "fix import", "run tests"],
        success=True,
        duration_s=12.5,
        errors=[],
        complexity="low",
        pattern_tag="python_import_error",
        goal="fix ImportError in main.py",
    )
    # Doit retourner un bool sans exception
    assert isinstance(result, bool), f"record_task must return bool, got {type(result)}"

    # Même avec des valeurs limites
    result2 = record_task(
        task_type="",
        tools_used=[],
        action_sequence=[],
        success=False,
        duration_s=0,
        errors=["critical error"] * 20,  # tronqué à 10
        goal="",
    )
    assert isinstance(result2, bool), "record_task must return bool even with edge inputs"


# ─── Test 2 : Pattern Similarity ─────────────────────────────────────────────

def test_pattern_similarity():
    """
    pattern_detector.detect_patterns doit retourner un dict structuré
    sans lever d'exception, même si Qdrant est indisponible.
    """
    from core.knowledge.pattern_detector import detect_patterns, find_similar_in_memory

    result = detect_patterns(goal="fix python import error", mission_type="bug_fix")

    # Vérifie la structure du résultat
    assert isinstance(result, dict), "detect_patterns must return dict"
    assert "similar_tasks" in result, "missing 'similar_tasks'"
    assert "memory_match" in result, "missing 'memory_match'"
    assert "effective_tools" in result, "missing 'effective_tools'"
    assert "frequent_errors" in result, "missing 'frequent_errors'"
    assert "effective_sequences" in result, "missing 'effective_sequences'"
    assert "has_prior_knowledge" in result, "missing 'has_prior_knowledge'"
    assert isinstance(result["similar_tasks"], list)
    assert isinstance(result["has_prior_knowledge"], bool)

    # find_similar_in_memory doit également être fail-open
    match = find_similar_in_memory(goal="debug api error", mission_type="api_usage")
    assert match is None or isinstance(match, dict), "must return dict or None"


# ─── Test 3 : Capability Score Update ────────────────────────────────────────

def test_capability_score_update():
    """
    capability_scorer.update_score et get_score doivent fonctionner
    de manière cohérente : score monte avec les succès.
    """
    from core.knowledge.capability_scorer import CapabilityScorer, DOMAINS

    scorer = CapabilityScorer()

    # Score initial (prior neutre = 0.5 si aucune donnée)
    initial_score = scorer.get_score("coding")
    assert 0.0 <= initial_score <= 1.0, f"score must be in [0,1], got {initial_score}"

    # Enregistrer des succès
    for _ in range(5):
        scorer.update_score("coding", success=True, duration_s=30.0, errors=0)

    score_after_success = scorer.get_score("coding")
    assert 0.0 <= score_after_success <= 1.0, "score must stay in [0,1]"
    assert score_after_success >= initial_score, "score should increase after successes"

    # Enregistrer des échecs
    for _ in range(3):
        scorer.update_score("coding", success=False, duration_s=200.0, errors=3)

    score_after_failure = scorer.get_score("coding")
    assert score_after_failure <= score_after_success, "score should decrease after failures"

    # Tous les domaines doivent être accessibles
    all_scores = scorer.get_all_scores()
    for domain in DOMAINS:
        assert domain in all_scores, f"domain {domain} missing from all_scores"
        assert 0.0 <= all_scores[domain] <= 1.0

    # update_from_task_type
    s = scorer.update_from_task_type("deploy", success=True, duration_s=45.0)
    assert 0.0 <= s <= 1.0

    # task_type inconnu → retourne 0.5 sans exception
    s_unknown = scorer.update_from_task_type("unknown_task_xyz", success=True)
    assert s_unknown == 0.5


# ─── Test 4 : Experience Reuse (planner) ─────────────────────────────────────

def test_experience_reuse():
    """
    planner.build_plan doit toujours retourner un dict avec 'steps'.
    Si prior_knowledge est présent, il doit être un dict.
    _search_similar_patterns doit être fail-open.
    """
    from core.planner import build_plan, _search_similar_patterns

    # _search_similar_patterns doit être fail-open
    result = _search_similar_patterns("fix login bug", "bug_fix")
    assert result is None or isinstance(result, dict), \
        "_search_similar_patterns must return dict or None"

    # build_plan doit toujours retourner un plan valide
    plan = build_plan(
        goal="deploy new version of API",
        mission_type="deploy",
        complexity="medium",
        mission_id="test_reuse_001",
    )
    assert isinstance(plan, dict), "build_plan must return dict"
    assert "steps" in plan, "plan must have 'steps'"
    assert isinstance(plan["steps"], list), "'steps' must be a list"
    assert len(plan["steps"]) > 0, "'steps' must not be empty"

    # prior_knowledge, si présent, doit être un dict
    if "prior_knowledge" in plan:
        assert isinstance(plan["prior_knowledge"], dict), \
            "prior_knowledge must be a dict"
        assert "has_prior_knowledge" in plan["prior_knowledge"]

    # Test avec mission_type inconnu
    plan2 = build_plan(goal="do something", mission_type="unknown_type")
    assert "steps" in plan2, "fallback plan must have 'steps'"


# ─── Test 5 : Memory Cleanup ─────────────────────────────────────────────────

def test_memory_cleanup():
    """
    knowledge_cleanup.run_full_cleanup doit retourner un rapport structuré
    sans lever d'exception (même si Qdrant est indisponible).
    """
    from core.knowledge.knowledge_cleanup import (
        run_full_cleanup,
        cleanup_local_memory,
        remove_stale_patterns,
        merge_similar_patterns,
        summarize_experiences,
    )

    # run_full_cleanup — rapport consolidé
    report = run_full_cleanup(
        similarity_threshold=0.8,
        max_age_days=30.0,
        max_entries=100,
    )
    assert isinstance(report, dict), "run_full_cleanup must return dict"
    assert "total_removed" in report, "missing 'total_removed'"
    assert "details" in report, "missing 'details'"
    assert isinstance(report["total_removed"], int)

    # cleanup_local_memory — fonctionne même avec KnowledgeMemory vide
    local_result = cleanup_local_memory()
    assert isinstance(local_result, dict)
    assert "removed_count" in local_result
    assert "total_before" in local_result
    assert "total_after" in local_result

    # remove_stale_patterns — fail-open si Qdrant indisponible
    stale_result = remove_stale_patterns(max_age_days=0.001)  # 0.001 jour = ~1 min
    assert isinstance(stale_result, dict)
    assert "removed_count" in stale_result

    # merge_similar_patterns — fail-open
    merge_result = merge_similar_patterns(similarity_threshold=0.5)
    assert isinstance(merge_result, dict)
    assert "merged_count" in merge_result

    # summarize_experiences — fail-open
    sum_result = summarize_experiences(max_entries=50)
    assert isinstance(sum_result, dict)
    assert "examined_count" in sum_result

    # Vérifier cohérence : total_after <= total_before
    assert local_result["total_after"] <= local_result["total_before"], \
        "cleanup cannot increase entry count"


# ─── Runner (facultatif, pour exécution directe) ─────────────────────────────

if __name__ == "__main__":
    tests = [
        test_pattern_storage,
        test_pattern_similarity,
        test_capability_score_update,
        test_experience_reuse,
        test_memory_cleanup,
    ]
    passed = 0
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
            print(f"  PASS  {test_fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {test_fn.__name__}: {e}")
            failed += 1
    print(f"\n{passed}/{passed + failed} tests passed")
    if failed:
        sys.exit(1)
