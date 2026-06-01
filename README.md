# Bea — Plateforme d’orchestration IA (monorepo)

## Vue d’ensemble

Bea est une plateforme d’orchestration d’agents IA orientée production avec :
- un backend Python (API, moteur d’orchestration, sécurité, mémoire, observabilité),
- un frontend web,
- une application mobile,
- des composants d’intégration (MCP/connecteurs) et de monitoring.

Ce dépôt est un **monorepo actif** avec plusieurs domaines techniques et des sous-projets historiques encore présents.

---

## Structure réelle (racine)

Répertoires principaux observés dans ce repo :
- `api/` — endpoints et couches d’accès API
- `core/` — logique centrale (orchestration, policy, exécution, mémoire, sécurité)
- `business/`, `business_agents/` — logique métier et agents
- `agents/` — agents et orchestration auxiliaire
- `frontend/` — interface web
- `mobile/` — application mobile
- `mcp/`, `connectors/`, `integrations/` — intégrations externes
- `monitoring/`, `observability/` — métriques et observabilité
- `db/`, `migrations/`, `models/` — persistance et modèles
- `scripts/`, `tools/` — scripts d’exploitation
- `tests/` — suite de tests (large volume)
- `docs/` — documentation interne

> Note : des dossiers `orchestrate-cli/` et `orchestrate-mobile/` existent encore, mais ne représentent pas à eux seuls l’architecture actuelle globale.

---

## Prérequis

- Python 3.11+
- Node.js 18+
- Docker + Docker Compose (recommandé pour stack complète)
- Git

---

## Démarrage rapide (local)

## 1) Cloner

```bash
git clone https://github.com/IA-optimist/Bea.git
cd Bea
```

## 2) Environnement Python

```bash
python -m venv .venv
source .venv/Scripts/activate  # Git Bash sous Windows
pip install -r requirements.txt
# Optionnel mais conseillé pour reproductibilité:
# pip install -r requirements.lock
```

## 3) Frontend

```bash
cd frontend
npm install
cd ..
```

## 4) Mobile (optionnel)

```bash
cd mobile
npm install
cd ..
```

## 5) Lancer les services (option Docker)

```bash
docker compose up -d
```

---

## Tests & qualité

## Tests Python ciblés (rapides)

```bash
pytest -q tests/test_v1_invariants.py tests/test_tool_registry.py tests/test_policy_engine.py
```

## Collecte globale des tests

```bash
pytest --collect-only -q
```

> Si des erreurs de collection apparaissent (`ModuleNotFoundError`), synchroniser l’environnement avec les dépendances Python déclarées.

## Lint Python

```bash
ruff check .
```

---

## CI/CD

Workflows GitHub Actions clés :
- `.github/workflows/ci.yml` — scans secrets, tests, vérifications type/build
- `.github/workflows/deploy.yml` — pipeline de déploiement

---

## Sécurité

- Secrets et variables sensibles : utiliser exclusivement des variables d’environnement et fichiers `.env` non versionnés.
- Contrôles en place : hooks pré-commit (`gitleaks`, `detect-secrets`, etc.).
- Référence audit sécurité : `docs/SECURITY_AUDIT.md`.

---

## Contribution

1. Créer une branche (`feat/...`, `fix/...`, `docs/...`)
2. Faire des commits atomiques
3. Exécuter au minimum lint + tests ciblés
4. Ouvrir une Pull Request

---

## Statut documentation

Ce README a été réaligné avec la structure observée du monorepo. La documentation détaillée par sous-domaine doit être maintenue dans `docs/` et dans les README locaux des sous-projets (`frontend/`, `mobile/`, etc.).
