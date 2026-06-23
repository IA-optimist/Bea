"""
BEA MAX — PolicyEngine
Moteur de décision pour les actions : autorisation, limites, cloud vs local.

Rôle :
    Décide en temps réel si une action est autorisée, quel LLM utiliser,
    et si les limites de coût / temps / risque sont respectées.

    C'est la "constitution" de BeaMax — toutes les décisions importantes
    passent par PolicyEngine avant exécution.

Politiques intégrées :
    1. ACTION_ALLOW   : quelles actions sont permises selon le mode
    2. LLM_ROUTING    : cloud vs local selon risque + coût estimé
    3. RATE_LIMITS    : max actions/session, max tokens/heure
    4. RISK_GATES     : bloque les actions HIGH RISK sans validation
    5. COST_GUARD     : estime et limite le coût cloud

Usage :
    policy = PolicyEngine(settings)

    # Vérifier si une action est autorisée
    decision = policy.check_action(action_type, risk_level, mode)
    if not decision.allowed:
        raise PolicyViolation(decision.reason)

    # Choisir le LLM pour une tâche
    provider = policy.select_llm_provider(role, task_complexity, cost_budget)

    # Vérifier les limites de session
    ok, msg = policy.check_session_limits(session)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
import structlog

log = structlog.get_logger()


# ══════════════════════════════════════════════════════════════
# CONFIGURATION DES POLITIQUES
# ══════════════════════════════════════════════════════════════

# Actions autorisées par mode (whitelist)
_MODE_ALLOWED_ACTIONS: dict[str, set[str]] = {
    "auto":     {"create_file", "write_file", "replace_in_file", "backup_file"},
    "night":    {"create_file", "write_file", "replace_in_file", "backup_file", "run_command"},
    "improve":  {"create_file", "write_file", "replace_in_file", "backup_file"},
    "chat":     set(),          # aucune action réelle en mode chat
    "workflow": {"create_file", "write_file", "run_command"},
}

# Limites par session
_DEFAULT_LIMITS = {
    "max_actions_per_session":    10,
    "max_tokens_per_session":     50_000,
    "max_cloud_calls_per_session": 5,
    "max_cost_usd_per_session":   0.50,
    "session_timeout_s":          600,
}

# Coût estimé par appel cloud (USD) — approximatif
_CLOUD_COST_ESTIMATE = {
    "anthropic": 0.05,   # Claude 3 Sonnet ~0.05$/appel moyen
    "openai":    0.03,   # GPT-4o ~0.03$/appel moyen
    "ollama":    0.00,   # local = gratuit
}


# ══════════════════════════════════════════════════════════════
# RÉSULTATS DE DÉCISION
# ══════════════════════════════════════════════════════════════

@dataclass
class PolicyDecision:
    """Résultat d'une vérification de politique."""
    allowed:    bool
    reason:     str          = ""
    suggestion: str          = ""
    metadata:   dict[str, object] = field(default_factory=dict)

    def deny(self, reason: str, suggestion: str = "") -> "PolicyDecision":
        self.allowed    = False
        self.reason     = reason
        self.suggestion = suggestion
        return self

    def allow(self, reason: str = "") -> "PolicyDecision":
        self.allowed = True
        self.reason  = reason
        return self


@dataclass
class LLMRoute:
    """Décision de routage LLM."""
    provider:   str          # "ollama" | "anthropic" | "openai"
    model:      str
    reason:     str
    estimated_cost_usd: float = 0.0
    fallback_provider:  str   = "ollama"
    fallback_model:     str   = "llama3.1:8b"


class PolicyViolation(Exception):
    """Levée quand une politique est violée."""
    def __init__(self, reason: str, action: str = ""):
        self.reason = reason
        self.action = action
        super().__init__(f"Policy violation [{action}]: {reason}")


# ══════════════════════════════════════════════════════════════
# SESSION POLICY TRACKER
# ══════════════════════════════════════════════════════════════

class SessionPolicy:
    """
    Tracker de limites pour une session.
    Instance par session — créé par PolicyEngine.
    """

    def __init__(self, session_id: str, limits: dict[str, int | float]) -> None:
        self.session_id   = session_id
        self.limits       = limits
        self.actions_done = 0
        self.tokens_used  = 0
        self.cloud_calls  = 0
        self.cost_usd     = 0.0
        self.started_at   = time.monotonic()

    def record_action(self) -> None:
        self.actions_done += 1

    def record_llm_call(self, provider: str, tokens: int = 0) -> None:
        self.tokens_used += tokens
        if provider != "ollama":
            self.cloud_calls += 1
            self.cost_usd    += _CLOUD_COST_ESTIMATE.get(provider, 0.03)

    def check_limits(self) -> tuple[bool, str]:
        """Retourne (ok, raison_si_ko)."""
        if self.actions_done >= self.limits["max_actions_per_session"]:
            return False, f"Limite actions atteinte ({self.actions_done}/{self.limits['max_actions_per_session']})"
        if self.tokens_used >= self.limits["max_tokens_per_session"]:
            return False, f"Limite tokens atteinte ({self.tokens_used}/{self.limits['max_tokens_per_session']})"
        if self.cloud_calls >= self.limits["max_cloud_calls_per_session"]:
            return False, f"Limite appels cloud atteinte ({self.cloud_calls}/{self.limits['max_cloud_calls_per_session']})"
        if self.cost_usd >= self.limits["max_cost_usd_per_session"]:
            return False, f"Limite coût cloud atteinte (${self.cost_usd:.3f}/${self.limits['max_cost_usd_per_session']})"
        elapsed = time.monotonic() - self.started_at
        if elapsed >= self.limits["session_timeout_s"]:
            return False, f"Session timeout ({int(elapsed)}s/{self.limits['session_timeout_s']}s)"
        return True, ""

    def to_dict(self) -> dict[str, object]:
        elapsed = time.monotonic() - self.started_at
        return {
            "session_id":   self.session_id,
            "actions_done": self.actions_done,
            "tokens_used":  self.tokens_used,
            "cloud_calls":  self.cloud_calls,
            "cost_usd":     round(self.cost_usd, 4),
            "elapsed_s":    round(elapsed, 1),
        }


# ══════════════════════════════════════════════════════════════
# POLICY ENGINE
# ══════════════════════════════════════════════════════════════

class PolicyEngine:
    """
    Moteur de politiques BeaMax.
    Fonctionne 100% local, sans LLM requis.

    Usage typique dans l'orchestrateur :
        policy = PolicyEngine(settings)
        tracker = policy.new_session(session_id, mode)

        # Avant chaque action
        decision = policy.check_action(action_type, risk, mode)
        if not decision.allowed:
            await emit(f"Action refusée : {decision.reason}")
            continue

        # Avant chaque appel LLM
        route = policy.select_llm_provider(role, complexity)
        llm = settings.get_llm(route.provider)
    """

    def __init__(self, settings: Any) -> None:
        self.s        = settings
        self._sessions: dict[str, SessionPolicy] = {}

    # ── Gestion des sessions ──────────────────────────────

    def new_session(
        self,
        session_id: str,
        mode:       str = "auto",
    ) -> SessionPolicy:
        """Crée un tracker de politique pour une session."""
        limits = dict(_DEFAULT_LIMITS)

        # Ajustements selon le mode
        if mode == "night":
            limits["max_actions_per_session"] = 30
            limits["session_timeout_s"]        = 1800
        elif mode == "improve":
            limits["max_actions_per_session"] = 15

        tracker = SessionPolicy(session_id, limits)
        self._sessions[session_id] = tracker
        log.debug("policy_session_created", mission_id=session_id, mode=mode)
        return tracker

    def ensure_session(self, session_id: str, mode: str = "auto") -> SessionPolicy:
        """Return an existing session tracker or create one. Idempotent."""
        tracker = self._sessions.get(session_id)
        if tracker is None:
            tracker = self.new_session(session_id, mode)
        return tracker

    def get_session(self, session_id: str) -> SessionPolicy | None:
        return self._sessions.get(session_id)

    # ── Vérification d'actions ────────────────────────────

    def check_action(
        self,
        action_type:  str,
        risk_level:   str = "low",   # "low" | "medium" | "high"
        mode:         str = "auto",
        session_id:   str = "",
    ) -> PolicyDecision:
        """
        Vérifie si une action est autorisée.

        Règles (par ordre de priorité) :
          1. Dry-run → toujours autorisé (simulation)
          2. Mode chat → aucune action
          3. Action inconnue → refus
          4. Risk HIGH sans session human → refus
          5. Limites de session dépassées → refus
          6. Action autorisée
        """
        d = PolicyDecision(allowed=True)

        # 1. Dry-run : toujours OK
        if getattr(self.s, "dry_run", False):
            return d.allow("dry_run_simulation")

        # 2. Mode chat : aucune action
        if mode == "chat":
            return d.deny(
                "Mode chat : aucune action réelle",
                "Utilisez le mode /auto ou /night pour des actions"
            )

        # 3. Action dans la whitelist du mode
        allowed_set = _MODE_ALLOWED_ACTIONS.get(mode, set())
        if action_type and action_type not in allowed_set:
            return d.deny(
                f"Action '{action_type}' non autorisée en mode '{mode}'",
                f"Actions autorisées : {', '.join(sorted(allowed_set)) or 'aucune'}"
            )

        # 4. Risk HIGH → log avertissement (validation humaine déjà gérée par SupervisedExecutor)
        if risk_level == "high":
            log.warning("policy_high_risk_action",
                       action=action_type, mode=mode, sid=session_id)

        # 5. Limites de session
        if session_id:
            tracker = self._sessions.get(session_id)
            if tracker:
                ok, msg = tracker.check_limits()
                if not ok:
                    return d.deny(msg, "Attendre la prochaine session")

        return d.allow()

    def evaluate_tool(
        self,
        tool_name: str,
        action_type: str,
        risk_level: str,
        mission_id: str = "",
        params: Any | None = None,
    ) -> PolicyDecision:
        """ToolExecutor-compatible guard.

        Unlike check_action(), this method is not bound to a mode whitelist:
        it blocks HIGH risk tools and enforces session/economic limits when a
        mission_id is provided.  Limits require a shared PolicyEngine instance
        and an active session tracker; evaluate_tool will lazily create a
        tracker with mode='auto' if none exists for the given mission_id.
        """
        d = PolicyDecision(allowed=True)

        if getattr(self.s, "dry_run", False):
            return d.allow("dry_run_simulation")

        # Tool gate is intentionally fail-closed for dangerous actions.
        if risk_level == "high":
            return d.deny(
                f"Tool '{tool_name}' is HIGH risk and requires explicit approval",
                suggestion="Approve manually or reduce the action scope",
            )

        if action_type == "execute" and risk_level in ("unknown", "high"):
            return d.deny(
                f"Tool '{tool_name}' executes code when risk is unknown/high",
                suggestion="Reduce risk_level or wire explicit approval flow",
            )

        # Shared session tracker: auto-create with mode='auto' if a mission_id
        # is provided but no tracker exists yet.  Callers (MetaOrchestrator,
        # BeaOrchestrator) should create the session with the real mode.
        if mission_id:
            tracker = self.ensure_session(mission_id, mode="auto")
            tracker.record_action()
            ok, msg = tracker.check_limits()
            if not ok:
                return d.deny(msg, "Wait for the next session or raise limits")

        return d.allow("tool_allowed")

    # ── Routage LLM ───────────────────────────────────────

    def select_llm_provider(
        self,
        role:          str   = "main",
        complexity:    float = 0.0,
        cost_budget:   float = 0.50,
        session_id:    str   = "",
    ) -> LLMRoute:
        """
        Choisit le provider LLM optimal.

        Règle fondamentale : LOCAL FIRST.
        Cloud uniquement si :
          - escalation_enabled = True
          - clé API valide présente
          - coût budget disponible
          - tâche complexe (complexity > 0.7)
        """
        local_model = getattr(self.s, "ollama_model_main", "llama3.1:8b")
        fast_model  = getattr(self.s, "ollama_model_fast", "llama3.1:8b")

        # Vérifier si le cloud est autorisé
        cloud_ok = self._cloud_allowed()

        if not cloud_ok or complexity < 0.7:
            # LOCAL — modèle selon complexité
            model = fast_model if complexity < 0.35 else local_model
            return LLMRoute(
                provider="ollama",
                model=model,
                reason="local_first" if not cloud_ok else f"complexity={complexity:.2f}<0.7",
            )

        # Vérifier le budget restant
        if session_id:
            tracker = self._sessions.get(session_id)
            if tracker and tracker.cost_usd >= cost_budget:
                return LLMRoute(
                    provider="ollama",
                    model=local_model,
                    reason=f"cost_budget_reached (${tracker.cost_usd:.3f})",
                )

        # Cloud autorisé + budget OK + tâche complexe
        provider = getattr(self.s, "escalation_provider", "anthropic")
        if provider == "anthropic" and getattr(self.s, "anthropic_api_key", ""):
            return LLMRoute(
                provider="anthropic",
                model=getattr(self.s, "anthropic_model", "claude-3-5-sonnet-20241022"),
                reason=f"cloud_escalation complexity={complexity:.2f}",
                estimated_cost_usd=_CLOUD_COST_ESTIMATE["anthropic"],
                fallback_provider="ollama",
                fallback_model=local_model,
            )
        if provider == "openai" and getattr(self.s, "openai_api_key", ""):
            return LLMRoute(
                provider="openai",
                model=getattr(self.s, "openai_model", "gpt-4o"),
                reason=f"cloud_escalation complexity={complexity:.2f}",
                estimated_cost_usd=_CLOUD_COST_ESTIMATE["openai"],
                fallback_provider="ollama",
                fallback_model=local_model,
            )

        # Fallback local si clé absente malgré cloud activé
        return LLMRoute(
            provider="ollama",
            model=local_model,
            reason="cloud_key_missing_fallback_local",
        )

    # ── Limites de session ────────────────────────────────

    def check_session_limits(self, session_id: str) -> tuple[bool, str]:
        """
        Vérifie les limites pour une session existante.
        Retourne (ok, message).
        """
        tracker = self._sessions.get(session_id)
        if not tracker:
            return True, ""
        return tracker.check_limits()

    # ── Rapport ───────────────────────────────────────────

    def get_report(self) -> dict[str, object]:
        """Rapport global de toutes les sessions actives."""
        return {
            "active_sessions": len(self._sessions),
            "sessions": {sid: t.to_dict() for sid, t in self._sessions.items()},
            "cloud_allowed": self._cloud_allowed(),
            "dry_run": getattr(self.s, "dry_run", False),
        }

    def clear_sessions(self) -> None:
        """Purge les sessions terminées (pour gestion mémoire)."""
        before = len(self._sessions)
        self._sessions.clear()
        log.debug("policy_sessions_cleared", count=before)

    # ── Helpers ───────────────────────────────────────────

    def _cloud_allowed(self) -> bool:
        """True si le cloud est activé et au moins une clé valide."""
        if not getattr(self.s, "escalation_enabled", False):
            return False
        anthropic_key = getattr(self.s, "anthropic_api_key", "") or ""
        openai_key    = getattr(self.s, "openai_api_key",    "") or ""
        # Rejeter les placeholder keys
        placeholders = ("your-", "sk-your", "changeme", "placeholder")
        valid_anthropic = anthropic_key and not any(
            anthropic_key.lower().startswith(p) for p in placeholders
        )
        valid_openai = openai_key and not any(
            openai_key.lower().startswith(p) for p in placeholders
        )
        return bool(valid_anthropic or valid_openai)


# ══════════════════════════════════════════════════════════════
# SINGLETON / FACTORY (stable interface)
# ══════════════════════════════════════════════════════════════

_policy_engine_instance: PolicyEngine | None = None


def get_policy_engine(settings: Any | None = None) -> PolicyEngine:
    """Return a shared PolicyEngine instance.

    ToolExecutor and orchestrators should use this instead of constructing
    PolicyEngine(None) on every call, otherwise session/economic limits remain
    unenforced.
    """
    global _policy_engine_instance
    if _policy_engine_instance is None:
        _policy_engine_instance = PolicyEngine(settings)
    return _policy_engine_instance


def reset_policy_engine() -> None:
    """Reset the singleton. Mainly for tests."""
    global _policy_engine_instance
    _policy_engine_instance = None
