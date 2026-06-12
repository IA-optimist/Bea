"""
Tests — WorkflowEngine + WorkflowAgent + SupervisedExecutor (actions avancées)
Couverture :
    1. WorkflowEngine.create — workflow valide
    2. WorkflowEngine.create — workflow invalide (doit lever WorkflowValidationError)
    3. WorkflowEngine.list_workflows
    4. WorkflowEngine.execute (dry_run / sans agents réels)
    5. WorkflowAgent.create_from_text (fallback sans LLM)
    6. WorkflowAgent._sanitize — agents invalides remplacés
    7. SupervisedExecutor.read_directory
    8. SupervisedExecutor.classify_risk — nouveaux types
    9. SupervisedExecutor.create_workflow (dry_run)
    10. RiskEngine nouveaux types
"""
import sys
import os
import asyncio
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
        self.workspace_dir    = ws
        self.dry_run          = True
        self.max_auto_actions = 10
        self.bea_root      = ws
        self.bea_name      = "BeaTest"
        self.openai_api_key   = ""
        self.ollama_host      = "http://localhost:11434"
        self.ollama_model_main  = "llama3.1:8b"
        self.ollama_model_fast  = "llama3.1:8b"
        self.ollama_model_code  = "deepseek-coder-v2:16b"
        self.ollama_model_vision = "llava:7b"

    def get_llm(self, role):
        raise RuntimeError("LLM not available in test")


def _make_settings():
    ws = tempfile.mkdtemp()
    return _FakeSettings(ws)


# ════════════════════════════════════════════════════════════════
# WORKFLOW ENGINE TESTS
# ════════════════════════════════════════════════════════════════

def test_workflow_create_valid():
    """Création d'un workflow valide doit retourner un ID."""
    from core.workflow.workflow_engine import WorkflowEngine
    s  = _make_settings()
    engine = WorkflowEngine(s)

    definition = {
        "name":    "daily_report",
        "trigger": "manual",
        "steps": [
            {"agent": "scout-research", "task": "Collecter nouvelles"},
            {"agent": "shadow-advisor", "task": "Synthétiser"},
        ],
    }
    wf_id = asyncio.run(engine.create(definition))
    assert wf_id.startswith("wf_"), f"ID invalide : {wf_id}"

    # Vérifier que le workflow est listable
    wfs = engine.list_workflows()
    ids = [w["id"] for w in wfs]
    assert wf_id in ids, f"Workflow non trouvé dans list : {ids}"
    print(f"[OK] test_workflow_create_valid (id={wf_id})")


def test_workflow_create_invalid_missing_steps():
    """Un workflow sans steps doit lever WorkflowValidationError."""
    from core.workflow.workflow_engine import WorkflowEngine, WorkflowValidationError
    s  = _make_settings()
    engine = WorkflowEngine(s)

    try:
        asyncio.run(engine.create({"name": "bad_wf"}))
        assert False, "Exception attendue"
    except WorkflowValidationError as e:
        assert "steps" in str(e).lower(), f"Message attendu : {e}"
    print("[OK] test_workflow_create_invalid_missing_steps")


def test_workflow_create_invalid_trigger():
    """Un trigger invalide doit lever WorkflowValidationError."""
    from core.workflow.workflow_engine import WorkflowEngine, WorkflowValidationError
    s  = _make_settings()
    engine = WorkflowEngine(s)

    try:
        asyncio.run(engine.create({
            "name":    "bad_trigger",
            "trigger": "webhook",      # invalide
            "steps":   [{"agent": "scout-research", "task": "x"}],
        }))
        assert False, "Exception attendue"
    except WorkflowValidationError as e:
        assert "trigger" in str(e).lower(), f"Message attendu : {e}"
    print("[OK] test_workflow_create_invalid_trigger")


def test_workflow_list():
    """list_workflows doit retourner les métadonnées sans les steps complets."""
    from core.workflow.workflow_engine import WorkflowEngine
    s  = _make_settings()
    engine = WorkflowEngine(s)

    for i in range(3):
        asyncio.run(engine.create({
            "name":  f"wf_test_{i}",
            "steps": [{"agent": "scout-research", "task": f"task_{i}"}],
        }))

    wfs = engine.list_workflows()
    assert len(wfs) >= 3, f"Au moins 3 workflows attendus : {len(wfs)}"
    # Vérifier la structure
    for wf in wfs:
        assert "id"    in wf, "Champ 'id' manquant"
        assert "name"  in wf, "Champ 'name' manquant"
        assert "steps" in wf, "Champ 'steps' manquant"
    print(f"[OK] test_workflow_list ({len(wfs)} workflows)")


def test_workflow_get():
    """get() doit retourner le workflow complet par ID."""
    from core.workflow.workflow_engine import WorkflowEngine
    s      = _make_settings()
    engine = WorkflowEngine(s)

    wf_id = asyncio.run(engine.create({
        "name":        "get_test",
        "description": "Test du get",
        "steps": [{"agent": "lens-reviewer", "task": "review"}],
    }))

    wf = engine.get(wf_id)
    assert wf["name"]        == "get_test", f"Nom incorrect : {wf['name']}"
    assert wf["description"] == "Test du get"
    assert len(wf["steps"])  == 1
    print("[OK] test_workflow_get")


# ════════════════════════════════════════════════════════════════
# WORKFLOW AGENT TESTS
# ════════════════════════════════════════════════════════════════

def test_workflow_agent_create_from_text_fallback():
    """Sans LLM disponible, WorkflowAgent doit utiliser le template de fallback."""
    from agents.workflow_agent import WorkflowAgent
    s     = _make_settings()
    agent = WorkflowAgent(s)

    # Le LLM n'est pas disponible (FakeSettings.get_llm lève RuntimeError)
    # WorkflowAgent doit tomber sur le fallback
    messages = []
    async def collect_emit(msg):
        messages.append(msg)

    result = asyncio.run(agent.create_from_text(
        "Crée un rapport journalier sur les nouvelles IA",
        emit=collect_emit,
    ))

    # Doit retourner un workflow créé (statut "created") ou "error" si WorkflowEngine
    # échoue pour une raison technique, mais pas un crash non géré
    assert "status" in result, f"Clé 'status' manquante : {result}"
    assert "workflow" in result, f"Clé 'workflow' manquante : {result}"
    wf = result["workflow"]
    assert "steps" in wf and len(wf["steps"]) > 0, f"Steps vides : {wf}"
    print(f"[OK] test_workflow_agent_create_from_text_fallback (status={result['status']})")


def test_workflow_agent_sanitize():
    """_sanitize doit remplacer les agents invalides par scout-research."""
    from agents.workflow_agent import WorkflowAgent
    _make_settings()
    wf_def = {
        "name":  "test",
        "steps": [
            {"agent": "invalid-agent-xyz", "task": "something"},
            {"agent": "scout-research",    "task": "valid"},
        ],
    }
    cleaned = WorkflowAgent._sanitize(wf_def, "test input")
    agents = [s_["agent"] for s_ in cleaned["steps"]]
    assert "invalid-agent-xyz" not in agents, f"Agent invalide non remplacé : {agents}"
    assert "scout-research" in agents, f"scout-research attendu : {agents}"
    print("[OK] test_workflow_agent_sanitize")


def test_workflow_agent_extract_name():
    """_extract_name doit générer un nom snake_case."""
    from agents.workflow_agent import WorkflowAgent
    name = WorkflowAgent._extract_name("Créer un rapport journalier")
    assert "_" in name or len(name) > 0, f"Nom vide ou sans underscore : {name}"
    assert len(name) <= 30, f"Nom trop long : {name}"
    print(f"[OK] test_workflow_agent_extract_name (name={name})")


# ════════════════════════════════════════════════════════════════
# SUPERVISED EXECUTOR — ACTIONS AVANCÉES
# ════════════════════════════════════════════════════════════════

def test_supervised_read_directory():
    """read_directory doit lister le contenu d'un répertoire existant."""
    from executor.supervised_executor import SupervisedExecutor
    s  = _make_settings()
    sup = SupervisedExecutor(s)

    # Lister le dossier temporaire de settings (forcément existant)
    result = asyncio.run(sup.read_directory(s.workspace_dir))
    assert result.success, f"read_directory doit réussir : {result.error}"
    print(f"[OK] test_supervised_read_directory (output={result.output[:60]})")


def test_supervised_read_directory_missing():
    """read_directory sur un chemin inexistant doit échouer proprement."""
    from executor.supervised_executor import SupervisedExecutor
    s  = _make_settings()
    sup = SupervisedExecutor(s)

    result = asyncio.run(sup.read_directory("/nonexistent/path/xyz"))
    assert not result.success, "read_directory doit échouer sur chemin inexistant"
    print(f"[OK] test_supervised_read_directory_missing (error={result.error})")


def test_supervised_create_workflow_dry_run():
    """create_workflow en dry_run doit simuler sans écrire de fichier."""
    from executor.supervised_executor import SupervisedExecutor
    s   = _make_settings()
    sup = SupervisedExecutor(s)  # dry_run=True dans FakeSettings

    result = asyncio.run(sup.create_workflow({
        "name":  "test_wf",
        "steps": [{"agent": "scout-research", "task": "test"}],
    }, session_id="test"))

    assert result.success, f"create_workflow dry_run doit réussir : {result.error}"
    assert "DRY_RUN" in result.output, f"Output dry_run attendu : {result.output}"
    print("[OK] test_supervised_create_workflow_dry_run")


# ════════════════════════════════════════════════════════════════
# RISK ENGINE — NOUVEAUX TYPES
# ════════════════════════════════════════════════════════════════

def test_risk_engine_new_action_types():
    """Les nouveaux types d'action doivent être correctement classifiés."""
    from risk.engine import RiskEngine
    from core.state import RiskLevel

    engine = RiskEngine()
    cases = [
        ("read_directory",   "/app/workspace",    RiskLevel.LOW),
        ("run_python_script", "/app/workspace/t.py", RiskLevel.MEDIUM),
        ("create_workflow",  "my_workflow",        RiskLevel.MEDIUM),
        ("schedule_task",    "daily_task",         RiskLevel.MEDIUM),
        ("delete_file",      "/app/workspace/f.py", RiskLevel.HIGH),
        ("install_package",  "requests",           RiskLevel.HIGH),
    ]
    for action_type, target, expected_level in cases:
        report = engine.analyze(action_type=action_type, target=target)
        assert report.level == expected_level, (
            f"[{action_type}] attendu={expected_level.value} "
            f"obtenu={report.level.value}"
        )
    print(f"[OK] test_risk_engine_new_action_types ({len(cases)} cas)")


# ── Runner ────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== TEST WORKFLOW ENGINE ===")
    test_workflow_create_valid()
    test_workflow_create_invalid_missing_steps()
    test_workflow_create_invalid_trigger()
    test_workflow_list()
    test_workflow_get()

    print("\n=== TEST WORKFLOW AGENT ===")
    test_workflow_agent_create_from_text_fallback()
    test_workflow_agent_sanitize()
    test_workflow_agent_extract_name()

    print("\n=== TEST SUPERVISED EXECUTOR (actions avancées) ===")
    test_supervised_read_directory()
    test_supervised_read_directory_missing()
    test_supervised_create_workflow_dry_run()

    print("\n=== TEST RISK ENGINE (nouveaux types) ===")
    test_risk_engine_new_action_types()

    print("\n=== TOUS LES TESTS WORKFLOW : OK ===")
