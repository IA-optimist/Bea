"""
Tests — LearningEngine + ModelSelector + MetricsCollector
Couverture :
    1. LearningEngine.record_run + get_recent_runs
    2. LearningEngine.compute_success_rates
    3. LearningEngine.recommend_strategy — pas assez de runs
    4. LearningEngine.recommend_strategy — agent faible
    5. LearningEngine.generate_report
    6. ModelSelector.select — rôle simple
    7. ModelSelector.select — tâche code
    8. ModelSelector.select — tâche simple (fast model)
    9. ModelSelector.get_status
    10. MetricsCollector.inc + get_snapshot
    11. MetricsCollector.record_run
    12. MetricsCollector.record_latency
    13. MetricsCollector.get_report
"""
import sys
import os
import tempfile
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
    def __init__(self, ws):
        self.workspace_dir       = ws
        self.dry_run             = True
        self.ollama_model_main   = "llama3.1:8b"
        self.ollama_model_fast   = "llama3.1:8b"
        self.ollama_model_code   = "deepseek-coder-v2:16b"
        self.ollama_model_vision = "llava:7b"
        self.escalation_enabled  = False
        self.openai_api_key      = ""
        self.anthropic_api_key   = ""

    def get_llm(self, role):
        raise RuntimeError("LLM not available in test")


def _make_settings():
    return _FakeSettings(tempfile.mkdtemp())


def _make_run(**kwargs):
    base = {
        "mode":              "improve",
        "files_scanned":     40,
        "findings":          10,
        "patches_generated": 4,
        "patches_approved":  3,
        "patches_applied":   3,
        "duration_s":        120.0,
        "agents_used":       ["scout-research", "forge-builder"],
        "agents_success":    {"scout-research": True, "forge-builder": True},
        "llm_calls":         {"improve": 2},
        "llm_latencies":     {"improve": 110.0},
        "escalated":         False,
        "error":             None,
    }
    base.update(kwargs)
    return base


# ════════════════════════════════════════════════════════════════
# LEARNING ENGINE TESTS
# ════════════════════════════════════════════════════════════════

def test_learning_record_and_get_recent():
    """record_run doit persister, get_recent_runs retourne les N derniers."""
    from core.learning.learning_engine import LearningEngine
    s  = _make_settings()
    le = LearningEngine(s)
    le.clear()

    run_id = le.record_run(_make_run())
    assert run_id.startswith("run_"), f"run_id invalide : {run_id}"

    recent = le.get_recent_runs(5)
    assert len(recent) == 1, f"1 run attendu : {len(recent)}"
    assert recent[0]["run_id"] == run_id
    print(f"[OK] test_learning_record_and_get_recent (id={run_id})")


def test_learning_compute_success_rates():
    """compute_success_rates doit calculer les ratios corrects."""
    from core.learning.learning_engine import LearningEngine
    s  = _make_settings()
    le = LearningEngine(s)
    le.clear()

    le.record_run(_make_run(patches_generated=4, patches_approved=4, patches_applied=4))
    le.record_run(_make_run(patches_generated=4, patches_approved=2, patches_applied=1))
    le.record_run(_make_run(patches_generated=4, patches_approved=4, patches_applied=3))

    rates = le.compute_success_rates()
    assert rates["total_runs"] == 3, f"3 runs attendus : {rates['total_runs']}"
    assert rates["patch_generated"] == 12
    assert rates["patch_approved"]  == 10
    assert 0.0 < rates["patch_approval_rate"] <= 1.0
    print(f"[OK] test_learning_compute_success_rates "
          f"(rate={rates['patch_approval_rate']})")


def test_learning_recommend_insufficient_data():
    """recommend_strategy avec < 3 runs doit indiquer pas assez de données."""
    from core.learning.learning_engine import LearningEngine
    s  = _make_settings()
    le = LearningEngine(s)
    le.clear()

    le.record_run(_make_run())
    strat = le.recommend_strategy()
    assert len(strat["notes"]) > 0
    assert any("assez" in n.lower() or "min" in n.lower() for n in strat["notes"]), \
        f"Message 'pas assez' attendu : {strat['notes']}"
    print("[OK] test_learning_recommend_insufficient_data")


def test_learning_recommend_weak_agent():
    """recommend_strategy doit détecter un agent faible."""
    from core.learning.learning_engine import LearningEngine
    s  = _make_settings()
    le = LearningEngine(s)
    le.clear()

    # forge-builder échoue 80% du temps
    for i in range(5):
        le.record_run(_make_run(
            agents_success={"scout-research": True, "forge-builder": i > 3}
        ))

    strat = le.recommend_strategy()
    assert "forge-builder" in strat["weak_agents"], \
        f"forge-builder attendu dans weak_agents : {strat['weak_agents']}"
    print(f"[OK] test_learning_recommend_weak_agent "
          f"(weak={strat['weak_agents']})")


def test_learning_generate_report():
    """generate_report doit retourner une string non vide."""
    from core.learning.learning_engine import LearningEngine
    s  = _make_settings()
    le = LearningEngine(s)
    le.clear()

    for _ in range(3):
        le.record_run(_make_run())

    report = le.generate_report()
    assert isinstance(report, str), "Rapport doit être une str"
    assert len(report) > 50, f"Rapport trop court : {len(report)}"
    assert "LearningEngine" in report, "En-tête manquant"
    print(f"[OK] test_learning_generate_report ({len(report)} chars)")


# ════════════════════════════════════════════════════════════════
# MODEL SELECTOR TESTS
# ════════════════════════════════════════════════════════════════

def test_model_selector_default_role():
    """select('main') doit retourner le modèle principal Ollama."""
    from core.model_selector import ModelSelector
    s  = _make_settings()
    ms = ModelSelector(s)

    rec = ms.select("main", "Résume ce texte")
    assert rec.provider == "ollama", f"Provider ollama attendu : {rec.provider}"
    assert rec.model == "llama3.1:8b", f"Model attendu llama3.1:8b : {rec.model}"
    print(f"[OK] test_model_selector_default_role (model={rec.model})")


def test_model_selector_code_task():
    """Tâche avec marqueurs code → modèle code."""
    from core.model_selector import ModelSelector
    s  = _make_settings()
    ms = ModelSelector(s)

    rec = ms.select("builder", "```python\ndef foo():\n    import asyncio\n    class Bar: pass")
    assert rec.model == "deepseek-coder-v2:16b", \
        f"Code model attendu : {rec.model}"
    print(f"[OK] test_model_selector_code_task (model={rec.model})")


def test_model_selector_simple_task():
    """Tâche simple courte → fast model."""
    from core.model_selector import ModelSelector
    s  = _make_settings()
    ms = ModelSelector(s)

    rec = ms.select("fast", "Bonjour")
    assert rec.provider == "ollama"
    assert "8b" in rec.model.lower() or "fast" in rec.reason.lower(), \
        f"Fast model attendu : {rec.model} | {rec.reason}"
    print(f"[OK] test_model_selector_simple_task (model={rec.model})")


def test_model_selector_get_status():
    """get_status doit retourner un dict avec les modèles configurés."""
    from core.model_selector import ModelSelector
    s  = _make_settings()
    ms = ModelSelector(s)

    status = ms.get_status()
    assert "models" in status
    assert "fast" in status["models"]
    assert "code" in status["models"]
    assert status["models"]["code"] == "deepseek-coder-v2:16b"
    print("[OK] test_model_selector_get_status")


# ════════════════════════════════════════════════════════════════
# METRICS COLLECTOR TESTS
# ════════════════════════════════════════════════════════════════

def test_metrics_inc_and_snapshot():
    """inc doit incrémenter, get_snapshot retourne les compteurs."""
    from core.observability.metrics import MetricsCollector
    s  = _make_settings()
    mc = MetricsCollector(s)
    mc.clear()

    mc.inc("patch_approved", 3)
    mc.inc("patch_approved", 1)
    snap = mc.get_snapshot()
    # Le snapshot lit depuis les events persistés
    assert isinstance(snap, dict)
    assert "runs_total" in snap
    print("[OK] test_metrics_inc_and_snapshot")


def test_metrics_record_run():
    """record_run doit alimenter le snapshot runs_total."""
    from core.observability.metrics import MetricsCollector
    s  = _make_settings()
    mc = MetricsCollector(s)
    mc.clear()

    mc.record_run(mode="improve", success=True,  duration_s=142.0, patches=4, approved=3)
    mc.record_run(mode="improve", success=False, duration_s=30.0,  patches=0, approved=0)
    mc.record_run(mode="auto",    success=True,  duration_s=60.0,  patches=2, approved=2)

    snap = mc.get_snapshot()
    assert snap["runs_total"]   == 3,  f"3 runs attendus : {snap['runs_total']}"
    assert snap["runs_success"] == 2,  f"2 succès attendus : {snap['runs_success']}"
    assert snap["runs_error"]   == 1,  f"1 erreur attendue : {snap['runs_error']}"
    assert snap["patch_total"]  == 6,  f"6 patches attendus : {snap['patch_total']}"
    assert snap["patch_approved"] == 5
    print(f"[OK] test_metrics_record_run (rate={snap['patch_success_rate']})")


def test_metrics_record_latency():
    """record_latency doit alimenter les latences moyennes."""
    from core.observability.metrics import MetricsCollector
    s  = _make_settings()
    mc = MetricsCollector(s)
    mc.clear()

    mc.record_latency("forge-builder", 1200.0)
    mc.record_latency("forge-builder", 800.0)
    mc.record_latency("scout-research", 500.0)

    snap = mc.get_snapshot()
    lat  = snap["agent_latency_avg_ms"]
    assert "forge-builder"  in lat, f"forge-builder manquant : {lat}"
    assert lat["forge-builder"] == 1000.0, f"Moy attendue 1000ms : {lat}"
    print("[OK] test_metrics_record_latency")


def test_metrics_get_report():
    """get_report doit retourner un rapport texte lisible."""
    from core.observability.metrics import MetricsCollector
    s  = _make_settings()
    mc = MetricsCollector(s)
    mc.clear()

    mc.record_run(mode="improve", success=True, patches=3, approved=2)
    report = mc.get_report()
    assert isinstance(report, str)
    assert "Métriques" in report, f"En-tête manquant : {report[:100]}"
    print(f"[OK] test_metrics_get_report ({len(report)} chars)")


# ── Runner ────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== TEST LEARNING ENGINE ===")
    test_learning_record_and_get_recent()
    test_learning_compute_success_rates()
    test_learning_recommend_insufficient_data()
    test_learning_recommend_weak_agent()
    test_learning_generate_report()

    print("\n=== TEST MODEL SELECTOR ===")
    test_model_selector_default_role()
    test_model_selector_code_task()
    test_model_selector_simple_task()
    test_model_selector_get_status()

    print("\n=== TEST METRICS COLLECTOR ===")
    test_metrics_inc_and_snapshot()
    test_metrics_record_run()
    test_metrics_record_latency()
    test_metrics_get_report()

    print("\n=== TOUS LES TESTS LEARNING/METRICS : OK ===")
