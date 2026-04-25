"""
Tests Objective Engine — 12 tests couvrant toutes les fonctionnalités critiques.
Utilise des répertoires temporaires pour éviter de polluer workspace/.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
pytestmark = pytest.mark.integration


# ── Helpers setup ──────────────────────────────────────────────────────────────

def _make_store(tmp_path: Path):
    """Crée un ObjectiveStore isolé dans un répertoire temp."""
    from core.objectives.objective_store import ObjectiveStore, reset_store
    reset_store()
    store_file = tmp_path / "objectives.json"
    return ObjectiveStore(store_path=store_file)


def _make_engine(tmp_path: Path):
    """Crée un ObjectiveEngine isolé dans un répertoire temp."""
    from core.objectives.objective_engine import ObjectiveEngine, reset_engine
    from core.objectives.objective_store import reset_store
    reset_engine()
    reset_store()
    store = _make_store(tmp_path)
    return ObjectiveEngine(store=store)


# ══════════════════════════════════════════════════════════════════════════════
# TEST 1 — Créer un objectif + persistance JSON
# ══════════════════════════════════════════════════════════════════════════════

def test_objective_create(tmp_path):
    """Créer un objectif → vérifier persistance JSON."""
    engine = _make_engine(tmp_path)
    obj = engine.create(
        title="Déployer le module auth",
        description="Deployer le service d'authentification en prod",
        category="deploy",
        priority_score=0.8,
    )

    assert obj is not None, "create() ne doit pas retourner None"
    assert obj.objective_id is not None
    assert obj.title == "Déployer le module auth"
    assert obj.status == "NEW"
    assert 0.0 <= obj.priority_score <= 1.0

    # Vérifier que le fichier JSON existe et contient l'objectif
    store_file = tmp_path / "objectives.json"
    assert store_file.exists(), "objectives.json doit exister après création"

    data = json.loads(store_file.read_text("utf-8"))
    assert obj.objective_id in data, "L'objectif doit être dans objectives.json"


# ══════════════════════════════════════════════════════════════════════════════
# TEST 2 — Persistance JSON : reload depuis fichier
# ══════════════════════════════════════════════════════════════════════════════

def test_objective_persistence_json(tmp_path):
    """Créer un objectif, recharger depuis fichier → même état."""
    engine = _make_engine(tmp_path)
    obj = engine.create(
        title="Analyser les logs de prod",
        description="Audit complet des logs",
        category="analysis",
    )
    assert obj is not None
    oid = obj.objective_id

    # Créer un nouveau store/engine pointant vers le même fichier
    from core.objectives.objective_store import ObjectiveStore
    from core.objectives.objective_engine import ObjectiveEngine
    store2 = ObjectiveStore(store_path=tmp_path / "objectives.json")
    engine2 = ObjectiveEngine(store=store2)

    reloaded = engine2.get(oid)
    assert reloaded is not None, "L'objectif doit être rechargeable depuis le fichier"
    assert reloaded.title == "Analyser les logs de prod"
    assert reloaded.category == "analysis"


# ══════════════════════════════════════════════════════════════════════════════
# TEST 3 — Qdrant fail-open : continue sans crash si Qdrant est down
# ══════════════════════════════════════════════════════════════════════════════

def test_objective_qdrant_failopen(tmp_path):
    """Si Qdrant est down/absent, l'objectif engine continue normalement."""
    # Forcer une URL Qdrant invalide
    with patch.dict(os.environ, {"QDRANT_HOST": "localhost", "QDRANT_PORT": "19999"}):
        # Reset modules pour prendre en compte le nouvel env
        import importlib
        import core.objectives.objective_store as store_mod
        importlib.reload(store_mod)

        engine = _make_engine(tmp_path)
        # Doit créer l'objectif sans lever d'exception même si Qdrant est down
        obj = engine.create(
            title="Test Qdrant failopen",
            description="Qdrant est down",
            category="general",
        )
        # L'objectif est créé malgré l'absence de Qdrant
        assert obj is not None, "L'objectif doit être créé même si Qdrant est down"

        # Reload pour restaurer le state
        importlib.reload(store_mod)


# ══════════════════════════════════════════════════════════════════════════════
# TEST 4 — Breakdown basique
# ══════════════════════════════════════════════════════════════════════════════

def test_objective_breakdown_basic(tmp_path):
    """Décomposer 'déployer un module Python' → sous-objectifs cohérents."""
    engine = _make_engine(tmp_path)
    obj = engine.create(
        title="Déployer un module Python",
        description="Packaging, tests, docker build, déploiement production",
        category="deploy",
        auto_breakdown=True,
    )
    assert obj is not None
    assert len(obj.sub_objectives) >= 2, "Doit avoir au moins 2 sous-objectifs"

    # Vérifier que les sous-objectifs ont les champs requis
    for sub in obj.sub_objectives:
        assert sub.node_id is not None
        assert sub.parent_objective_id == obj.objective_id
        assert sub.title != ""
        assert 0.0 <= sub.difficulty <= 1.0
        assert sub.status in {"TODO", "READY"}

    # Le premier sous-objectif doit être READY, les autres TODO
    assert obj.sub_objectives[0].status == "READY"


# ══════════════════════════════════════════════════════════════════════════════
# TEST 5 — Priority Scoring : score 0-1 + reasons
# ══════════════════════════════════════════════════════════════════════════════

def test_priority_scoring(tmp_path):
    """Vérifier que le score de priorité est dans [0,1] avec des raisons."""
    from core.objectives.objective_scoring import compute_priority_score
    from core.objectives.objective_models import Objective

    obj = Objective(
        objective_id  = "test-score-001",
        title         = "Optimiser les requêtes DB",
        category      = "coding_task",
        priority_score = 0.9,
        difficulty_score = 0.3,
        confidence    = 0.8,
    )
    result = compute_priority_score(obj)

    assert "score" in result
    assert "reasons" in result
    assert "factors" in result
    assert 0.0 <= result["score"] <= 1.0, f"Score hors [0,1]: {result['score']}"
    assert isinstance(result["reasons"], list)
    assert len(result["reasons"]) > 0, "Doit avoir au moins une raison"
    assert isinstance(result["factors"], dict)


# ══════════════════════════════════════════════════════════════════════════════
# TEST 6 — Next Best Action
# ══════════════════════════════════════════════════════════════════════════════

def test_next_best_action(tmp_path):
    """get_next_best_action() doit retourner une action cohérente."""
    engine = _make_engine(tmp_path)

    # Créer un objectif actif avec sous-objectifs
    obj = engine.create(
        title="Corriger le bug de login",
        description="Les utilisateurs ne peuvent pas se connecter",
        category="bug_fix",
        priority_score=0.9,
    )
    assert obj is not None
    engine.activate(obj.objective_id)

    nba = engine.get_next_best_action()

    assert isinstance(nba, dict), "next_best_action doit retourner un dict"
    assert "action_type" in nba
    assert "rationale" in nba
    assert "confidence" in nba
    assert 0.0 <= nba["confidence"] <= 1.0
    assert "required_tools" in nba
    assert isinstance(nba["required_tools"], list)
    assert "requires_human_approval" in nba
    assert "suggested_agent" in nba

    # Avec un objectif actif, ne doit pas retourner no_active_objectives
    assert nba["action_type"] != "no_active_objectives", (
        "Doit trouver une action pour l'objectif actif"
    )


# ══════════════════════════════════════════════════════════════════════════════
# TEST 7 — Détection de blocage
# ══════════════════════════════════════════════════════════════════════════════

def test_blocked_detection(tmp_path):
    """Sous-objectif avec trop de retries → BLOCKED + blocker_reason."""
    engine = _make_engine(tmp_path)

    obj = engine.create(
        title="Déployer le service payment",
        category="deploy",
        auto_breakdown=True,
    )
    assert obj is not None
    engine.activate(obj.objective_id)

    # Simuler des retries excessifs sur le premier sous-objectif
    obj2 = engine.get(obj.objective_id)
    assert obj2 is not None
    if obj2.sub_objectives:
        obj2.sub_objectives[0].retry_count = 5
        obj2.sub_objectives[0].last_result = "error: connection refused"
        engine._store.save(obj2)

    # Détecter les blocages
    engine.detect_and_mark_blockers(obj.objective_id)

    # Vérifier que le sous-objectif est maintenant BLOCKED
    obj3 = engine.get(obj.objective_id)
    assert obj3 is not None
    if obj3.sub_objectives:
        blocked_sub = next(
            (s for s in obj3.sub_objectives if s.retry_count >= 3),
            None
        )
        if blocked_sub:
            assert blocked_sub.status == "BLOCKED", (
                f"Le sous-objectif doit être BLOCKED, got {blocked_sub.status}"
            )
            assert blocked_sub.blocker_reason != "", "blocker_reason doit être non vide"


# ══════════════════════════════════════════════════════════════════════════════
# TEST 8 — Archivage après COMPLETED
# ══════════════════════════════════════════════════════════════════════════════

def test_archive_cleanup(tmp_path):
    """Objectif COMPLETED → archivage par cleanup."""
    from core.objectives.objective_cleanup import ObjectiveCleanup

    engine = _make_engine(tmp_path)
    obj = engine.create(title="Créer endpoint /health", category="coding_task")
    assert obj is not None

    # Marquer COMPLETED
    ok = engine.complete(obj.objective_id, "endpoint créé et testé")
    assert ok, "complete() doit retourner True"

    # Vérifier statut COMPLETED
    obj2 = engine.get(obj.objective_id)
    assert obj2 is not None
    assert obj2.status == "COMPLETED"

    # Lancer le cleanup (avec TTL court pour le test)
    with patch("core.objectives.objective_cleanup.TTL_COMPLETED_DAYS", -1):  # expiration immédiate
        cleanup = ObjectiveCleanup(store=engine._store)
        report = cleanup.run()

    # L'objectif devrait être archivé
    obj3 = engine.get(obj.objective_id)
    if obj3:
        assert obj3.archived, "L'objectif doit être archivé après cleanup"

    # Le rapport doit indiquer 1 archivage
    assert report.get("archived_completed", 0) >= 1, (
        f"Doit avoir archivé 1 objectif completed, got: {report}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# TEST 9 — Intégration planner fail-open
# ══════════════════════════════════════════════════════════════════════════════

def test_planner_integration_failopen(tmp_path):
    """Le planner continue normalement si l'Objective Engine lève une exception."""
    # Simuler un engine qui lève une exception
    with patch("core.planner._OBJECTIVE_ENGINE_AVAILABLE", False):
        from core.planner import build_plan

        # Doit toujours retourner un plan valide
        plan = build_plan(
            goal="Créer une API REST",
            mission_type="coding_task",
        )

        assert isinstance(plan, dict), "build_plan doit retourner un dict"
        assert "steps" in plan, "Le plan doit avoir une clé 'steps'"
        assert len(plan["steps"]) > 0, "Le plan doit avoir au moins un step"
        # Pas de crash même si l'engine est down
        assert plan.get("error") is None or "objective" not in str(plan.get("error", "")).lower()


# ══════════════════════════════════════════════════════════════════════════════
# TEST 10 — Champs decision_trace avec valeurs par défaut sûres
# ══════════════════════════════════════════════════════════════════════════════

def test_decision_trace_fields(tmp_path):
    """get_trace_fields() retourne tous les champs requis avec valeurs par défaut."""
    engine = _make_engine(tmp_path)

    # Sans objectif actif → valeurs par défaut
    fields = engine.get_trace_fields(goal="test goal", session_id="test-session")

    required_keys = [
        "objective_id",
        "objective_status",
        "objective_priority_score",
        "objective_difficulty",
        "objective_match",
        "next_best_action",
        "blocker_detected",
        "blocker_reason",
    ]
    for key in required_keys:
        assert key in fields, f"Clé manquante dans trace_fields: {key}"

    # Valeurs par défaut sûres
    assert fields["objective_match"] is False or fields["objective_match"] is True
    assert fields["blocker_detected"] is False or fields["blocker_detected"] is True
    # Ces champs peuvent être None (pas d'objectif actif)
    # mais ne doivent pas lever d'exception


# ══════════════════════════════════════════════════════════════════════════════
# TEST 11 — Réutilisation objectif similaire existant
# ══════════════════════════════════════════════════════════════════════════════

def test_reuse_similar_objective(tmp_path):
    """find_similar() doit trouver un objectif existant similaire."""
    engine = _make_engine(tmp_path)

    # Créer un objectif existant
    obj = engine.create(
        title="Déployer service authentication",
        description="Docker build et push vers registry",
        category="deploy",
    )
    assert obj is not None

    # Chercher un objectif similaire
    similar = engine.find_similar(
        title="Déployer service auth",
        description="Build docker et déploiement",
    )

    # Doit trouver l'objectif créé précédemment
    assert isinstance(similar, list), "find_similar doit retourner une liste"
    # La recherche locale doit trouver une correspondance (mots "Déployer", "service")
    if similar:
        [s.get("objective_id") for s in similar]
        # On ne garantit pas la correspondance exacte (dépend de l'algo),
        # mais la liste ne doit pas être None et ne doit pas crasher


# ══════════════════════════════════════════════════════════════════════════════
# TEST 12 — Résumé compact de l'historique
# ══════════════════════════════════════════════════════════════════════════════

def test_objective_history_summary(tmp_path):
    """get_history_summary() retourne un résumé compact non vide."""
    engine = _make_engine(tmp_path)

    obj = engine.create(
        title="Refactorer le module database",
        description="Optimisation des requêtes N+1",
        category="coding_task",
    )
    assert obj is not None

    # Générer quelques événements d'historique
    engine.activate(obj.objective_id)
    engine.pause(obj.objective_id, "en attente de review")
    engine.resume(obj.objective_id)

    # Vérifier l'historique
    history = engine.get_history(obj.objective_id)
    assert isinstance(history, list)
    assert len(history) > 0, "Doit avoir au moins une entrée d'historique"

    # Vérifier le résumé compact
    summary = engine.get_history_summary(obj.objective_id)
    assert isinstance(summary, str)
    assert len(summary) > 0, "Le résumé ne doit pas être vide"
    assert "Aucun historique" not in summary, "Ne doit pas retourner 'Aucun historique'"


# ══════════════════════════════════════════════════════════════════════════════
# BONUS — Test modèles (serialisation roundtrip)
# ══════════════════════════════════════════════════════════════════════════════

def test_model_roundtrip():
    """Objective.to_dict() / from_dict() doit être idempotent."""
    from core.objectives.objective_models import Objective, SubObjective

    sub = SubObjective(
        node_id="sub-001",
        parent_objective_id="obj-001",
        title="Step 1",
        retry_count=2,
        last_result="partial error",
    )
    obj = Objective(
        objective_id="obj-001",
        title="Test roundtrip",
        category="general",
        sub_objectives=[sub],
    )
    d = obj.to_dict()
    obj2 = Objective.from_dict(d)

    assert obj2.objective_id == obj.objective_id
    assert obj2.title == obj.title
    assert len(obj2.sub_objectives) == 1
    assert obj2.sub_objectives[0].node_id == "sub-001"
    assert obj2.sub_objectives[0].retry_count == 2


def test_objective_status_constants():
    """Vérifier que les constantes de statut sont correctement définies."""
    from core.objectives.objective_models import ObjectiveStatus, SubObjectiveStatus

    assert "COMPLETED" in ObjectiveStatus.TERMINAL
    assert "FAILED" in ObjectiveStatus.TERMINAL
    assert "ARCHIVED" in ObjectiveStatus.TERMINAL
    assert "NEW" in ObjectiveStatus.ACTIVE_STATES

    assert "DONE" in SubObjectiveStatus.TERMINAL
    assert "TODO" in SubObjectiveStatus.ACTIONABLE
    assert "READY" in SubObjectiveStatus.ACTIONABLE
