# AUDIT COMPLET — JarvisMax Master
**Date:** 2026-04-06 | **Auditeur lead:** BestOpenClaw | **Repo:** UniTy01/Jarvismax-master

---

## 📊 CHIFFRES CLÉS

| Métrique | Valeur |
|----------|--------|
| Fichiers Python | 953 |
| Lignes de code Python | 278 395 |
| Erreurs de syntaxe | 0 |
| Fichiers de tests | 236 |
| Rapports d'audit archivés | 165 |
| Routers API montés | ~50 (try/except) |
| Services Docker | 8+ (postgres, redis, qdrant, ollama, n8n, open-webui, caddy, jarvis_core) |

---

## ✅ CE QUI FONCTIONNE RÉELLEMENT

### 1. Chaîne d'import principale — 12/15 PASS
- `config.settings` ✅
- `core.meta_orchestrator` ✅
- `kernel.runtime.boot` ✅
- `core.memory_facade` ✅
- `core.orchestrator` (JarvisOrchestrator) ✅
- `executor.execution_engine` ✅
- `core.tool_registry` ⚠️ (PASS mais `search_in_files` manquant → fonctionnalité de recherche fichier silencieusement indisponible)
- `agents.agent_factory` ✅
- `core.planning.plan_runner` ✅
- `core.self_improvement.engine` ✅
- `learning.learning_engine` ✅
- `core.browser.browser_agent` ✅
- `business.business_orchestrator` ✅

### 2. Architecture kernel → core fonctionnelle
Le pattern de registration au boot (main.py) fonctionne : kernel enregistre policy, planner, classifier, evaluator, reflection, critique, lesson store, memory facade, router, agents. C'est bien découplé.

### 3. Docker Compose bien structuré
- Postgres 16, Redis 7, Qdrant, Ollama, n8n, Open-WebUI, Caddy — tous avec healthchecks
- Caddy pour TLS automatique
- Memory limits définis
- Init SQL pour les tables de base

### 4. Flutter App — Architecture correcte
- JWT auth avec refresh token
- WebSocket pour le temps réel (mission updates, actions)
- Profils de connexion (emulator, local, tailscale, production)
- HTTPS en production via Caddy

### 5. CI basique fonctionnel
- 95 tests de régression ciblés qui tournent à chaque PR
- Job d'intégration séparé (nightly avec secrets)

---

## ❌ CE QUI NE FONCTIONNE PAS

### 1. Import cassé : `api.main` (FAIL)
`from api.main import app` → `ModuleNotFoundError: No module named 'fastapi'`
**Impact:** L'API ne peut pas démarrer hors Docker/venv.
**Fix:** S'assurer que l'environnement a toutes les deps installées.

### 2. Import cassé : `core.rag.pipeline` — Nom de classe incorrect
Le code exporte `RagPipeline` mais les consommateurs cherchent `RAGPipeline` (casse différente).
**Impact:** Tout code utilisant `RAGPipeline` crash silencieusement.
**Fix:** Renommer la classe ou auditer tous les consommateurs.

### 3. Multimodal — Stubs non implémentés
```python
@app.post("/api/multimodal/image")
async def multimodal_image(request: dict, _user=Depends(require_auth)):
    return {"ok": False, "error": "multimodal not implemented"}
```
Les 3 endpoints multimodal (image, TTS, STT) retournent "not implemented".

### 4. `search_in_files` manquant dans `file_tool.py`
Référencé dans `tool_registry.py` (lignes 309, 357) mais la fonction n'existe pas.
**Impact:** L'outil de recherche dans les fichiers est silencieusement désactivé.

---

## ⚠️ PROBLÈMES STRUCTURELS GRAVES

### 1. DUPLICATION MASSIVE — Le problème #1 du repo

**Orchestrateurs (5+ versions) :**
- `core/orchestrator.py` (JarvisOrchestrator)
- `core/orchestrator_v2.py` (OrchestratorV2 avec DAG + asyncpg)
- `core/meta_orchestrator.py` (MetaOrchestrator — le "canonical")
- `core/orchestrator_lg/` (LangGraph flow)
- `business/business_orchestrator.py`
- `core/orchestration/` (14 fichiers — decision pipeline, reasoning, etc.)
- `core/orchestration_bridge.py`, `core/orchestration_guard.py`

**Mémoire (20+ fichiers hors tests) :**
- `core/memory.py`, `core/memory_facade.py`, `core/memory/` (4 fichiers)
- `core/memory_graph/` (3 fichiers), `core/knowledge_memory.py`
- `core/mission_memory.py`, `core/improvement_memory.py`
- `memory/` (20 fichiers — vector_memory, vault_memory, agent_memory, etc.)
- `core/planning/execution_memory.py`, `core/planning/learning_memory.py`
- `core/economic/strategic_memory.py`, `core/finance/finance_memory.py`

**Self-improvement (10+ fichiers hors tests) :**
- `core/self_improvement.py`, `core/self_improvement_engine.py`, `core/self_improvement_loop.py`
- `core/improvement_loop.py`, `core/improvement_daemon.py`, `core/improvement_detector.py`
- `core/improvement_memory.py`, `core/improvement_proposals.py`
- `core/self_improvement/` (30+ fichiers — un sous-répertoire entier)

**Policy engines (4+) :**
- `core/policy_engine.py`, `core/policy/policy_engine.py`
- `core/execution_policy.py`, `core/policy_mode.py`
- `kernel/policy/engine.py`

### 2. DOUBLE BASE DE DONNÉES — SQLite + Postgres non réconciliés
- `core/db.py` → SQLite (`workspace/jarvismax.db`) avec 4 tables (vault_entries, actions, missions, goals)
- `docker/postgres/init.sql` → Postgres avec 4 tables différentes (vault_memory, action_log, sessions, runtime_config)
- `core/orchestrator_v2.py` → essaie asyncpg puis fallback SQLite
- `core/improvement_memory.py` → "SQLite primary + asyncpg upgrade path"

**Résultat :** Personne ne sait quelle DB est la source de vérité. Les tables ne matchent même pas.

### 3. API "FAIL-OPEN" — 50 routers avec try/except
Chaque router est monté avec un try/except qui log un warning et continue. Si un composant critique crashe au chargement, l'API boot quand même mais avec des fonctionnalités silencieusement manquantes. Aucun moyen de savoir ce qui marche réellement sans vérifier les logs.

### 4. FICHIERS ORPHELINS (jamais importés)
- `agents/peer_review.py`
- `agents/recovery_agent.py`
- `api/mission_summary_builder.py`
- `core/agent_loop.py`
- `core/background_dispatcher.py`
- `core/mission_repair.py`
- `executor/coding_loop.py`
- `executor/hardening.py`
- `executor/loop_guard.py`
- `executor/safe_tool.py`
- `plugins/plugin_health.py`
- `tools/dependency_tool.py`, `tools/filesystem_tool.py`, `tools/python_tool.py`

### 5. TESTS — Couverture illusoire
- 236 fichiers de tests MAIS seulement 95 sont exécutés en CI
- Les 141 autres ne sont jamais lancés automatiquement
- Pas de pytest installé sur le système hors Docker
- Beaucoup de tests testent des schémas/contrats Pydantic, pas du comportement réel

### 6. 165 RAPPORTS D'AUDIT ARCHIVÉS
Le dossier `docs/archive/` contient 165 rapports — preuve d'un pattern de "correction par accumulation" :
- Chaque agent/session ajoute du code et un rapport
- Personne ne consolide ni ne supprime l'ancien
- Le code grandit mais ne se simplifie jamais

---

## 🔗 CONNEXIONS — CE QUI EST BRANCHÉ vs DÉBRANCHÉ

| Composant | Branché | Notes |
|-----------|---------|-------|
| Kernel → MetaOrchestrator | ✅ | Via `register_orchestrator()` au boot |
| Kernel → Policy Engine | ✅ | Via `register_core_policy_fn()` |
| Kernel → Planner | ✅ | Via `register_core_planner()` |
| Kernel → Classifier | ✅ | Via `register_core_classifier()` |
| Kernel → Evaluator | ✅ | Via `register_core_evaluator()` |
| Kernel → Memory Facade | ✅ | Via `register_facade_store/search()` |
| Kernel → Learning Loop | ✅ | Via `register_lesson_store/retrieve()` |
| Kernel → Agents | ✅ | Via `build_and_register_kernel_agents()` |
| Flutter → API v3/missions | ✅ | POST/GET /api/v3/missions |
| Flutter → WebSocket | ✅ | /ws/stream avec JWT |
| Flutter → Auth | ✅ | /auth/token + /auth/refresh |
| Postgres → Code Python | ⚠️ | Déclaré dans Docker mais très peu utilisé dans le code (seulement orchestrator_v2 + improvement_memory) |
| Redis → Code Python | ⚠️ | Surtout dans rate_limiter, env_validator, skill_builder — pas de cache centralisé |
| Qdrant → Vector Memory | ⚠️ | Référencé mais la plupart des stores mémoire utilisent des dicts en RAM |
| Multimodal (image/TTS/STT) | ❌ | Stubs "not implemented" |
| Voice/Call System | ⚠️ | Router monté mais Twilio est optionnel/commenté |
| MCP Servers | ⚠️ | Framework présent, activation via env vars (QDRANT_MCP_ENABLED, etc.) |
| OpenHands/Devin Agent | ⚠️ | Code présent dans `agents/autonomous/` mais non testé en CI |

---

## 📋 PLAN DE CORRECTION — PAR PRIORITÉ

### 🔴 P0 — CRITIQUE (faire immédiatement)

1. **Réconcilier SQLite vs Postgres** — Choisir UNE source de vérité. Si Postgres est le choix prod, migrer les 4 tables SQLite et supprimer `core/db.py` comme store primaire.

2. **Fixer le naming `RagPipeline` → `RAGPipeline`** — Ou auditer tous les consommateurs. `grep -rn 'RAGPipeline' .` pour trouver les cassés.

3. **Implémenter `search_in_files` dans `file_tool.py`** — Ou supprimer les références mortes dans `tool_registry.py`.

4. **Ajouter un health-check de démarrage** — Au lieu du fail-open sur 50 routers, ajouter un `/api/v3/system/readiness` qui liste explicitement quels composants sont chargés et lesquels ont échoué.

### 🟠 P1 — CONSOLIDATION (1-2 semaines)

5. **Fusionner les orchestrateurs** — MetaOrchestrator est le canonical. Supprimer ou absorber orchestrator.py, orchestrator_v2.py, orchestrator_lg/. Documenter un seul chemin d'exécution.

6. **Fusionner les systèmes mémoire** — `memory_facade.py` est le point d'entrée. Supprimer les 15+ fichiers mémoire qui ne passent pas par la facade.

7. **Fusionner les policy engines** — `core/policy_engine.py` + `core/policy/policy_engine.py` + `core/execution_policy.py` → UN seul.

8. **Supprimer les fichiers orphelins** — 15 fichiers jamais importés = code mort.

9. **Nettoyer `docs/archive/`** — 165 rapports qui ne servent plus. Garder les 5-10 plus pertinents, archiver le reste dans un tag git.

### 🟡 P2 — AMÉLIORATION (2-4 semaines)

10. **Étendre la couverture CI** — Passer de 95 à 200+ tests en CI. Sélectionner les meilleurs parmi les 236 existants.

11. **Implémenter le multimodal** — Les 3 endpoints sont des stubs. Soit les implémenter, soit les supprimer pour éviter la confusion.

12. **Consolider les self-improvement** — 10+ fichiers pour une seule feature. Réduire à 3-4 max (engine, memory, daemon, safety).

13. **Vraie intégration Postgres/Redis/Qdrant** — Beaucoup de code référence ces services mais utilise des fallbacks en RAM. Brancher réellement ou supprimer les dépendances Docker.

14. **Documenter l'architecture réelle** — ARCHITECTURE.md existe mais ne reflète plus la réalité du code. Réécrire basé sur ce qui tourne vraiment.

### 🟢 P3 — NICE TO HAVE

15. **Flutter : ajouter des tests widget**
16. **MCP : documenter l'activation et tester E2E**
17. **Réduire les 953 fichiers Python** — Objectif réaliste : 400-500 après consolidation

---

## VERDICT GLOBAL

> **Le repo est un prototype ambitieux qui fonctionne dans son chemin principal (kernel → meta_orchestrator → missions) mais souffre d'une dette technique massive due à l'accumulation de code par couches successives sans consolidation.**

- Le core path (soumettre une mission, la planifier, l'exécuter, retourner un résultat) **fonctionne**
- L'API boot et sert des requêtes **fonctionne**
- L'app Flutter communique avec le backend **fonctionne**
- La mémoire, l'improvement, le multimodal, les agents autonomes = **partiellement fonctionnel ou stubs**
- La base de données est **en double** et **incohérente**
- 40-50% du code est probablement **du code mort ou dupliqué**
