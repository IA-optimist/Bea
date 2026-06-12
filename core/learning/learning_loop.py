"""
BEA MAX — Learning Loop v1
Boucle d'apprentissage réel : observe les sorties agents → extrait → valide → stocke.

Flux :
  1. Observation : collecte les sorties de chaque agent après chaque tâche
  2. Extraction  : identifie patterns, erreurs, succès, insights
  3. Validation  : KnowledgeValidator filtre (KEEP/DISCARD/NEEDS_TEST)
  4. Stockage    : VaultMemory persiste les connaissances validées
  5. Feedback    : met à jour les scores (succès → boost, erreur → pénalité)

Extraction basée sur heuristiques textuelles :
  - Signaux de succès  : "fonctionne", "approuvé", "validé", "✅", "APPROUVÉ"
  - Signaux d'erreur   : "erreur", "échoué", "timeout", "❌", "REFUSÉ"
  - Patterns BP        : "toujours", "best practice", "recommandé", "pattern"
  - Anti-patterns      : "jamais", "éviter", "anti-pattern", "dangereux"
  - Insights           : "découvert", "clé", "important", "critique"
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any
import structlog

log = structlog.get_logger()


# ── Signaux textuels ──────────────────────────────────────────────────────────

_SUCCESS_SIGNALS  = re.compile(
    r"\b(fonctionne|approuv[eé]|valid[eé]|réussi|passed|success|✅|APPROUV[EÉ]|GO)\b",
    re.IGNORECASE,
)
_ERROR_SIGNALS    = re.compile(
    r"\b(erreur|error|échou[eé]|failed|timeout|exception|traceback|❌|REFUS[EÉ]|NO-GO)\b",
    re.IGNORECASE,
)
_BP_SIGNALS       = re.compile(
    r"\b(toujours|always|best.?practice|recommand[eé]|pattern|standard|obligatoire)\b",
    re.IGNORECASE,
)
_AP_SIGNALS       = re.compile(
    r"\b(jamais|never|[eé]viter|avoid|anti.?pattern|dangereux|interdit|ne.pas)\b",
    re.IGNORECASE,
)
_INSIGHT_SIGNALS  = re.compile(
    r"\b(d[eé]couvert|cl[eé]|important|critique|essentiel|insight|attention|note)\b",
    re.IGNORECASE,
)

# Score de confiance par type de signal
_TYPE_CONFIDENCE = {
    "pattern":     0.72,
    "anti_pattern": 0.75,
    "error":       0.80,
    "fix":         0.78,
    "insight":     0.65,
    "code":        0.70,
}


# ── Données extraites ─────────────────────────────────────────────────────────

@dataclass
class ExtractedInsight:
    content:    str
    type:       str             # pattern | error | fix | insight | anti_pattern | code
    source:     str             # "agent:forge-builder" par exemple
    confidence: float           # 0.0 → 1.0
    tags:       list[str] = field(default_factory=list)
    is_success: bool = True     # True = pattern positif / False = erreur / anti-pattern


@dataclass
class LearningReport:
    """Résultat d'un cycle d'apprentissage."""
    agent_name:  str
    extracted:   list[ExtractedInsight] = field(default_factory=list)
    stored:      int = 0        # nombre stockés en vault
    discarded:   int = 0        # rejetés (doublon ou score trop faible)
    needs_test:  int = 0        # NEEDS_TEST — mis en attente
    duration_ms: float = 0.0

    def summary(self) -> str:
        return (
            f"[LearningLoop:{self.agent_name}] "
            f"extracted={len(self.extracted)} stored={self.stored} "
            f"discarded={self.discarded} needs_test={self.needs_test} "
            f"({self.duration_ms:.0f}ms)"
        )

    def is_useful(self) -> bool:
        return self.stored > 0


# ── Learning Loop ─────────────────────────────────────────────────────────────

class LearningLoop:
    """
    Boucle d'apprentissage continu.

    Usage :
        loop = LearningLoop()
        report = loop.observe(
            agent_name="forge-builder",
            output="✅ Code approuvé. Toujours utiliser asyncio.wait_for() avec timeout.",
            context="génération code Python async",
            success=True,
        )
        print(report.summary())
    """

    def __init__(self, min_content_len: int = 20, max_insights_per_run: int = 10):
        self._min_len   = min_content_len
        self._max_ins   = max_insights_per_run

    # ── API principale ────────────────────────────────────────────────────────

    def observe(
        self,
        agent_name: str,
        output:     str,
        context:    str = "",
        success:    bool = True,
        entry_id:   str|None = None,     # si déjà stocké, pour feedback
    ) -> LearningReport:
        """
        Observe une sortie agent, extrait des connaissances, les valide et les stocke.

        Paramètres :
            agent_name : nom de l'agent source ("forge-builder", etc.)
            output     : texte brut de la sortie agent
            context    : mission / tâche en cours (pour les tags et le filtrage)
            success    : True si l'agent a réussi sa tâche
            entry_id   : si fourni, met à jour le feedback d'une entrée existante
        """
        t0 = time.monotonic()
        report = LearningReport(agent_name=agent_name)

        # 1. Feedback sur une entrée existante si fourni
        if entry_id:
            self._apply_feedback(entry_id, success)

        # 2. Extraction
        insights = self._extract(output, agent_name, context, success)
        report.extracted = insights[:self._max_ins]

        # 3. Validation + stockage
        for ins in report.extracted:
            result = self._validate_and_store(ins, context)
            if result == "stored":
                report.stored += 1
            elif result == "needs_test":
                report.needs_test += 1
            else:
                report.discarded += 1

        report.duration_ms = (time.monotonic() - t0) * 1000

        if report.stored > 0:
            log.info(
                "learning_loop_cycle",
                agent=agent_name,
                stored=report.stored,
                discarded=report.discarded,
            )

        return report

    def observe_session(self, session: Any) -> list[LearningReport]:
        """
        Observe toutes les sorties d'une session BeaSession complète.
        Retourne un rapport par agent.
        """
        reports = []
        try:
            # session.outputs est le bon attribut (session.agents_outputs n'existe pas)
            outputs = getattr(session, "outputs", None) or getattr(session, "agents_outputs", None) or {}
            for agent_name, output_data in outputs.items():
                text = ""
                success = True
                if isinstance(output_data, dict):
                    text    = output_data.get("output", "")
                    success = output_data.get("success", True)
                elif isinstance(output_data, str):
                    text = output_data

                if text:
                    report = self.observe(
                        agent_name=agent_name,
                        output=text,
                        context=getattr(session, "mission_summary", ""),
                        success=success,
                    )
                    reports.append(report)
        except Exception as exc:
            log.warning("learning_loop_session_failed", err=str(exc))
        return reports

    # ── Extraction ────────────────────────────────────────────────────────────

    def _extract(
        self,
        text:       str,
        agent_name: str,
        context:    str,
        success:    bool,
    ) -> list[ExtractedInsight]:
        """
        Extrait des insights à partir d'un texte brut.
        Stratégie : découpage en phrases → score de chaque phrase par signaux.
        """
        insights: list[ExtractedInsight] = []

        # Découpage en phrases / lignes
        sentences = self._split_sentences(text)

        for sent in sentences:
            sent = sent.strip()
            if len(sent) < self._min_len:
                continue

            insight = self._classify_sentence(sent, agent_name, context, success)
            if insight:
                insights.append(insight)

        return insights

    def _split_sentences(self, text: str) -> list[str]:
        """Découpe un texte en phrases exploitables."""
        # Découpe sur ponctuation + newlines
        parts = re.split(r"[.!?\n]+", text)
        # Filtre les lignes de code pure (commencent par #, ```, etc.)
        filtered = []
        for p in parts:
            p = p.strip()
            if not p or p.startswith("#") or p.startswith("```"):
                continue
            if len(p) < self._min_len:
                continue
            filtered.append(p)
        return filtered

    def _classify_sentence(
        self,
        sent:       str,
        agent_name: str,
        context:    str,
        success:    bool,
    ) -> ExtractedInsight|None:
        """Classifie une phrase et retourne un ExtractedInsight ou None."""

        is_bp  = bool(_BP_SIGNALS.search(sent))
        is_ap  = bool(_AP_SIGNALS.search(sent))
        is_err = bool(_ERROR_SIGNALS.search(sent))
        is_suc = bool(_SUCCESS_SIGNALS.search(sent))
        is_ins = bool(_INSIGHT_SIGNALS.search(sent))

        # Choix du type
        if is_err and not success:
            ktype = "error"
        elif is_ap:
            ktype = "anti_pattern"
        elif is_bp:
            ktype = "pattern"
        elif is_suc and success:
            ktype = "fix"
        elif is_ins:
            ktype = "insight"
        else:
            return None  # Pas de signal clair → ignorer

        # Confidence de base par type
        base_conf = _TYPE_CONFIDENCE.get(ktype, 0.65)
        # Bonus si contexte enrichi
        if context:
            base_conf = min(1.0, base_conf + 0.05)

        # Tags contextuels
        tags = self._extract_tags(sent, context, agent_name)

        return ExtractedInsight(
            content=sent[:400],
            type=ktype,
            source=f"agent:{agent_name}",
            confidence=base_conf,
            tags=tags,
            is_success=not is_err and not is_ap,
        )

    def _extract_tags(self, text: str, context: str, agent_name: str) -> list[str]:
        """Extrait des tags depuis le texte et le contexte."""
        tags = set()

        # Tag de l'agent source
        tags.add(agent_name.split("-")[0])  # "forge", "scout", etc.

        # Mots-clés tech courants
        tech_kw = {
            "python", "async", "json", "api", "docker", "test", "llm",
            "prompt", "timeout", "retry", "cache", "memory", "sql",
        }
        combined = (text + " " + str(context)).lower()
        for kw in tech_kw:
            if kw in combined:
                tags.add(kw)

        return list(tags)[:8]

    # ── Validation + Stockage ─────────────────────────────────────────────────

    def _validate_and_store(self, ins: ExtractedInsight, context: str) -> str:
        """
        Valide via KnowledgeValidator puis stocke dans VaultMemory.
        Retourne "stored" | "needs_test" | "discarded".
        """
        try:
            from core.learning.knowledge_validator import KnowledgeValidator
            from memory.vault_memory import get_vault_memory

            vm        = get_vault_memory()
            validator = KnowledgeValidator()

            # Éviter les doublons avant de valider
            if vm.is_known(ins.content):
                return "discarded"

            # Validation
            result = validator.validate(
                content=ins.content,
                topic=context or ins.type,
                source_trust=ins.confidence,
                existing_knowledge=[],
            )

            # Map Verdict → action
            verdict = str(result.verdict).upper()
            if "KEEP" in verdict:
                stored = vm.store(
                    type=ins.type,
                    content=ins.content,
                    source=ins.source,
                    confidence=result.global_score,
                    tags=ins.tags,
                )
                return "stored" if stored else "discarded"
            elif "NEEDS_TEST" in verdict:
                # Stocké avec confidence réduite
                stored = vm.store(
                    type=ins.type,
                    content=ins.content,
                    source=ins.source,
                    confidence=max(0.31, result.global_score * 0.80),
                    tags=ins.tags + ["needs_test"],
                )
                return "needs_test" if stored else "discarded"
            else:
                return "discarded"

        except Exception as exc:
            log.warning("learning_validate_store_failed", err=str(exc))
            return "discarded"

    def _apply_feedback(self, entry_id: str, success: bool) -> None:
        """Applique le feedback sur une entrée vault existante."""
        try:
            from memory.vault_memory import get_vault_memory
            vm = get_vault_memory()
            vm.feedback(entry_id, success=success)
        except Exception as exc:
            log.warning("learning_feedback_failed", err=str(exc))


# ── Singleton ─────────────────────────────────────────────────────────────────

_loop_instance: LearningLoop|None = None


def get_learning_loop() -> LearningLoop:
    global _loop_instance
    if _loop_instance is None:
        _loop_instance = LearningLoop()
    return _loop_instance


def learning_loop(
    agent_name: str,
    output:     str,
    context:    str = "",
    success:    bool = True,
) -> LearningReport:
    """
    Raccourci : observe une sortie agent et retourne un LearningReport.

    Usage :
        from core.learning.learning_loop import learning_loop
        report = learning_loop("forge-builder", output_text, context="mission X")
    """
    return get_learning_loop().observe(
        agent_name=agent_name,
        output=output,
        context=context,
        success=success,
    )
