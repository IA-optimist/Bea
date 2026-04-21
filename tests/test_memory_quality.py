"""
Tests — Memory Quality Scoring (core/knowledge/memory_quality.py)

4 tests :
  test_high_quality_memory    — succès propre → bon score (>0.7)
  test_failure_with_rollback  — failure + rollback → score faible (<0.4)
  test_anti_pattern_detection — anti-patterns détectés correctement
  test_quality_report_structure — rapport complet bien structuré
"""
from __future__ import annotations

import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ─── Test 1 : Haute qualité ───────────────────────────────────────────────────

def test_high_quality_memory():
    """
    Mission réussie, sans retry ni rollback → score élevé (> 0.7).
    """
    from core.knowledge.memory_quality import compute_memory_quality, classify_memory, QUALITY_HIGH

    mission_data = {
        "success": True,
        "result_status": "success",
        "duration_s": 30.0,
        "retry_count": 0,
        "rollback_count": 0,
        "error_count": 0,
        "timeout_count": 0,
        "loop_detected": False,
        "mission_type": "bug_fix",
    }
    score = compute_memory_quality(mission_data)
    assert 0.0 <= score <= 1.0, f"score must be in [0,1], got {score}"
    assert score > 0.7, f"clean success should score > 0.7, got {score}"
    assert classify_memory(score) == QUALITY_HIGH, f"should be HIGH, got {classify_memory(score)}"


# ─── Test 2 : Failure avec rollback ──────────────────────────────────────────

def test_failure_with_rollback():
    """
    Mission échouée + rollback → score faible (< 0.4).
    """
    from core.knowledge.memory_quality import compute_memory_quality, classify_memory

    mission_data = {
        "success": False,
        "result_status": "failure",
        "duration_s": 300.0,
        "retry_count": 3,
        "rollback_count": 1,
        "error_count": 5,
        "timeout_count": 0,
        "loop_detected": False,
        "mission_type": "bug_fix",
    }
    score = compute_memory_quality(mission_data)
    assert 0.0 <= score <= 1.0, f"score must be in [0,1], got {score}"
    assert score < 0.4, f"failure+rollback should score < 0.4, got {score}"

    # Mémoire de faible valeur ne doit pas être prioritaire comme référence positive
    label = classify_memory(score)
    assert label in ("low_value", "anti_pattern"), \
        f"bad mission should be low_value or anti_pattern, got {label}"


# ─── Test 3 : Détection anti-patterns ─────────────────────────────────────────

def test_anti_pattern_detection():
    """
    Anti-patterns (boucle, timeouts répétés, échec + retry excessif) détectés.
    """
    from core.knowledge.memory_quality import is_anti_pattern, compute_memory_quality

    # Boucle détectée
    loop_mission = {
        "success": False,
        "loop_detected": True,
        "retry_count": 1,
        "rollback_count": 0,
    }
    assert is_anti_pattern(loop_mission) is True, "loop_detected must be anti_pattern"
    score = compute_memory_quality(loop_mission)
    assert score < 0.3, f"loop anti-pattern score should be < 0.3, got {score}"

    # Timeouts répétés
    timeout_mission = {
        "success": False,
        "timeout_count": 3,
        "retry_count": 2,
        "rollback_count": 0,
        "loop_detected": False,
    }
    assert is_anti_pattern(timeout_mission) is True, "3+ timeouts must be anti_pattern"

    # Retries excessifs avec échec
    retry_mission = {
        "success": False,
        "retry_count": 5,
        "rollback_count": 0,
        "loop_detected": False,
        "timeout_count": 0,
    }
    assert is_anti_pattern(retry_mission) is True, "5 retries + failure must be anti_pattern"

    # Mission normale (succès) → pas d'anti-pattern
    ok_mission = {
        "success": True,
        "retry_count": 0,
        "rollback_count": 0,
        "loop_detected": False,
        "timeout_count": 0,
    }
    assert is_anti_pattern(ok_mission) is False, "clean success must not be anti_pattern"


# ─── Test 4 : Rapport structuré ──────────────────────────────────────────────

def test_quality_report_structure():
    """
    get_quality_report doit toujours retourner un dict bien structuré.
    Testé aussi avec des données vides (fail-open).
    """
    from core.knowledge.memory_quality import get_quality_report

    # Données complètes
    report = get_quality_report({
        "success": True,
        "duration_s": 45.0,
        "retry_count": 1,
        "rollback_count": 0,
        "error_count": 1,
        "mission_type": "coding_task",
    })
    assert isinstance(report, dict), "must return dict"
    assert "score" in report
    assert "label" in report
    assert "should_store" in report
    assert "is_anti_pattern" in report
    assert "reasons" in report
    assert 0.0 <= report["score"] <= 1.0
    assert isinstance(report["label"], str)
    assert isinstance(report["is_anti_pattern"], bool)
    assert isinstance(report["reasons"], list)

    # Données vides → fail-open
    report_empty = get_quality_report({})
    assert isinstance(report_empty, dict), "must not crash on empty input"
    assert "score" in report_empty
    assert 0.0 <= report_empty["score"] <= 1.0

    # Input invalide → fail-open
    report_bad = get_quality_report({"success": "not_a_bool", "retry_count": "abc"})
    assert isinstance(report_bad, dict)


# ─── Runner ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_high_quality_memory,
        test_failure_with_rollback,
        test_anti_pattern_detection,
        test_quality_report_structure,
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
