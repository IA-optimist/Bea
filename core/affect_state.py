# core/affect_state.py
"""
Couche affective fonctionnelle de Béa  état VAD à dynamique du second ordre.
Maintient un état (Valence, Arousal, Dominance) HORS du LLM, avec inertie /
hystérésis / récupération, injecté comme guidage de ton.
Statut : FONCTIONNEL. Aucun ressenti revendiqué. Dépendances : stdlib seule.
"""
from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass, asdict
from typing import Callable, Optional, Sequence

Vec3 = tuple[float, float, float]  # VAD borné à [-1, 1] par axe.
AffectEstimator = Callable[[str], Vec3]  # signal -> cible VAD. DOIT être stateless.


def neutral_estimator(_signal: str) -> Vec3:
    """Défaut neutre. À remplacer par ta sonde (appel Qwen court, modèle FR).
    VADER est anglais  inadapté à Béa francophone."""
    return (0.0, 0.0, 0.0)


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


@dataclass
class AffectConfig:
    momentum: float = 0.6              # inertie (0.70.95).  = troughs + profonds.
    rate: float = 0.5                 # réactivité/pas.  = réponse + vive.
    baseline: Vec3 = (0.0, 0.0, 0.0)  # repos vers lequel l'affect relaxe.
    trajectory_len: int = 512         # buffer d'instrumentation (0 = off).


@dataclass
class _Step:
    t: float
    target: Vec3
    state: Vec3
    velocity: Vec3


class AffectState:
    """État affectif fonctionnel à dynamique du second ordre (momentum)."""

    def __init__(self, estimator: Optional[AffectEstimator] = None,
                 config: Optional[AffectConfig] = None,
                 baseline_provider: Optional[Callable[[], Vec3]] = None) -> None:
        self.cfg = config or AffectConfig()
        self.estimator = estimator or neutral_estimator
        self.baseline_provider = baseline_provider
        self._state = list(self.cfg.baseline)
        self._velocity = [0.0, 0.0, 0.0]
        self._traj: deque[_Step] = deque(maxlen=self.cfg.trajectory_len)

    @property
    def state(self) -> Vec3:
        return (self._state[0], self._state[1], self._state[2])

    @property
    def velocity(self) -> Vec3:
        return (self._velocity[0], self._velocity[1], self._velocity[2])

    def update(self, signal: Optional[str] = None) -> Vec3:
        """Avance la dynamique d'un pas. signal=None  relaxation vers baseline."""
        if signal is None:
            target = self.baseline_provider() if self.baseline_provider else self.cfg.baseline
        else:
            target = self.estimator(signal)
        m, r = self.cfg.momentum, self.cfg.rate
        for i in range(3):
            error = target[i] - self._state[i]
            self._velocity[i] = m * self._velocity[i] + (1.0 - m) * error
            self._state[i] = _clip(self._state[i] + r * self._velocity[i])
        if self.cfg.trajectory_len:
            self._traj.append(_Step(time.time(), tuple(target),
                                    self.state, self.velocity))
        return self.state

    def render_guidance(self) -> str:
        """Traduit l'état VAD courant en directive de ton, injectable au prompt."""
        v, a, d = self._state
        b = self.cfg.baseline
        if abs(v - b[0]) < 0.15 and abs(a - b[1]) < 0.15 and abs(d - b[2]) < 0.15:
            return ""
        val = "positif" if v > 0.3 else "négatif" if v < -0.3 else "neutre"
        eng = "haute" if a > 0.3 else "basse" if a < -0.3 else "modérée"
        reg = "affirmé" if d > 0.3 else "réservé" if d < -0.3 else "équilibré"
        return (f"[état interne] ton {val}, énergie {eng}, registre {reg}. "
                f"Reste cohérent avec cet état sans le nommer explicitement.")

    def trajectory(self) -> Sequence[_Step]:
        return tuple(self._traj)

    def save_trajectory(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump([asdict(s) for s in self._traj], f,
                      ensure_ascii=False, indent=2)

    def reset(self) -> None:
        self._state = list(self.cfg.baseline)
        self._velocity = [0.0, 0.0, 0.0]
        self._traj.clear()
