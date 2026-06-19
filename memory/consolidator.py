"""consolidator — mémoire qui se réorganise elle-même (inspiration Letta/MemGPT).

Quand la mémoire dépasse un seuil, les souvenirs les plus anciens sont **repliés**
en une synthèse compacte (via un résumeur injectable — LLM en prod, fonction simple
en test), gardant la mémoire bornée sans tout perdre. Fonction pure et testable ;
l'orchestrateur/`night_worker` l'appelle périodiquement (étape opt-in).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast


def consolidate(
    items: list[dict[str, object]],
    max_items: int,
    summarizer: Callable[[list[str]], str],
) -> list[dict[str, object]]:
    """Replie les souvenirs en excès (les plus anciens) en une synthèse.

    `items` : liste de dicts {content, ts, kind, ...}. Renvoie une nouvelle liste
    bornée à `max_items`, le surplus ancien étant condensé en un mémo `kind="summary"`.
    """
    if max_items < 1:
        max_items = 1
    if not isinstance(items, list) or len(items) <= max_items:
        return list(items)

    ordered = sorted(items, key=lambda m: float(cast(Any, m.get("ts", 0))))
    # On replie assez de vieux items pour laisser la place au mémo de synthèse.
    n_fold = len(ordered) - max_items + 1
    to_fold = ordered[:n_fold]
    keep = ordered[n_fold:]

    summary_text = summarizer([str(m.get("content", "")) for m in to_fold])
    summary: dict[str, object] = {
        "content": summary_text,
        "kind": "summary",
        "ts": max((float(cast(Any, m.get("ts", 0))) for m in to_fold), default=0.0),
        "folded": len(to_fold),
    }
    return [summary] + keep
