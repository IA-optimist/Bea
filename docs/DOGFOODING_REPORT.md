# Béa Dogfooding Report

This document tracks controlled dogfooding runs used to accumulate evidence
before any routing policy change.

## Routing Advice Evidence Pack

### Objectif

Accumuler des preuves avant toute modification du router automatique.
Le router n'est pas modifié par ces résultats.

### 5 Missions (fixture mode)

| ID | Rôle | Provider conseillé | Provider utilisé | Matched | Passed | Score |
|----|------|--------------------|-----------------|---------|--------|-------|
| A  | forge-builder  | openrouter | openrouter | ✅ | ✅ | 1.0  |
| B  | forge-builder  | openrouter | openrouter | ✅ | ✅ | 1.0  |
| C  | scout-research | openrouter | openrouter | ✅ | ✅ | 1.0  |
| D  | shadow-advisor | openrouter | openrouter | ✅ | ✅ | 1.0  |
| E  | shadow-advisor | openrouter | openrouter | ✅ | ❌ | 0.67 |

**Summary**: 4/5 passed, 1/5 failed (partial schema on planning mission), 0 skipped,
5/5 matched_advice, advice_match_rate=100%.

Mission E failed because the planning output had `schema_valid=False` and
`no_markdown=False` — the model wrapped its response in markdown fences.

### Comment lire matched_advice

`matched_advice=true` signifie que le provider utilisé correspond au provider
recommandé par l'advisory. Cela ne prouve pas que le conseil était correct —
seulement qu'il a été suivi pendant ce run.

Un taux élevé de `matched_advice` avec un taux élevé de `passed` suggère que
l'advisory est utile. Mais **1 run n'est pas une preuve suffisante**.

### Lancer le script

```bash
python scripts/dogfood_routing_advice.py --json
python scripts/dogfood_routing_advice.py --json --output workspace/dogfood_routing_advice_report.json
```

### Limites

- **Mode fixture uniquement** — les missions utilisent des résultats pré-définis,
  pas des vrais appels LLM.
- 1 seul run par mission dans ce pack.
- Router automatique non modifié.
- `runtime_enforced=false` invariant.
- Pour passer en mode réel, utiliser `benchmark_model_roles.py --real` d'abord,
  puis alimenter `model_routing_advice.py` avec les vrais résultats.

### Prochaine étape

Accumuler plusieurs runs réels indépendants avant toute décision de routing.
La confidence passera de `"low"` à un niveau plus élevé seulement avec des
données reproductibles sur plusieurs sessions.
