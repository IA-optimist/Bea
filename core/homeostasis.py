"""État homéostatique fonctionnel de Béa  variables de viabilité projetées
en une cible VAD, consommée par la couche affective (arête homéostasie-affect).
Statut : FONCTIONNEL. Aucun ressenti revendiqué. Dépendances : stdlib seule."""
from __future__ import annotations
from dataclasses import dataclass

Vec3 = tuple[float, float, float]


def _clip(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


@dataclass
class Homeostasis:
    resources: float = 1.0   # [0,1] ; 1 = plein
    load: float = 0.0   # [0,1] ; 1 = saturé
    baseline_vad: Vec3 = (0.0, 0.0, 0.0)  # cible à viabilité nominale
    gain: float = 0.6        # amplitude du déplacement de cible

    def set(self, *, resources: float | None = None, load: float | None = None) -> None:
        if resources is not None:
            self.resources = _clip(resources, 0.0, 1.0)
        if load is not None:
            self.load = _clip(load, 0.0, 1.0)

    def viability(self) -> float:
        """Scalaire [0,1] : haut = sain."""
        return _clip(self.resources - self.load, 0.0, 1.0)

    def target_vad(self) -> Vec3:
        """Projette la viabilité en cible VAD. Viabilité basse = valence
        négative, arousal = mobilisation, dominance = baisse. Neutre = baseline_vad."""
        v = self.viability()
        deficit = 1.0 - v  # 0 = sain, 1 = critique
        bv, ba, bd = self.baseline_vad
        return (
            _clip(bv - self.gain * deficit, -1.0, 1.0),
            _clip(ba + self.gain * deficit, -1.0, 1.0),
            _clip(bd - self.gain * deficit, -1.0, 1.0),
        )
