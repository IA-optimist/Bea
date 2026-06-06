"""model_advisor — scan matériel + scoring de compatibilité modèle (Cookbook).

Inspiration Odysseus : dire quel modèle local tourne sur la machine. Le scan
hardware est **fail-open** (renvoie 0 si indétectable, jamais d'exception) ; la
logique de recommandation est pure et testable.
"""
from __future__ import annotations

# Paliers VRAM → modèles viables (min_vram_gb, tier, modèles, note)
_TIERS = [
    (0,  "cpu",   ["TinyLlama-1.1B", "Phi-2-2.7B"],
     "CPU only : petits modèles, lent pour le complexe"),
    (8,  "entry", ["Llama-3.1-8B (Q4)", "Mistral-7B", "Gemma-2-9B"],
     "GPU d'entrée : 7B quantisés, bon pour le perso"),
    (12, "mid",   ["Llama-3.1-8B (FP16)", "CodeLlama-13B (Q4)", "Qwen2-14B (Q4)"],
     "Milieu de gamme : 13B quantisés / 7B pleine précision"),
    (24, "high",  ["Llama-3.1-70B (Q4)", "Mixtral-8x7B", "DeepSeek-V2"],
     "Haut de gamme : 70B quantisés viables"),
]


def recommend(vram_gb: float) -> dict:
    """Renvoie le palier et les modèles conseillés pour une VRAM donnée."""
    try:
        v = float(vram_gb)
    except (TypeError, ValueError):
        v = 0.0
    chosen = _TIERS[0]
    for tier in _TIERS:
        if v >= tier[0]:
            chosen = tier
    min_vram, tier_name, models, note = chosen
    return {"tier": tier_name, "min_vram_gb": min_vram, "models": models, "note": note}


def model_fits(model_min_vram_gb: float, vram_gb: float) -> bool:
    """True si un modèle de besoin `model_min_vram_gb` tient dans `vram_gb`."""
    try:
        return float(vram_gb) >= float(model_min_vram_gb)
    except (TypeError, ValueError):
        return False


def scan_hardware() -> dict:
    """Détecte VRAM/RAM/GPU. Fail-open : renvoie des 0 si indétectable."""
    info = {"vram_gb": 0.0, "ram_gb": 0.0, "gpu": ""}
    # RAM
    try:
        import psutil
        info["ram_gb"] = round(psutil.virtual_memory().total / (1024 ** 3), 1)
    except Exception:  # nosec B110 — fail-open volontaire (détection best-effort)
        pass
    # VRAM via torch
    try:
        import torch
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            info["vram_gb"] = round(props.total_memory / (1024 ** 3), 1)
            info["gpu"] = props.name
            return info
    except Exception:  # nosec B110 — fail-open volontaire (détection best-effort)
        pass
    # VRAM via nvidia-smi (fallback)
    try:
        import subprocess  # nosec B404 — détection hardware locale, commande fixe
        out = subprocess.run(  # nosec B603 B607 — argv fixe nvidia-smi, aucune entrée externe
            ["nvidia-smi", "--query-gpu=memory.total,name",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            first = out.stdout.strip().splitlines()[0]
            mem, _, name = first.partition(",")
            info["vram_gb"] = round(float(mem.strip()) / 1024, 1)
            info["gpu"] = name.strip()
    except Exception:  # nosec B110 — fail-open volontaire (détection best-effort)
        pass
    return info


def advise() -> dict:
    """Scan + recommandation en un appel (pour un endpoint/CLI Cookbook)."""
    hw = scan_hardware()
    rec = recommend(hw["vram_gb"])
    return {**hw, **rec}
