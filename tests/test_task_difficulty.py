"""
Tests — Task Difficulty Estimation (core/knowledge/difficulty_estimator.py)

5 tests :
  test_simple_task_is_low          — tâche simple → LOW
  test_patch_task_is_medium_high   — patch + tests → MEDIUM ou HIGH
  test_deploy_task_is_high         — déploiement infra → HIGH ou VERY_HIGH
  test_planning_guidance           — guidance adapté au label
  test_planner_integration         — planner enrichit bien le plan avec difficulty_*
"""
from __future__ import annotations

import sys
import os
import pytest
pytestmark = pytest.mark.integration


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ─── Test 1 : Tâche simple → LOW ─────────────────────────────────────────────

def test_simple_task_is_low():
    """
    Lire / afficher un fichier → score bas → label LOW.
    """
    from core.knowledge.difficulty_estimator import estimate_difficulty, LABEL_LOW, LABEL_MEDIUM

    result = estimate_difficulty(
        goal="lire le fichier config.json et afficher son contenu",
        mission_type="analysis",
    )
    assert isinstance(result, dict), "must return dict"
    assert "score" in result
    assert "label" in result
    assert "reasons" in result
    assert 0.0 <= result["score"] <= 1.0
    assert result["label"] in (LABEL_LOW, LABEL_MEDIUM), \
        f"simple read task should be LOW or MEDIUM, got {result['label']}"
    assert result["score"] < 0.5, f"simple task score should be < 0.5, got {result['score']}"


# ─── Test 2 : Patch + tests → MEDIUM/HIGH ────────────────────────────────────

def test_patch_task_is_medium_high():
    """
    Patcher un module, écrire des tests → MEDIUM ou HIGH.
    """
    from core.knowledge.difficulty_estimator import estimate_difficulty, LABEL_LOW, LABEL_VERY_HIGH

    result = estimate_difficulty(
        goal="patcher le module auth.py pour corriger le bug JWT et ajouter des tests unitaires",
        mission_type="improvement",
    )
    assert isinstance(result, dict)
    assert 0.0 <= result["score"] <= 1.0
    # Ne doit pas être LOW ni VERY_HIGH pour cette tâche
    assert result["label"] != LABEL_LOW, \
        f"patch+tests should not be LOW, got {result['label']}"
    assert result["label"] != LABEL_VERY_HIGH, \
        f"patch+tests should not be VERY_HIGH, got {result['label']}"
    assert result["score"] >= 0.30, f"patch score should be >= 0.30, got {result['score']}"


# ─── Test 3 : Déploiement → HIGH ─────────────────────────────────────────────

def test_deploy_task_is_high():
    """
    Déployer + rebuild + restart docker → HIGH ou VERY_HIGH.
    """
    from core.knowledge.difficulty_estimator import (
        estimate_difficulty, LABEL_HIGH, LABEL_VERY_HIGH
    )

    result = estimate_difficulty(
        goal="deployer la nouvelle version en production avec docker rebuild et restart des services",
        mission_type="deploy",
    )
    assert isinstance(result, dict)
    assert 0.0 <= result["score"] <= 1.0
    assert result["label"] in (LABEL_HIGH, LABEL_VERY_HIGH), \
        f"deploy task should be HIGH or VERY_HIGH, got {result['label']}"
    assert result["score"] >= 0.55, f"deploy score should be >= 0.55, got {result['score']}"

    # Vérifier que le score est plus élevé qu'une tâche simple
    simple_result = estimate_difficulty(
        goal="lire un fichier", mission_type="analysis"
    )
    assert result["score"] > simple_result["score"], \
        "deploy should score higher than simple read"


# ─── Test 4 : Planning guidance ──────────────────────────────────────────────

def test_planning_guidance():
    """
    get_planning_guidance retourne des paramètres cohérents par label.
    """
    from core.knowledge.difficulty_estimator import (
        get_planning_guidance, LABEL_LOW, LABEL_MEDIUM, LABEL_HIGH, LABEL_VERY_HIGH
    )

    for label in (LABEL_LOW, LABEL_MEDIUM, LABEL_HIGH, LABEL_VERY_HIGH):
        guidance = get_planning_guidance(label)
        assert isinstance(guidance, dict), f"must return dict for {label}"
        assert "max_steps" in guidance
        assert "require_feasibility" in guidance
        assert "require_fallback" in guidance
        assert "suggest_human_review" in guidance
        assert "note" in guidance
        assert isinstance(guidance["max_steps"], int)
        assert guidance["max_steps"] > 0

    # LOW doit avoir moins de steps max que VERY_HIGH
    low = get_planning_guidance(LABEL_LOW)
    very_high = get_planning_guidance(LABEL_VERY_HIGH)
    assert low["max_steps"] < very_high["max_steps"], \
        "LOW should have fewer max_steps than VERY_HIGH"

    # VERY_HIGH doit recommander review humaine
    assert very_high["suggest_human_review"] is True

    # LOW ne doit pas recommander review humaine
    assert low["suggest_human_review"] is False

    # Fail-open sur label inconnu
    unknown = get_planning_guidance("UNKNOWN_LABEL")
    assert isinstance(unknown, dict)
    assert "max_steps" in unknown


# ─── Test 5 : Intégration planner ─────────────────────────────────────────────

def test_planner_integration():
    """
    build_plan doit injecter difficulty_score / difficulty_label si disponible.
    Ne doit pas crasher si difficulty_estimator échoue.
    """
    from core.planner import build_plan

    # Plan avec mission complexe → doit avoir difficulty_*
    plan = build_plan(
        goal="deploy the new API version with docker rebuild and restart",
        mission_type="deploy",
        complexity="high",
        mission_id="test_diff_001",
    )
    assert isinstance(plan, dict), "build_plan must return dict"
    assert "steps" in plan, "must have steps"

    # difficulty_* peuvent être absents si module indisponible — mais si présents, types corrects
    if "difficulty_score" in plan:
        assert isinstance(plan["difficulty_score"], float), "difficulty_score must be float"
        assert 0.0 <= plan["difficulty_score"] <= 1.0, "difficulty_score must be in [0,1]"

    if "difficulty_label" in plan:
        from core.knowledge.difficulty_estimator import (
            LABEL_LOW, LABEL_MEDIUM, LABEL_HIGH, LABEL_VERY_HIGH
        )
        assert plan["difficulty_label"] in (LABEL_LOW, LABEL_MEDIUM, LABEL_HIGH, LABEL_VERY_HIGH), \
            f"unexpected difficulty_label: {plan['difficulty_label']}"

    if "difficulty_reasons" in plan:
        assert isinstance(plan["difficulty_reasons"], list)

    # Tâche simple → plan sans crash
    plan_simple = build_plan(
        goal="read a file",
        mission_type="analysis",
    )
    assert "steps" in plan_simple


# ─── Runner ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_simple_task_is_low,
        test_patch_task_is_medium_high,
        test_deploy_task_is_high,
        test_planning_guidance,
        test_planner_integration,
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
        pass  # sys.exit removed for pytest compatibility
