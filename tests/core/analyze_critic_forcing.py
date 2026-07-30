"""Analyse de la brique 4 : les reruns forcés (viabilité basse) améliorent-ils le
travail ? Lit le journal cognitif JSONL. Mesure de régulation fonctionnelle,
aucun ressenti. Observation passive : relancer périodiquement à mesure que les
données s'accumulent.
Usage : python -m tests.core.analyze_critic_forcing [--journal-dir data/cognitive_events] [--since TIMESTAMP]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import statistics
from pathlib import Path


def load_reruns(journal_dir: str, since: float | None):
    forced, natural = [], []
    paths = sorted(glob.glob(os.path.join(journal_dir, "journal-*.jsonl")))
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                        p = ev.get("payload") or {}
                        if p.get("kind") != "critic_rerun":
                            continue
                        if since is not None and ev.get("timestamp", 0) < since:
                            continue
                        delta = p.get("delta")
                        if delta is None:
                            continue
                        (forced if p.get("forced") else natural).append(float(delta))
                    except (json.JSONDecodeError, ValueError, TypeError):
                        continue
        except OSError:
            continue
    return forced, natural


def summarize(name, deltas):
    if not deltas:
        print(f"  {name}: aucun")
        return
    pos = sum(1 for d in deltas if d > 0)
    print(
        f"  {name}: n={len(deltas)}  delta_moyen={statistics.mean(deltas):+.3f}"
        f"  améliorés={pos}/{len(deltas)} ({100 * pos / len(deltas):.0f}%)"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--journal-dir", default="data/cognitive_events")
    ap.add_argument("--since", type=float, default=None)
    args = ap.parse_args()

    forced, natural = load_reruns(args.journal_dir, args.since)
    print("# Analyse brique 4  reruns forcés vs naturels")
    print("Mesure de régulation fonctionnelle, aucun ressenti.")
    summarize("forcés  (viabilité basse)", forced)
    summarize("naturels (critic)        ", natural)

    print("\n# Verdict dette 1")
    if len(forced) < 5:
        print(f"  INSUFFISANT  {len(forced)} reruns forcés (<5). Normal en début")
        print("  d'observation passive : relancer après usage réel sous charge.")
        return
    mean_f = statistics.mean(forced)
    pos_ratio = sum(1 for d in forced if d > 0) / len(forced)
    if mean_f > 0 and pos_ratio > 0.5:
        print(f"  VALIDÉ  delta_moyen(forcés)={mean_f:+.3f}>0, {100 * pos_ratio:.0f}% améliorés.")
        print("  Le couplage viabilitéprudence améliore le travail marginal sous charge.")
    elif mean_f <= 0:
        print(f"  CONTRE-PRODUCTIF  delta_moyen(forcés)={mean_f:+.3f}<=0.")
        print("  Les reruns forcés brûlent du budget sans gain. Resserrer la bande")
        print("  marginale (_MARGINAL_OVERALL_BAND) ou revoir le seuil de viabilité.")
    else:
        print(f"  MITIGÉ  delta_moyen={mean_f:+.3f}>0 mais seulement {100 * pos_ratio:.0f}%")
        print("  améliorés (>50%). Effet réel mais inconstant : à surveiller.")


if __name__ == "__main__":
    main()
