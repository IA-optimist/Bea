# Bea — AI orchestration monorepo

Repo principal du projet **Bea** (IA-optimist), avec backend Python, noyau d’orchestration, API, agents, sécurité, mobile/web, et outillage CI/CD.

## Ce que contient ce repo

- `core/` — logique métier principale
- `kernel/` — cœur d’orchestration et contrats
- `api/` — endpoints FastAPI
- `agents/` — agents et bridges
- `security/` — politiques et audit
- `tests/` — tests unitaires/intégration
- `.github/workflows/` — CI GitHub Actions
- `scripts/` — scripts d’exploitation
- `orchestrate-cli/`, `orchestrate-mobile/`, `frontend/`, `mobile/` — couches produit

## Prérequis

- Python 3.12 recommandé
- pip à jour
- (Optionnel local complet) PostgreSQL + Redis si tu veux reproduire l’environnement CI

## Démarrage rapide (local)

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## CI local reproductible (P0)

Le repo fournit maintenant une exécution locale alignée CI:

```bash
bash scripts/ci/local_ci.sh
```

Ce que fait `scripts/ci/local_ci.sh`:

- installe les dépendances runtime + test
- lance `ruff check .` (bloquant)
- lance `pytest tests/ -n auto --dist=loadfile`
- applique la même gate couverture que CI: `--cov-fail-under=55`

Variables d’environnement (avec valeurs par défaut compatibles local):

- `DATABASE_URL` (default: `postgresql://bea:***@localhost:5432/beamax_test`)
- `REDIS_URL` (default: `redis://localhost:6379`)
- `TESTING` (default: `true`)

## CI GitHub (résumé)

Workflows principaux:

- `.github/workflows/ci.yml` — gitleaks + lint + tests + couverture
- `.github/workflows/unit.yml` — sanity multi-OS
- `.github/workflows/kernel_ci.yml` — règles architecture kernel

## Hardening GitHub (plan-gated)

Une partie du hardening (branch protection/rulesets privés) dépend du plan GitHub.

Après upgrade, appliquer en une commande:

```bash
bash scripts/github/apply_p2_repo_hardening.sh IA-optimist/Bea main
```

Référence:

- `docs/security/p2-hardening-status.md`
- `scripts/github/apply_p2_repo_hardening.sh`

## Commandes utiles

```bash
# Lancer la CI locale complète
bash scripts/ci/local_ci.sh

# Tests seuls (sans lint)
bash scripts/ci/local_tests_only.sh

# E2E Playwright
npm run test:e2e
```

## Contribution

- Voir `CONTRIBUTING.md`
- Convention de commit recommandée: Conventional Commits
