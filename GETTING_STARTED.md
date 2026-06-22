# Getting Started avec Béa

## Prérequis

- Python 3.11+
- Docker Desktop
- Git
- OpenRouter API key (`sk-or-v1-...`, compte gratuit suffisant)

## 1. Cloner le repo

```bash
git clone git@github.com:IA-optimist/Bea.git
cd Bea
```

## 2. Environnement Python

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

pip install -e .
```

## 3. Configuration .env

```bash
# Windows
copy .env.example .env

# Linux / macOS
cp .env.example .env
```

Éditer `.env` et renseigner au minimum :

```
OPENROUTER_API_KEY=sk-or-v1-...   # obligatoire
BEA_API_TOKEN=bea-...             # générer avec: python -c "import secrets; print(secrets.token_urlsafe(40))"
```

Optionnel (pour fallback local) :

```
OLLAMA_BASE_URL=http://127.0.0.1:11434
```

> **Important** : ne jamais committer `.env`. Il est gitignored.

## 4. Démarrer les services Docker

```bash
docker compose up -d
```

Vérifier que les conteneurs sont healthy :

```bash
docker ps --filter name=beamax
```

Attendu : `beamax-postgres`, `beamax-redis`, `beamax-qdrant` — status `healthy`.

## 5. Lancer le backend

```bash
# Mode développement
python scripts/run_api_local.py

# ou via le point d'entrée packaging
bea-api-local
```

Vérifier que l'API répond :

```bash
curl http://localhost:8000/api/v3/system/health
```

## 6. Valider l'installation

```bash
# Gate locale complète
python scripts/validate_local.py --quick

# Smoke E2E (sans LLM, sans Docker pour Qdrant)
python scripts/smoke_e2e_cycle.py --fixture sha256 --skip-bea-eval --json
```

Résultat attendu : `[OK] Bea E2E cycle smoke passed`

## 7. Vérifier les providers

```bash
# Benchmark mock (valide la logique sans appel réseau)
python scripts/benchmark_model_roles.py --mock --json

# Advisory depuis derniers résultats benchmark (si workspace/model_role_benchmark_multi_role.json existe)
python scripts/model_routing_advice.py --input workspace/model_role_benchmark_multi_role.json --json
```

## 8. Lancer une mission test

```bash
curl -X POST http://localhost:8000/api/v3/missions \
  -H "Authorization: Bearer $BEA_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "Ecris une fonction Python hello_world() qui retourne Hello World",
    "mode": "auto"
  }'
```

Récupérer le résultat :

```bash
curl http://localhost:8000/api/v3/missions/{mission_id} \
  -H "Authorization: Bearer $BEA_API_TOKEN"
```

## 9. Benchmark multi-rôle réel (optionnel)

Nécessite OpenRouter key valide et/ou Ollama actif.

```bash
python scripts/benchmark_model_roles.py \
  --real \
  --roles forge-builder,scout-research,shadow-advisor \
  --providers openrouter,ollama \
  --json \
  --output workspace/model_role_benchmark_multi_role.json
```

## Troubleshooting

Voir [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
