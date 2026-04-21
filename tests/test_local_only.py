"""
Tests — Garantie Local-Only
Vérifie que JAMAIS un appel cloud n'est tenté si la clé est absente ou placeholder.

Couverture :
    1. _is_valid_key — clé vide
    2. _is_valid_key — placeholder sk-CHANGE_ME
    3. _is_valid_key — clé valide (format correct)
    4. _is_valid_key — clé trop courte
    5. LLMFactory._build_openai — sk-CHANGE_ME → None (pas de ChatOpenAI)
    6. LLMFactory._build_anthropic — vide → None
    7. LLMFactory.get("fast") — sk-CHANGE_ME → retourne Ollama
    8. LLMFactory.get("builder") — toutes clés vides → retourne Ollama
    9. EscalationEngine.validate_cloud_keys — toutes invalides
    10. EscalationEngine.validate_cloud_keys — clé valide
    11. EscalationEngine — sk-CHANGE_ME → disabled
    12. ModelSelector._cloud_allowed — sk-CHANGE_ME → False
    13. ModelSelector.select — sk-CHANGE_ME → ollama
    14. ModelSelector.get_status — mode local_only
    15. Clé valide simulée → cloud_allowed = True
"""
import sys
import os
import types
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Mock langchain si absent (environnement local sans deps) ──
for _mod in [
    "langchain_core", "langchain_core.language_models",
    "langchain_openai", "langchain_anthropic",
    "langchain_google_genai", "langchain_ollama",
]:
    if _mod not in sys.modules:
        _m = types.ModuleType(_mod)
        if _mod == "langchain_core.language_models":
            _m.BaseChatModel = object
        if _mod == "langchain_openai":
            class _ChatOpenAI:
                def __init__(self, **kw): self.openai_api_key = kw.get("api_key","")
            _m.ChatOpenAI = _ChatOpenAI
        if _mod == "langchain_anthropic":
            class _ChatAnthropic:
                def __init__(self, **kw): pass
            _m.ChatAnthropic = _ChatAnthropic
        if _mod == "langchain_ollama":
            class _ChatOllama:
                def __init__(self, **kw):
                    self.model = kw.get("model", "")
                    self.base_url = kw.get("base_url", "")
            _m.ChatOllama = _ChatOllama
        sys.modules[_mod] = _m
        # Register parent package if needed
        parts = _mod.split(".")
        if len(parts) > 1:
            parent = sys.modules.get(parts[0])
            if parent:
                setattr(parent, parts[-1], _m)

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

class _Settings:
    def __init__(self,
                 openai_key:    str = "",
                 anthropic_key: str = ""):
        self.workspace_dir       = tempfile.mkdtemp()
        self.openai_api_key      = openai_key
        self.anthropic_api_key   = anthropic_key
        self.openai_model        = "gpt-4o"
        self.openai_model_fast   = "gpt-4o-mini"
        self.anthropic_model     = "claude-3-5-sonnet-20241022"
        self.google_api_key      = ""
        self.google_model        = ""
        self.ollama_host         = "http://localhost:11434"
        self.ollama_model_main   = "llama3.1:8b"
        self.ollama_model_fast   = "llama3.1:8b"
        self.ollama_model_code   = "deepseek-coder-v2:16b"
        self.ollama_model_vision = "llava:7b"
        self.model_strategy      = "openai"
        self.model_fallback      = "ollama"
        self.escalation_enabled  = True   # activé mais clé invalide
        self.escalation_prefer   = "openai"


# Clé valide simulée (> 20 chars, sans placeholder)
_VALID_OPENAI_KEY    = "sk-" + "a" * 48   # 51 chars, format-like
_VALID_ANTHROPIC_KEY = "sk-ant-" + "b" * 80


# ════════════════════════════════════════════════════════════════
# _is_valid_key TESTS
# ════════════════════════════════════════════════════════════════

def test_is_valid_key_empty():
    from core.llm_factory import _is_valid_key
    assert not _is_valid_key(""),    "vide → invalide"
    assert not _is_valid_key(None),  "None → invalide"
    assert not _is_valid_key("   "), "espaces → invalide"
    print("[OK] test_is_valid_key_empty")


def test_is_valid_key_placeholder():
    from core.llm_factory import _is_valid_key
    assert not _is_valid_key("sk-CHANGE_ME"),      "sk-CHANGE_ME → invalide"
    assert not _is_valid_key("sk-change_me_xxx"),   "sk-change_me → invalide"
    assert not _is_valid_key("your_api_key_here"),  "placeholder → invalide"
    assert not _is_valid_key("CHANGE_ME_strong_db"), "CHANGE_ME → invalide"
    print("[OK] test_is_valid_key_placeholder")


def test_is_valid_key_too_short():
    from core.llm_factory import _is_valid_key
    assert not _is_valid_key("sk-abc123"), "< 20 chars → invalide"
    assert not _is_valid_key("short"),      "5 chars → invalide"
    print("[OK] test_is_valid_key_too_short")


def test_is_valid_key_valid():
    from core.llm_factory import _is_valid_key
    assert _is_valid_key(_VALID_OPENAI_KEY),    "clé valide OpenAI → True"
    assert _is_valid_key(_VALID_ANTHROPIC_KEY), "clé valide Anthropic → True"
    print("[OK] test_is_valid_key_valid")


# ════════════════════════════════════════════════════════════════
# LLMFactory — blocage des clés invalides
# ════════════════════════════════════════════════════════════════

def test_llm_factory_openai_placeholder_returns_none():
    """_build_openai avec sk-CHANGE_ME doit retourner None."""
    from core.llm_factory import LLMFactory
    s   = _Settings(openai_key="sk-CHANGE_ME")
    fac = LLMFactory(s)
    result = fac._build_openai("fast")
    assert result is None, f"Doit retourner None pour sk-CHANGE_ME : {result}"
    print("[OK] test_llm_factory_openai_placeholder_returns_none")


def test_llm_factory_anthropic_empty_returns_none():
    """_build_anthropic avec clé vide doit retourner None."""
    from core.llm_factory import LLMFactory
    s   = _Settings(anthropic_key="")
    fac = LLMFactory(s)
    result = fac._build_anthropic("builder")
    assert result is None, f"Doit retourner None pour clé vide : {result}"
    print("[OK] test_llm_factory_anthropic_empty_returns_none")


def test_llm_factory_fast_role_uses_ollama_with_placeholder():
    """get('fast') avec sk-CHANGE_ME doit retourner Ollama, pas ChatOpenAI."""
    from core.llm_factory import LLMFactory
    s   = _Settings(openai_key="sk-CHANGE_ME")
    fac = LLMFactory(s)
    llm = fac.get("fast")
    # ChatOllama a un attribut model, ChatOpenAI a openai_api_key
    assert not hasattr(llm, "openai_api_key"), \
        f"Ne doit PAS être ChatOpenAI : {type(llm)}"
    # Doit être un ChatOllama (vérification duck-typing)
    assert hasattr(llm, "base_url") or "ollama" in type(llm).__name__.lower(), \
        f"Doit être ChatOllama : {type(llm)}"
    print(f"[OK] test_llm_factory_fast_role_uses_ollama_with_placeholder ({type(llm).__name__})")


def test_llm_factory_builder_role_uses_ollama_no_keys():
    """get('builder') sans aucune clé valide → Ollama."""
    from core.llm_factory import LLMFactory
    s   = _Settings(openai_key="", anthropic_key="")
    fac = LLMFactory(s)
    llm = fac.get("builder")
    assert not hasattr(llm, "openai_api_key"), "Ne doit PAS être ChatOpenAI"
    print(f"[OK] test_llm_factory_builder_role_uses_ollama_no_keys ({type(llm).__name__})")


def test_llm_factory_chain_skips_cloud_with_placeholder():
    """available_for_role('fast') avec sk-CHANGE_ME doit retourner 'ollama'."""
    from core.llm_factory import LLMFactory
    s        = _Settings(openai_key="sk-CHANGE_ME", anthropic_key="")
    fac      = LLMFactory(s)
    provider = fac.available_for_role("fast")
    assert provider == "ollama", f"Provider attendu 'ollama' : {provider}"
    print(f"[OK] test_llm_factory_chain_skips_cloud_with_placeholder (provider={provider})")


# ════════════════════════════════════════════════════════════════
# EscalationEngine — validate_cloud_keys
# ════════════════════════════════════════════════════════════════

def test_escalation_validate_keys_all_invalid():
    """validate_cloud_keys avec toutes clés invalides → any_valid=False."""
    from core.escalation_engine import EscalationEngine
    s    = _Settings(openai_key="sk-CHANGE_ME", anthropic_key="")
    keys = EscalationEngine.validate_cloud_keys(s)
    assert not keys["openai"],    f"openai doit être False : {keys}"
    assert not keys["anthropic"], f"anthropic doit être False : {keys}"
    assert not keys["any_valid"], f"any_valid doit être False : {keys}"
    print("[OK] test_escalation_validate_keys_all_invalid")


def test_escalation_validate_keys_valid_openai():
    """validate_cloud_keys avec clé OpenAI valide → openai=True."""
    from core.escalation_engine import EscalationEngine
    s    = _Settings(openai_key=_VALID_OPENAI_KEY, anthropic_key="")
    keys = EscalationEngine.validate_cloud_keys(s)
    assert keys["openai"],     f"openai doit être True : {keys}"
    assert keys["any_valid"],  f"any_valid doit être True : {keys}"
    print("[OK] test_escalation_validate_keys_valid_openai")


def test_escalation_disabled_with_placeholder():
    """EscalationEngine doit être désactivé si la clé est sk-CHANGE_ME."""
    from core.escalation_engine import EscalationEngine
    s      = _Settings(openai_key="sk-CHANGE_ME", anthropic_key="")
    engine = EscalationEngine(s)
    assert not engine.is_enabled, \
        "EscalationEngine doit être DISABLED avec clé placeholder"
    print("[OK] test_escalation_disabled_with_placeholder")


# ════════════════════════════════════════════════════════════════
# ModelSelector — local-first
# ════════════════════════════════════════════════════════════════

def test_model_selector_cloud_not_allowed_with_placeholder():
    """_cloud_allowed() doit retourner False si clé est sk-CHANGE_ME."""
    from core.model_selector import ModelSelector
    s  = _Settings(openai_key="sk-CHANGE_ME", anthropic_key="")
    ms = ModelSelector(s)
    assert not ms._cloud_allowed(), \
        "_cloud_allowed() doit être False avec clé placeholder"
    print("[OK] test_model_selector_cloud_not_allowed_with_placeholder")


def test_model_selector_select_returns_ollama_no_keys():
    """select() sans clé valide doit toujours retourner Ollama."""
    from core.model_selector import ModelSelector
    s  = _Settings(openai_key="sk-CHANGE_ME", anthropic_key="")
    ms = ModelSelector(s)

    for role in ("fast", "builder", "reviewer", "director", "planner", "main"):
        rec = ms.select(role, "Analyze the system architecture")
        assert rec.provider == "ollama", \
            f"Rôle {role} doit utiliser ollama : {rec.provider} ({rec.reason})"
    print("[OK] test_model_selector_select_returns_ollama_no_keys")


def test_model_selector_status_local_only():
    """get_status() avec clé invalide → mode='local_only'."""
    from core.model_selector import ModelSelector
    s  = _Settings(openai_key="sk-CHANGE_ME")
    ms = ModelSelector(s)
    status = ms.get_status()
    assert status["mode"] == "local_only", \
        f"mode doit être 'local_only' : {status['mode']}"
    assert not status["cloud_allowed"], \
        f"cloud_allowed doit être False : {status}"
    print(f"[OK] test_model_selector_status_local_only (mode={status['mode']})")


def test_model_selector_cloud_allowed_with_valid_key():
    """_cloud_allowed() avec vraie clé → True."""
    from core.model_selector import ModelSelector
    s  = _Settings(openai_key=_VALID_OPENAI_KEY)
    ms = ModelSelector(s)
    assert ms._cloud_allowed(), \
        "_cloud_allowed() doit être True avec clé valide"
    print("[OK] test_model_selector_cloud_allowed_with_valid_key")


def test_model_selector_status_cloud_available():
    """get_status() avec clé valide → mode='cloud_available'."""
    from core.model_selector import ModelSelector
    s  = _Settings(openai_key=_VALID_OPENAI_KEY)
    ms = ModelSelector(s)
    status = ms.get_status()
    assert status["mode"] == "cloud_available", \
        f"mode doit être 'cloud_available' : {status['mode']}"
    print(f"[OK] test_model_selector_status_cloud_available (mode={status['mode']})")


# ── Runner ────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== TEST _is_valid_key ===")
    test_is_valid_key_empty()
    test_is_valid_key_placeholder()
    test_is_valid_key_too_short()
    test_is_valid_key_valid()

    print("\n=== TEST LLMFactory — blocage cloud ===")
    test_llm_factory_openai_placeholder_returns_none()
    test_llm_factory_anthropic_empty_returns_none()
    test_llm_factory_fast_role_uses_ollama_with_placeholder()
    test_llm_factory_builder_role_uses_ollama_no_keys()
    test_llm_factory_chain_skips_cloud_with_placeholder()

    print("\n=== TEST EscalationEngine — validate_cloud_keys ===")
    test_escalation_validate_keys_all_invalid()
    test_escalation_validate_keys_valid_openai()
    test_escalation_disabled_with_placeholder()

    print("\n=== TEST ModelSelector — local-first ===")
    test_model_selector_cloud_not_allowed_with_placeholder()
    test_model_selector_select_returns_ollama_no_keys()
    test_model_selector_status_local_only()
    test_model_selector_cloud_allowed_with_valid_key()
    test_model_selector_status_cloud_available()

    print("\n=== TOUS LES TESTS LOCAL-ONLY : OK ===")
