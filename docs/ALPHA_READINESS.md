# Béa — Alpha Readiness Assessment

> **Date :** 2026-06-21  
> **SHA main :** `bdd86d5` (PR #92 merged)  
> **Scope :** PRs #89–#92 + état cumulatif du repo  
> **Verdict :** 🟡 **ALPHA-READY avec réserves** — core stable, provider résolu, Flutter migré, mémoire active. Blocages connus documentés ci-dessous.

---

## 1. PRs récentes — ce qui a été livré

### PR #89 — Mission Learning Loop (`c15ff48`)
**Titre :** `feat(memory,evaluation): active memory, model router and mission learning loop`

| Livrable | État |
|---|---|
| `MissionReportParser` (JSON + Markdown fallback) | ✅ |
| `MissionLearner` — 6 types de mémoire produits (eval_result, model_result, bug_memory, skill, test_map, risk) | ✅ |
| `ModelRouter` — scoring depuis l'historique `model_result` | ✅ |
| `bea_eval.py` étendu à 25 évaluations | ✅ |
| Tests + fixtures + `docs/MISSION_LEARNING.md` | ✅ |

**Validation :** 25/25 bea eval, 70 pytest passés, ruff clean.

---

### PR #90 — Endpoints v3 pause/resume/stream (`535d7be`)
**Titre :** `feat(api): add v3 pause/resume/stream endpoints — unblock Flutter migration`

| Endpoint | Sémantique |
|---|---|
| `POST /api/v3/missions/{id}/pause` | Acknowledgement-only (miroir v1) |
| `POST /api/v3/missions/{id}/resume` | Acknowledgement-only (miroir v1) |
| `GET /api/v3/missions/{id}/stream` | SSE, délègue à `_sse_generator` de `mission_control.py` |

Les endpoints v1 sont **conservés** — Flutter en dépendait encore au moment du merge. APK rebuild prévu PR #91.

---

### PR #91 — Flutter migré v1 → v3 (`3ca8dfb`)
**Titre :** `feat(flutter): migrate 3 v1 calls to v3 + empty allowlist`

| Appel Flutter | Avant | Après |
|---|---|---|
| `pauseMission` | `/api/v1/missions/{id}/pause` | `/api/v3/missions/{id}/pause` |
| `resumeMission` | `/api/v1/missions/{id}/resume` | `/api/v3/missions/{id}/resume` |
| `streamMissionLogs` | `/api/v1/missions/{id}/stream` | `/api/v3/missions/{id}/stream` |

Le format SSE est identique — aucune modification de parsing côté client. La liste d'autorisation v1 dans `api/v1_allowlist.py` est maintenant **vide** (zéro appels Flutter vers v1).

---

### PR #92 — Provider runtime health + Ollama autodiscovery (`bdd86d5`)
**Titre :** `feat(providers): runtime health check + Ollama host autodiscovery`

| Livrable | État |
|---|---|
| `core/providers/runtime_health.py` — sonde async OpenRouter + Ollama | ✅ |
| `_resolve_ollama_host()` — TCP probe + cache, fallback `127.0.0.1:11434` | ✅ |
| `scripts/provider_healthcheck.py` — diagnostic CLI `--json`, Windows-safe | ✅ |
| 14 tests mock (zéro dépendance réseau) | ✅ |
| `docs/PROVIDERS.md` | ✅ |

**Résout :** CLI détaché échouait silencieusement quand `OPENROUTER_API_KEY` absent + `OLLAMA_HOST` pointait vers hostname Docker inaccessible.

---

### PR #96 — Alpha environment polish (cette PR)

| Livrable | État |
|---|---|
| `scripts/provider_healthcheck.py` — crash Unicode Windows corrigé | ✅ |
| `scripts/audit_memory_store.py` — `--dry-run` explicite ajouté | ✅ |
| 26 nouveaux tests CLI (healthcheck + audit) | ✅ |
| `docs/ALPHA_READINESS.md`, `docs/PROVIDERS.md`, `docs/MEMORY_HYGIENE.md` mis à jour | ✅ |

> ℹ️ **Note :** Les PR #93 et #94 mentionnées dans le brief n'existent pas encore au moment de la rédaction. Ce document couvre #89–#92 + #96.

---

## 2. État des validations passées

### Gate tests (bloquants)

| Gate | Résultat | Commande |
|---|---|---|
| `ruff check .` | ✅ Passé (tous fichiers PRs) | Bloquant pre-push |
| `pytest` tests critiques | ✅ 149 passés | — |
| Kernel import boundaries | ✅ Passé | `scripts/check_kernel_import_boundaries.py` |
| Coverage threshold | ✅ ≥ 60 % (baseline `min_fail_under: 59`) | `scripts/check_coverage_threshold.py` |
| `bea_eval.py` | ✅ 25/25 (PR #89) | `python scripts/bea_eval.py --json` |

### Gates ratchet (non-bloquants, mais surveillés)

| Gate | Baseline actuelle | État |
|---|---|---|
| mypy | `max_errors: 870` (mesuré 840 post Phase-1 auth) | 🟡 Dégradé acceptable |
| bandit | 0 issues | ✅ |
| pip-audit | Baseline maintenue | ✅ |
| except/pass | Ratchet en place | ✅ |
| Silent swallows | `legacy_silent_swallows.json` en place | ✅ |

### Régression 0 confirmée

- `tests/test_provider_fallback.py` — **12/12** ✅
- `tests/test_llm_provider_abstraction.py` — **4/4** ✅
- `tests/test_provider_runtime_health.py` — **14/14** ✅
- `tests/test_provider_healthcheck_cli.py` — **16/16** ✅ (nouveaux PR #96)
- `tests/test_audit_memory_store_cli.py` — **10/10** ✅ (nouveaux PR #96)

---

## 3. Diagnostic provider — état attendu

**Important :** `provider_healthcheck.py` peut retourner `UNAVAILABLE` même quand
tous les gates projet passent. Ce n'est **pas un échec de CI** — c'est un avertissement
runtime LLM.

| Résultat `provider_healthcheck.py` | Signification | Action requise |
|---|---|---|
| `[READY]` | OpenRouter actif (+ Ollama optionnel) | Rien |
| `[DEGRADED]` | OpenRouter absent, Ollama actif | Fonctionnel en local ; configurer OR pour le cloud |
| `[UNAVAILABLE]` | Aucun provider disponible | Non bloquant pour CI, **bloquant pour exécution de missions** |

### Lancer le diagnostic

```cmd
python scripts\provider_healthcheck.py
```

En cas de `[UNAVAILABLE]` en environnement de dev local sans `.env` chargé :

```cmd
REM Option 1 : charger le .env manuellement (Windows CMD)
for /f "tokens=1,2 delims==" %i in (.env) do set %i=%j
python scripts\provider_healthcheck.py

REM Option 2 : utiliser le service Windows (charge .env automatiquement)
bea_api_service.cmd

REM Option 3 : corriger l'encodage console avant tout
set PYTHONIOENCODING=utf-8
python scripts\provider_healthcheck.py
```

Le script détecte automatiquement l'encodage de la console et utilise des symboles
ASCII (`OK`/`FAIL`) à la place de `✓`/`✗` si nécessaire — aucun crash Unicode.

---

## 4. Scripts de validation disponibles

| Script | Usage alpha | Statut |
|---|---|---|
| `python scripts/validate_local.py --quick` | Gate local rapide (ruff + pytest + kernel boundaries) | ✅ Opérationnel |
| `python scripts/validate_local.py --full` | Gate complet (+ mypy + bandit + coverage + wheel) | ✅ Opérationnel |
| `python scripts/provider_healthcheck.py` | Diagnostic provider READY/DEGRADED/UNAVAILABLE | ✅ Windows-safe (PR #96) |
| `python scripts/provider_healthcheck.py --json` | JSON machine-readable pour monitoring | ✅ Opérationnel |
| `python scripts/audit_memory_store.py --dry-run` | Audit mémoire read-only explicite | ✅ `--dry-run` ajouté (PR #96) |
| `python scripts/audit_memory_store.py --apply` | Nettoyage mémoire (DESTRUCTIF) | ✅ Opérationnel |
| `python scripts/bea_eval.py --json` | Évaluation LLM 25 évals (nécessite provider actif) | ✅ Opérationnel |
| `python scripts/seed_bea_memory.py` | Seed mémoire opérationnelle initiale (Qdrant) | ✅ Opérationnel |
| `python scripts/seed_bea_self_knowledge.py` | Seed erreurs/fixes session | ✅ Opérationnel |
| `python scripts/ingest_mission_report.py` | Ingestion rapport mission → mémoire | ✅ Opérationnel |
| `python scripts/run_api_local.py` | Démarrage API dev local | ✅ Opérationnel |
| `python scripts/smoke_e2e_cycle.py` | Smoke test cycle complet | ✅ Opérationnel |
| `bea_api_service.cmd` | Service Windows (charge .env, démarre l'API) | ✅ En production |

---

## 5. Architecture courante — état des composants

| Couche | Composant clé | Maturité |
|---|---|---|
| **Orchestration** | `MetaOrchestrator` 12 phases | 🟢 PROVEN |
| **LLM routing** | `LLMFactory` + `_resolve_ollama_host()` | 🟢 PROVEN (PR #92) |
| **Provider health** | `check_provider_health()` READY/DEGRADED/UNAVAIL | 🟢 PROVEN (PR #92) |
| **Diagnostic CLI** | `provider_healthcheck.py` Windows-safe | 🟢 PROVEN (PR #96) |
| **Mémoire** | `beamax_memory_384` Qdrant + RAG actif | 🟢 PROVEN (PR #83) |
| **Mission learning** | `MissionLearner` + `ModelRouter` | 🟢 PROVEN (PR #89) |
| **API v3** | pause/resume/stream opérationnels | 🟢 PROVEN (PR #90) |
| **Flutter** | 100 % migré v3, allowlist v1 vide | 🟢 PROVEN (PR #91) |
| **Auth** | `require_auth` sur 46/53 routes, middleware fail-closed | 🟢 PROVEN |
| **Self-improvement** | Daemon + gate opérateur + `proposal_saved` réel | 🟢 PROVEN |
| **Bot Telegram** | Codex gpt-5.5 + vision + YouTube | 🟢 PROVEN |
| **Business** | AutoContentFlow + CVOptimIA sur Railway | 🟢 PROVEN |
| **Docker stack** | postgres/redis/qdrant healthy | 🟢 PROVEN |
| **MemoryFacade** | Wired, pas stress-testé Qdrant live | 🟡 WIRED |
| **MCP server** | 3 outils read-only, pas de client live | 🟡 WIRED |
| **Connectors** | Code présent, agents utilisent outils directs | 🟡 WIRED |
| **Business handlers (deploy/revenue)** | Stubs — Vercel API + Stripe non câblés | 🔴 STUB |
| **HexStrike v2** | 17/156 outils extraits, `psutil` manquant | 🔴 STUB |

---

## 6. Risques restants

### 🔴 Bloquants pour une release publique

| Risque | Détail | Mitigation disponible |
|---|---|---|
| **APK non redéployée** | Flutter migré en code (PR #91) mais l'APK sur les appareils test utilise encore d'anciens binaires | `flutter build apk --release --no-tree-shake-icons` + livraison manuelle |
| **`.env` non chargé en CLI** | Tout lancement nu sans `bea_api_service.cmd` perd `OPENROUTER_API_KEY` | `provider_healthcheck.py` aide au diagnostic ; voir section 3 |
| **mypy 840 erreurs** | Budget 870 — proche du seuil, aucune marge | Première session de nettoyage mypy strictement nécessaire avant alpha |
| **Merge conflict `api/routes/skills.py`** | Conflit pré-existant sur branche `kilo-kimi/mission-learning-loop` (hors main) | Résoudre ou abandonner la branche ; n'affecte pas main |

### 🟡 Dégradants mais non bloquants

| Risque | Détail |
|---|---|
| **v1 endpoints toujours présents** | `POST/GET /api/v1/missions/*` actifs malgré migration Flutter. Sunset prévu 2026-10-01. |
| **Ollama host cache process-wide** | Si Ollama redémarre après le premier probe, le cache `_OLLAMA_RESOLVED_HOST` est périmé jusqu'au redémarrage de l'API. Appeler `reset_ollama_host_cache()` si besoin. |
| **Coverage 60 % (seuil plancher)** | Le gate passe mais la couverture est minimale. Modules critiques `core/bea_executor.py` et `core/meta_orchestrator.py` peu couverts. |
| **Dépendances obsolètes** | `pytest 7.4.4` vs 8.x actuel, `fastapi 0.109.0` vs 0.115.x. `psutil` manquant pour hexstrike_v2. |
| **React Native (`mobile/`)** | 2 767 lignes Expo SDK 50 non maintenu. À geler explicitement. |
| **Business handlers build/deploy/revenue** | `# TODO: Implement actual deployment (Vercel API + Railway API)` — stubs actifs. |

### ℹ️ Informatif

| Point | Détail |
|---|---|
| `PRODUCTION_READINESS.md` daté 2026-04-11 | Rapport généré automatiquement, ne reflète plus l'état actuel |
| PRs Dependabot (#18–67) ouvertes | 15 PRs Dependabot non mergées (CI, Flutter, Python) — traiter groupées |
| Docs v1 allowlist | `STATUS.md` mentionne encore "3 v1 calls remain in Flutter" — obsolète depuis PR #91 |

---

## 7. Ce qui manque pour passer en beta

| Manquant | Effort estimé |
|---|---|
| Vrai fallback `POST /pause` + `POST /resume` (changement d'état réel, pas acknowledgement-only) | 1–2 sessions |
| APK livrée sur appareil (Flutter build + install + test golden path) | 0,5 session |
| Mypy < 500 erreurs | 2–3 sessions de nettoyage |
| Endpoint `/api/v3/providers/health` (expose `check_provider_health()` via API) | 0,5 session — architecture prête |
| Stripe live pour AutoContentFlow (actuellement en mode test) | Vérification compte + webhook |
| Supprimer ou implémenter `business.deploy_product` (TODO Vercel/Railway) | 1 session |
| Pipeline HexStrike v2 > 30 % complète + `psutil` dans `requirements.txt` | 2+ sessions |

---

## 8. Checklist alpha go / no-go

```
BLOQUANTS
  [ ] APK redéployée sur appareil test et testée manuellement
  [ ] provider_healthcheck.py READY confirmé sur machine de prod (ou DEGRADED accepté)
  [ ] Merge conflict kilo-kimi/mission-learning-loop résolu ou branche abandonnée

REQUIS AVANT DÉPLOIEMENT UTILISATEUR
  [x] API démarrage stable (bea_api_service.cmd)
  [x] Auth bloquante sur toutes les routes critiques
  [x] Bot Telegram opérationnel (Codex gpt-5.5 + fallback)
  [x] Mémoire RAG active (beamax_memory_384)
  [x] Mission learning loop active
  [x] Docker stack healthy (postgres/redis/qdrant)
  [x] Self-improvement gated (opérateur requis)
  [x] Provider fallback OpenRouter → Ollama documenté
  [x] Diagnostics CLI Windows-safe (PR #96)
  [ ] mypy sous le seuil max_errors courant (870) — surveiller

NON-BLOQUANTS (à traiter avant bêta)
  [ ] Endpoints pause/resume avec état réel
  [ ] v1 endpoints dépréciés + sunset header
  [ ] Dependabot PRs groupées et mergées
  [ ] React Native gelé explicitement (README + branch protection)
```

---

## 9. Commande de diagnostic alpha

Lancer dans cet ordre avant toute démonstration ou déploiement :

```bash
# 1. Vérifier les providers LLM (Windows-safe depuis PR #96)
python scripts/provider_healthcheck.py

# 2. Gate local rapide
python scripts/validate_local.py --quick

# 3. Audit mémoire (read-only, explicite)
python scripts/audit_memory_store.py --dry-run

# 4. Évaluation fonctionnelle (nécessite provider READY ou DEGRADED)
python scripts/bea_eval.py --json | python -c "import sys,json; d=json.load(sys.stdin); print('Score:', sum(v for v in d.values() if isinstance(v,bool)), '/ 25')"

# 5. Smoke test cycle cognitif
python scripts/smoke_e2e_cycle.py
```

Résultat attendu en état alpha sain :
- `provider_healthcheck.py` → `[READY]` ou `[DEGRADED]` (UNAVAILABLE = pas de mission possible)
- `validate_local.py --quick` → toutes gates vertes
- `audit_memory_store.py --dry-run` → `Mode: dry-run (read-only, no changes)`
- `bea_eval.py` → ≥ 22/25
- `smoke_e2e_cycle.py` → `SUCCESS`

---

*Dernière mise à jour : 2026-06-21 — SHA `bdd86d5` + PR #96 — PRs #89–#92 + #96 incluses*
