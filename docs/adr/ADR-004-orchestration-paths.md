# ADR-004 — Orchestration Paths : Autorité, Hiérarchie, Tests

**Status:** Accepted  
**Date:** 2026-06-23  
**Author:** Claude Opus audit session  
**Vérifié par:** import probe + code reading direct

---

## Contexte

Le dépôt contient plusieurs fichiers portant un nom "orchestrateur". Des audits passés ont classé certains à tort comme legacy ou cassés. Cette ADR répond aux 5 questions canoniques sur l'orchestration et établit des règles pour éviter la confusion future.

---

## Réponse aux 5 questions

### 1. MetaOrchestrator est-il le seul point d'entrée canonique ?

**Oui.**

`core/meta_orchestrator.py` (`MetaOrchestrator`) est le seul point d'entrée autorisé pour exécuter une mission. Il expose :
- `run_mission(goal, mission_id, …)` — pipeline complet 12 phases
- `run(user_input, …)` — alias de compatibilité
- `submit_and_run(goal, …)` — wrapping API

Les 55 routers dans `api/` appellent tous `get_meta_orchestrator()` via `api/main.py:lifespan`. Aucun code neuf ne doit instancier `BeaOrchestrator` ou `OrchestratorV2` directement.

### 2. OrchestratorV2 est-il actif, legacy, expérimental ou mort-code ?

**Actif — délégué interne pour missions avec `use_budget=True`.**

`core/orchestrator_v2.py` est importé par `MetaOrchestrator.bea_v2` (lazy-property, ligne 115+) quand une mission demande le mode budget/DAG. Il ajoute :
- `BudgetGuard` — limite tokens / temps / coût USD
- `TaskDAG` — exécution parallèle topologique
- `CheckpointStore` — reprise après crash (asyncpg + SQLite fallback)

**Historique important :** il avait été déplacé à tort dans `core/_legacy/` et son shim cassait son import. L'Audit S8 (2026-05-20, issue #15) l'a rapatrié à `core/orchestrator_v2.py`. Import confirmé OK (2026-06-23).

**Règle :** ne pas le renommer, ne pas le bouger dans `_legacy/` à nouveau.

### 3. BeaOrchestrator est-il encore runtime ou seulement compat ?

**Runtime actif, sous le nom `core.bea_executor.BeaOrchestrator`.**

C'est le délégué principal de MetaOrchestrator pour les missions standard (non-budget). Il est composé de 4 mixins :
- `LazyComponentsMixin` — sous-systèmes lazy
- `PipelineAutoMixin` — pipeline auto/code/business/plan/research
- `PipelineModesMixin` — chat/night/improve/workflow
- `ReportingMixin` — status et rapport final

**Points à connaître :**
- Le module s'appelle `core.bea_executor`, PAS `core.bea_orchestrator` (qui n'existe pas).
- `core/orchestrator.py` est un **shim de compat** qui re-exporte depuis `core.bea_executor` avec un `DeprecationWarning`. Ne pas supprimer avant que tous les callers soient migrés.
- `from core.bea_orchestrator import BeaOrchestrator` → **ImportError** (module inexistant).

### 4. Comment éviter 8 orchestrateurs concurrents ?

**Règle unique : MetaOrchestrator via `get_meta_orchestrator()`.**

Inventaire des fichiers "orchestrateur" (au 2026-06-23) :

| Fichier | Rôle | À utiliser directement ? |
|---------|------|--------------------------|
| `core/meta_orchestrator.py` | Point d'entrée canonique | **Oui** — seul autorisé côté API |
| `core/bea_executor.py` | Délégué interne (BeaOrchestrator) | Non — instancié par MetaOrchestrator uniquement |
| `core/orchestrator_v2.py` | Délégué budget/DAG | Non — lazy-loadé par MetaOrchestrator |
| `core/orchestrator.py` | Shim compat deprecated | Non — garder, ne pas importer en code neuf |
| `core/cognition/orchestrator.py` | Module cognition interne | Non — détail interne de BeaOrchestrator |
| `business/business_orchestrator.py` | Orchestrateur business SaaS | Non — scaffolding, pas wired |
| `business/business_engine.py` | Facade business | Non — scaffolding |
| `business/layer.py` | Abstraction business | Non — scaffolding |

**Règle de code :**
```python
# BON
from core.meta_orchestrator import get_meta_orchestrator
orchestrator = get_meta_orchestrator()
result = await orchestrator.run_mission(goal=..., mission_id=...)

# MAUVAIS (deprecated, DeprecationWarning)
from core.orchestrator import BeaOrchestrator

# MAUVAIS (orchestrateur interne, ne pas instancier)
from core.bea_executor import BeaOrchestrator
```

### 5. Quels tests garantissent que le chemin runtime réel ne dépend pas d'un module supprimé ?

Tests en place (au 2026-06-23) :

| Test | Ce qu'il garantit |
|------|------------------|
| `python -c "from core.meta_orchestrator import MetaOrchestrator"` | Import de base |
| `python -c "from core.orchestrator_v2 import OrchestratorV2"` | OrchestratorV2 importable |
| `tests/core/test_meta_orchestrator_*.py` | Lifecycle de mission |
| `tests/self_improvement/` | Pipeline auto-amélioration end-to-end |
| `smoke_e2e_cycle.py --fixture sha256` | Chemin complet sans LLM |
| CI `test-windows` job | Portabilité Windows |

**Gap identifié :** il n'existe pas de test qui instancie `MetaOrchestrator` + `BeaOrchestrator` + `OrchestratorV2` ensemble dans un seul test d'intégration et vérifie que la délégation passe correctement. Recommandé en P2.

---

## Décision

1. **MetaOrchestrator** est le seul point d'entrée autorisé. Pas de retour arrière.
2. **OrchestratorV2** reste à `core/orchestrator_v2.py`. Ne pas déplacer.
3. **BeaOrchestrator** reste dans `core/bea_executor.py`. Le shim `core/orchestrator.py` est conservé jusqu'à nettoyage complet des callers.
4. Tout nouveau code qui a besoin d'orchestration **doit** passer par `get_meta_orchestrator()`.
5. Les 4 fichiers business (`business_orchestrator.py`, etc.) sont du scaffolding et ne font pas partie de la chaîne d'orchestration runtime.

---

## Conséquences

- **Positif :** un seul chemin, testable, documenté.
- **Négatif :** la documentation doit être maintenue à chaque refactor majeur (risk de dérive comme avec STATUS.md).
- **Action requise :** ajouter un test d'intégration `test_orchestration_delegation_chain.py` qui vérifie la chaîne MetaOrchestrator → BeaOrchestrator → OrchestratorV2 (P2).
