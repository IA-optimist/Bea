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
## Real Dogfood Runtime Evidence Pack

`scripts/dogfood_runtime_evidence.py` extends the fixture pack into a controlled
runtime evidence pack with 10 missions and per-mission JSON reports.

### Commandes

```bash
python scripts/dogfood_runtime_evidence.py --mode fixture --json --output workspace/dogfood_runtime_fixture.json
python scripts/dogfood_runtime_evidence.py --mode real --json --output workspace/dogfood_runtime_real.json
```

### Mission set

1. identity
2. security-fastapi
3. forge-builder-sha256
4. forge-builder-mini-refactor
5. scout-alpha-risks
6. scout-routing-policy
7. shadow-json-alpha
8. shadow-json-release
9. planning-next-prs
10. provider-fallback-test

### What the pack records

- `mode`: `fixture` or `real`
- `provider_used`, `model_used`, `provider_status`, `fallback_used`
- `matched_advice` and `runtime_enforced=false`
- `success`, `passed`, `score`, `duration_s`, `error_category`
- `artifacts`, `files_changed`, `tests_run`, `report_path`

### Observed result

The current `real` run used the benchmark artifact at
`workspace/model_role_benchmark_multi_role.json`, so the evidence is real but
controlled, not a live provider call in this workspace. The run produced:

- `total=10`
- `passed=8`
- `failed=2`
- `skipped=0`
- `matched_advice_count=7`
- `runtime_enforced=false`

Provider breakdown:

- `openrouter`: 7 total, 7 passed, 0 failed
- `ollama`: 3 total, 1 passed, 2 failed

Role breakdown:

- `shadow-advisor`: 4 total, 3 passed, 1 failed
- `forge-builder`: 3 total, 2 passed, 1 failed
- `scout-research`: 3 total, 3 passed, 0 failed

### Ingestion

One safe report was ingested successfully:

```bash
python scripts/ingest_mission_report.py workspace/dogfood_runtime_real_reports/forge-builder-sha256.json --json
```

That created 4 memories and left `bea_eval` green on the next run.
