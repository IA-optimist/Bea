# core/viability_adapter.py
"""Adaptateur de viabilité : lit ResourceGuard, lisse (EMA), pousse vers Homeostasis.
Seul point de contact entre le runtime bruité et la couche affect/homéostasie.
Homeostasis et AffectState restent purs. Statut : FONCTIONNEL, aucun ressenti.
Dépendances : stdlib seule."""
from __future__ import annotations
from typing import Optional
from core.homeostasis import Homeostasis

FULL_CHARGE_AGENTS = 2   # fallback local ; doit suivre ResourceGuard._profile.max_agents.
RAM_COMFORT = 0.85       # jusqu'à 85% RAM utilisée, la viabilité reste au plateau sain.
EMA_ALPHA = 0.3          # lissage court : absorbe le jitter CPU sans trop retarder.


def _clip01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


class ViabilityAdapter:
    def __init__(self, homeostasis: Homeostasis, resource_guard,
                 full_charge_agents: int = FULL_CHARGE_AGENTS,
                 alpha: float = EMA_ALPHA) -> None:
        self.h = homeostasis
        self.guard = resource_guard
        guard_profile = getattr(resource_guard, "_profile", None)
        if guard_profile is not None:
            full_charge_agents = int(getattr(guard_profile, "max_agents", full_charge_agents) or full_charge_agents)
        self.n = max(1, int(full_charge_agents))
        self.alpha = alpha
        self._res_ema: Optional[float] = None
        self._load_ema: Optional[float] = None

    def update(self) -> None:
        """Lit l'état resource courant, lisse, pousse vers Homeostasis.
        Lecture safe : get_status() renvoie le snapshot déjà rafraîchi par le
        monitor loop de fond. Sur statut UNKNOWN, on NE met PAS à jour (on garde
        le dernier EMA) pour ne pas injecter une fausse santé."""
        st = self.guard.get_status()
        status_name = getattr(getattr(st, "status", None), "name", "") or str(getattr(st, "status", ""))
        if "UNKNOWN" in status_name.upper():
            return
        ram_pct = float(getattr(st, "ram_pct", 0.0) or 0.0)
        cpu_pct = float(getattr(st, "cpu_pct", 0.0) or 0.0)
        agents  = int(getattr(st, "active_agents", 0) or 0)

        free = 1.0 - ram_pct / 100.0
        res_raw = _clip01(free / (1.0 - RAM_COMFORT))
        load_raw = _clip01(0.5 * (cpu_pct / 100.0) + 0.5 * min(agents / self.n, 1.0))

        self._res_ema  = res_raw  if self._res_ema  is None else \
            self.alpha * res_raw  + (1.0 - self.alpha) * self._res_ema
        self._load_ema = load_raw if self._load_ema is None else \
            self.alpha * load_raw + (1.0 - self.alpha) * self._load_ema

        self.h.set(resources=self._res_ema, load=self._load_ema)
