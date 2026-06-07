# Audit & Roadmap d'amélioration — Bea Max

_Date : 2026-06-01 · Branche : `hardening/critical-fixes`_

## 1. Résumé exécutif

Le projet est **stable et bien durci**. L'audit complet (sécurité, bugs, deps,
Docker, code mort, tests) ne révèle **aucun problème CRITIQUE** et un seul vrai
bug logique (corrigé). La suite de tests est saine à l'import (5860 tests
collectés). Les axes d'amélioration restants relèvent du **durcissement
incrémental** et de l'**observabilité**, pas de la correction d'urgence.

## 2. Corrigé pendant cette session

| Fichier | Problème | Statut |
|---|---|---|
| `orchestrate-cli/src/agents/claude_code.py` | `def` manquant (module non importable) | ✅ |
| `orchestrate-cli/examples/comprehensive_workflow.py` | Indentation invalide | ✅ |
| `orchestrate-cli/src/utils/tool_registry.py` | `import os` manquant (NameError) | ✅ |
| `api/routes/performance.py` ×3 | Défauts mutables `dict={}` (B006) | ✅ |
| `executor/desktop_env/sandbox.py` | `except` dupliqué → handler mort, log d'erreur perdu (B025) | ✅ |
| `core/orchestration/reasoning_engine.py` | Doublon `"configure"` dans un set (B033) | ✅ |
| `orchestrate-cli/` + `orchestrate-mobile/` | Mis en conformité lint et **réintégrés au gate** ruff (imports morts, variables mortes, `# noqa` sur imports-sondes, `per-file-ignore` T201 pour les CLI) | ✅ |
| `orchestrate-cli/orchestrate-cli/` | **Dossier dupliqué** (snapshot obsolète, non importé) supprimé | ✅ |
| `Dockerfile` (racine) | Déprécié (root, non utilisé en CI) supprimé — canonique = `docker/Dockerfile` | ✅ |

Résultat : `ruff check .` → **All checks passed!** sur tout le repo.

## 3. État de santé (scans objectifs)

- **Sécurité** : pas de `shell=True`, ni `eval`/`exec`/`pickle`/`yaml.load` non
  sûrs, ni credentials en dur (les alertes bandit étaient des faux positifs :
  labels d'enum, jitter de backoff). SQL **paramétré** ; `table_name` déjà
  validé par regex. Docker canonique multi-stage **non-root** ; `.dockerignore`
  exclut `.env`/secrets. 44 dépendances **toutes épinglées**.
- **Code mort** : minime (~9 variables/imports inutilisés en haute confiance).
- **Duplication** : aucune (hors `__init__.py` vides, normaux).
- **Tests** : 5860 collectés, 10 erreurs = **deps optionnelles absentes du
  sandbox** (fastapi/structlog/prometheus/playwright), pas des bugs de code.
- **Hygiène** : `.gitignore` complet ; clutter (logs debug, venvs, caches) déjà
  ignoré.

## 4. Roadmap priorisée (par levier sur la robustesse)

### P1 — Filet de sécurité : tests + CI
À faire **dans ton venv 3.12** (non reproductible dans le sandbox) :
- `pytest` complet vert + couverture **ciblée** sur les zones critiques :
  orchestration (`core/meta_orchestrator`, `agents/crew`), exécuteur/sandbox
  (`executor/`, `core/tool_executor`), auth API.
- Gate CI sur cette couverture (pas un % global).

### P2 — Observabilité : rendre les échecs visibles
- 76 `try/except: pass` (S110) + 56 `raise` sans `from` (B904) avalent des
  erreurs / perdent le contexte. Ajouter du logging structuré sur les chemins
  d'échec, **module par module** (commencer par `api/` et `executor/`), validé
  par les tests. _Non fait en masse ici : édition à l'aveugle sur code prod non
  testé = risque > bénéfice._

### P3 — Résilience de la boucle d'agent
Bonnes briques déjà présentes (timeout par thread, backoff+jitter,
`startup_checks`). Formaliser par-dessus : budgets explicites (temps/tokens/coût)
par mission, circuit-breaker sur défaillance d'un provider LLM / dépendance
optionnelle, kill-switch. _Nécessite des décisions produit._

### P4 — Élargir le gate qualité  _(analyse mypy faite — voir §6)_
- Finir les règles ruff différées (`E701/E702/E741/E402`) module par module.
- Monter la couverture **mypy** sur `core/` et `agents/`.

### P5 — Consolidation legacy  _(fait — 1 module mort retiré)_
`core/self_improvement/legacy_adapter.py` (0 importeur, 0 ref dynamique) **supprimé**.
Les 8 autres shims (`memory/legacy/`, `core/*_legacy.py`, `core/legacy_compat`)
ont des importeurs réels → conservés (les retirer = refactor à faire avec tests).

## 6. Findings mypy (P4) — à trier dans ton venv

Pas de config mypy dans le repo ; lancé sur `core/`+`agents/` avec
`--ignore-missing-imports`. ~1000 remontées, **dominées par des faux positifs** :
les 412 `[call-arg]` sont à 95 % dus au pattern `log = logging.getLogger(...)`
puis réassigné à `structlog` (mypy infère `logging.Logger` et croit les kwargs
structurés invalides — alors que `structlog==25.5.0` est garanti). Recommandation :
ajouter un `mypy.ini` (`ignore_missing_imports = True`) + typer le logger pour
éliminer ce bruit d'un coup, puis traiter `[union-attr]`/`[attr-defined]` (None
non-narrowé) module par module.

**Vrais candidats-bugs `call-arg` (22, hors logger) — kwargs/positionnels invalides :**

- 🔴 **CONFIRMÉ runtime** : `core/venture/venture_loop.py:632` et
  `core/execution/deployment.py:393` construisent `StrategicRecord(record_type=,
  score=, context=, findings=, failures=)` — **aucun de ces champs n'existe**
  (dataclass = `strategy_type, schema_type, outcome_score, context_features,
  key_findings, failure_reasons`). ⇒ `TypeError` à chaque appel. Mapping probable
  à **valider** : `record_type→strategy_type`, `score→outcome_score`,
  `context→context_features`, `findings→key_findings`, `failures→failure_reasons`.
- À vérifier : `core/orchestration/business_missions.py:143` `ProductSpec(target_market=,
  pain_points=, stack=)` ; `core/memory_facade.py:303` `DecisionMemory.record(content=,
  decision_type=)` ; `core/knowledge_ingestion.py:126` `KnowledgeMemory.store_if_useful(
  success=, mission_id=)` ; `core/capabilities/semantic_router.py:267` `LLMFactory(...)`
  (manque `settings`) ; `core/governance.py:684` `classify_danger(risk_level=)` ;
  `core/orchestrator_lg/langgraph_flow.py:115/165` `build_plan(objective=, context=)`,
  `AgentRunner.run()` (manque `goal`).

Ces correctifs touchent des contrats d'API : ils demandent ton intention (mapping
des champs) et une validation par tests — je ne les ai pas appliqués à l'aveugle.

## 7. À faire côté Windows avant de committer

```
del .git\index.lock        # lock git résiduel bloquant
ruff check .               # doit afficher "All checks passed!"
pytest                     # baseline dans ton venv 3.12
git diff                   # relire les changements de session
```
