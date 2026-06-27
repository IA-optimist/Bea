# Claude Public Beta Tester — Baseline (PHASE 0)

Generated: 2026-06-27
Tester role: external beta tester (not principal developer)

## Commit testé

`c7da42c9d20f4f12d7c830f7cf44322d63e843a9` (HEAD local = merge + PRE_INVITE_CHECK)
Main GitHub HEAD au moment du test: `25b98cde` (fix eval isolation + completion truth)

## Environnement

| Élément | Valeur |
|---------|--------|
| OS | Windows 11 Home 10.0.26200 |
| Python | 3.11.15 (Hermes venv) |
| Python executable | `C:\Users\maxen\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe` |
| Node.js | v24.14.0 |
| Flutter | Non disponible sur PATH bash (installé à `C:\flutter` mais hors scope ce test) |
| Branche test | `test/public-beta-candidate-claude` |

## Gates baseline

| Gate | Résultat |
|------|----------|
| `check_docs_truth.py` | ✅ PASS — DOCS_TRUTH_SYNC: true, PUBLIC_BETA_READY: false |
| `private_beta_gate.py --json` | ✅ PASS — private_beta_ready: true, public_beta_ready: false |
| `validate_local.py --quick` | ✅ PASS — 14/14 checks passed |
| `ruff check .` | ✅ PASS — 0 erreur |
| `pytest -q` (complet) | ⚠️ 8 failed / 6091 passed / 761 skipped / 6 xfailed (13m39s) |

## Fichiers docs suivis

- `README.md` ✅ présent
- `README_PUBLIC_BETA.md` ✅ présent — PUBLIC_BETA_READY: false confirmé
- `docs/TESTER_QUICKSTART.md` ✅ présent
- `PUBLIC_BETA_CHECKLIST.md` ✅ présent
- `docs/ALPHA_READINESS.md` ✅ présent
- `.env.example` ✅ présent (token placeholder = `REPLACE_ME`)

## État connu des tests

### Failures identifiées (8 total)

| Fichier test | Failure | Catégorie | Bloque beta? |
|-------------|---------|-----------|--------------|
| `test_rate_limit_config.py` x4 | `RATE_LIMIT_ENABLED` attribut manquant dans le module | P2 — test stale | Non (rate limiting fonctionne) |
| `test_sprint3_agent_coder.py::test_repo_map*` | ranking retourne `RepoMapService.build` ≠ `build_repo_map` | P3 — drift ranking | Non (feature fonctionne) |
| `test_sprint3_agent_coder.py::test_swe_lite*` | score 0.922 < 1.0 (cascade du ranking) | P3 | Non |
| `test_stabilization_final.py::test_no_report_files_at_root` | whitelist root .md non mise à jour (RELEASE_NOTES.md, README_PUBLIC_BETA.md, etc.) | P2 | Oui si test = gate |
| `test_operating_final.py::test_scheduler_connector` | Max scheduled tasks reached (50) — scheduler plein en production | P3 — env-specific | Non (isolation manquante) |

### Résumé: 0 P0, 0 P1 test-related, 2 P2, 3 P3

## Risques connus avant test

1. **Qdrant live**: item privé `ecdaea85-db3` (Fun fact romantique sur Max) toujours présent → P1 pour public beta
2. **Secrets**: token de test = `REPLACE_ME` (10 chars) dans .env.example — facilement devinable
3. **Android**: APK non validée sur device physique (mission UI + offline)
4. **RedisSessionStore**: non configuré, in-memory uniquement

## Actions humaines encore listées dans la doc

1. HUMAN_REQUIRED: clean Qdrant live memory item ecdaea85-db3
2. HUMAN_REQUIRED: rotate historical/shared secrets
3. HUMAN_REQUIRED: validate Android mission UI on physical device
4. HUMAN_REQUIRED: validate Android offline/network-failure on physical device
5. HUMAN_REQUIRED: issue per-tester tokens without committing them
6. HUMAN_REQUIRED: use RedisSessionStore for multi-process or multi-worker testing
