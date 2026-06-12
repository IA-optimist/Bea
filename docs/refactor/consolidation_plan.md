# Plan de consolidation — micro-paquets top-level (audit 2026-06-10)

Le repo compte 50+ dossiers racine. Plusieurs sont des micro-paquets
(1–4 fichiers) qui recouvrent des concepts existants. Chaque déplacement
ci-dessous est petit, mais touche des imports : **un déplacement = une PR**,
validée par la gate pre-push + les tests listés.

La règle de gel (« plus aucun nouveau top-level ») est dans
`CONTRIBUTING.md §5 — Structure rules`.

## Cibles, par ordre de risque croissant

| # | Paquet | Contenu | Importé par (vérifié) | Destination proposée |
|---|--------|---------|------------------------|----------------------|
| 1 | `observability/` | `langfuse_tracer.py` | `core/llm_factory.py` | `core/observability/` (existe déjà !) |
| 2 | `observer/` | `watcher.py` | `core/bea_executor.py`, `main.py` | `core/observability/watcher.py` |
| 3 | `workflow/` | `workflow_engine.py` | `agents/workflow_agent.py`, `tests/test_workflow.py` | `core/workflow/` (à côté de `core/workflow_runtime.py`) |
| 4 | `bea_mcp/` | serveur + 2 adaptateurs | `api/startup_checks.py`, 2 tests | `mcp/bea/` (sous le paquet `mcp/` existant) |
| 5 | `learning/` | engine + loop + filtres | 5 modules core/api + tests | `core/learning/` |
| 6 | `monitoring/` | mixte : code py + docs + compose monitoring | 4 modules + tests | code → `core/observability/`, docs → `docs/monitoring/`, `docker-compose-monitoring.yml` → `deploy/` |

Cas particulier — le doublon `core/observability/` vs `observability/`
racine est exactement le genre de confusion que `ARCHITECTURE.md` a été créé
pour éliminer (cf. `business/` vs `core/business/`) : c'est la cible n°1.

## Procédure par PR

1. `git mv` du paquet vers sa destination.
2. Mise à jour des imports (liste exacte ci-dessus, re-vérifier avec
   `grep -rn "from <paquet>\|import <paquet>" --include="*.py" .`).
3. Shim de compatibilité **temporaire** dans l'ancien emplacement si un
   code dynamique (plugins, missions générées) importe par chaîne :
   `<paquet>/__init__.py` → `from core.<dest> import *  # deprecated, sunset T+30j`.
4. Gate : `ruff check .` + `scripts/validate_local.ps1` +
   `pytest tests/ -q -m "not integration"`.

## Non-cibles (gardés tels quels, justifiés)

- `business/` vs `core/business/` : documenté et assumé (ARCHITECTURE.md).
- `kernel/` : règle d'isolation load-bearing, ne pas toucher.
- `memory/` vs `core/memory/` : 23 fichiers, couplage RAG — à traiter
  seulement après les 6 cibles ci-dessus, avec une analyse dédiée.
