"""Tests pour core.cookbook.model_advisor — logique pure + scan fail-open."""
from __future__ import annotations

from core.cookbook.model_advisor import advise, model_fits, recommend, scan_hardware


def test_recommend_tiers():
    assert recommend(0)["tier"] == "cpu"
    assert recommend(8)["tier"] == "entry"
    assert recommend(10)["tier"] == "entry"   # entre 8 et 12
    assert recommend(12)["tier"] == "mid"
    assert recommend(16)["tier"] == "mid"
    assert recommend(24)["tier"] == "high"
    assert recommend(48)["tier"] == "high"


def test_recommend_returns_models():
    r = recommend(8)
    assert isinstance(r["models"], list) and r["models"]
    assert r["min_vram_gb"] == 8


def test_recommend_bad_input():
    assert recommend("nan")["tier"] == "cpu"
    assert recommend(None)["tier"] == "cpu"


def test_model_fits():
    assert model_fits(8, 12) is True
    assert model_fits(24, 8) is False
    assert model_fits("x", 10) is False


def test_scan_hardware_failopen():
    hw = scan_hardware()
    assert set(["vram_gb", "ram_gb", "gpu"]).issubset(hw)
    assert hw["vram_gb"] >= 0  # jamais d'exception, valeurs >= 0


def test_advise_combines():
    a = advise()
    assert "tier" in a and "models" in a and "vram_gb" in a
