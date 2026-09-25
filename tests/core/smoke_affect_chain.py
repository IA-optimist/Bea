"""Smoke test d'observation : chaine viabilite/homeostasie/affect sur machine reelle.
Sonde fonctionnelle, aucune assertion, aucun ressenti revendique.
N'appelle PAS l'orchestrateur : exerce la chaine directement.
Usage : python -m tests.core.smoke_affect_chain [--load] [--viability-sweep]
  --load : applique une charge CPU synthetique a mi-parcours pour voir la
           viabilite chuter et l'humeur suivre (sinon, machine au repos = cible ~neutre).
  --viability-sweep : pilote directement la viabilite pour observer la pente
           affective sans estimateur ni charge CPU reelle.
"""
from __future__ import annotations

import sys
import time
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.affect_state import AffectState, AffectConfig
from core.homeostasis import Homeostasis
from core.viability_adapter import ViabilityAdapter
from core.resource_guard import get_resource_guard


def probe_estimator(signal):
    if signal == "neg":
        return (-1.0, 0.5, -0.5)
    if signal == "pos":
        return (1.0, 0.5, 0.5)
    return (0.0, 0.0, 0.0)


SEQ = [None, None, "neg", None, None, None, "pos", None, None, None]
SWEEP = [
    (1.0, 0.0),
    (1.0, 0.0),
    (0.5, 0.3),
    (0.2, 0.7),
    (0.2, 0.7),
    (0.2, 0.7),
    (1.0, 0.0),
    (1.0, 0.0),
    (1.0, 0.0),
    (1.0, 0.0),
]


def _burn_cpu(stop_evt, seconds):
    """Charge CPU synthetique (busy loop multi-thread) pour --load."""
    end = time.time() + seconds
    x = 0.0
    while time.time() < end and not stop_evt.is_set():
        x += 1.0  # busy
    return


def maybe_load(enable, turn):
    """A mi-parcours (turn==4), lance une charge CPU breve sur plusieurs threads."""
    if not enable or turn != 4:
        return None
    stop = threading.Event()
    threads = [
        threading.Thread(target=_burn_cpu, args=(stop, 3.0), daemon=True)
        for _ in range(max(2, (threading.active_count() or 2)))
    ]
    for t in threads:
        t.start()
    return stop


def fmt(v3):
    return "(" + ", ".join(f"{x:+.3f}" for x in v3) + ")"


def main():
    use_load = "--load" in sys.argv
    use_sweep = "--viability-sweep" in sys.argv
    guard = get_resource_guard()
    time.sleep(1.0)
    homeo = Homeostasis()
    affect = AffectState(
        estimator=None if use_sweep else probe_estimator,
        config=AffectConfig(momentum=0.6 if use_sweep else 0.8, rate=0.5, trajectory_len=0),
        baseline_provider=homeo.target_vad,
    )
    adapter = ViabilityAdapter(homeo, guard)

    print("# Smoke test chaine affect ; --load =", use_load, "; --viability-sweep =", use_sweep)
    print(f"{'turn':>4} {'via':>6} {'target_vad':>22} {'affect':>22}  guidance")
    if use_sweep:
        for turn, (res, load) in enumerate(SWEEP):
            homeo.set(resources=res, load=load)
            state = affect.update(None)
            via = homeo.viability()
            g = affect.render_guidance() or "(neutre, non injecte)"
            print(f"{turn:>4} {via:>6.3f} {fmt(homeo.target_vad()):>22} {fmt(state):>22}  {g}")
    else:
        for turn, sig in enumerate(SEQ):
            _stop = maybe_load(use_load, turn)
            adapter.update()
            state = affect.update(sig)
            via = homeo.viability()
            g = affect.render_guidance() or "(neutre, non injecte)"
            print(f"{turn:>4} {via:>6.3f} {fmt(homeo.target_vad()):>22} {fmt(state):>22}  {g}")
            time.sleep(0.8)

    print("\nObservations a verifier toi-meme :")
    print("- au repos : viability proche de 1, cible ~neutre, guidance souvent non injectee.")
    print("- avec --load au tour 4 : viability chute, cible tiree au negatif,")
    print("  et l'humeur (affect) descend AVEC INERTIE (pas d'un coup) puis recupere.")
    print("- les tours 'neg'/'pos' montrent la dynamique d'inertie independante de la charge.")


if __name__ == "__main__":
    main()
