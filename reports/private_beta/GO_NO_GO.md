# Béa Private Beta GO/NO-GO

## Verdict
**PRIVATE_BETA_READY: true**
PUBLIC_BETA_READY: false

---

## Commit
`410452cf7000bb066e13c2029f2a84f798d65434`
Branche: `release/private-beta-0.1`
Date: 2026-06-24

---

## Ce qui est prêt

- Gate local complet : `validate_local.py --quick` 14/14 PASS
- `release_check.py` PASS : version 0.1.0-dev-preview, tous les fichiers requis présents
- Ruff : 0 violation
- Principal auth binding : 24 call sites, 0 gaps (principal depuis request.state.user, jamais hardcodé)
- Mission ID propagation : 6 call sites, 0 gaps
- Approval audit : approved_by/rejected_by depuis auth, jamais "human" hardcodé
- SessionStore : abstraction InMemory/Redis, clé `principal_id:mission_id`
- Auth : `BEA_ADMIN_PASSWORD` requis, `/health` public, reste protégé en 401
- Public seed : `public_safe=True`, 8 items neutres, 0 private_joke/personal_data/secret
- Issue templates GitHub : 4 templates (bug_report, beta_feedback, incident_report, security_report)
- CI workflows : ci.yml, flutter_apk.yml, pr-smoke.yml, kernel_ci.yml, security_pr.yml
- Docs testeurs : BETA_TESTER_GUIDE, KNOWN_LIMITATIONS, PRIVACY_FOR_TESTERS, FEEDBACK_GUIDE, TROUBLESHOOTING
- Nouveaux docs bêta : PRIVATE_BETA_SCOPE, TESTER_QUICKSTART, TESTER_SAFETY_RULES, BETA_ACCESS_SETUP, BETA_INCIDENT_RUNBOOK, APK_PHYSICAL_DEVICE_VALIDATION
- Pytest : 3451 passed après correction de 3 tests de conformité (contract sync, docs stale, env template)
- Rate-limiting actif (slowapi, `BEA_RATE_LIMIT_ENABLED`, 60 req/min par défaut)
- Self-improvement désactivé par défaut (`BEA_CONTINUOUS_IMPROVEMENT` non défini)

---

## Ce qui reste risqué mais acceptable pour 5–10 testeurs

- **InMemorySessionStore** en dev : pas de persistance cross-process. Pour beta multi-worker, passer à `RedisSessionStore`. Pour 1 process local par testeur, acceptable.
- **APK Flutter** : status "supported experimental". Build CI existe mais validation device physique HUMAN_REQUIRED. Les testeurs peuvent utiliser l'API directement.
- **Rate-limiting sans TLS** : le rate-limiter slowapi est actif, mais sans reverse proxy TLS l'API ne doit pas être exposée sur internet public. Pour accès Tailscale ou local, acceptable.
- **Modèle Ollama gemma4:12b** : limites documentées (forge-builder = artifact_invalid, shadow-advisor = json_invalid). OpenRouter free tier recommandé.
- **v1 endpoints maintenus** : `/api/v1/*` gelé mais non supprimé (3 endpoints load-bearing Flutter). Non bloquant.

---

## Ce qui bloque encore

Aucun blocker pour la bêta PRIVÉE.

Pour la bêta PUBLIQUE (hors scope) :
- APK validée sur device physique (HUMAN_REQUIRED)
- Memory store live : 1 item privé à nettoyer (`audit_memory_store.py --apply`)
- Secrets historiques rotés (action propriétaire)
- RedisSessionStore pour multi-worker
- Reverse proxy TLS pour exposition internet

---

## Actions humaines obligatoires avant invitation

1. **Rotation secrets** : Si `BEA_API_TOKEN`, `BEA_ADMIN_PASSWORD`, ou `BEA_SECRET_KEY` ont été partagés ou si le repo a été accessible à des tiers, les régénérer dans `.env` (ne pas committer).
2. **Nettoyage memory** : `python scripts/audit_memory_store.py --apply --privacy-scan` pour supprimer l'item "Fun fact romantique sur Max" (`ecdaea85-db3`) du store Qdrant live.
3. **Créer les tokens testeurs** : Via `POST /api/v3/admin/tokens` — un token `jv-xxx` par testeur. Ne jamais partager `BEA_API_TOKEN` (token maître).
4. **Vérifier accès réseau** : Si les testeurs accèdent à distance, configurer Tailscale ou un reverse proxy avec TLS.

---

## Commandes lancées

| Commande | Résultat | Classification |
|---|---|---|
| `python scripts/validate_local.py --quick` | ✅ 14/14 PASS | gate |
| `python scripts/release_check.py` | ✅ PASS | gate |
| `python scripts/check_client_v1_usage.py` | ✅ 0 active /api/v1 | gate |
| `python scripts/check_policy_principal_binding.py` | ✅ 24 sites, 0 gaps | gate |
| `python scripts/check_tool_executor_mission_id.py` | ✅ 6 sites, 0 gaps | gate |
| `python -m ruff check .` | ✅ All checks passed | gate |
| `python scripts/seed_bea_memory.py --report --profile public` | ✅ public_safe=True | gate |
| `python scripts/audit_memory_store.py --dry-run --privacy-scan` | ⚠️ 1 item privé live store | warning |
| `pytest -q --tb=no` (full suite ~10 min) | ✅ 3451 passed / 1 fixed | gate |
| `flutter --version` | ❌ hors PATH local | human_required |

---

## Tests

| Zone | Résultat |
|---|---|
| test_release_check | PASS |
| test_public_beta_docs_consistency | PASS (après fix README stale claim) |
| test_public_beta_guards | PASS |
| test_beta_ratchets | PASS |
| test_beta_stabilization | PASS |
| test_env_examples | PASS (après fix .env.example template refs) |
| test_mission_runner_protocol | PASS (après sync kernel contract + submitted_by/principal_id) |
| test_principal_propagation | PASS |
| test_mission_submitted_by | PASS |
| test_policy_session_store | PASS |
| test_policy_constants | PASS |
| Pytest full suite | 3451 passed, 375 skipped, 4 xfailed |

---

## Sécurité

| Gate | Résultat |
|---|---|
| Aucun secret dans .env.example | ✅ PASS |
| BEA_CONTINUOUS_IMPROVEMENT désactivé | ✅ PASS |
| BEA_SKIP_IMPROVEMENT_GATE non défini | ✅ PASS |
| Auth active (BEA_ADMIN_PASSWORD requis) | ✅ PASS |
| /health public, reste protégé 401 | ✅ Architecture vérifiée |
| principal_id injecté depuis request.state.user | ✅ PASS (24 call sites) |
| mission_id propagé | ✅ PASS (6 call sites) |
| approved_by depuis auth, pas hardcodé | ✅ PASS |
| Public seed propre (public_safe=True) | ✅ PASS |
| Memory store live | ⚠️ 1 item privé (HUMAN_REQUIRED pour nettoyage) |

---

## Docs

| Document | Statut |
|---|---|
| docs/BETA_TESTER_GUIDE.md | ✅ Existant, conforme |
| docs/KNOWN_LIMITATIONS.md | ✅ Existant, conforme |
| docs/PRIVACY_FOR_TESTERS.md | ✅ Existant, conforme |
| docs/FEEDBACK_GUIDE.md | ✅ Existant, conforme |
| docs/TROUBLESHOOTING.md | ✅ Existant |
| docs/PRIVATE_BETA_SCOPE.md | ✅ Créé sur cette branche |
| docs/TESTER_QUICKSTART.md | ✅ Créé sur cette branche |
| docs/TESTER_SAFETY_RULES.md | ✅ Créé sur cette branche |
| docs/BETA_ACCESS_SETUP.md | ✅ Créé sur cette branche |
| docs/BETA_INCIDENT_RUNBOOK.md | ✅ Créé sur cette branche |
| docs/APK_PHYSICAL_DEVICE_VALIDATION.md | ✅ Créé (HUMAN_REQUIRED checklist) |
| README_PUBLIC_BETA.md | ✅ Corrigé (claim rate-limiting) |

---

## Mobile

| Élément | Statut |
|---|---|
| Flutter build CI (flutter_apk.yml) | ✅ Workflow existe |
| check_client_v1_usage.py | ✅ 0 active /api/v1 (Flutter uses /api/v3) |
| APK buildée manuellement (local) | ✅ Confirmé dans memory (commit 3f2fb83) |
| Validation physique sur device Android | ❌ HUMAN_REQUIRED |
| Statut APK dans cette bêta | ⚠️ `supported experimental` |

---

## Recommandation

**GO pour bêta privée — 5 à 10 testeurs techniques** avec les 4 actions humaines listées ci-dessus (secrets, memory, tokens testeurs, accès réseau). Béa n'est pas stable, pas production-ready, pas autonome sans supervision — c'est précisément ce qu'une bêta privée avec des testeurs techniques permet de documenter.
