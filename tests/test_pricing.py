"""Tests pour core.observability.pricing — calcul pur."""
from __future__ import annotations

from core.observability.pricing import estimate_cost


def test_local_or_unknown_is_free():
    assert estimate_cost("bea-v3.1", 1000, 1000) == 0.0
    assert estimate_cost("llama3.1:8b", 5000, 5000) == 0.0
    assert estimate_cost("", 100, 100) == 0.0


def test_known_cloud_model_cost():
    # gpt-4o-mini : (0.15, 0.60) / 1M
    c = estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000)
    assert abs(c - 0.75) < 1e-6


def test_substring_match():
    # un nom complet de provider doit matcher la clé connue
    assert estimate_cost("openai/gpt-4o-2024-08-06", 1_000_000, 0) > 0
    assert estimate_cost("anthropic/claude-3-5-sonnet-latest", 0, 1_000_000) > 0


def test_zero_tokens():
    assert estimate_cost("gpt-4o", 0, 0) == 0.0


def test_bad_token_input():
    assert estimate_cost("gpt-4o", "x", None) == 0.0
