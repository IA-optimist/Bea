"""
BEA MAX — AgentMemory
Mémoire per-agent : enregistre les sorties réussies et patterns utiles.

Objectif :
    Permettre à chaque agent d'apprendre de ses succès passés.
    Les patterns réussis sont injectables dans les prompts futurs
    pour réduire la dépendance aux LLM externes (Phase 6).

Stockage :
    workspace/agent_memory.json
    {
      "scout-research": [
        {"task": "...", "output": "...", "ts": 1234567890.0, "score": 1.0},
        ...
      ],
      ...
    }

Interface :
    am = AgentMemory(settings)
    am.record(agent_name, task, output, success=True, score=1.0)
    ctx = am.get_context(agent_name, max_items=3)   # injectable dans prompt
    patterns = am.get_patterns(agent_name)           # liste brute

Limites :
    - Max 50 entrées par agent (rotation automatique)
    - Texte tronqué à 500 chars pour limiter l'empreinte mémoire
    - Pas de vectorisation (lookup récent, pas sémantique)
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
import structlog

log = structlog.get_logger()

_MAX_PER_AGENT   = 50    # entrées max par agent
_OUTPUT_TRUNCATE = 500   # chars max conservés par sortie
_TASK_TRUNCATE   = 200   # chars max conservés par tâche
_FILE_NAME       = "agent_memory.json"


class AgentMemory:
    """
    Mémoire persistante per-agent.

    Usage :
        am = AgentMemory(settings)

        # Enregistrer une sortie réussie
        am.record("scout-research", task="Analyse IA", output="...", success=True)

        # Récupérer du contexte injectable dans un prompt
        ctx = am.get_context("scout-research", max_items=3)
    """

    def __init__(self, settings):
        self.s     = settings
        self._data: dict[str, list[dict]] = {}
        self._path = self._resolve_path()
        self._loaded = False

    # ── Persistance ───────────────────────────────────────────

    def _resolve_path(self) -> Path:
        base = Path(getattr(self.s, "workspace_dir", "/app/workspace"))
        base.mkdir(parents=True, exist_ok=True)
        return base / _FILE_NAME

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            if self._path.exists():
                self._data = json.loads(self._path.read_text("utf-8"))
                log.debug("agent_memory_loaded",
                           agents=len(self._data),
                           total=sum(len(v) for v in self._data.values()))
        except Exception as e:
            log.warning("agent_memory_load_error", err=str(e))
            self._data = {}

    def _save(self) -> None:
        try:
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            log.warning("agent_memory_save_error", err=str(e))

    # ── Écriture ──────────────────────────────────────────────

    def record(
        self,
        agent_name: str,
        task:       str,
        output:     str,
        success:    bool  = True,
        score:      float = 1.0,
    ) -> None:
        """
        Enregistre une sortie d'agent (succès uniquement par défaut).

        Paramètres :
            agent_name : nom de l'agent (ex: "scout-research")
            task       : tâche assignée à l'agent
            output     : contenu produit
            success    : True = mémoriser, False = ignorer (sauf score > 0.5)
            score      : qualité estimée (0.0 – 1.0)
        """
        # Ne mémoriser que les sorties de qualité
        if not success and score < 0.5:
            return
        if not output or len(output.strip()) < 30:
            return

        self._load()

        entry: dict[str, Any] = {
            "task":    task[:_TASK_TRUNCATE],
            "output":  output[:_OUTPUT_TRUNCATE],
            "ts":      time.time(),
            "score":   round(score, 2),
            "success": success,
        }

        bucket = self._data.setdefault(agent_name, [])
        bucket.append(entry)

        # Rotation : garder les _MAX_PER_AGENT plus récents
        if len(bucket) > _MAX_PER_AGENT:
            self._data[agent_name] = bucket[-_MAX_PER_AGENT:]

        self._save()
        log.debug("agent_memory_recorded",
                  agent=agent_name, score=score, chars=len(output))

    # ── Lecture ───────────────────────────────────────────────

    def get_patterns(self, agent_name: str) -> list[dict]:
        """Retourne toutes les entrées mémorisées pour un agent (brut)."""
        self._load()
        return list(self._data.get(agent_name, []))

    def get_context(self, agent_name: str, max_items: int = 3) -> str:
        """
        Retourne un bloc de texte injectable dans un prompt agent.
        Contient les max_items sorties les plus récentes et de meilleure qualité.

        Exemple de sortie :
            ## Exemples de bonnes réponses passées (scout-research)

            ### Tâche : Analyser les tendances IA
            Résultat précédent : Les tendances 2024 montrent...

            ### Tâche : Identifier les acteurs clés
            Résultat précédent : Les principaux acteurs sont...
        """
        self._load()
        bucket = self._data.get(agent_name, [])
        if not bucket:
            return ""

        # Trier par score décroissant + récence
        sorted_entries = sorted(
            bucket,
            key=lambda e: (e.get("score", 0), e.get("ts", 0)),
            reverse=True,
        )[:max_items]

        if not sorted_entries:
            return ""

        lines = [f"## Exemples de bonnes réponses passées ({agent_name})"]
        for e in sorted_entries:
            lines.append(f"\n### Tâche : {e.get('task', '?')[:150]}")
            lines.append(f"Résultat précédent : {e.get('output', '')[:300]}")

        return "\n".join(lines)

    def stats(self) -> dict[str, int]:
        """Retourne {agent_name: nb_entries} pour les logs."""
        self._load()
        return {k: len(v) for k, v in self._data.items()}

    def clear_agent(self, agent_name: str) -> None:
        """Supprime les entrées d'un agent (tests / reset)."""
        self._load()
        if agent_name in self._data:
            del self._data[agent_name]
            self._save()

    def clear_all(self) -> None:
        """Vide toute la mémoire per-agent (tests)."""
        self._data = {}
        self._save()
