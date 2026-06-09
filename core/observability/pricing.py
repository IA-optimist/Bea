"""pricing — estimation du coût USD d'un appel LLM à partir des tokens.

Table de tarification indicative (USD par **million** de tokens, entrée/sortie).
Les modèles **locaux/auto-hébergés** (Bea v3.1, Ollama, llama.cpp…) ou inconnus
renvoient **0.0** — on n'invente pas de coût. Mise à jour : ajouter une entrée dans
`_PRICES` (clé = sous-chaîne du nom de modèle, en minuscules).

`estimate_cost(model, prompt_tokens, completion_tokens) -> float` (USD).
"""
from __future__ import annotations

# (prix_entrée, prix_sortie) en USD / 1M tokens. Indicatif, à ajuster.
_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.0),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "o3-mini": (1.10, 4.40),
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-3-5-sonnet": (3.00, 15.0),
    "claude-3-opus": (15.0, 75.0),
    "claude-sonnet-4": (3.00, 15.0),
    "claude-haiku-4": (1.00, 5.00),
    "claude-opus-4": (15.0, 75.0),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.00),
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
    "mistral-large": (2.00, 6.00),
}


def _match(model: str) -> tuple[float, float] | None:
    m = (model or "").lower()
    # match exact d'abord, puis sous-chaîne la plus longue
    if m in _PRICES:
        return _PRICES[m]
    best: tuple[float, float] | None = None
    best_len = 0
    for key, price in _PRICES.items():
        if key in m and len(key) > best_len:
            best, best_len = price, len(key)
    return best


def estimate_cost(model: str, prompt_tokens: int = 0, completion_tokens: int = 0) -> float:
    """Coût USD estimé. 0.0 si modèle local/inconnu ou tokens nuls."""
    price = _match(model)
    if price is None:
        return 0.0
    try:
        pt = max(0, int(prompt_tokens))
        ct = max(0, int(completion_tokens))
    except (TypeError, ValueError):
        return 0.0
    cost = (pt / 1_000_000) * price[0] + (ct / 1_000_000) * price[1]
    return round(cost, 6)
