"""
JARVIS MAX — ModelSelector
Sélection adaptative du modèle LLM selon la tâche et les performances passées.

Règle fondamentale :
    LOCAL FIRST — Ollama est TOUJOURS la cible par défaut.
    Cloud uniquement si :
      1. EscalationEngine.validate_cloud_keys() renvoie True
      2. ET escalation_enabled=True dans les settings

Logique :
    tâches simples  → modèle rapide local (llama3.1:8b)
    tâches complexes → modèle principal local (llama3.1:8b)
    tâches code      → modèle code local (deepseek-coder-v2:16b)
    escalade cloud   → bloquée si clé absente / placeholder

Sources de décision (ordre de priorité) :
    1. Validation clé cloud (bloque cloud si invalide)
    2. Suggestion LearningEngine (succès historique par rôle)
    3. Score de complexité
    4. Table de routing statique (rôle → modèle Ollama par défaut)

Utilisé en lecture-only par l'orchestrateur — ne modifie pas llm_factory.py.

Interface :
    selector = ModelSelector(settings)
    rec = selector.select(role, task, learning_hint)
    # → ModelRecommendation(provider="ollama", model="llama3.1:8b", ...)
"""
from __future__ import annotations

import structlog
_silent_log = __import__("structlog").get_logger(__name__)

log = structlog.get_logger()

# ── Table statique rôle → modèle Ollama ───────────────────────

_ROLE_TO_MODEL: dict[str, str] = {
    "fast":      "ollama_model_fast",    # llama3.1:8b
    "main":      "ollama_model_main",    # llama3.1:8b
    "builder":   "ollama_model_main",
    "reviewer":  "ollama_model_main",
    "improve":   "ollama_model_main",
    "director":  "ollama_model_main",
    "planner":   "ollama_model_main",
    "research":  "ollama_model_main",
    "code":      "ollama_model_code",    # deepseek-coder-v2:16b
    "vision":    "ollama_model_vision",  # llava:7b
}

# Seuils de complexité
_THRESHOLD_FAST   = 0.35   # < 0.35 → fast model
_THRESHOLD_CODE   = 0.6    # ≥ 0.6 + code markers → code model


class ModelRecommendation:
    """Résultat de la sélection de modèle."""
    __slots__ = ("provider", "model", "role", "reason", "complexity")

    def __init__(self, provider: str, model: str, role: str,
                 reason: str, complexity: float = 0.0):
        self.provider   = provider
        self.model      = model
        self.role       = role
        self.reason     = reason
        self.complexity = complexity

    def to_dict(self) -> dict:
        return {
            "provider":   self.provider,
            "model":      self.model,
            "role":       self.role,
            "reason":     self.reason,
            "complexity": self.complexity,
        }


class ModelSelector:
    """
    Sélecteur de modèle adaptatif.
    Fonctionne 100% local — aucune API requise.
    """

    def __init__(self, settings):
        self.s = settings
        self._learning: object | None = None

    # ── Lazy LearningEngine ───────────────────────────────────

    def _get_learning(self):
        if self._learning is None:
            try:
                from learning.learning_engine import LearningEngine
                self._learning = LearningEngine(self.s)
            except Exception as e:
                log.debug("model_selector_no_learning", err=str(e)[:60])
        return self._learning

    # ── API publique ──────────────────────────────────────────

    def _cloud_allowed(self) -> bool:
        """
        Retourne True uniquement si une clé cloud VALIDE est configurée.
        Toujours False si aucune clé ou clé placeholder.
        """
        try:
            from core.escalation_engine import EscalationEngine
            keys = EscalationEngine.validate_cloud_keys(self.s)
            if not keys["any_valid"]:
                log.debug(
                    "CLOUD_ESCALATION_DISABLED_NO_KEY",
                    reason="ModelSelector: aucune clé cloud valide",
                )
            return keys["any_valid"]
        except Exception:
            return False

    def select(
        self,
        role:          str   = "main",
        task:          str   = "",
        learning_hint: bool  = True,
    ) -> ModelRecommendation:
        """
        Sélectionne le modèle optimal pour un rôle + tâche donnés.

        Règle de base : LOCAL FIRST.
        Cloud uniquement si validate_cloud_keys() est True.

        Paramètres :
            role          : rôle LLM (fast / builder / code / vision / ...)
            task          : texte de la tâche (pour calcul complexité)
            learning_hint : utiliser l'historique LearningEngine
        """
        # 1. Complexité de la tâche (sans LLM)
        complexity = self._compute_complexity(task) if task else 0.0

        # 2. Code task → code model
        if role == "code" or self._is_code_task(task):
            model = self._get_model_name("ollama_model_code")
            return ModelRecommendation(
                provider="ollama", model=model, role="code",
                reason="Tâche de code → modèle code dédié",
                complexity=complexity,
            )

        # 3. Vision task
        if role == "vision":
            model = self._get_model_name("ollama_model_vision")
            return ModelRecommendation(
                provider="ollama", model=model, role="vision",
                reason="Tâche vision",
                complexity=complexity,
            )

        # 4. Tâche simple → modèle rapide
        if complexity < _THRESHOLD_FAST and role in ("fast", "chat", "reviewer"):
            model = self._get_model_name("ollama_model_fast")
            return ModelRecommendation(
                provider="ollama", model=model, role=role,
                reason=f"Complexité faible ({complexity:.2f}) → fast model",
                complexity=complexity,
            )

        # 5. Suggestion learning (succès historique)
        if learning_hint:
            learned = self._learning_recommend(role, task)
            if learned:
                return learned

        # 6. Table statique par rôle
        attr = _ROLE_TO_MODEL.get(role, "ollama_model_main")
        model = self._get_model_name(attr)
        return ModelRecommendation(
            provider="ollama", model=model, role=role,
            reason=f"Routing statique rôle={role}",
            complexity=complexity,
        )

    def get_status(self) -> dict:
        """Retourne l'état du sélecteur pour diagnostic."""
        cloud_ok = self._cloud_allowed()
        return {
            "mode":           "local_only" if not cloud_ok else "cloud_available",
            "cloud_allowed":  cloud_ok,
            "models": {
                "fast":   self._get_model_name("ollama_model_fast"),
                "main":   self._get_model_name("ollama_model_main"),
                "code":   self._get_model_name("ollama_model_code"),
                "vision": self._get_model_name("ollama_model_vision"),
            },
            "thresholds": {
                "fast":  _THRESHOLD_FAST,
                "code":  _THRESHOLD_CODE,
            },
            "learning_enabled": self._get_learning() is not None,
        }

    # ── Helpers internes ──────────────────────────────────────

    def _get_model_name(self, attr: str) -> str:
        """Lit le nom de modèle depuis les settings."""
        return getattr(self.s, attr, "llama3.1:8b")

    def _compute_complexity(self, task: str) -> float:
        """Score 0.0–1.0 via EscalationEngine (si disponible) ou heuristique."""
        try:
            from core.escalation_engine import EscalationEngine
            return EscalationEngine(self.s)._compute_complexity(task)
        except Exception:
            _silent_log.debug("suppressed_exception", src='model_selector.py')
        # Heuristique fallback
        if not task:
            return 0.0
        length_score  = min(len(task) / 600, 0.3)
        keyword_score = 0.15 if any(
            kw in task.lower() for kw in
            ("architecture", "refactor", "sécurité", "migration")
        ) else 0.0
        return round(min(length_score + keyword_score, 1.0), 3)

    def _is_code_task(self, task: str) -> bool:
        """Détecte si la tâche est principalement du code."""
        if not task:
            return False
        code_markers = ["def ", "class ", "async def", "```python", "import ", "pip install"]
        return sum(1 for m in code_markers if m in task) >= 2

    def _get_llm_perf(self):
        """Lazy LLMPerformanceMonitor."""
        if not hasattr(self, "_llm_perf"):
            try:
                from monitoring.metrics import LLMPerformanceMonitor
                self._llm_perf = LLMPerformanceMonitor(self.s)
            except Exception as e:
                log.debug("model_selector_no_llm_perf", err=str(e)[:60])
                self._llm_perf = None
        return self._llm_perf

    def select_with_drift_detection(
        self,
        role:     str   = "main",
        task:     str   = "",
    ) -> ModelRecommendation:
        """
        Variante de select() qui prend en compte le drift LLM détecté par
        LLMPerformanceMonitor. Si drift détecté → fast fallback ou modèle recommandé.
        """
        # Vérifier si un drift est détecté pour ce rôle
        perf = self._get_llm_perf()
        if perf:
            try:
                drift = perf.detect_drift(role)
                if drift.get("drift"):
                    # Essayer la recommandation du moniteur
                    recommended = perf.recommend_model(role)
                    fast_model  = self._get_model_name("ollama_model_fast")
                    log.info(
                        "model_selector_drift_fallback",
                        role=role,
                        reasons=drift.get("reasons", [])[:2],
                        recommended=recommended,
                    )
                    # Utiliser le modèle recommandé par le moniteur si différent du current
                    actual_model = recommended or fast_model
                    return ModelRecommendation(
                        provider="ollama",
                        model=actual_model,
                        role=role,
                        reason=f"drift_detected: {drift.get('reasons', ['?'])[0][:60]}",
                    )
            except Exception as e:
                log.debug("model_selector_drift_check_failed", err=str(e)[:60])

        # Pas de drift → sélection normale
        return self.select(role=role, task=task)

    def _learning_recommend(self, role: str, task: str) -> ModelRecommendation | None:
        """
        Interroge le LearningEngine pour recommander le modèle le plus efficace.
        Combine avec LLMPerformanceMonitor pour une décision plus robuste.
        Retourne None si pas assez de données.
        """
        # 1. Vérifier LLMPerformanceMonitor d'abord (plus direct)
        perf = self._get_llm_perf()
        if perf:
            try:
                stats = perf.get_stats(role, window=10)
                avg_lat_ms = stats.get("avg_latency_ms", 0)
                # Si latence moyenne > 90s → fallback immédiat
                if avg_lat_ms > 90_000 and role not in ("code", "vision"):
                    recommended = perf.recommend_model(role)
                    model = recommended or self._get_model_name("ollama_model_fast")
                    return ModelRecommendation(
                        provider="ollama", model=model, role=role,
                        reason=f"LLMPerf: avg_latency={avg_lat_ms:.0f}ms > 90s",
                    )
            except Exception:
                _silent_log.debug("suppressed_exception", src='model_selector.py')

        # 2. Fallback sur LearningEngine
        engine = self._get_learning()
        if not engine:
            return None
        try:
            rates = engine.compute_success_rates()
            if rates.get("total_runs", 0) < 3:
                return None

            # Si latence builder > 120s → suggérer fast model comme fallback
            lat = rates.get("llm_avg_latency_s", {}).get(role, 0)
            if lat > 120 and role not in ("code", "vision"):
                model = self._get_model_name("ollama_model_fast")
                return ModelRecommendation(
                    provider="ollama", model=model, role=role,
                    reason=f"Latence historique {role} elevee ({lat}s) -> fast fallback",
                )
        except Exception as e:
            log.debug("model_selector_learning_error", err=str(e)[:60])
        return None
