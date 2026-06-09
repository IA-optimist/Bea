"""
BEA MAX - TaskRouter
Analyse l intention de l utilisateur et produit :
  - le TaskMode (CHAT / RESEARCH / PLAN / CODE / AUTO / NIGHT / IMPROVE)
  - la liste ordonnee des agents a mobiliser

Regles de routing :
  - CHAT   : message court (< 30 chars) ou salutation simple
  - RESEARCH : verbe d analyse/exploration sans verbe d action
  - PLAN   : verbe de planification/architecture
  - CODE   : verbe de generation de code/script
  - IMPROVE: demande d auto-modification du systeme
  - NIGHT  : mission longue multi-cycles explicitement demandee
  - AUTO   : tout le reste (mission substantielle sans classification claire)

needs_actions = True uniquement pour CODE, AUTO, NIGHT (modes qui ecrivent des fichiers).
RESEARCH et PLAN ne declenchent JAMAIS d actions automatiques.
"""
from __future__ import annotations
import re
import structlog
from dataclasses import dataclass, field

try:
    from core.state import TaskMode as _ImportedTaskMode
    # Verify it's the real enum, not a MagicMock (mock attributes return MagicMock, not str)
    if not isinstance(_ImportedTaskMode.CHAT.value, str):
        raise AttributeError("mocked")
    TaskMode = _ImportedTaskMode
except Exception:
    # Fallback: minimal TaskMode implementation for test isolation
    class _Mode:
        __slots__ = ("value",)

        def __init__(self, v: str) -> None:
            self.value = v

        def __eq__(self, other: object) -> bool:
            return isinstance(other, _Mode) and self.value == other.value

        def __hash__(self) -> int:
            return hash(self.value)

        def __repr__(self) -> str:
            return f"TaskMode.{self.value.upper()}"

    class _TaskModeMeta:
        CHAT     = _Mode("chat")
        RESEARCH = _Mode("research")
        PLAN     = _Mode("plan")
        CODE     = _Mode("code")
        AUTO     = _Mode("auto")
        NIGHT    = _Mode("night")
        IMPROVE  = _Mode("improve")
        BUSINESS = _Mode("business")

        def __new__(cls, value: str):  # type: ignore[misc]
            # TaskMode("chat") → TaskMode.CHAT  (mimic enum constructor)
            for attr in ("CHAT", "RESEARCH", "PLAN", "CODE", "AUTO",
                         "NIGHT", "IMPROVE", "BUSINESS"):
                m = getattr(cls, attr)
                if m.value == value:
                    return m
            raise ValueError(f"'{value}' is not a valid TaskMode")

    TaskMode = _TaskModeMeta  # type: ignore[assignment]

log = structlog.get_logger()


# ── Patterns de detection, ordre strict : du plus specifique au plus general ──

_PATTERNS: list[tuple[TaskMode, re.Pattern]] = [

    # BUSINESS — Business Layer (venture, offre, saas, workflow, métier)
    # Doit rester avant RESEARCH/AUTO pour ne pas être capturé par l'heuristique
    # ATTENTION : ne pas capturer "analyse le marché" générique → exiger un terme business précis
    (TaskMode.BUSINESS, re.compile(
        r"(\bventure\b|opportunite\s+business|niche\s+(business|marche)|"
        r"offre\s+commerciale|design\s+d.offre|"
        r"blueprint\s+saas|mvp\s+saas|creer\s+un\s+saas|lancer\s+un\s+(nouveau\s+)?saas|"
        r"workflow\s+business|automatisation\s+business|"
        r"agent\s+(ia\s+)?metier|artisan\s+ia|"
        r"chauffagiste\s+ia|plombier\s+ia|tpe\s+ia|"
        r"trade.?ops|business.?layer|"
        r"genere?\s+des?\s+revenus?|generer\s+des?\s+revenus?|"
        r"premier\s+(client\s+payant|paiement\s+reel)|"
        r"acquisition\s+(clients?|leads?|utilisateurs?)|strategie\s+d.?acquisition|"
        r"tunnel\s+d.?acquisition|monetis[ae]r?|"
        r"(?:^|\s)/venture|(?:^|\s)/offre|(?:^|\s)/saas|"
        r"(?:^|\s)/metier|(?:^|\s)/business)",
        re.IGNORECASE
    )),

    # IMPROVE — auto-modification du systeme (doit rester avant CODE)
    (TaskMode.IMPROVE, re.compile(
        r"\b(ameliore(-toi)?|auto.?ameli|analyse\s+ton\s+code|"
        r"corrige\s+(tes\s+)?(bug|erreur)|ajoute\s+un\s+agent|"
        r"/improve|patch\s+toi|optimise\s+ton\s+(code|systeme))\b",
        re.IGNORECASE
    )),

    # NIGHT — travail long multi-cycles (doit rester avant AUTO)
    # Note : \b ne matche pas '/' (non word-char) — utiliser (?:^|\s) pour /night
    (TaskMode.NIGHT, re.compile(
        r"((?:^|\s)/night\b|travail\s+(de\s+)?nuit|multi.?cycle|"
        r"mission\s+longue|pendant\s+(la\s+)?nuit|autonome\s+pendant\s+plusieurs|"
        r"plusieurs\s+heures|toute\s+la\s+nuit)",
        re.IGNORECASE
    )),

    # CODE — execution bash/shell/commande (doit rester avant le bloc CODE général)
    (TaskMode.CODE, re.compile(
        r"\b(execut[ei]?r?\s+(la\s+)?(commande|cmd|bash|shell|script)|"
        r"lance[rz]?\s+(la\s+)?(commande|bash|shell)|"
        r"run\s+(bash|shell|command|cmd|this\s+command)|"
        r"(commande|bash|shell)\s+(suivante?|ci.?dessous)|"
        r"execut[ei]?r?\s+.*\becho\b|"
        r"execut[ei]?r?\s+.*\bpython\b|"
        r"execut[ei]?r?\s+.*\bnpm\b|"
        r"execut[ei]?r?\s+.*\bgit\b)",
        re.IGNORECASE
    )),

    # CODE — generation de code/script (verbes d ecriture + artefact technique)
    (TaskMode.CODE, re.compile(
        r"\b(ecris?\s+(un\s+)?(script|code|fonction|classe|module|programme)|"
        r"genere?(\s+le|\s+du|\s+un)?\s+code|"
        r"cree?\s+un\s+(script|fichier\s+\.?py|programme|module)|"
        r"implemente?(\s+la|\s+le|\s+un)?|"
        r"developpe?\s+(un|une|le|la|ce)|"
        r"code\s+(la|le|cet?te|cette)|"
        r"le\s+code\s+(de|pour|du))\b",
        re.IGNORECASE
    )),

    # PLAN — planification, architecture, strategie
    # ATTENTION : "comment faire" ne doit PAS capturer des questions de recherche simples
    # On exige un verbe d action fort (planifie, cree un plan, roadmap...) ou un nom explicite
    (TaskMode.PLAN, re.compile(
        r"\b(planifie?|cree?\s+un\s+plan(\s+pour)?|roadmap|"
        r"etapes\s+(pour|de)|"
        r"comment\s+(mettre\s+en\s+place|deployer|lancer|construire)|"
        r"strategie\s+(pour|de)|architecture\s+(de|pour|du)|"
        r"structure\s+(du\s+projet|de\s+l|pour))\b",
        re.IGNORECASE
    )),

    # RESEARCH — questions, analyses, comparaisons (pas d action concrete attendue)
    # "comment fonctionne" va ici, pas dans PLAN
    (TaskMode.RESEARCH, re.compile(
        r"\b(recherche|synthetise|compare|evalue|"
        r"qu.est.ce\s+que|comment\s+fonctionne|"
        r"quels?\s+sont(\s+les)?|liste(\s+les)?|resume|explique|"
        r"qu.est.ce\s+qu|c.est\s+quoi|pourquoi\s+est.ce|"
        r"dis.moi\s+(ce\s+que|comment|pourquoi)|"
        r"analyse\s+(le\s+marche|les\s+tendances|les\s+concurrents|les\s+options))\b",
        re.IGNORECASE
    )),

    # CHAT — salutation / acquittement / message tres court
    # Ancre debut + fin pour eviter de capturer des phrases longues
    (TaskMode.CHAT, re.compile(
        r"^(bonjour|salut|hello|coucou|hi|hey|ok|okay|"
        r"merci|thanks|oui|non|ouais|nope|"
        r"super|bien|parfait|nickel|cool|"
        r"continue|go|c.est\s+bon|vu|d.?acc)[^a-z]{0,5}$",
        re.IGNORECASE
    )),
]

# ── Plans d agents par mode ────────────────────────────────────
_AGENT_PLANS: dict[TaskMode, list[dict]] = {
    TaskMode.CHAT: [],

    TaskMode.RESEARCH: [
        {"agent": "vault-memory",   "task": "Rappel contexte pertinent",   "priority": 1},
        {"agent": "scout-research", "task": "Recherche et synthese",        "priority": 2, "timeout": 45},
        {"agent": "shadow-advisor", "task": "Angles alternatifs",           "priority": 2, "timeout": 35},
        {"agent": "lens-reviewer",  "task": "Validation qualite",           "priority": 3, "timeout": 30},
    ],

    TaskMode.PLAN: [
        {"agent": "vault-memory",   "task": "Rappel contexte pertinent",   "priority": 1},
        {"agent": "scout-research", "task": "Contexte et contraintes",      "priority": 2, "timeout": 45},
        {"agent": "map-planner",    "task": "Plan detaille",                "priority": 2, "timeout": 35},
        {"agent": "shadow-advisor", "task": "Risques et angles oublies",    "priority": 2, "timeout": 35},
        {"agent": "lens-reviewer",  "task": "Validation du plan",           "priority": 3, "timeout": 30},
    ],

    TaskMode.CODE: [
        {"agent": "vault-memory",   "task": "Contexte projet existant",    "priority": 1},
        {"agent": "scout-research", "task": "Patterns et bonnes pratiques", "priority": 2},
        {"agent": "forge-builder",  "task": "Generation du code",           "priority": 2},
        {"agent": "lens-reviewer",  "task": "Review securite et qualite",   "priority": 3},
        {"agent": "pulse-ops",      "task": "Preparation ecriture fichier", "priority": 3},
    ],

    TaskMode.AUTO: [
        {"agent": "vault-memory",   "task": "Rappel memoire",               "priority": 1},
        {"agent": "scout-research", "task": "Recherche",                    "priority": 2},
        {"agent": "shadow-advisor", "task": "Perspectives alternatives",    "priority": 2, "timeout": 45},
        {"agent": "map-planner",    "task": "Planification",                "priority": 2},
        {"agent": "forge-builder",  "task": "Construction / code",          "priority": 3},
        {"agent": "lens-reviewer",  "task": "Controle qualite",             "priority": 4},
        {"agent": "pulse-ops",      "task": "Preparation actions",          "priority": 4},
    ],

    TaskMode.NIGHT: [
        {"agent": "vault-memory",   "task": "Rappel contexte",              "priority": 1},
        {"agent": "atlas-director", "task": "Plan multi-cycles",            "priority": 1},
    ],

    TaskMode.IMPROVE: [
        {"agent": "vault-memory",   "task": "Historique des modifications", "priority": 1},
    ],

    TaskMode.BUSINESS: [
        {"agent": "venture-builder",    "task": "Analyse d'opportunités business",         "priority": 1, "timeout": 90},
        {"agent": "offer-designer",     "task": "Design d'offre commerciale",              "priority": 2, "timeout": 90},
        {"agent": "workflow-architect", "task": "Architecture de workflows",               "priority": 3, "timeout": 90},
        {"agent": "saas-builder",       "task": "Blueprint MVP SaaS",                      "priority": 4, "timeout": 90},
        {"agent": "trade-ops",          "task": "Agent IA métier spécialisé",              "priority": 2, "timeout": 90},
    ],
}

# Modes qui peuvent declencher des actions automatiques
_ACTION_MODES = frozenset({TaskMode.CODE, TaskMode.AUTO, TaskMode.NIGHT})
# Modes business : pas d'actions fichiers, mais routing spécial via BusinessLayer
_BUSINESS_MODES = frozenset({TaskMode.BUSINESS})


@dataclass
class RoutingDecision:
    """Result of routing a user message to a task mode and agent plan.

    Attributes:
        mode: Detected TaskMode (CHAT, RESEARCH, PLAN, CODE, AUTO, NIGHT, IMPROVE, BUSINESS).
        agents: Ordered list of agent descriptors [{agent, task, priority, ...}].
        confidence: Routing confidence 0.0-1.0 (1.0 = explicit command or exact pattern).
        reason: Human-readable explanation (e.g. "pattern:code", "heuristic:short").
        needs_actions: True if mode can trigger file-writing actions (CODE, AUTO, NIGHT).
        uncensored_mode: True if uncensored reasoning is enabled for this request.
    """
    mode:           TaskMode
    agents:         list[dict] = field(default_factory=list)
    confidence:     float      = 1.0
    reason:         str        = ""
    needs_actions:  bool       = False
    uncensored_mode: bool      = False


class TaskRouter:
    """
    Analyse le message et retourne une RoutingDecision.
    Instanciable sans settings (aucun LLM appele ici).
    """

    def route(self, user_input: str, explicit_mode: str | None = None,
              uncensored_mode: bool = False, session_id: str = "") -> RoutingDecision:
        """
        Determine le mode et le plan d agents.
        explicit_mode (commande /auto, /night...) prend toujours le dessus.
        """
        # ── 0. Uncensored mode — force local LLM, skip shadow_gate ──
        if uncensored_mode:
            log.info("Uncensored mode active for session %s", session_id or "?")

        # ── 1. Mode explicite ─────────────────────────────────
        if explicit_mode:
            try:
                mode = TaskMode(explicit_mode)
                # Guard: even with explicit mode=auto, short conversational inputs
                # (greetings, questions ≤ 30 chars) must go to CHAT — never the
                # full 7-agent pipeline. Prevents 5+ minute wait on "bonjour".
                if mode == TaskMode.AUTO and len(user_input.strip()) <= 30:
                    log.info("task_router_short_override",
                             original_mode=explicit_mode, len=len(user_input.strip()))
                    return self._make(TaskMode.CHAT, user_input,
                                      reason="heuristic:short_override_auto",
                                      confidence=0.9,
                                      uncensored_mode=uncensored_mode)
                # "auto" est le mode par défaut de OrchestratorSession — pas un override
                # explicite utilisateur. On laisse les patterns prendre le dessus.
                # Les vrais overrides (/code, /business, /night...) passent directement.
                if mode != TaskMode.AUTO:
                    return self._make(mode, user_input,
                                      reason=f"explicit:{explicit_mode}",
                                      uncensored_mode=uncensored_mode)
            except ValueError:
                log.warning("unknown_explicit_mode", mode=explicit_mode)

        text = user_input.strip()

        # ── 2. Message vide ───────────────────────────────────
        if not text:
            return self._make(TaskMode.CHAT, user_input,
                              reason="empty_input", confidence=1.0,
                              uncensored_mode=uncensored_mode)

        # Normaliser les accents pour le matching des patterns.
        # "écris" → "ecris", "crées" → "crees", "développe" → "developpe".
        # On conserve le texte original pour tout le reste (agents, logs).
        import unicodedata
        normalized = unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode("ascii")

        # ── 3. Detection par patterns (sur texte normalisé) ───
        for mode, pattern in _PATTERNS:
            if pattern.search(normalized):
                log.debug("task_router_match",
                          mode=mode.value, pattern=pattern.pattern[:50])
                return self._make(mode, user_input, reason=f"pattern:{mode.value}",
                                  uncensored_mode=uncensored_mode)

        # ── 4. Heuristiques de longueur ───────────────────────

        # Message court sans pattern = CHAT
        if len(text) <= 30:
            return self._make(TaskMode.CHAT, user_input,
                              reason="heuristic:short", confidence=0.7,
                              uncensored_mode=uncensored_mode)

        # Message moyen sans verbe d action fort = RESEARCH par defaut
        # (evite de declencher AUTO + actions pour une simple question)
        if len(text) <= 70:
            return self._make(TaskMode.RESEARCH, user_input,
                              reason="heuristic:medium_no_action", confidence=0.5,
                              uncensored_mode=uncensored_mode)

        # Message long + verbe d action fort = AUTO (sur texte normalisé)
        # Verbes conjugués inclus : crées/crees, faites/fais, développez/developpe...
        if re.search(
            r"\b(crees?|cree|fais?|faites?|developpe[sz]?|construis?|"
            r"mets?\s+en\s+place|deploie[sz]?|lances?|genere[sz]?|"
            r"produis?|realise[sz]?|execute[sz]?)\b",
            normalized, re.IGNORECASE,
        ):
            return self._make(TaskMode.AUTO, user_input,
                              reason="heuristic:long_action", confidence=0.65,
                              uncensored_mode=uncensored_mode)

        # Message long sans verbe d action = RESEARCH
        return self._make(TaskMode.RESEARCH, user_input,
                          reason="heuristic:long_no_action", confidence=0.5,
                          uncensored_mode=uncensored_mode)

    def _make(self, mode: TaskMode, user_input: str,
              reason: str = "", confidence: float = 1.0,
              uncensored_mode: bool = False) -> RoutingDecision:

        # Deep copy pour eviter la mutation des dicts partages _AGENT_PLANS
        agents = [dict(a) for a in _AGENT_PLANS.get(mode, [])]

        # Injecter la mission dans les agents qui n ont pas de tache predefined
        for a in agents:
            if not a.get("task"):
                a["task"] = user_input[:200]

        d = RoutingDecision(
            mode=mode,
            agents=agents,
            confidence=confidence,
            reason=reason,
            needs_actions=(mode in _ACTION_MODES),
            uncensored_mode=uncensored_mode,
        )
        log.info("task_routed",
                 mode=mode.value,
                 agents=[a["agent"] for a in agents],
                 confidence=confidence,
                 reason=reason)
        return d

    def summarize(self, decision: RoutingDecision) -> str:
        """Format lisible pour notifications."""
        names = [a["agent"] for a in decision.agents]
        return (
            f"Mode : {decision.mode.value}\n"
            f"Agents : {', '.join(names) if names else '(aucun)'}\n"
            f"Actions : {'oui' if decision.needs_actions else 'non'}"
        )
