"""
JarvisMax — Security Layer: Improvement Gate Enforcement Tests

Ces tests vérifient que le gate d'amélioration fonctionne RÉELLEMENT
quand JARVIS_SKIP_IMPROVEMENT_GATE n'est PAS défini.

Ils testent que:
1. Les modifications du code core/ sont bloquées sans approbation
2. Le SecurityLayer rejette les patches non-approuvés
3. L'audit trail enregistre les tentatives
"""
import os
import pytest
from pathlib import Path


@pytest.fixture(scope="module", autouse=True)
def enable_security_gate():
    """Force l'activation du security gate pour ce module"""
    # Enlever le skip si présent
    old_value = os.environ.pop("JARVIS_SKIP_IMPROVEMENT_GATE", None)
    yield
    # Restaurer après les tests
    if old_value:
        os.environ["JARVIS_SKIP_IMPROVEMENT_GATE"] = old_value


def test_improvement_gate_blocks_core_modification():
    """Le gate doit bloquer les modifications core/ sans approbation"""
    from security.improvement_gate import check_modification_allowed
    
    # Test: modification d'un fichier core
    result = check_modification_allowed(
        target_path="core/meta_orchestrator.py",
        change_type="patch",
        approved=False
    )
    
    assert result["allowed"] is False, "Gate doit bloquer core/ sans approbation"
    assert "approval required" in result.get("reason", "").lower()


def test_security_layer_rejects_unapproved_patch():
    """SecurityLayer doit rejeter un patch non-approuvé"""
    from security.security_layer import SecurityLayer
    
    layer = SecurityLayer()
    
    action = {
        "action_type": "code_patch",
        "target": "core/orchestrator.py",
        "patch": "# test patch",
        "approved": False
    }
    
    result = layer.check(action)
    
    assert result["needs_approval"] is True, "Patch core/ doit nécessiter approbation"
    assert result["risk_level"] in ["HIGH", "CRITICAL"]


def test_gate_allows_approved_modification():
    """Le gate doit permettre les modifications SI approuvées"""
    from security.improvement_gate import check_modification_allowed
    
    result = check_modification_allowed(
        target_path="core/meta_orchestrator.py",
        change_type="patch",
        approved=True  # Approbation explicite
    )
    
    assert result["allowed"] is True, "Gate doit permettre avec approbation"


def test_audit_trail_records_gate_rejection():
    """L'audit trail doit enregistrer les rejets du gate"""
    from security.audit.trail import get_recent_events
    from security.improvement_gate import check_modification_allowed
    
    # Déclencher un rejet
    check_modification_allowed(
        target_path="core/kernel.py",
        change_type="replace",
        approved=False
    )
    
    # Vérifier l'enregistrement
    events = get_recent_events(limit=10, event_type="gate_rejection")
    
    assert len(events) > 0, "Au moins un événement de rejet doit être enregistré"
    latest = events[0]
    assert "kernel.py" in latest.get("target", "")


@pytest.mark.parametrize("protected_path", [
    "core/meta_orchestrator.py",
    "kernel/runtime.py",
    "security/security_layer.py",
    "executor/supervised_executor.py"
])
def test_gate_blocks_all_critical_files(protected_path):
    """Le gate doit bloquer TOUS les fichiers critiques"""
    from security.improvement_gate import check_modification_allowed
    
    result = check_modification_allowed(
        target_path=protected_path,
        change_type="patch",
        approved=False
    )
    
    assert result["allowed"] is False, f"{protected_path} doit être protégé"


def test_gate_skip_env_var_actually_bypasses():
    """Vérifier que SKIP_IMPROVEMENT_GATE bypass réellement le gate"""
    from security.improvement_gate import check_modification_allowed
    
    # Activer le skip temporairement
    os.environ["JARVIS_SKIP_IMPROVEMENT_GATE"] = "1"
    
    result = check_modification_allowed(
        target_path="core/meta_orchestrator.py",
        change_type="patch",
        approved=False
    )
    
    # Nettoyer
    os.environ.pop("JARVIS_SKIP_IMPROVEMENT_GATE")
    
    assert result["allowed"] is True, "SKIP doit bypass le gate"
    assert "bypassed" in result.get("reason", "").lower()
