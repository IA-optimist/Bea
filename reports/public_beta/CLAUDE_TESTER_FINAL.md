# Claude Public Beta Tester Final Report

Generated: 2026-06-27
Tester: Claude Sonnet 4.6 (external tester role)
Repo: IA-optimist/Bea

---

## Verdict

```
PUBLIC_BETA_CANDIDATE: false
PUBLIC_BETA_READY: false
INVITE_MORE_PRIVATE_TESTERS: true
INVITE_PUBLIC_USERS: false
```

**Justification**: 1 P1 blocker actif (Qdrant `ecdaea85-db3`), 2 P2 tests stale à corriger, 2 P2 API/auth à documenter/patcher. La base technique est solide (99.87% tests passent, gates automatiques toutes vertes, auth correcte, completion truth opérationnelle). Après résolution des blockers listés, le statut passerait à `PUBLIC_BETA_CANDIDATE: true`.

---

## Commit tested

`c7da42c9d20f4f12d7c830f7cf44322d63e843a9` (local main post-merge PRE_INVITE_CHECK)
GitHub HEAD: `25b98cde` (fix eval isolation + completion truth gates)

---

## Summary

- **8 bugs trouvés** (0 P0, 1 P1, 4 P2, 3 P3)
- **8 failures pytest** (0 P0/P1, 4 P2, 4 P3)
- **Gates automatiques**: toutes vertes (validate_local, ruff, check_docs_truth, private_beta_gate)
- **Completion truth**: opérationnelle (25/25 evals, 7/7 regression tests, 4/4 isolated)
- **Auth/token**: correct côté serveur (principal non injectable), token URL cockpit P2
- **Rate limiting**: en place, tests stale
- **Mémoire/privacy**: 1 item privé persistant (P1 BLOCKER)
- **Android**: non validé sur device (HUMAN_REQUIRED, bloquant public beta)

---

## Gates

| Gate | Result |
|------|--------|
| check_docs_truth | ✅ PASS — DOCS_TRUTH_SYNC: true, PUBLIC_BETA_READY: false |
| private_beta_gate | ✅ PASS — private_beta_ready: true, public_beta_ready: false |
| validate_local --quick | ✅ PASS — 14/14 checks |
| ruff | ✅ PASS — 0 erreur |
| pytest full | ⚠️ 8 failed / 6091 passed (99.87%) |
| bea_eval --isolated | ✅ PASS — 25/25, 0 failed |
| completion truth | ✅ PASS — 7/7 regression tests |
| memory privacy | ❌ FAIL — 1 item privé ecdaea85-db3 |
| auth/token | ⚠️ Token dans URL cockpit (P2) |
| rate limit | ⚠️ 4 tests stale (fonctionnel mais non testé) |
| sprint3 agent coder | ⚠️ 2 fails P3 (ranking drift, non bloquant) |
| stabilization final | ⚠️ 1 fail P2 (whitelist stale, à corriger) |
| Android APK | ❌ HUMAN_REQUIRED — device physique requis |

---

## Bugs found

| ID | Severity | Area | Description | Repro | Blocks public beta? |
|----|----------|------|-------------|-------|---------------------|
| BUG-MEM-1 | P1 | Memory | Qdrant item privé `ecdaea85-db3` "Fun fact romantique sur Max" toujours présent | `audit_memory_store.py --dry-run --privacy-scan --json` | OUI |
| BUG-API-1 | P2 | API | Mission submit bloque 30+ secondes (synchrone) | POST /api/v3/missions + chronomètre | Non bloquant mais risque DoS |
| BUG-API-2 | P2 | API | Goal null / 10k chars timeout sans erreur rapide | `{"goal": null}` ou `{"goal": "A"*10000}` | Non bloquant mais UX mauvaise |
| BUG-AUTH-2 | P2 | Auth/Cockpit | Token dans URL `/cockpit.html?token=X` accepté (logs, history) | `curl "http://127.0.0.1:8000/cockpit.html?token=REPLACE_ME"` → 200 | Non bloquant si doc/fix |
| BUG-RL-1 | P2 | Tests | 4 tests rate_limit_config stale (RATE_LIMIT_ENABLED manquant) | `pytest tests/test_rate_limit_config.py` | Non (fonctionnel mais non testé) |
| BUG-STAB-1 | P2 | Tests | test_no_report_files_at_root: whitelist root .md stale | `pytest tests/test_stabilization_final.py::TestDocumentation::test_no_report_files_at_root` | Oui si gate finale |
| BUG-SPRINT3-1 | P3 | Tests | Repo map ranking drift: ranked[0]="RepoMapService.build" ≠ "build_repo_map" | `pytest tests/test_sprint3_agent_coder.py` | NON |
| BUG-SCHED-1 | P3 | Tests | test_scheduler_connector: scheduler plein (50/50 tasks) en env prod | `pytest tests/test_operating_final.py::test_scheduler_connector` | NON |

---

## P0 blockers

*Aucun.*

---

## P1 blockers

* **BUG-MEM-1**: Item privé Qdrant `ecdaea85-db3` ("Fun fact romantique sur Max") persistant dans la BD live. Un testeur ayant accès à la mémoire pourrait lire ce contenu personnel. HUMAN_REQUIRED: `python scripts/audit_memory_store.py --apply --privacy-scan`.

---

## P2 bugs

1. **BUG-API-1**: Mission submit synchrone (30+s). Impact UX majeur + vecteur DoS. Fix: rendre le submit réellement async (202 immédiat + polling).
2. **BUG-API-2**: Goal null/10k chars timeout. Fix: ajouter validation Pydantic `goal: str = Field(..., min_length=1, max_length=5000)`.
3. **BUG-AUTH-2**: Token cockpit dans URL. Fix: ajouter `history.replaceState` dans cockpit.html après lecture `?token=`.
4. **BUG-RL-1**: 4 tests rate_limit stale. Fix: mettre à jour les tests pour tester le `limiter` configuré au lieu de `RATE_LIMIT_ENABLED`.
5. **BUG-STAB-1**: whitelist root .md stale. Fix: ajouter README_PUBLIC_BETA.md, PUBLIC_BETA_CHECKLIST.md, etc. à la whitelist.

---

## P3 improvements

1. **Doc install**: `pip install -e .` ≠ `pip install -r requirements.txt`. Ajouter la commande correcte dans TESTER_QUICKSTART.md.
2. **Doc OS**: Quickstart utilise `copy` (Windows-only). Préciser l'OS ou utiliser une commande cross-platform.
3. **Redaction courte**: Tokens < 40 chars non redactés (comportement documenté). Documenter la limite dans le guide tester.
4. **Ranking drift**: `test_repo_map` attend le 1er résultat exact. Assouplir l'assertion.
5. **Scheduler test**: isolation manquante dans `test_scheduler_connector`. Ajouter un mock du scheduler.
6. **Token exemple**: `.env.example` utilise `REPLACE_ME` (10 chars, devinable). Recommander un token généré automatiquement.

---

## Human required

* **Qdrant cleanup**: `python scripts/audit_memory_store.py --apply --privacy-scan` → supprimer ecdaea85-db3 (**bloquant P1**)
* **Secrets rotation**: Prouver que les tokens historiques (Telegram, OpenRouter, Codex) sont révoqués ou non exposés
* **Android physical validation**: Mission UI + offline sur device physique (**bloquant pour public beta**)
* **RedisSessionStore**: Configurer Redis avant tout test multi-worker
* **Tester tokens**: Émettre des tokens uniques par testeur (pas partager le token admin)

---

## Recommended next patches

Pour atteindre `PUBLIC_BETA_CANDIDATE: true`:

1. **Fix P1 (HUMAN)**: Nettoyer Qdrant ecdaea85-db3
2. **Fix P2-STAB-1**: Mettre à jour whitelist `test_no_report_files_at_root` (trivial)
3. **Fix P2-COCKPIT**: Ajouter `history.replaceState` dans cockpit.html  
4. **Fix P2-API-2**: Validation Pydantic `goal` (min_length=1, max_length=5000)
5. **Fix P2-RL**: Mettre à jour tests rate_limit pour le module actuel
6. **HUMAN**: Android device test
7. **HUMAN**: Rotation secrets
8. **Fix P3-SPRINT3**: Assouplir assertion ranking repo_map
9. **Fix P3-SCHED**: Isolation scheduler dans test_operating_final

---

## Suggested GitHub issues

### Issue 1 — [BUG][P1] Qdrant private item ecdaea85-db3 persists in live store
- **Labels**: `bug`, `privacy`, `P1`, `blocker`
- **Description**: The audit scan consistently finds item `ecdaea85-db3` ("Fun fact romantique sur Max") in the live Qdrant store. This private item must be removed before any wider beta release.
- **Repro**: `python scripts/audit_memory_store.py --dry-run --privacy-scan --json`
- **Expected**: 0 private items
- **Actual**: 1 private item found
- **Fix**: Run `--apply` mode or manual Qdrant delete

### Issue 2 — [BUG][P2] Mission submit endpoint is synchronous (~30s)
- **Labels**: `bug`, `api`, `performance`, `P2`
- **Description**: POST /api/v3/missions blocks for 30+ seconds before returning 201. Should return 202 immediately.
- **Repro**: `time curl -X POST .../api/v3/missions -d '{"goal":"ping"}'`
- **Expected**: 202 Accepted in < 1s
- **Actual**: 201 Created after ~30s

### Issue 3 — [BUG][P2] Cockpit: token in URL not cleaned (no history.replaceState)
- **Labels**: `security`, `ui`, `P2`
- **Description**: `/cockpit.html?token=X` works and leaves the token in the URL, browser history, and server logs.
- **Fix**: Add `history.replaceState(null, '', '/cockpit.html')` after reading `?token` param.

### Issue 4 — [BUG][P2] test_rate_limit_config.py: 4 tests fail (RATE_LIMIT_ENABLED missing)
- **Labels**: `test`, `tech-debt`, `P2`
- **Description**: 4 tests check `rlm.RATE_LIMIT_ENABLED` which no longer exists. Rate limiting works but tests are stale.
- **Fix**: Rewrite tests to check `rlm.limiter` configuration instead.

### Issue 5 — [BUG][P2] test_stabilization_final: root .md whitelist outdated
- **Labels**: `test`, `docs`, `P2`
- **Description**: Beta docs added since the test was written (README_PUBLIC_BETA.md, PUBLIC_BETA_CHECKLIST.md, etc.) are not in the whitelist.
- **Fix**: Add the 6 beta doc files to ALLOWED_ROOT_MD set.

### Issue 6 — [BUG][P3] Goal validation: null/large goals timeout instead of 400
- **Labels**: `api`, `validation`, `P3`
- **Description**: `{"goal": null}` and `{"goal": "A"*10000}` timeout instead of returning 400 quickly.
- **Fix**: Add Pydantic field validation `goal: str = Field(..., min_length=1, max_length=5000)`.

---

## Final recommendation

**NO-GO public beta.**

Blockers actifs:
1. **P1**: Qdrant private item (`ecdaea85-db3`) dans la BD live — risque privacy inacceptable
2. **HUMAN**: Android physical device validation non prouvée
3. **HUMAN**: Rotation secrets non prouvée

**GO pour inviter 3-5 testeurs privés supplémentaires** (au total 6-8 testeurs techniques) APRÈS:
1. Nettoyage Qdrant (HUMAN)
2. Fix whitelist test_stabilization_final (trivial, 5 minutes)
3. Documentation explicite "token dans URL = dev-only" dans le Quickstart

La base technique est excellente : 99.87% tests passent, auth solide, completion truth opérationnelle, rate limiting en place, docs vérité en ordre. Les bugs restants sont tous adressables sans refactoring majeur.

`PUBLIC_BETA_CANDIDATE: false` → deviendra `true` après les 3 actions ci-dessus + Android validé.
