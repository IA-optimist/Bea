"""
Tests — FailureMemory + PatchMemory
Couverture :
    1. FailureMemory.record_rejection + get_context
    2. FailureMemory.has_failed_before (dédoublonnage)
    3. FailureMemory.get_stats
    4. PatchMemory.record_success + get_success_patterns
    5. PatchMemory.get_context
    6. PatchMemory.get_best_model
"""
import sys
import os
import tempfile
import types

# ── Bootstrap path & mock structlog ──────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Mock structlog si non disponible
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


# ── Fixture settings ─────────────────────────────────────────

class _FakeSettings:
    def __init__(self, ws):
        self.workspace_dir = ws


def _make_settings():
    ws = tempfile.mkdtemp()
    return _FakeSettings(ws)


# ── Helpers ───────────────────────────────────────────────────

def _make_patch(patch_id="p1", file="self_improve/auditor.py",
                finding_id="f1", old_str="async def run(", new_str="async def run(  # noqa",
                category="architecture_improvement"):
    """Retourne un dict simulant un PatchSpec minimal."""
    return {
        "id":         patch_id,
        "file":       file,
        "finding_id": finding_id,
        "old_str":    old_str,
        "new_str":    new_str,
        "category":   category,
        "patch_type": "replace_in_file",
    }


# ════════════════════════════════════════════════════════════════
# FAILURE MEMORY TESTS
# ════════════════════════════════════════════════════════════════

def test_failure_memory_record_and_context():
    """Un rejet enregistré doit apparaître dans get_context."""
    from memory.legacy.failure_memory import FailureMemory
    s  = _make_settings()
    fm = FailureMemory(s)
    fm.clear()

    patch = _make_patch()
    fm.record_rejection(patch, reason="SyntaxError : unexpected indent")

    ctx = fm.get_context("self_improve/auditor.py")
    assert "PREVIOUS FAILURES" in ctx, "Le contexte doit contenir l'en-tête"
    assert "SyntaxError" in ctx, f"La raison doit apparaître dans le contexte : {ctx}"
    assert "async def run(" in ctx, f"old_str doit apparaître : {ctx}"
    print("[OK] test_failure_memory_record_and_context")


def test_failure_memory_deduplication():
    """Deux rejets identiques ne doivent pas être doublonnés."""
    from memory.legacy.failure_memory import FailureMemory
    s  = _make_settings()
    fm = FailureMemory(s)
    fm.clear()

    patch = _make_patch()
    fm.record_rejection(patch, reason="no_old_str")
    fm.record_rejection(patch, reason="no_old_str")  # doublon

    stats = fm.get_stats()
    assert stats["total"] == 1, f"Doublon non filtré : total={stats['total']}"
    print("[OK] test_failure_memory_deduplication")


def test_failure_memory_has_failed_before():
    """has_failed_before doit retourner True après un enregistrement."""
    from memory.legacy.failure_memory import FailureMemory
    s  = _make_settings()
    fm = FailureMemory(s)
    fm.clear()

    patch = _make_patch()
    assert not fm.has_failed_before(patch), "has_failed_before doit être False avant enregistrement"
    fm.record_rejection(patch, reason="SyntaxError")
    assert fm.has_failed_before(patch), "has_failed_before doit être True après enregistrement"
    print("[OK] test_failure_memory_has_failed_before")


def test_failure_memory_empty_context():
    """get_context doit retourner '' si aucun échec pour ce fichier."""
    from memory.legacy.failure_memory import FailureMemory
    s  = _make_settings()
    fm = FailureMemory(s)
    fm.clear()

    ctx = fm.get_context("self_improve/models.py")
    assert ctx == "", f"Contexte doit être vide : {repr(ctx)}"
    print("[OK] test_failure_memory_empty_context")


def test_failure_memory_stats():
    """get_stats doit retourner le bon total."""
    from memory.legacy.failure_memory import FailureMemory
    s  = _make_settings()
    fm = FailureMemory(s)
    fm.clear()

    patches = [
        _make_patch("p1", "file_a.py", old_str="def a():"),
        _make_patch("p2", "file_b.py", old_str="def b():"),
        _make_patch("p3", "file_a.py", old_str="def c():"),
    ]
    for i, p in enumerate(patches):
        fm.record_rejection(p, reason=f"reason_{i}")

    stats = fm.get_stats()
    assert stats["total"] == 3, f"Total attendu 3 : {stats}"
    assert "file_a.py" in stats["files"], f"file_a.py attendu dans files : {stats}"
    print("[OK] test_failure_memory_stats")


# ════════════════════════════════════════════════════════════════
# PATCH MEMORY TESTS
# ════════════════════════════════════════════════════════════════

def test_patch_memory_record_and_get_patterns():
    """Un succès enregistré doit apparaître dans get_success_patterns."""
    from memory.legacy.patch_memory import PatchMemory
    s  = _make_settings()
    pm = PatchMemory(s)
    pm.clear()

    patch = _make_patch()
    pm.record_success(patch, model="llama3.1:8b", source="pre_patch")

    patterns = pm.get_success_patterns(file="self_improve/auditor.py")
    assert len(patterns) >= 1, f"Au moins un pattern attendu : {patterns}"
    assert "architecture_improvement" in patterns[0], f"Catégorie attendue : {patterns[0]}"
    print("[OK] test_patch_memory_record_and_get_patterns")


def test_patch_memory_context():
    """get_context doit retourner un bloc de texte formaté."""
    from memory.legacy.patch_memory import PatchMemory
    s  = _make_settings()
    pm = PatchMemory(s)
    pm.clear()

    pm.record_success(_make_patch("p1", old_str="def a():"), model="llama3.1:8b")
    ctx = pm.get_context(file="self_improve/auditor.py")
    assert "SUCCESSFUL PATTERNS" in ctx, f"En-tête manquant : {ctx}"
    print("[OK] test_patch_memory_context")


def test_patch_memory_get_best_model():
    """get_best_model doit retourner le modèle avec le plus de succès."""
    from memory.legacy.patch_memory import PatchMemory
    s  = _make_settings()
    pm = PatchMemory(s)
    pm.clear()

    pm.record_success(_make_patch("p1", old_str="def a():"), model="llama3.1:8b")
    pm.record_success(_make_patch("p2", old_str="def b():"), model="llama3.1:8b")
    pm.record_success(_make_patch("p3", old_str="def c():"), model="deepseek")

    best = pm.get_best_model()
    assert best == "llama3.1:8b", f"Best model attendu llama3.1:8b : {best}"
    print("[OK] test_patch_memory_get_best_model")


def test_patch_memory_empty_context():
    """get_context doit retourner '' si aucun succès."""
    from memory.legacy.patch_memory import PatchMemory
    s  = _make_settings()
    pm = PatchMemory(s)
    pm.clear()

    ctx = pm.get_context(file="some_file.py")
    assert ctx == "", f"Contexte doit être vide : {repr(ctx)}"
    print("[OK] test_patch_memory_empty_context")


# ── Runner ────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== TEST FAILURE MEMORY ===")
    test_failure_memory_record_and_context()
    test_failure_memory_deduplication()
    test_failure_memory_has_failed_before()
    test_failure_memory_empty_context()
    test_failure_memory_stats()

    print("\n=== TEST PATCH MEMORY ===")
    test_patch_memory_record_and_get_patterns()
    test_patch_memory_context()
    test_patch_memory_get_best_model()
    test_patch_memory_empty_context()

    print("\n=== TOUS LES TESTS MÉMOIRE : OK ===")
