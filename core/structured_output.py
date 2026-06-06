"""structured_output — parsing robuste de sorties LLM en JSON validé.

Inspiration PydanticAI : transformer une réponse LLM (souvent entourée de prose
ou de blocs ```json) en données structurées fiables. Sans dépendance dure ; si un
modèle Pydantic est fourni, il est utilisé pour valider/coercer.

`parse_structured(text, required_keys=..., model=...)` renvoie le dict outil
standard : {ok, data, error}.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_json(text: str) -> Optional[Any]:
    """Extrait le premier objet/tableau JSON valide d'un texte LLM."""
    if not isinstance(text, str) or not text.strip():
        return None
    candidates: list[str] = []
    # 1) contenu d'un bloc de code ```json ... ```
    m = _FENCE_RE.search(text)
    if m:
        candidates.append(m.group(1).strip())
    # 2) texte brut entier
    candidates.append(text.strip())
    # 3) première accolade/équerre … dernière correspondante
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = text.find(opener), text.rfind(closer)
        if i != -1 and j != -1 and j > i:
            candidates.append(text[i:j + 1])
    for c in candidates:
        try:
            return json.loads(c)
        except (ValueError, TypeError):
            continue
    return None


def parse_structured(
    text: str,
    required_keys: Optional[list[str]] = None,
    model: Any = None,
) -> dict:
    """Parse + valide une sortie LLM. `model` = classe Pydantic optionnelle."""
    data = extract_json(text)
    if data is None:
        return {"ok": False, "data": None, "error": "no_json_found"}

    if required_keys:
        if not isinstance(data, dict):
            return {"ok": False, "data": None, "error": "expected_object"}
        missing = [k for k in required_keys if k not in data]
        if missing:
            return {"ok": False, "data": data, "error": f"missing_keys: {missing}"}

    if model is not None:
        try:
            validated = model(**data) if isinstance(data, dict) else model(data)
            # pydantic v2 .model_dump, v1 .dict, sinon l'objet tel quel
            dump = getattr(validated, "model_dump", None) or getattr(validated, "dict", None)
            return {"ok": True, "data": dump() if dump else validated, "error": None}
        except Exception as e:
            return {"ok": False, "data": data, "error": f"validation_failed: {str(e)[:200]}"}

    return {"ok": True, "data": data, "error": None}
