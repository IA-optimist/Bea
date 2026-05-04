"""Text utilities for mission outcomes.

Extrait depuis core/meta_orchestrator.py pour isoler les helpers de
normalisation de texte (extraction de résultats encapsulés dans des
`ExecutionOutcome(...)` wrappers, etc.).
"""
from __future__ import annotations


def strip_execution_outcome(text: str | None) -> str | None:
    """Retire le wrapper ``ExecutionOutcome(...)`` du texte de résultat.

    Renvoie le texte inchangé si le format n'est pas reconnu.
    """
    if not text:
        return text
    t = text.strip()
    if not t.startswith("ExecutionOutcome("):
        return text
    idx = t.find("result=")
    if idx == -1:
        return text
    rest = t[idx + 7:]
    extracted = ""
    if rest and rest[0] in ("'", '"'):
        q = rest[0]
        rest = rest[1:]
        i = 0
        while i < len(rest):
            if rest[i] == q and (i == 0 or rest[i - 1] != "\\"):
                extracted = rest[:i]
                break
            i += 1
        else:
            extracted = rest.rstrip(")")
    else:
        paren = rest.find(")")
        extracted = rest[:paren] if paren != -1 else rest
    extracted = extracted.replace("\\n", "\n").replace("\\t", "\t")
    return extracted.strip() or text


__all__ = ["strip_execution_outcome"]
