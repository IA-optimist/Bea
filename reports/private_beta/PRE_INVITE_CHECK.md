# PRE_INVITE_CHECK — Private Beta (3 testeurs initiaux)

Generated: 2026-06-26
Main HEAD: `25b98cde523bdcafd2ac5a55503e07cbf941778e`

---

## Verdict global

**INVITE_GO: NO-GO**

3 testeurs initiaux peuvent recevoir une invitation **sous condition que les HUMAN_REQUIRED listés ci-dessous soient résolus par le propriétaire avant l'envoi**. Les gates automatisées passent toutes.

---

## Gates automatisées (résultats locaux)

| Gate | Résultat | Détails |
|------|----------|---------|
| `ruff check .` | ✅ PASS | 0 erreur |
| `validate_local.py --quick` (14 checks) | ✅ PASS | All checks passed |
| `check_docs_truth.py` | ✅ PASS | DOCS_TRUTH_SYNC: true, PUBLIC_BETA_READY: false |
| `check_client_v1_usage.py` | ✅ PASS | 0 active /api/v1 calls Flutter |
| `tests/test_false_completed_regression.py` | ✅ PASS | 7/7 (incl. positive control) |
| `tests/core/evals/test_bea_eval_isolated.py` | ✅ PASS | 4/4 (75s, isolation SQLite corrigée) |
| `bea_eval --json --isolated` | ✅ PASS | 25/25, RC=0, ~19s |
| lock-drift (requirements.lock) | ✅ PASS | 44 direct pins alignés |
| mypy-delta-gate | ✅ PASS | 0 nouveaux erreurs vs baseline 870 |
| kernel-boundary ratchet | ✅ PASS | |
| security strict mypy | ✅ PASS | |
| coverage threshold | ✅ PASS | |

---

## PRs mergées dans cette session

| PR | Titre | Commit |
|----|-------|--------|
| #21 | deps: prometheus-client 0.19→0.25 | squash-merged |
| #60 | deps: pytest 9.0.3→9.1.1 | squash-merged |
| #116 | docs: synchronize private beta truth | `924c0f68` |
| #112 | fix(eval): stabilize bea_eval + completion truth gates | `25b98cde` |

---

## Completion Truth Gate (P0 — ne jamais régresser)

- `validate_coding_report()` wrapper : ✅ présent dans `core/coding_agent/artifact_validator.py`
- `.valid`/`.reason` property aliases : ✅ présents
- Régression test 1 (text-only sans artefact) : ✅ REJETÉ
- Régression test 2 (fichier Python invalide) : ✅ présent
- Régression test 3 (fichier manquant) : ✅ REJETÉ
- Régression test 4 (tests_run vides) : ✅ REJETÉ
- Régression test 5 (mission non-code sans artefact) : ✅ ACCEPTÉ
- Régression test 6 (provider_unavailable sans artefact) : ✅ REJETÉ
- Régression test 7 (rapport valide avec preuve py_compile) : ✅ ACCEPTÉ

**Invariant vérifié :** COMPLETED sans artefact vérifiable → rejeté. COMPLETED sans test_result structuré sur mission code → rejeté.

---

## Isolation bea_eval (fix supplémentaire)

- `_DEFAULT_DB` dans `operational_memory.py` était calculé à l'import (avant que `--isolated` change l'env var) → la BD réelle était verrouillée par Bea_API → echecs SQLite `database is locked`
- **Fix :** converti en `_default_db()` fonction, calculée à la création du store (call-time)
- Résultat : `--isolated` utilise maintenant un store SQLite temporaire dédié, sans conflit avec la BD de production

---

## PRs ouvertes restantes

| # | Titre | Action recommandée |
|---|-------|--------------------|
| 115 | DRAFT: bea upgrade tooling | Garder ouvert (DRAFT) |
| 95 | deps(py): runtime group 6 updates | Merger via GitHub UI après test venv |
| 94 | docs(flutter): validate v3 + APK rebuild | Merger via GitHub UI (docs only) |
| 93 | fix(scripts): Windows Unicode safety | Merger via GitHub UI (safe script fix) |
| 39 | flutter_secure_storage 9→10 (major) | HUMAN: flutter test + device test requis |
| 38 | flutter_local_notifications 17→21 (major) | HUMAN: flutter test + device test requis |
| 37 | web_socket_channel 2→3 (major) | HUMAN: flutter test + device test requis |
| 36 | stripe 8→15 (major) | HUMAN: audit call-sites requis |
| 20 | ci: codecov-action 3→7 | Merger via GitHub UI (CI action seulement) |
| 19 | ci: action-gh-release 2→3 | Merger via GitHub UI (CI action seulement) |
| 18 | ci: setup-buildx-action 3→4 | Merger via GitHub UI (CI action seulement) |

**Note :** PRs #18, #19, #20 touchent `.github/workflows/` → merger via GitHub web UI (token local sans scope `workflow`).

---

## HUMAN_REQUIRED (bloquants avant envoi)

Ces items ne peuvent pas être prouvés automatiquement et doivent être attestés par le propriétaire :

1. **Qdrant live privacy scan** : `python scripts/audit_memory_store.py --dry-run --privacy-scan --json` doit retourner 0 items privés sur la BD de production. Un scan précédent a trouvé 1 item privé (`bea:amour_unique`). À résoudre avant d'exposer la mémoire vectorielle aux testeurs.

2. **Rotation des secrets historiques** : tokens partagés, clés API en clair dans `.env`, credentials anciens — à révoquer/régénérer avant beta.

3. **Validation APK sur device physique** : mission UI (soumettre une mission depuis l'app Flutter, voir le statut live) et comportement offline/erreur réseau — non prouvés en l'état.

4. **RedisSessionStore pour multi-process** : si Bea_API tourne en mode multi-worker, le store de session doit être Redis et non in-process.

---

## Checklist NOT-YET avant envoi

- [ ] HUMAN: Qdrant privacy scan = 0 items privés
- [ ] HUMAN: Rotation secrets historiques
- [ ] HUMAN: APK validée sur device (mission UI + offline)
- [ ] HUMAN: RedisSessionStore si multi-worker
- [ ] OWNER: Merger PRs #18/#19/#20/#93/#94 via GitHub UI (safe, no major)
- [ ] OWNER: Décider de PRs #36/#37/#38/#39 (flutter/stripe majors)

---

## Ce qui est prouvé et prêt

- Completion truth gates : COMPLETED nécessite artefact vérifiable + test structuré
- bea_eval --isolated : reproductible (25/25, 2 runs = score identique, store isolé)
- 0 active Flutter /api/v1 calls
- Docs truth : PUBLIC_BETA_READY: false, HUMAN_REQUIRED documentés
- lock-drift : requirements.lock aligné
- ruff, mypy-delta, bandit-delta, kernel-boundary : propres
- BEA_CONTINUOUS_IMPROVEMENT non activé par défaut
- Pas de secrets dans les fichiers commités (gitleaks pass)

---

## Décision

**GO pour préparer les invitations.** Les 3 testeurs initiaux peuvent recevoir le guide tester une fois les 4 HUMAN_REQUIRED résolus par le propriétaire. Ne pas envoyer les invitations avant attestation de (1) Qdrant clean et (2) rotation secrets.

PUBLIC_BETA_READY: false — toujours vrai. Ce document confirme que les gates automatisées sont propres pour une beta privée technique supervisée.
