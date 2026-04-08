"""
JARVIS MAX — LLM Factory
Routing intelligent par rôle avec cascade de fallback.

Règles :
- LOCAL_ONLY_ROLES : jamais de fallback cloud (advisor, memory, code, vision)
- builder/improve : fallback ollama TOUJOURS si clé cloud absente/invalide
- Une clé est invalide si : None | vide | contient CHANGE_ME | < 20 chars
- logs explicites : LOCAL_MODEL_SELECTED / CLOUD_ESCALATION_DISABLED_NO_KEY
- probe optionnel au démarrage pour détecter les providers disponibles
"""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import os
import time
import structlog
try:
    from langchain_core.language_models import BaseChatModel
except ImportError:
    from langchain_core.language_models.chat_models import BaseChatModel

# Per-task provider override — set by MetaOrchestrator when Phase 0c routing
# selects a specific provider. Thread-safe: each asyncio Task has its own context.
_provider_override: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_provider_override", default=None
)

# Pass 43 — use_safer_model: when True, non-LOCAL_ONLY roles prefer ollama (lighter, local)
# Set by meta_orchestrator when confidence_policy.use_safer_model=True.
# Async-safe ContextVar — scoped to the running coroutine only.
_safer_model_active: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_safer_model_active", default=False
)


@contextlib.contextmanager
def _null_ctx():
    """Contexte no-op pour remplacer tracer.generation() quand Langfuse est désactivé."""
    yield None

log = structlog.get_logger()

# ── Cache MetricsCollector (singleton par workspace) ──────────────────────────
# Évite d'instancier un nouveau collector (+ lecture disque) à chaque safe_invoke().
_METRICS_CACHE: dict[str, object] = {}


# ── Cache LangfuseTracer (singleton par workspace) ────────────────────────────
def _get_tracer(settings):
    """Retourne le LangfuseTracer singleton. Silencieux si absent/désactivé."""
    try:
        from observability.langfuse_tracer import get_tracer
        return get_tracer(settings)
    except Exception:
        return None


def _get_metrics(settings) -> object | None:
    """Retourne le MetricsCollector singleton pour ce workspace. Silencieux si absent."""
    try:
        ws = str(getattr(settings, "workspace_dir", ""))
        if ws not in _METRICS_CACHE:
            from monitoring.metrics import MetricsCollector
            _METRICS_CACHE[ws] = MetricsCollector(settings)
        return _METRICS_CACHE[ws]
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════
# CIRCUIT BREAKER — Ollama fail-fast
# ══════════════════════════════════════════════════════════════

class OllamaCircuitBreaker:
    """
    Fail-fast si Ollama est indisponible.
    Évite les cascades de timeout (5 agents × 120s = 10min de blocage).

    États :
      CLOSED  : circuit fermé — appels autorisés (état normal)
      OPEN    : Ollama présumé down — appels bloqués, fallback cloud
      HALF    : demi-ouverture pour tester la récupération

    Seuils par défaut :
      threshold=3  : 3 échecs consécutifs → OPEN
      window_s=60  : fenêtre d'observation (1 min)
      recover_s=30 : délai avant tentative HALF-OPEN
    """

    def __init__(self, threshold: int = 3, window_s: float = 60.0,
                 recover_s: float = 30.0):
        self.threshold  = threshold
        self.window_s   = window_s
        self.recover_s  = recover_s
        self._failures: list[float] = []
        self._opened_at: float      = 0.0
        self._state: str            = "CLOSED"

    def record_failure(self) -> None:
        now = time.monotonic()
        self._failures.append(now)
        # Nettoyer les échecs hors fenêtre
        self._failures = [t for t in self._failures if now - t <= self.window_s]
        if len(self._failures) >= self.threshold and self._state == "CLOSED":
            self._state     = "OPEN"
            self._opened_at = now
            log.warning(
                "ollama_circuit_open",
                failures=len(self._failures),
                window_s=self.window_s,
                hint="Ollama présumé down — fallback cloud activé",
            )

    def record_success(self) -> None:
        self._failures.clear()
        if self._state in ("OPEN", "HALF"):
            log.info("ollama_circuit_closed",
                     msg="Ollama de nouveau disponible — circuit fermé")
        self._state = "CLOSED"

    @property
    def is_open(self) -> bool:
        """True → Ollama présumé down, ne pas tenter de connexion."""
        if self._state == "CLOSED":
            return False
        if self._state == "OPEN":
            # Demi-ouverture après recover_s pour tester la récupération
            if time.monotonic() - self._opened_at >= self.recover_s:
                self._state = "HALF"
                log.info("ollama_circuit_half",
                         msg="Test de récupération Ollama (demi-ouverture)...")
                return False
            return True
        # HALF : laisser passer une tentative
        return False

    def get_status(self) -> dict:
        return {
            "state":     self._state,
            "failures":  len(self._failures),
            "threshold": self.threshold,
        }


# Singleton partagé entre toutes les instances de LLMFactory
_OLLAMA_CIRCUIT = OllamaCircuitBreaker(threshold=3, window_s=60.0, recover_s=30.0)

# ── Patterns de clés placeholder (invalides) ───────────────────
_PLACEHOLDER_FRAGMENTS: frozenset[str] = frozenset({
    "change_me", "changeme", "your_key", "your-key",
    "insert_key", "placeholder", "sk-change", "xxx",
    "yyy", "zzz", "api_key_here", "your_api_key",
})

def _is_valid_key(key: str | None) -> bool:
    """
    Retourne True uniquement si la clé API est réelle (non-placeholder).

    Invalide si :
      - None ou chaîne vide
      - Contient un fragment placeholder (CHANGE_ME, sk-CHANGE, etc.)
      - Longueur < 20 caractères
    """
    if not key:
        return False
    key_lower = key.lower().strip()
    if len(key_lower) < 20:
        return False
    for frag in _PLACEHOLDER_FRAGMENTS:
        if frag in key_lower:
            return False
    return True

# ── Rôles et leur provider préféré ─────────────────────────────
# IMPORTANT : les providers cloud ne sont tentés que si _is_valid_key() est True.
# En l'absence de clé valide, tous ces rôles basculent automatiquement sur Ollama.
ROLE_PROVIDERS: dict[str, str] = {
    "director":  "openrouter",  # Sonnet 4.5 via OpenRouter
    "builder":   "openrouter",  # Sonnet 4.5 → fallback anthropic → ollama
    "reviewer":  "openrouter",  # Sonnet 4.5 → fallback anthropic → ollama
    "research":  "openrouter",
    "planner":   "openrouter",
    "context":   "openrouter",
    "ops":       "openrouter",
    "improve":   "openrouter",  # Sonnet 4.5 → fallback anthropic → ollama
    "analyst":   "openrouter",  # Business analysis, strategy — Sonnet via OpenRouter
    "fast":      "openrouter",  # GPT-4o-mini via OpenRouter
    "default":   "openrouter",
    # Cloud-preferred roles (were ollama-only, now openrouter with ollama fallback)
    "advisor":    "openrouter",  # shadow-advisor — needs real LLM
    "memory":     "openrouter",  # vault-memory — needs real LLM
    # Local-only : jamais de cloud même en fallback
    "code":       "ollama",
    "vision":     "ollama",
    "uncensored": "ollama",  # 100% local — jamais de fallback cloud
}

# Ces rôles ne peuvent PAS utiliser de provider cloud
# Note : "advisor" (shadow-advisor) retiré de LOCAL_ONLY — il peut désormais fallback
# sur OpenAI-fast si Ollama est lent ou indisponible (R-06 SRE).
# "uncensored" : LOCAL_ONLY absolu — si Ollama est indisponible, RuntimeError levée.
LOCAL_ONLY_ROLES: frozenset[str] = frozenset({"code", "vision", "uncensored", "memory"})

# Rôles qui acceptent le fallback ollama si aucun cloud n'est dispo.
# Ces rôles préfèrent un LLM cloud mais fonctionnent 100% en local si
# aucune clé API n'est configurée (mode offline-safe garanti).
CLOUD_PREFERRED_ROLES: frozenset[str] = frozenset({
    "builder", "reviewer", "improve",   # self-improve pipeline
    "director", "planner", "fast",      # orchestrateur — offline-safe
})


class LLMFactory:
    def __init__(self, settings):
        self.s = settings
        # Cache par (provider, role) pour éviter de réinstancier
        self._cache: dict[tuple, BaseChatModel] = {}

    # Alias for callers that use get_llm() instead of get()
    def get_llm(self, role: str = "default") -> "BaseChatModel":
        return self.get(role)

    def get(self, role: str = "default",  # noqa: PLR0913
            task_description: str = "",
            complexity: str = "",
            budget: str = "",
            latency: str = "",
            mission_id: str = "") -> BaseChatModel:
        """
        Retourne le meilleur LLM disponible pour ce rôle.
        Lève RuntimeError si aucun provider n'est disponible.
        Reads _provider_override ContextVar set by Phase 0c routing.
        """
        _override = _provider_override.get()
        if _override and role not in LOCAL_ONLY_ROLES:
            preferred = _override
            log.debug("llm_provider_override_applied", role=role, provider=_override)
        else:
            preferred = ROLE_PROVIDERS.get(role, self.s.model_strategy)

        # Pass 43 — use_safer_model: downgrade cloud roles to ollama (local, conservative)
        # when confidence_policy decided the mission needs a lighter/safer model.
        # LOCAL_ONLY_ROLES already use ollama; _provider_override from routing takes priority.
        if _safer_model_active.get() and not _override and role not in LOCAL_ONLY_ROLES:
            preferred = "ollama"
            log.info("llm_safer_model_applied", role=role, downgraded_to="ollama")

        providers = self._build_chain(role, preferred)

        for provider in providers:
            cache_key = (provider, role)
            if cache_key in self._cache:
                return self._cache[cache_key]

            llm = self._build(provider, role)
            if llm:
                self._cache[cache_key] = llm
                if provider == "ollama":
                    log.info(
                        "LOCAL_MODEL_SELECTED",
                        role=role,
                        provider="ollama",
                        local_only=(role in LOCAL_ONLY_ROLES),
                    )
                else:
                    log.info(
                        "CLOUD_MODEL_SELECTED",
                        role=role,
                        provider=provider,
                    )
                # Alias lisible dans les logs existants
                log.info(
                    "llm_selected",
                    role=role,
                    provider=provider,
                    local_only=(role in LOCAL_ONLY_ROLES),
                )
                return llm

        raise RuntimeError(
            f"Aucun LLM disponible pour le rôle '{role}'. "
            f"Providers tentés : {providers}. "
            "Vérifier Ollama (ollama serve) ou configurer une clé API cloud."
        )

    def _build_chain(self, role: str, preferred: str) -> list[str]:
        """
        Construit la chaîne de fallback pour ce rôle.

        LOCAL_ONLY → [ollama] uniquement.
        CLOUD_PREFERRED → [preferred, fallback_cloud, ollama] :
            fallback ollama garanti pour builder/improve/reviewer
            → mode Ollama-only fonctionnel sans aucune clé cloud.
        Autres → [preferred, model_fallback, ollama].
        """
        if role in LOCAL_ONLY_ROLES:
            # Uncensored NEVER uses cloud. Other local-only roles can use openrouter if explicitly preferred.
            if role == "uncensored" or preferred != "openrouter":
                return ["ollama"]
            return ["openrouter", "ollama"]

        order: list[str] = [preferred]

        # Pour builder/improve/reviewer : s'assurer qu'ollama est toujours en fallback final
        if role in CLOUD_PREFERRED_ROLES:
            for extra in [self.s.model_fallback, "openai", "anthropic", "ollama"]:
                if extra not in order:
                    order.append(extra)
        else:
            fb = self.s.model_fallback
            if fb not in order:
                order.append(fb)
            if "ollama" not in order:
                order.append("ollama")

        return order

    def _build(self, provider: str, role: str) -> BaseChatModel | None:
        try:
            result = None
            if provider == "openai":
                result = self._build_openai(role)
            elif provider == "anthropic":
                result = self._build_anthropic(role)
            elif provider == "google":
                result = self._build_google(role)
            elif provider == "openrouter":
                result = self._build_openrouter(role)
            elif provider == "ollama":
                result = self._build_ollama(role)

            # Feedback circuit breaker : succès Ollama → fermer le circuit
            if result is not None and provider == "ollama":
                _OLLAMA_CIRCUIT.record_success()

            # Tagger le provider pour que safe_invoke() puisse remonter les métriques
            if result is not None:
                try:
                    result._jarvis_provider = provider  # type: ignore[attr-defined]
                except Exception:
                    pass

            return result

        except Exception as e:
            log.warning("llm_build_failed", provider=provider, role=role, error=str(e))
            # Feedback circuit breaker : échec Ollama → incrémenter les failures
            if provider == "ollama":
                _OLLAMA_CIRCUIT.record_failure()
        return None

    def _build_openai(self, role: str) -> BaseChatModel | None:
        key = getattr(self.s, "openai_api_key", "")
        if not _is_valid_key(key):
            log.debug(
                "CLOUD_ESCALATION_DISABLED_NO_KEY",
                provider="openai", role=role,
                reason="clé absente ou placeholder",
            )
            return None
        from langchain_openai import ChatOpenAI
        model = self.s.openai_model_fast if role == "fast" else self.s.openai_model
        return ChatOpenAI(
            model=model,
            api_key=key,
            temperature=0.3,
            timeout=90,
        )

    def _build_anthropic(self, role: str) -> BaseChatModel | None:
        key = getattr(self.s, "anthropic_api_key", "")
        if not _is_valid_key(key):
            log.debug(
                "CLOUD_ESCALATION_DISABLED_NO_KEY",
                provider="anthropic", role=role,
                reason="clé absente ou placeholder",
            )
            return None
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=self.s.anthropic_model,
            api_key=key,
            temperature=0.3,
            timeout=90,
        )

    def _build_google(self, role: str) -> BaseChatModel | None:
        key = getattr(self.s, "google_api_key", "")
        if not _is_valid_key(key):
            return None
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=self.s.google_model,
            google_api_key=key,
            temperature=0.3,
        )


    def _build_openrouter(self, role: str) -> BaseChatModel | None:
        """Build OpenRouter LLM — role-based model routing via cloud gateway.

        Model strategy (stability-first):
        - ORCHESTRATOR (sonnet): complex orchestration, architecture, coding, self-improvement
        - FAST (gpt-4o-mini): classification, triage, short summaries, extraction, validation
        - FALLBACK (gpt-4o-mini): used when primary model fails
        - VISION (gpt-4o-mini): lightweight image understanding
        """
        key = getattr(self.s, "openrouter_api_key", "")
        if not _is_valid_key(key):
            log.debug(
                "CLOUD_ESCALATION_DISABLED_NO_KEY",
                provider="openrouter", role=role,
                reason="clé absente ou placeholder",
            )
            return None
        from langchain_openai import ChatOpenAI

        # Role → model mapping (stability-first: expensive only when necessary)
        _FAST = getattr(self.s, "fast_model", "openai/gpt-4o-mini")
        _ORCH = getattr(self.s, "orchestrator_model", "anthropic/claude-sonnet-4.5")
        _ARCH = getattr(self.s, "architect_model", _ORCH)
        _CODE = getattr(self.s, "coder_model", _ORCH)
        _SELF = getattr(self.s, "self_improvement_model", _ORCH)
        _FALL = getattr(self.s, "fallback_model", _FAST)
        _VIS  = getattr(self.s, "vision_model_or", _FAST)

        model_map = {
            # ── Heavy roles → Sonnet ──────────────────────────────────────
            "director":            _ORCH,
            "planner":             _ORCH,
            "ops":                 _ORCH,
            "research":            _ORCH,
            "default":             _ORCH,
            "builder":             _CODE,
            "improve":             _SELF,
            "reviewer":            _CODE,
            "context":             _ARCH,
            "analyst":             _ORCH,   # Business analysis, strategy
            "advisor":             _ORCH,   # Shadow-advisor — security/audit
            "memory":              _FAST,   # Vault-memory — context/retrieval
            # ── Light roles → GPT-4o-mini ─────────────────────────────────
            "fast":                _FAST,
            "classify":            _FAST,
            "route":               _FAST,
            "extract":             _FAST,
            "summarize":           _FAST,
            "validate":            _FAST,
            "pre_assess":          _FAST,
            "risk_score":          _FAST,
            "format_output":       _FAST,
            # ── Special roles ─────────────────────────────────────────────
            "vision":              _VIS,
            "fallback":            _FALL,
        }

        model_id = model_map.get(role, _ORCH)

        # ── ModelSelector: use evidence-driven model when catalog is populated ──
        # Falls back to model_map if selector fails or has no catalog data.
        # Set MODEL_SELECTOR_ENABLED=false in .env to always use model_map values.
        _selector_model: str | None = None
        _selector_reason: str = ""
        _selector_is_fallback: bool = True
        _selector_score: float = 0.0
        # Default to DISABLED — model_selector was overriding reliable configured models
        # with free/unstable models causing timeouts. Set MODEL_SELECTOR_ENABLED=true to re-enable.
        _selector_enabled = os.getenv("MODEL_SELECTOR_ENABLED", "false").lower() in ("true", "1", "yes")
        if _selector_enabled:
            try:
                from core.model_intelligence.selector import get_model_selector
                sel = get_model_selector()
                result = sel.select_for_role(role, budget_mode="normal")
                if result and result.model_id and not result.is_fallback:
                    _selector_model = result.model_id
                    _selector_reason = result.rationale or ""
                    _selector_is_fallback = False
                    _selector_score = round(result.final_score, 3)
            except Exception:
                pass  # Selector unavailable → use model_map default

        if _selector_model and _selector_model != model_id:
            log.info(
                "model_selector_override",
                role=role,
                model_map_default=model_id,
                selector_choice=_selector_model,
                score=_selector_score,
                rationale=_selector_reason[:120],
            )
            model_id = _selector_model

        # OPENROUTER_MODEL_SELECTED — canonical log event for routing decisions
        log.info(
            "OPENROUTER_MODEL_SELECTED",
            role=role,
            model=model_id,
            tier="FAST" if model_id == _FAST else "ORCHESTRATOR" if model_id == _ORCH else "SPECIAL",
            selector_used=(not _selector_is_fallback),
            selector_score=_selector_score,
        )
        model = model_id
        return ChatOpenAI(
            model=model,
            api_key=key,
            base_url=getattr(self.s, "openrouter_base_url", "https://openrouter.ai/api/v1"),
            temperature=0.3,
            timeout=90,
            default_headers={
                "HTTP-Referer": "https://jarvis.jarvismaxapp.co.uk",
                "X-Title": "JarvisMax",
            },
        )

    def _build_ollama(self, role: str) -> BaseChatModel | None:
        # Circuit breaker : si Ollama est présumé down, ne pas construire le LLM
        if _OLLAMA_CIRCUIT.is_open:
            log.warning(
                "ollama_circuit_blocked",
                role=role,
                state=_OLLAMA_CIRCUIT.get_status()["state"],
                hint="Circuit ouvert — fallback cloud ou dégradé",
            )
            return None

        from langchain_ollama import ChatOllama
        # Mapping rôle → modèle Ollama
        # Pour builder/improve en mode local : deepseek-coder-v2:16b recommandé,
        # mais on utilise ollama_model_code (configurable via OLLAMA_MODEL_CODE).
        model_map = {
            "code":       self.s.ollama_model_code,
            "vision":     self.s.ollama_model_vision,
            "fast":       self.s.ollama_model_fast,
            "memory":     self.s.ollama_model_fast,
            "advisor":    self.s.ollama_model_fast,
            # llama3.1:8b : plus rapide, suit mieux les instructions JSON
            # deepseek-coder-v2:16b trop lent (timeout 120s) et refuse les tâches de patch
            "builder":    self.s.ollama_model_main,
            "improve":    self.s.ollama_model_main,
            "reviewer":   self.s.ollama_model_main,
            # Mode uncensored : modèle dédié sans filtres de sécurité
            "uncensored": getattr(self.s, "ollama_model_uncensored", "dolphin-mixtral"),
        }
        m = model_map.get(role, self.s.ollama_model_main)

        # Pour builder/reviewer/improve : activer le mode JSON natif d'Ollama.
        # format="json" force physiquement une sortie JSON valide, quel que soit le modèle.
        # Sans cela, les modèles répondent en texte libre même avec un prompt strict.
        # "improve" = rôle audit LLM → doit aussi retourner un JSON structuré.
        json_roles = frozenset({"builder", "reviewer", "improve"})
        kwargs: dict = {"model": m, "base_url": self.s.ollama_host, "temperature": 0.1}
        if role in json_roles:
            kwargs["format"] = "json"

        return ChatOllama(**kwargs)

    # ── Warm-up optionnel ────────────────────────────────────

    async def probe_providers(self) -> dict[str, bool]:
        """
        Teste la disponibilité des providers au démarrage.
        N'interrompt pas le démarrage si un provider est indisponible.
        """
        import httpx
        results: dict[str, bool] = {}

        # OpenAI — seulement si clé valide (non-placeholder)
        oai_key = getattr(self.s, "openai_api_key", "")
        if _is_valid_key(oai_key):
            try:
                async with httpx.AsyncClient(timeout=5.0) as c:
                    r = await c.get(
                        "https://api.openai.com/v1/models",
                        headers={"Authorization": f"Bearer {oai_key}"},
                    )
                    results["openai"] = r.status_code == 200
            except Exception:
                results["openai"] = False
        else:
            results["openai"] = False
            log.debug("CLOUD_ESCALATION_DISABLED_NO_KEY",
                      provider="openai", reason="probe: clé absente ou placeholder")

        # Anthropic — seulement si clé valide
        ant_key = getattr(self.s, "anthropic_api_key", "")
        if _is_valid_key(ant_key):
            try:
                async with httpx.AsyncClient(timeout=5.0) as c:
                    r = await c.get(
                        "https://api.anthropic.com/v1/models",
                        headers={
                            "x-api-key": ant_key,
                            "anthropic-version": "2023-06-01",
                        },
                    )
                    results["anthropic"] = r.status_code == 200
            except Exception:
                results["anthropic"] = False
        else:
            results["anthropic"] = False
            log.debug("CLOUD_ESCALATION_DISABLED_NO_KEY",
                      provider="anthropic", reason="probe: clé absente ou placeholder")

        # Ollama — /api/version disponible dès le démarrage, avant tout modèle
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(f"{self.s.ollama_host}/api/version")
                results["ollama"] = r.status_code == 200
        except Exception:
            results["ollama"] = False

        # Google
        results["google"] = bool(self.s.google_api_key)

        log.info("llm_providers_probe", results=results)

        if not results.get("ollama"):
            log.warning(
                "ollama_unreachable",
                msg="Ollama indisponible — LOCAL_ONLY roles et mode local-only ne fonctionneront pas",
            )

        cloud_ok = any(results.get(p) for p in ["openai", "anthropic", "google"])
        if not cloud_ok:
            log.warning(
                "no_cloud_provider",
                msg="Aucun provider cloud — mode Ollama-only. "
                    "builder/improve/reviewer utiliseront OLLAMA_MODEL_CODE.",
            )

        return results

    async def safe_invoke(
        self,
        messages: list,
        role: str = "fast",
        timeout: float = 60.0,
        session_id: str = "",
        agent_name: str = "",
        task_description: str = "",
        budget: str = "",
        latency: str = "",
    ):
        """
        Invoque le LLM avec protection circuit breaker + fallback automatique.

        Comportement :
        - Tente le provider principal (get(role))
        - Sur succès  → alimente record_success() si Ollama + trace Langfuse
        - Sur échec   → alimente record_failure() si Ollama + erreur Langfuse
                      → tente les providers cloud en cascade (pour non LOCAL_ONLY)
        - Log structuré à chaque étape : llm_call_ok / llm_call_failed / llm_fallback_*

        Paramètres optionnels :
            session_id : ID de session JarvisSession (pour grouper les traces)
            agent_name : nom de l'agent appelant (pour le tag Langfuse)

        Usage :
            factory = LLMFactory(settings)
            resp = await factory.safe_invoke(messages, role="fast", timeout=60.0)
            text = resp.content
        """
        llm       = self.get(role)
        provider  = getattr(llm, "_jarvis_provider", "unknown")
        model_name = getattr(llm, "model_name", getattr(llm, "model", provider))
        t0        = time.monotonic()

        # ── Traçage Langfuse (optionnel, non-bloquant) ────────
        tracer = _get_tracer(self.s)

        # ── Tentative principale ──────────────────────────────
        with (tracer.generation(session_id, role, messages, model_name, agent_name)
              if tracer else _null_ctx()) as gen_ctx:
            try:
                resp = await asyncio.wait_for(llm.ainvoke(messages), timeout=timeout)
                ms   = int((time.monotonic() - t0) * 1000)
                log.info(
                    "llm_call_ok",
                    role=role, provider=provider, latency_ms=ms,
                )
                if provider == "ollama":
                    _OLLAMA_CIRCUIT.record_success()
                # ── Métriques observabilité ───────────────────
                try:
                    m = _get_metrics(self.s)
                    if m:
                        m.record_llm_call(role, latency_s=ms / 1000.0, error=False)
                except Exception:
                    pass
                # ── Langfuse : clôturer la generation ─────────
                if gen_ctx is not None:
                    try:
                        output_text = getattr(resp, "content", str(resp))
                        # Tokens si disponibles (OpenAI response_metadata)
                        usage = getattr(resp, "response_metadata", {}).get("token_usage", {})
                        gen_ctx.finish(
                            output=output_text,
                            input_tokens=usage.get("prompt_tokens", 0),
                            output_tokens=usage.get("completion_tokens", 0),
                        )
                    except Exception:
                        pass
                return resp

            except Exception as first_err:
                ms         = int((time.monotonic() - t0) * 1000)
                is_timeout = isinstance(first_err, asyncio.TimeoutError)
                log.warning(
                    "llm_call_failed",
                    role=role, provider=provider, latency_ms=ms,
                    error_type="timeout" if is_timeout else type(first_err).__name__,
                    err=str(first_err)[:120],
                )
                if provider == "ollama":
                    _OLLAMA_CIRCUIT.record_failure()
                # ── Langfuse : signaler l'erreur ──────────────
                if gen_ctx is not None:
                    try:
                        gen_ctx.finish(error=str(first_err)[:200])
                    except Exception:
                        pass
            # ── Métriques erreur ──────────────────────────────
            try:
                m = _get_metrics(self.s)
                if m:
                    m.record_llm_call(role, latency_s=ms / 1000.0, error=True)
            except Exception:
                pass

        # ── Fallback cloud (uniquement pour rôles non-LOCAL_ONLY) ─
        if role not in LOCAL_ONLY_ROLES:
            preferred     = ROLE_PROVIDERS.get(role, "openai")
            fallback_chain = [
                p for p in self._build_chain(role, preferred)
                if p != provider and p != "ollama"
            ]
            for fb_provider in fallback_chain:
                fb_llm = (
                    self._cache.get((fb_provider, role))
                    or self._build(fb_provider, role)
                )
                if not fb_llm:
                    continue
                t1 = time.monotonic()
                try:
                    log.info(
                        "llm_fallback_attempt",
                        role=role, primary=provider, fallback=fb_provider,
                    )
                    resp2 = await asyncio.wait_for(
                        fb_llm.ainvoke(messages), timeout=timeout
                    )
                    ms2 = int((time.monotonic() - t1) * 1000)
                    log.info(
                        "llm_fallback_ok",
                        role=role, fallback=fb_provider, latency_ms=ms2,
                    )
                    try:
                        m = _get_metrics(self.s)
                        if m:
                            m.record_llm_call(
                                f"{role}_fallback_{fb_provider}",
                                latency_s=ms2 / 1000.0,
                                error=False,
                            )
                    except Exception:
                        pass
                    return resp2

                except Exception as fb_err:
                    ms2 = int((time.monotonic() - t1) * 1000)
                    log.warning(
                        "llm_fallback_failed",
                        role=role, fallback=fb_provider, latency_ms=ms2,
                        err=str(fb_err)[:80],
                    )

        # Aucun provider n'a répondu → reraise TimeoutError pour que
        # l'appelant puisse afficher un message de dégradation propre.
        raise asyncio.TimeoutError(
            f"LLM '{role}' indisponible (provider={provider}, fallbacks épuisés)"
        )

    def available_for_role(self, role: str) -> str:
        """Retourne le provider qui sera utilisé pour ce rôle (debug/status)."""
        preferred = ROLE_PROVIDERS.get(role, "openai")
        chain = self._build_chain(role, preferred)
        for provider in chain:
            llm = self._build(provider, role)
            if llm:
                return provider
        return "none"

    @staticmethod
    def get_circuit_status() -> dict:
        """Retourne l'état du circuit breaker Ollama."""
        return _OLLAMA_CIRCUIT.get_status()

    @staticmethod
    def reset_circuit() -> None:
        """Réinitialise manuellement le circuit breaker (debug/admin)."""
        _OLLAMA_CIRCUIT.record_success()
        log.info("ollama_circuit_reset_manual")
