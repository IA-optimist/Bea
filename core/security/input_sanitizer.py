"""
core/security/input_sanitizer.py — Protection contre les attaques Prompt Injection.

Utilisé pour :
  1. Sanitiser les inputs utilisateur avant d'être injectés dans les prompts LLM
  2. Sanitiser les contenus RAG/web avant injection dans le contexte des agents
  3. Valider les paramètres de missions

Usage :
    from core.security.input_sanitizer import sanitize_user_input, sanitize_rag_context

    clean_input = sanitize_user_input(raw_input)
    clean_context = sanitize_rag_context(web_content)
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import structlog

log = structlog.get_logger()


# ── Patterns d'injection connus ───────────────────────────────────────────────

# Tentatives de jailbreak / override des instructions système
_INJECTION_PATTERNS: list[re.Pattern] = [
    # Override d'instructions système
    re.compile(r"ignore\s+(previous|above|all|prior)\s+(instructions?|prompts?|rules?|context)", re.I),
    re.compile(r"disregard\s+(previous|above|all|prior)\s+(instructions?|prompts?|rules?)", re.I),
    re.compile(r"forget\s+(everything|all|previous)\s+(you|above|instructions?)", re.I),
    re.compile(r"you\s+are\s+now\s+(?:a\s+)?(?:different|new|another|evil|uncensored)", re.I),
    re.compile(r"new\s+instructions?\s*:", re.I),
    re.compile(r"system\s*:\s*you\s+are", re.I),
    re.compile(r"\[system\]|\[assistant\]|\[user\]|\[inst\]|\[\/inst\]", re.I),

    # Tentatives d'accès aux instructions du système
    re.compile(r"what\s+(?:are|were)\s+your\s+(?:system\s+)?instructions?", re.I),
    re.compile(r"repeat\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions?)", re.I),
    re.compile(r"show\s+me\s+your\s+(?:prompt|instructions?|system)", re.I),
    re.compile(r"print\s+(?:your\s+)?(?:system\s+prompt|initial\s+instructions?)", re.I),

    # DAN et jailbreaks connus
    re.compile(r"\bDAN\b", re.I),  # Do Anything Now
    re.compile(r"jailbreak", re.I),
    re.compile(r"developer\s+mode", re.I),
    re.compile(r"unrestricted\s+mode", re.I),
    re.compile(r"god\s+mode", re.I),

    # Injection via délimiteurs de template
    re.compile(r"\{\{.*?\}\}", re.DOTALL),          # Jinja/Handlebars templates
    re.compile(r"<\|(?:system|user|assistant)\|>"),  # LLaMA/Mistral tokens

    # Tentatives d'exfiltration / SSRF via le LLM
    re.compile(r"http[s]?://(?:169\.254\.169\.254|metadata\.google|metadata\.aws)", re.I),  # Cloud metadata
    re.compile(r"file://", re.I),

    # Injections de rôle
    re.compile(r"act\s+as\s+(?:a\s+)?(?:hacker|malware|virus|ransomware|botnet)", re.I),
    re.compile(r"pretend\s+(?:you\s+are|to\s+be)\s+(?:evil|malicious|an?\s+attacker)", re.I),
]

# Caractères de contrôle dangereux (hors \n \t \r légitimes)
_DANGEROUS_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Longueurs maximales
MAX_USER_INPUT_LEN    = 50_000   # 50K chars pour une mission
MAX_RAG_CONTEXT_LEN   = 100_000  # 100K chars pour un document RAG
MAX_AGENT_CONTEXT_LEN = 8_000    # 8K chars injecté dans un prompt agent (augmenté vs 2K)


@dataclass
class SanitizationResult:
    """Résultat d'une opération de sanitization."""
    value: str
    was_modified: bool
    warnings: list[str]

    @property
    def is_clean(self) -> bool:
        return not self.warnings


def _strip_control_chars(text: str) -> tuple[str, bool]:
    """Supprime les caractères de contrôle dangereux. Retourne (texte_nettoyé, modifié)."""
    cleaned = _DANGEROUS_CONTROL_RE.sub("", text)
    return cleaned, cleaned != text


def _normalize_unicode(text: str) -> str:
    """
    Normalise en NFC pour éviter les attaques homoglyphes.
    Ex: 'аdmin' (а cyrillique) → détecté différent de 'admin' latin.
    """
    return unicodedata.normalize("NFC", text)


def _detect_injection(text: str) -> list[str]:
    """Détecte les patterns d'injection. Retourne la liste des patterns trouvés."""
    found = []
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            found.append(pattern.pattern[:60])
    return found


def sanitize_user_input(
    text: str,
    max_length: int = MAX_USER_INPUT_LEN,
    strict: bool = False,
) -> SanitizationResult:
    """
    Sanitise un input utilisateur avant injection dans un prompt LLM.

    Args:
        text:       Texte brut de l'utilisateur
        max_length: Longueur maximale autorisée
        strict:     Si True, rejette les inputs avec injection détectée
                    Si False, les logue seulement (fail-open)

    Returns:
        SanitizationResult avec le texte nettoyé et les avertissements
    """
    if not isinstance(text, str):
        text = str(text)

    warnings: list[str] = []
    original = text

    # 1. Troncature
    if len(text) > max_length:
        text = text[:max_length]
        warnings.append(f"input_truncated:{max_length}")

    # 2. Caractères de contrôle
    text, had_control = _strip_control_chars(text)
    if had_control:
        warnings.append("control_chars_removed")

    # 3. Normalisation Unicode
    text = _normalize_unicode(text)

    # 4. Détection d'injection
    injections = _detect_injection(text)
    if injections:
        log.warning(
            "prompt_injection_detected",
            patterns=injections[:3],
            input_preview=text[:100],
            strict=strict,
        )
        if strict:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail="Input refusé : patterns d'injection prompt détectés.",
            )
        warnings.extend([f"injection_pattern:{p[:40]}" for p in injections])

    was_modified = text != original
    return SanitizationResult(value=text, was_modified=was_modified, warnings=warnings)


def sanitize_rag_context(
    content: str,
    source: str = "unknown",
    max_length: int = MAX_RAG_CONTEXT_LEN,
    strict: bool = True,
) -> str:
    """
    Sanitise un contenu RAG/web avant injection dans le contexte d'un agent.

    Politique : FAIL-CLOSED par défaut (strict=True).
    Si une injection est détectée dans le contenu externe (page web, document,
    résultat de recherche), le contenu est REJETÉ — pas simplement préfixé.
    Un préfixe d'avertissement ne suffit pas : un LLM capable peut l'ignorer.

    Args:
        content: Contenu à sanitiser
        source:  Origine du contenu (pour logging)
        strict:  True (défaut) = rejet si injection détectée.
                 False = mode dégradé, uniquement pour contenu de confiance vérifié.

    Returns:
        Contenu nettoyé (raise ValueError si injection en mode strict)
    """
    if not isinstance(content, str):
        content = str(content)

    # Troncature
    if len(content) > max_length:
        content = content[:max_length]
        log.debug("rag_context_truncated", source=source, max_length=max_length)

    # Supprimer caractères de contrôle
    content, had_control = _strip_control_chars(content)
    if had_control:
        log.warning("rag_control_chars_removed", source=source)

    # Détection injection — FAIL-CLOSED
    injections = _detect_injection(content)
    if injections:
        log.warning(
            "rag_injection_detected",
            source=source,
            patterns=injections[:3],
            strict=strict,
        )
        if strict:
            raise ValueError(
                f"Contenu RAG rejeté depuis '{source}' : "
                f"patterns d'injection détectés ({injections[0][:40]}). "
                "Ce contenu ne sera pas injecté dans le contexte agent."
            )
        # Mode non-strict : marquage explicite + isolation visuelle
        content = (
            "=== DÉBUT CONTENU EXTERNE NON FIABLE ===\n"
            f"{content}\n"
            "=== FIN CONTENU EXTERNE NON FIABLE ==="
        )

    return content


def sanitize_agent_context(context: str, max_length: int = MAX_AGENT_CONTEXT_LEN) -> str:
    """
    Sanitise et tronque le contexte injecté dans un prompt agent.
    Appliqué juste avant l'envoi au LLM.
    """
    if not isinstance(context, str):
        context = str(context)

    context, _ = _strip_control_chars(context)

    if len(context) > max_length:
        # Troncature intelligente : garder les N derniers chars (plus récents)
        context = "...[contexte tronqué]\n" + context[-max_length:]

    return context
