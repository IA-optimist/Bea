# JARVISMAX — TRUTH AUDIT
## 2026-04-06 — Atlas Director Assessment

**Méthode** : Chaque surface testée en runtime sur jarvismax-prod (77.42.40.146).
Classification basée sur le comportement réel, pas sur le code existant.

---

## CLASSIFICATION LÉGENDE

| Tag | Signification |
|-----|---------------|
| **PROVEN** | Retourne des données réelles, testé end-to-end, utilisé en production |
| **WIRED** | Code branché, endpoint répond, mais pas prouvé end-to-end |
| **PARTIAL** | Fonctionne partiellement (certaines fonctions OK, d'autres stub) |
| **STUB** | Endpoint existe, retourne 200, mais données vides/statiques/hardcodées |
| **NOT VERIFIED** | Code existe mais pas testé runtime |
| **DEAD** | Import cassé, 404/500, ou jamais appelé |

---

## 1. MISSION PIPELINE

| Composant | Classification | Preuve |
|-----------|---------------|--------|
| POST /api/v2/missions/submit | **PROVEN** | Missions s'exécutent, agents assignés, status transitions CREATED→PLANNED→RUNNING→REVIEW→DONE |
| GET /api/v2/missions | **PROVEN** | Retourne historique réel (45 missions) |
| GET /api/v2/missions/{id} | **PROVEN** | Détails complets avec plan_steps, agent_results, trace |
| GET /api/v3/mission-state | **PROVEN** | 45 missions, statuts réels |
| GET /api/v3/mission-state/stats | **PROVEN** | FAILED:34, DONE:11 — chiffres honnêtes |
| POST /api/v1/mission/run | **WIRED** | Code existe, non testé cette session |
| approve/reject/cancel/pause/resume | **WIRED** | Code branché, non testé end-to-end |
| mission.exception handling | **PARTIAL** | Le bug needs_approval est fixé, mais agents ne font pas d'appel LLM substantif — retournent des listings workspace |

### VERDICT MISSION
**Le pipeline mission est PROVEN pour le flow basique (submit → plan → agents → done).**
**MAIS : les agents NE FONT PAS de vrai appel LLM pour répondre aux questions.** Ils retournent des listings workspace au lieu de réponses intelligentes. Le `final_output` vient d'un fallback ou d'un kernel_adapter, pas d'un agent qui a raisonné.

---

## 2. KERNEL

| Composant | Classification | Preuve |
|-----------|---------------|--------|
| Kernel boot | **PROVEN** | 0 warnings, tous subsystems registered |
| /api/v3/kernel/status | **PROVEN** | booted=true, 19 capabilities, subsystems all true |
| /api/v3/kernel/capabilities | **PROVEN** | 19 capabilities listées avec descriptions |
| Kernel orchestrator registration | **PROVEN** | orchestrator=True, missions exécutées via kernel |
| Kernel evaluator | **PROVEN** | EvaluationEngine registered, evaluate_result() fonctionne |
| Kernel classifier | **PROVEN** | mission_classifier registered |
| Kernel policy | **PROVEN** | policy_engine registered |
| Kernel performance tracking | **WIRED** | Data file exists (13 records), endpoint répond |
| Kernel convergence | **WIRED** | /api/v3/kernel/convergence existe mais non testé profondément |

### VERDICT KERNEL
**Kernel est PROVEN pour le boot et l'orchestration.** Il sert réellement de fondation runtime.

---

## 3. AGENTS

| Composant | Classification | Preuve |
|-----------|---------------|--------|
| Agent registry | **PROVEN** | 36 agents listés |
| jarvis_team availability | **PROVEN** | available=true, agent_count=36 |
| crew availability | **WIRED** | available=false (CrewAI non installé) |
| Agent execution (scout-research) | **PARTIAL** | Exécuté dans missions, mais retourne listing workspace, pas analyse LLM |
| Agent execution (lens-reviewer) | **PARTIAL** | Idem |
| Agent execution (shadow-advisor) | **PARTIAL** | Idem |
| Agent creation/deletion API | **STUB** | Endpoints existent, non testés |

### VERDICT AGENTS
**L'infrastructure agent est PROVEN. L'intelligence des agents est PARTIAL — ils s'exécutent mais ne font pas de vrai raisonnement LLM sur la tâche.**

---

## 4. MÉMOIRE

| Composant | Classification | Preuve |
|-----------|---------------|--------|
| VaultMemory (Postgres) | **PROVEN** | store/retrieve/invalidate testés en live |
| CanonicalMissionStore (Postgres) | **PROVEN** | Missions persistées en PG |
| ImprovementMemory (asyncpg) | **PROVEN** | Backend pg confirmé |
| CheckpointStore (asyncpg) | **PROVEN** | Backend pg confirmé |
| MemoryBus | **WIRED** | Code branché, utilisé dans le flow, mais layers vides |
| VectorMemory (Qdrant) | **PARTIAL** | 101 points dans collection 384, collection 1536 vide |
| MemoryStore (store.py) | **PARTIAL** | Embeddings OpenRouter OK, mais 0 documents indexés |
| DecisionMemory | **WIRED** | Endpoint répond, non prouvé end-to-end |
| RAG pipeline | **PARTIAL** | Status: 0 fichiers indexés, store="qdrant" |

### VERDICT MÉMOIRE
**Infrastructure mémoire PROVEN (Postgres + Qdrant). Utilisation réelle PARTIAL — les systèmes tournent mais sont sous-alimentés en données.**

---

## 5. API SURFACE

| Surface | Classification | Preuve |
|---------|---------------|--------|
| /api/health | **PROVEN** | Retourne composants réels |
| /api/v3/system/readiness | **PROVEN** | Probes LLM/Qdrant/Orchestrator |
| /api/v3/system/registry | **PROVEN** | 56 routers, 633 routes |
| /api/v2/self-improve/* | **WIRED** | Endpoints existent, daemon bloqué par security_gate |
| /api/v3/finance/* | **STUB** | Retourne des zéros (revenue:0, arr:0, customers:0) |
| /api/v3/venture/* | **STUB** | active:true mais 0 hypotheses, 0 experiments, 0 evaluations |
| /api/v3/economic/* | **PARTIAL** | 85 strategic_memory_records, mais recommendations=empty |
| /api/v3/playbooks | **STUB** | 9787B de données mais ce sont des templates statiques, pas des exécutions réelles |
| /api/v3/plans | **EMPTY** | Retourne [] |
| /api/v2/multimodal/capabilities | **STUB** | dit dalle3:true, vision_gpt4o:true mais aucune clé OpenAI (les appels échoueraient) |
| /api/v2/browser/* | **STUB** | Endpoints POST, non testables sans Playwright |
| /api/v2/voice/* | **STUB** | Aucune config Twilio |
| /aios/* | **WIRED** | Dashboard AIOS retourne des données mais ce sont des introspections statiques |
| /api/v3/observability/* | **DEAD** | Retourne 401 (route mal configurée ou auth différente) |
| /api/v3/cognitive/* | **PARTIAL** | memory_graph=2 nodes, 0 edges. Modules=8 mais données minimales |
| /api/v3/connectors | **STUB** | Liste 5 connectors (github, slack, etc.) mais tous status="not_configured" |
| /api/v3/mcp/servers | **PARTIAL** | 11 servers listés, la plupart "disabled" ou sans URL configurée |
| /api/v3/tools | **WIRED** | 15 tools listés mais aucune exécution prouvée |
| /api/v3/skills | **STUB** | 6 skills listées (market-research, etc.) mais ce sont des templates |
| /api/v3/self-model | **PARTIAL** | readiness=0.2, ready_capabilities=0, degraded=2 — chiffres honnêtes |

### VERDICT API
**582 endpoints, dont ~30 PROVEN, ~100 WIRED, ~150 STUB, ~300 potentiellement DEAD ou non vérifiés.**
**Le ratio signal/bruit est très faible. Un frontend qui consomme cette API afficherait massivement des données vides ou fausses.**

---

## 6. INFRASTRUCTURE

| Composant | Classification | Preuve |
|-----------|---------------|--------|
| Docker stack (10 containers) | **PROVEN** | Tous healthy |
| Postgres + pgvector | **PROVEN** | 9 tables, vector extension active |
| Redis | **PROVEN** | Connecté, 0 keys (sous-utilisé) |
| Qdrant | **PROVEN** | 3 collections, 101 points |
| Caddy (reverse proxy) | **PROVEN** | Running |
| Ollama | **WIRED** | Container up mais pas utilisé par le pipeline |
| N8N | **WIRED** | Container up, health OK, mais non intégré au flow mission |
| Open WebUI | **WIRED** | Container up, non testé |
| GitHub MCP | **PARTIAL** | Container up, health=disabled |
| Qdrant MCP | **PARTIAL** | Container up, health=disabled |
| LLM (OpenRouter) | **PROVEN** | Appels réussis, réponses reçues |
| Embeddings (OpenRouter) | **PROVEN** | text-embedding-3-small fonctionne via OpenRouter |

---

## 7. TESTS

| Composant | Classification | Preuve |
|-----------|---------------|--------|
| Unit tests (4847 passing) | **PROVEN** | Exécution locale confirmée |
| CI gate (700+ tests) | **PROVEN** | 15 fichiers de test gatés |
| Integration tests | **NOT VERIFIED** | Nécessitent secrets GitHub Actions |
| Smoke tests | **NOT VERIFIED** | Nécessitent --run-infra-tests |

---

## 8. DOCUMENTATION

| Document | Classification | Preuve |
|----------|---------------|--------|
| ARCHITECTURE.md | **PARTIAL** | Reflète la structure mais pas l'état runtime |
| DB_RECONCILIATION_PLAN.md | **PROVEN** | Phases 1-2 complétées, Phase 3 en cours |
| README.md | **PARTIAL** | Chiffres mis à jour mais mélange aspirationnel et réel |

---

## SYNTHÈSE GLOBALE

### Ce qui est VRAI et PROUVÉ
1. Le kernel boot et orchestre des missions
2. Le pipeline mission fonctionne end-to-end (submit→plan→execute→done)
3. La persistence Postgres est câblée et fonctionne
4. Les embeddings fonctionnent via OpenRouter
5. Les 10 containers Docker sont stables
6. 4847 tests passent

### Ce qui est FAUX ou TROMPEUR
1. **Les agents ne raisonnent pas** — ils retournent des listings workspace, pas des analyses LLM
2. **582 endpoints** mais seuls ~30 retournent des données réelles exploitables
3. **Multimodal "capabilities"** dit DALL-E/Vision "true" sans clé OpenAI
4. **Finance** affiche 0 partout — STUB présenté comme feature
5. **Venture/Playbooks/Plans** — templates statiques présentés comme système actif
6. **Connectors** — tous "not_configured" mais listés comme disponibles
7. **MCP servers** — 11 listés, la plupart disabled
8. **Self-model readiness=0.2** — le système s'évalue lui-même à 20% de readiness

### PRIORITÉS D'ACTION
1. **P0 — CRITICAL** : Fixer le pipeline agent→LLM pour que les agents fassent de vrais appels
2. **P0 — CRITICAL** : Classifier les 582 endpoints (canonical/legacy/stub/dead) dans le code
3. **P1** : Supprimer ou marquer clairement les stubs qui mentent (multimodal, finance, voice, browser)
4. **P1** : Aligner la documentation sur la réalité runtime
5. **P2** : Activer les MCP servers (github, qdrant) qui sont disabled
6. **P2** : Alimenter la mémoire (RAG, vector memory) avec des données réelles
7. **P3** : Consolider v1/v2/v3 en une surface API claire
