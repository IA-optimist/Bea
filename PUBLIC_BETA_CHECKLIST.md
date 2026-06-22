# Béa — Public Beta Readiness Checklist

> Évaluation au 2026-06-22. Recommandation : **Developer Preview** (pas encore Public Beta stable).

## Go / No-Go par critère

### Installation

| Critère | Statut | Notes |
|---------|:------:|-------|
| `git clone` + `pip install -e .` | ✅ | `pyproject.toml` OK |
| `.env.example` présent et à jour | ✅ | Champs Béa présents |
| `docker compose up -d` démarre | ✅ | beamax-postgres / redis / qdrant healthy |
| `bea-api-local` répond sur :8000 | ✅ | `/api/v3/system/health` 200 |

### Provider

| Critère | Statut | Notes |
|---------|:------:|-------|
| OpenRouter key valide | ✅ | `sk-or-v1-...` 73 chars |
| OpenRouter forge-builder PASS | ✅ | score 1.0 |
| Ollama optionnel documenté | ✅ | scout-research OK, autres rôles KO |
| Provider indisponible → skipped, pas crash | ✅ | Tests 117/117 |

### Smoke / Validation

| Critère | Statut | Notes |
|---------|:------:|-------|
| `smoke_e2e_cycle --fixture sha256` | ✅ | `[OK]` |
| `bea_eval --json` | ✅ | 25/25 (1.0) |
| `benchmark_model_roles --mock` | ✅ | 6/6 score 1.0 |
| `validate_local --quick` | ✅ | All checks passed |

### Dogfood & Advisory

| Critère | Statut | Notes |
|---------|:------:|-------|
| 5 missions dogfood fixture | ✅ | 4/5 passed |
| `routing_advisor` génère recommandations | ✅ | runtime_enforced=false |
| `dogfood_routing_advice.py` stable | ✅ | mode=fixture, 117 tests |

### APK Mobile

| Critère | Statut | Notes |
|---------|:------:|-------|
| Flutter utilise /api/v3 uniquement | ✅ | grep : 0 appel /api/v1 dans lib/ |
| Build APK release exécuté en CI | ⚠️ | Non validé en CI — build manuel OK |
| APK testée sur device réel | ⚠️ | Pixel 7 (User 11), validée manuellement |
| `_V1_ALLOWLIST` vide | ✅ | `tests/test_client_v1_allowlist.py` garde |

### Sécurité

| Critère | Statut | Notes |
|---------|:------:|-------|
| Aucun secret dans les docs | ✅ | grep : 0 clé exposée |
| `BEA_CONTINUOUS_IMPROVEMENT` désactivé par défaut | ✅ | opt-in uniquement |
| `runtime_enforced=false` invariant | ✅ | Tests 117/117 |
| `BEA_SKIP_IMPROVEMENT_GATE` documenté comme dangereux | ✅ | SECURITY_MODEL.md |
| Rate-limiting API | ✅ | slowapi 60/min (BEA_RATE_LIMIT_PER_MINUTE), Redis en prod |
| CORS configuré (pas wildcard) | ✅ | BEA_CORS_ORIGINS, jamais wildcard+credentials, fail-hard en prod |
| Auth 2FA cockpit admin | ❌ | Pas implémenté |

### Documentation

| Critère | Statut | Notes |
|---------|:------:|-------|
| `README_PUBLIC_BETA.md` | ✅ | Ce release |
| `GETTING_STARTED.md` | ✅ | Ce release |
| `SECURITY_MODEL.md` | ✅ | Ce release |
| `TROUBLESHOOTING.md` | ✅ | Ce release |
| `docs/MODEL_ROUTING.md` | ✅ | Advisory + benchmark documentés |
| `docs/DOGFOODING_REPORT.md` | ✅ | 5 missions + matched_advice |
| `docs/ALPHA_READINESS.md` | ✅ | À jour |

### CI / Checks

| Critère | Statut | Notes |
|---------|:------:|-------|
| Ruff sur PR | ⚠️ | CI locale seulement (pas GitHub Actions) |
| Pytest sur PR | ⚠️ | CI locale seulement |
| Smoke enforced sur PR | ❌ | Non configuré |
| Benchmark réel en CI | ❌ | Trop lent / coûteux pour CI |

## Blockers restants pour Public Beta

1. ~~**Rate-limiting API**~~ ✅ Résolu — slowapi + BEA_RATE_LIMIT_PER_MINUTE
2. ~~**CORS**~~ ✅ Résolu — BEA_CORS_ORIGINS, pas de wildcard, fail-hard prod
3. **CI GitHub Actions** — smoke + pytest sur chaque PR
4. **APK build CI** — valider APK v3 automatiquement
5. **Audit endpoints v1 serveur** — lister et dater la dépréciation planifiée

## Recommandation

**Developer Preview** — prêt pour des testeurs identifiés avec supervision.

Pas encore **Public Beta stable** en raison des blockers CI.

Prochaine milestone : CI GitHub Actions smoke → passer en Beta.
