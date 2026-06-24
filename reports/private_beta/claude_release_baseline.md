# Béa — Claude Release Baseline
> Produit par: Claude Sonnet 4.6 (Release Manager)
> Date: 2026-06-24
> Branche: release/private-beta-0.1

## Commit de départ
`410452cf7000bb066e13c2029f2a84f798d65434`
Message: `chore(gate): beta-testable-gate — GO verdict, 3 minor fixes`

## Contexte Kilo+Kimi
Les 20 derniers commits montrent un travail de hardening auth/session consécutif.
Les branches liées à la bêta trouvées dans le repo :
- `beta/auth-session-hardening` (base des derniers merges)
- `claude/beta-release-packaging-versioning`
- `claude/beta-runtime-observability-lite`
- `claude/flutter-v3-apk-ci-and-v1-deprecation-plan`
- `claude/flutter-v3-apk-validation`
- `claude/flutter-v3-migration`
- `claude/stabilize-bea-eval-and-completion-truth-gates`

Historique récent (20 commits) — travail Kilo+Kimi identifiable :
- `410452c` chore(gate): beta-testable-gate — GO verdict, 3 minor fixes
- `185f413` fix(session): wire SessionStore into lifespan startup
- `fe606cb` merge(approval): fix/approval-queue-auth
- `3bfaa54` feat(ci): ratchets approval-audit-binding + policy-session-store
- `25766c5` fix(approval): replace hardcoded approved_by/rejected_by
- `f67b4c6` feat(policy): SessionStore abstraction — InMemory + Redis
- `3c678f8` docs(beta): identity/session store semantics
- `00ca25b` merge(policy+mission): principal auth binding + submitted_by
- `39c501c` fix(mission+auth): consolidate principal binding pipeline
- `4ccc53c` fix(mission): add submitted_by field

## Preuves VALIDES trouvées

| Preuve | Source |
|--------|--------|
| `validate_local.py --quick` : 14/14 PASS | Lancé en live |
| `release_check.py` : PASS, version 0.1.0-dev-preview | Lancé en live |
| `check_client_v1_usage.py` : 0 active /api/v1 calls (Flutter uses /api/v3) | Lancé en live |
| `check_policy_principal_binding.py` : 24 call sites, 0 gaps | Lancé en live |
| `check_tool_executor_mission_id.py` : 6 call sites, 0 gaps | Lancé en live |
| `ruff check .` : All checks passed | Lancé en live |
| `seed_bea_memory.py --report --profile public` : public_safe=True | Lancé en live |
| `.env.example` : aucun secret réel | Vérifié |
| `README_PUBLIC_BETA.md` : aucune claim "production ready" | Vérifié |
| `.github/ISSUE_TEMPLATE/` : 4 templates (bug_report, beta_feedback, incident_report, security_report) | Vérifié |
| `tests/test_release_check.py` + `test_public_beta_docs_consistency.py` + `test_beta_ratchets.py` : 121 PASS | Lancé en live |
| Pytest full suite: 3451 passed, 375 skipped, 4 xfailed, 1 failed (voir ci-dessous) | Lancé en live (10 min) |

## Corrections appliquées sur cette branche

| Fix | Commit | Impact |
|-----|--------|--------|
| `.env.example` : ajout référence à `.env.example.local` et `.env.example.production` | Sur branche | Test `test_env_example_points_to_templates` : FAIL→PASS |
| `README_PUBLIC_BETA.md` : remplacement "Pas de rate-limiting" par "Rate-limiting intégré" | Sur branche | Test `test_readme_does_not_say_rate_limiting_missing` : FAIL→PASS |
| `kernel/contracts/mission_runner.py` : ajout `submitted_by` et `principal_id` au Protocol | Sur branche | Test `test_meta_orchestrator_signature_unchanged` : FAIL→PASS |
| `tests/test_mission_runner_protocol.py` : mise à jour `_EXPECTED_PARAMS` | Sur branche | Cohérent avec l'ajout au Protocol |

## Preuves MANQUANTES

| Élément | État | Impact |
|---------|------|--------|
| APK validée sur device physique | HUMAN_REQUIRED — pas de device branché | WARNING pour private beta |
| `audit_memory_store.py` sur Qdrant live | Lancé — 1 item privé détecté (fun_fact romantique) | WARNING |
| CI flutter_apk run réelle | Flutter hors PATH shell local — dépend de GitHub Actions | WARNING |
| `bandit` + `pip-audit` JSON baselines | Requièrent artefacts CI — non générés localement | INFO |
| Rotation des secrets historiques | Action propriétaire humaine requise | HUMAN_REQUIRED |

## Ce qui BLOQUE une bêta privée

Aucun vrai BLOCKER détecté après corrections. Les 3 tests qui échouaient ont été corrigés.

## Ce qui BLOQUE seulement une bêta PUBLIQUE

- APK v3 non validée sur device physique → flutter est "supported experimental"
- `audit_memory_store` : 1 item privé dans le store live (hors public seed) → à nettoyer avant expo publique
- Rate-limiting actif mais sans reverse proxy TLS → ne pas exposer sur internet public
- Secrets historiques à rotation complète (action propriétaire)
- Memory Qdrant : duplicats détectés (non bloquants pour beta privée)
- `InMemorySessionStore` (dev) → passer à `RedisSessionStore` en beta

## Ce qui nécessite une ACTION HUMAINE

1. **Rotation des secrets historiques** (tokens BEA_API_TOKEN, BEA_ADMIN_PASSWORD, JWT key) — hors repo
2. **Validation APK sur Pixel 7 ou autre Android** — device physique requis
3. **Nettoyage memory item privé** (`ecdaea85-db3` : "Fun fact romantique sur Max") via `audit_memory_store.py --apply`
4. **Invitation effective des testeurs** — ne pas committer les adresses email / tokens testeurs
5. **Passage à RedisSessionStore** pour le déploiement bêta (actuellement InMemorySessionStore en dev)
