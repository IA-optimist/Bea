"""
BEA MAX — EscalationEngine
Préparation de l'escalade intelligente vers les modèles cloud (OpenAI / Claude).

IMPORTANT : Les API cloud sont DÉSACTIVÉES par défaut.
L'escalade ne s'active que si :
  1. Une clé API est configurée dans .env
  2. `escalation_enabled = True` dans les settings
  3. Le score de complexité dépasse le seuil configuré

Architecture :
    local_model (Ollama llama3.1:8b)
         ↓  si tâche complexe ET escalade activée
    cloud_model (OpenAI gpt-4 ou Claude claude-3-5-sonnet)

L'EscalationEngine ne modifie pas llm_factory.py.
Il se branche via un flag optionnel dans les agents.

Interface :
    engine = EscalationEngine(settings)
    if engine.should_escalate(context):
        model = engine.get_escalation_model(role)
        # utiliser model pour l'invocation LLM
    ctx = engine.build_context(task, failures, complexity)
"""
from __future__ import annotations

import structlog
from dataclasses import dataclass, field

log = structlog.get_logger()

# ── Seuils de complexité ──────────────────────────────────────

_DEFAULT_COMPLEXITY_THRESHOLD = 0.75    # score 0.0–1.0
_DEFAULT_FAILURE_THRESHOLD    = 3       # nb d'échecs consécutifs
_DEFAULT_OUTPUT_LENGTH_LIMIT  = 500     # chars minimum attendus en local

# ── Mapping rôle → modèle cloud préféré ──────────────────────

_CLOUD_MODELS: dict[str, dict] = {
    "director":  {"openai": "gpt-4o",               "anthropic": "claude-opus-4-5"},
    "builder":   {"openai": "gpt-4o",               "anthropic": "claude-sonnet-4-5"},
    "reviewer":  {"openai": "gpt-4o-mini",          "anthropic": "claude-haiku-4-5"},
    "research":  {"openai": "gpt-4o",               "anthropic": "claude-sonnet-4-5"},
    "planner":   {"openai": "gpt-4o",               "anthropic": "claude-sonnet-4-5"},
    "default":   {"openai": "gpt-4o-mini",          "anthropic": "claude-haiku-4-5"},
}

# ── Indicateurs de complexité élevée ─────────────────────────

_COMPLEXITY_KEYWORDS = {
    "architecture", "refactor", "migration", "sécurité", "security",
    "cryptographie", "performance critique", "multi-tenant",
    "système distribué", "scalabilité", "audit complet",
    "review complète", "conception globale",
}


@dataclass
class EscalationContext:
    """Contexte de décision d'escalade."""
    task:           str
    role:           str           = "default"
    failure_count:  int           = 0
    complexity_score: float       = 0.0
    local_output:   str           = ""     # sortie du modèle local (pour évaluation qualité)
    reasons:        list[str]     = field(default_factory=list)


@dataclass
class EscalationDecision:
    """Résultat de la décision d'escalade."""
    should_escalate: bool
    provider:        str    = ""       # "openai" | "anthropic" | ""
    model:           str    = ""       # nom du modèle
    reason:          str    = ""
    complexity:      float  = 0.0
    local_used:      bool   = True     # True = modèle local utilisé en premier


class EscalationEngine:
    """
    Moteur de décision d'escalade vers le cloud.

    Par défaut : DÉSACTIVÉ (escalation_enabled=False dans settings ou absent).
    L'escalade ne s'active que si explicitement configurée.
    Le moteur peut toujours être utilisé pour calculer des scores de complexité
    même sans clé API.
    """

    def __init__(self, settings):
        self.s = settings
        self._enabled = self._check_enabled()

    # ── Activation ────────────────────────────────────────────

    @staticmethod
    def validate_cloud_keys(settings) -> dict[str, bool]:
        """
        Valide les clés API cloud en vérifiant :
          - présence non vide
          - absence de fragments placeholder (CHANGE_ME, sk-CHANGE, etc.)
          - longueur minimale de 20 caractères

        Retourne :
            {"openai": bool, "anthropic": bool, "any_valid": bool}
        """
        try:
            from core.llm_factory import _is_valid_key
        except ImportError:
            # Fallback inline si import circulaire
            def _is_valid_key(k):  # type: ignore[misc]
                if not k:
                    return False
                kl = k.lower()
                return len(k) >= 20 and "change_me" not in kl and "placeholder" not in kl

        ok_openai    = _is_valid_key(getattr(settings, "openai_api_key",    ""))
        ok_anthropic = _is_valid_key(getattr(settings, "anthropic_api_key", ""))
        any_valid    = ok_openai or ok_anthropic

        if not any_valid:
            log.debug(
                "CLOUD_ESCALATION_DISABLED_NO_KEY",
                openai=ok_openai, anthropic=ok_anthropic,
                reason="aucune clé API valide — mode 100% local",
            )
        return {"openai": ok_openai, "anthropic": ok_anthropic, "any_valid": any_valid}

    def _check_enabled(self) -> bool:
        """
        L'escalade est activée si :
        - settings.escalation_enabled est True
        - ET au moins une clé API cloud VALIDE est configurée
          (non vide, non placeholder, longueur ≥ 20)
        Sinon → toujours local.
        """
        enabled = getattr(self.s, "escalation_enabled", False)
        keys    = self.validate_cloud_keys(self.s)
        result  = enabled and keys["any_valid"]

        if result:
            log.info("escalation_engine_enabled",
                     openai=keys["openai"], anthropic=keys["anthropic"])
        else:
            if not enabled:
                reason = "flag_disabled"
            elif not keys["any_valid"]:
                reason = "no_valid_api_key"
            else:
                reason = "unknown"
            log.debug("escalation_engine_disabled", reason=reason)
        return result

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    # ── API principale ────────────────────────────────────────

    def should_escalate(self, context: EscalationContext) -> bool:
        """
        Détermine si l'escalade vers le cloud est justifiée.

        Critères (mode ET) :
        1. Escalade globalement activée (clé API + flag settings)
        2. Score de complexité ≥ seuil OU nb d'échecs ≥ seuil
        3. Pas de sortie locale suffisante

        Retourne toujours False si escalade désactivée (mode 100% local).
        """
        if not self._enabled:
            return False

        threshold  = getattr(self.s, "escalation_threshold",  _DEFAULT_COMPLEXITY_THRESHOLD)
        fail_limit = getattr(self.s, "escalation_fail_limit", _DEFAULT_FAILURE_THRESHOLD)

        score = context.complexity_score
        if score == 0.0:
            score = self._compute_complexity(context.task)

        # Critères d'escalade
        by_complexity = score >= threshold
        by_failures   = context.failure_count >= fail_limit
        (
            bool(context.local_output) and
            len(context.local_output.strip()) < _DEFAULT_OUTPUT_LENGTH_LIMIT
        )

        should = by_complexity or by_failures
        if should:
            log.info("escalation_triggered",
                     score=round(score, 2), failures=context.failure_count,
                     by_complexity=by_complexity, by_failures=by_failures)
        return should

    def get_escalation_model(self, role: str = "default") -> EscalationDecision:
        """
        Retourne le modèle cloud à utiliser pour un rôle donné.
        Si escalade désactivée → retourne une décision locale.
        Préférence : OpenAI > Anthropic (ordre configurable).
        """
        if not self._enabled:
            return EscalationDecision(
                should_escalate=False,
                reason="Escalade désactivée — utilisation locale obligatoire",
                local_used=True,
            )

        models = _CLOUD_MODELS.get(role, _CLOUD_MODELS["default"])

        # Préférence cloud configurable
        prefer   = getattr(self.s, "escalation_prefer", "openai")
        fallback = "anthropic" if prefer == "openai" else "openai"

        # Utiliser validate_cloud_keys (vérifie placeholders)
        keys = self.validate_cloud_keys(self.s)
        has_key = {
            "openai":    keys["openai"],
            "anthropic": keys["anthropic"],
        }

        # Choisir le provider disponible
        provider = ""
        model    = ""
        if has_key.get(prefer):
            provider = prefer
            model    = models[prefer]
        elif has_key.get(fallback):
            provider = fallback
            model    = models[fallback]

        if not provider:
            return EscalationDecision(
                should_escalate=False,
                reason="Clé API absente — fallback local",
                local_used=True,
            )

        return EscalationDecision(
            should_escalate=True,
            provider=provider,
            model=model,
            reason=f"Escalade {provider}/{model} pour rôle {role}",
            local_used=False,
        )

    def build_context(
        self,
        task: str,
        failure_count: int = 0,
        role: str = "default",
        local_output: str = "",
    ) -> EscalationContext:
        """Construit un contexte d'escalade avec score calculé automatiquement."""
        complexity = self._compute_complexity(task)
        return EscalationContext(
            task=task,
            role=role,
            failure_count=failure_count,
            complexity_score=complexity,
            local_output=local_output,
        )

    # ── Score de complexité ───────────────────────────────────

    def _compute_complexity(self, task: str) -> float:
        """
        Calcule un score de complexité 0.0–1.0 basé sur des heuristiques.
        Ne nécessite aucun LLM.

        Facteurs :
        - Longueur de la tâche
        - Présence de mots-clés de complexité
        - Nombre d'entités techniques mentionnées
        """
        if not task:
            return 0.0

        score = 0.0
        task_lower = task.lower()

        # Longueur : tâches > 200 chars = plus complexes
        length_score = min(len(task) / 600, 0.3)
        score += length_score

        # Mots-clés de haute complexité
        keyword_hits = sum(1 for kw in _COMPLEXITY_KEYWORDS if kw in task_lower)
        keyword_score = min(keyword_hits * 0.15, 0.45)
        score += keyword_score

        # Présence de code ou de structures techniques
        tech_markers = ["def ", "class ", "async ", "await ", "import ", "```", "json", "api"]
        tech_hits = sum(1 for m in tech_markers if m in task_lower)
        tech_score = min(tech_hits * 0.05, 0.25)
        score += tech_score

        return round(min(score, 1.0), 3)

    def get_status(self) -> dict:
        """Retourne l'état de l'engine pour diagnostic."""
        return {
            "enabled":          self._enabled,
            "openai_key":       bool(getattr(self.s, "openai_api_key",    "")),
            "anthropic_key":    bool(getattr(self.s, "anthropic_api_key", "")),
            "threshold":        getattr(self.s, "escalation_threshold",  _DEFAULT_COMPLEXITY_THRESHOLD),
            "fail_limit":       getattr(self.s, "escalation_fail_limit", _DEFAULT_FAILURE_THRESHOLD),
            "prefer":           getattr(self.s, "escalation_prefer",     "openai"),
            "cloud_models":     list(_CLOUD_MODELS.keys()),
        }
