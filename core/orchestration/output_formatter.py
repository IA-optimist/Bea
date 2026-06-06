"""Output formatting helpers for mission results.

Nettoie les préambules conversationnels et les filler LLM, extrait le JSON
des réponses markdown, et préserve les sorties structurées.

Utilisé par core/meta_orchestrator.py:1811 (phase de mission finalization)
et par test_practical_usefulness.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

# Préambules LLM typiques à supprimer (match en début de texte).
_PREAMBLE_PATTERNS = [
    r"^\s*(sure|certainly|of course|absolutely|yes)[!.,]?\s*(here'?s|here is|let me)?[^\n]*[\n]+",
    r"^\s*here'?s\s+(?:the|a|an|your)?[^\n]*[\n]+",
    r"^\s*i'?(ll|d be happy to|m going to)[^\n]*[\n]+",
    r"^\s*let me[^\n]*[\n]+",
    r"^\s*(okay|ok|alright)[!.,]?\s*(?:here'?s|here is|let me)?[^\n]*[\n]+",
]

# Trailers conversationnels à supprimer (en fin de texte).
_TRAILER_PATTERNS = [
    r"\n+\s*let me know if[^.]*[.!?]?\s*$",
    r"\n+\s*(?:feel free|happy) to[^.]*[.!?]?\s*$",
    r"\n+\s*(?:hope|i hope) (?:this|that)[^.]*[.!?]?\s*$",
    r"\n+\s*(?:is there anything|anything else)[^.]*\?\s*$",
    r"\n+\s*(?:do you have|if you have)[^.]*\?\s*$",
]


def _is_already_structured(text: str) -> bool:
    """True si le texte semble déjà formaté (markdown, liste, JSON, ...)."""
    t = text.lstrip()
    if t.startswith(("#", "- ", "* ", "1.", "```", "|", "{", "[")):
        return True
    if text.count("\n#") >= 1 or text.count("\n- ") >= 2:
        return True
    return False


def format_output(text: str, task_type: Optional[str] = None, goal: Optional[str] = None) -> str:
    """Clean conversational LLM output while preserving structured content.

    Args:
        text: raw LLM output.
        task_type: optional hint (analysis, query, deployment, ...). Hook pour
            future per-type formatting.
        goal: optional original goal (hook pour future).

    Returns:
        Cleaned text. Preserves whitespace si vide, ou si déjà structuré.
    """
    if not text:
        return text
    # Preserve pour whitespace-only.
    if not text.strip():
        return text
    # Already-structured : passthrough (tests expect exact equality).
    if _is_already_structured(text):
        return text

    out = text
    for patt in _PREAMBLE_PATTERNS:
        out = re.sub(patt, "", out, count=1, flags=re.IGNORECASE)
    for patt in _TRAILER_PATTERNS:
        out = re.sub(patt, "", out, count=1, flags=re.IGNORECASE)
    return out.strip() if out != text else text


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


def try_extract_json(text: str) -> Optional[Any]:
    """Extrait un objet/tableau JSON depuis du texte, renvoie None sur échec.

    Gère :
      - ```` ```json\n{...}\n``` ```` fences markdown
      - Direct JSON
      - JSON embarqué dans du texte plus grand (greedy first match)
    """
    if not text:
        return None

    # 1. Markdown-fenced JSON.
    m = _JSON_FENCE_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            import logging as _lg; _lg.getLogger(__name__).debug("swallowed_exception", exc_info=True)

    # 2. Direct parse.
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        import logging as _lg; _lg.getLogger(__name__).debug("swallowed_exception", exc_info=True)

    # 3. First balanced {...} or [...].
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = text.find(open_ch)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == open_ch:
                depth += 1
            elif text[i] == close_ch:
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break
    return None


__all__ = ["format_output", "try_extract_json"]
