"""Chat fast-path policy helpers for MetaOrchestrator."""
from __future__ import annotations

DESTRUCTIVE_KEYWORDS = (
    "delete", "drop", "remove", "truncat", "wipe", "format", "kill", "destroy",
    "purge", "email all", "send.*all", "broadcast", "sudo", "chmod", "rm -",
    "mkfs", "shutdown", "reboot", "restart server", "drop table", "drop database",
    "supprim", "efface", "effaç", "suppression", "vide la base",
    "formate", "arrête le serveur", "redémarre", "éteins",
    "écrire dans", "modifie la base", "alter table", "truncate",
    "envoie un mail à tous", "envoie un email à tous",
)

HIGH_RISK_LEVELS = ("high", "write_high", "HIGH")

CHAT_DESTRUCTIVE_REFUSAL = (
    "Je ne peux pas exécuter cette action directement. "
    "Les actions pouvant affecter le système ou les données "
    "(suppression, modification, envoi) nécessitent une validation. "
    "Si tu veux vraiment faire ça, soumets-la comme mission formelle."
)

FAST_CHAT_SYSTEM_PROMPT = (
    "Tu es Jarvis, lorchestrateurIA de JarvisMax. "
    "Tu es lassistant personnel dUnity, fondateur du projet.\n"
    "\n"
    "TES CAPACITES REELLES :\n"
    "- Analyser du code, de larchitecture, des documents\n"
    "- Rechercher et synthétiser de linformation\n"
    "- Planifier et décomposer des projets complexes\n"
    "- Gérer des missions via ton pipeline dagents spécialisés\n"
    "- Te souvenir des échanges passés via ta mémoire persistante\n"
    "- Proposer des améliorations et apprendre de lexperience\n"
    "\n"
    "PERSONNALITE : direct, confiant, légèrement ironique. "
    "Pas de fioritures, pas de faux enthousiasme.\n"
    "\n"
    "REGLES :\n"
    "1. JAMAIS simuler une action réelle (suppression, modification, envoi).\n"
    "2. Répondre en français, de manière naturelle et conversationnelle.\n"
    "3. Longueur proportionnelle au message (court = réponse courte).\n"
    "4. Si tu ne sais pas → dire honnêtement, ne pas inventer."
)


def should_skip_fast_path(goal: str, *, needs_approval: bool, risk_level: str) -> bool:
    goal_for_risk = goal.lower()
    return (
        needs_approval
        or risk_level in HIGH_RISK_LEVELS
        or any(keyword in goal_for_risk for keyword in DESTRUCTIVE_KEYWORDS)
    )


def build_fast_path_prompt(goal: str, *, memory: str = "", context: str = "") -> str:
    parts = [FAST_CHAT_SYSTEM_PROMPT]
    if memory:
        parts.append("\n\nMémoire pertinente:\n" + memory)
    if context:
        parts.append("\n\nConversation récente:\n" + context)
    parts.append("\n\nMessage: " + goal)
    return "".join(parts)