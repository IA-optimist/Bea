"""Skill de résumé de texte."""
from __future__ import annotations


async def execute(input: dict, context: dict | None = None) -> str:
    text = input.get("text", "")
    max_sentences = input.get("max_sentences", 5)

    if not text:
        return "(texte vide)"

    # Résumé heuristique si pas de LLM disponible
    sentences = [s.strip() for s in text.replace("\n", " ").split(".") if s.strip()]
    selected = sentences[:max_sentences]
    return ". ".join(selected) + ("." if selected else "")
