# Troubleshooting Béa

## OpenRouter key invalide ou tronquée

**Symptôme** : missions échouent avec `error_category: "auth_error"` ou 401.

**Diagnostic** :
```bash
python -c "
import os; from dotenv import load_dotenv; load_dotenv()
k = os.getenv('OPENROUTER_API_KEY','')
print(f'len={len(k)} prefix={k[:10]}')
"
```

**Fix** : la clé doit commencer par `sk-or-v1-` et faire 73+ caractères.
Vérifier dans `.env` que la clé n'est pas tronquée ou entourée de quotes.

## Ollama non joignable

**Symptôme** : `fallback_used=true` ou timeout sur les missions, `skipped=true` dans le benchmark.

**Diagnostic** :
```bash
curl http://127.0.0.1:11434/api/tags
ollama list
```

**Fix** : lancer `ollama serve`, puis `ollama pull gemma4:12b` si le modèle manque.

> Ollama est **optionnel** — OpenRouter est le provider primaire recommandé.

## Unicode / accents dans les chemins (Windows)

**Symptôme** : erreurs d'encodage lors du build Flutter ou des scripts Python.

**Fix** : travailler depuis un chemin sans accents.
Exemple : `C:\Users\maxen\Documents\Béa` → copier dans `C:\bea_app`.

## Docker Desktop ne démarre pas

**Symptôme** : `docker ps` échoue, backend Béa ne peut pas joindre Postgres/Redis/Qdrant.

**Fix** :
1. Vérifier que Docker Desktop est démarré (icône dans la barre système)
2. Si `EnableDockerAI` cause un crash : `settings-store.json` → `"EnableDockerAI": false`
3. Relancer Docker Desktop, puis `docker compose up -d`

## Provider indisponible dans le benchmark

**Symptôme** : résultats avec `skipped=true` dans le JSON benchmark.

**Comportement attendu** : le benchmark skippe proprement sans crasher.
`skipped=true` ≠ modèle mauvais — le provider était simplement injoignable.

## APK Flutter et /api/v1

**Symptôme** : l'APK fait des appels `/api/v1` ou reçoit des erreurs 404.

**Diagnostic** :
```bash
grep -r "api/v1" beamax_app/lib/ --include="*.dart" | grep -v "_V1_ALLOWLIST\|//"
```

**Statut actuel** : 0 appel `/api/v1` dans le code Flutter — l'APK utilise `/api/v3`.
Le serveur maintient `/api/v1` pour compatibilité descendante jusqu'à validation APK complète.

## Smoke E2E qui échoue

**Commande de diagnostic** :
```bash
python scripts/smoke_e2e_cycle.py --fixture sha256 --skip-bea-eval --json
```

**Causes fréquentes** :
- Venv non activé → `source .venv/bin/activate`
- `pytest` non installé → `pip install -e .`
- Qdrant injoignable → `docker compose up -d beamax-qdrant`

## Ruff ou pytest qui échouent

```bash
# Ruff : auto-fix
python -m ruff check . --fix

# Pytest : debug verbose
python -m pytest tests/ -q --tb=short -x
```

## Mémoire Qdrant vide après redémarrage

**Symptôme** : missions sans contexte mémoriel, scores de recall à 0.

**Cause** : Docker volume Qdrant non persistant ou conteneur recréé.

**Fix** : vérifier que `beamax-qdrant` est healthy et que le volume persiste :
```bash
docker volume ls | grep qdrant
docker inspect beamax-qdrant | grep Mounts -A 10
```

## validate_local --quick échoue

```bash
python scripts/validate_local.py --quick 2>&1 | tail -20
```

Lire le message d'erreur : généralement un import manquant ou un test cassé.
Relancer `pip install -e .` puis réessayer.

## Score Ollama bas sur forge-builder ou shadow-advisor

**Comportement connu** : `gemma4:12b` ignore les section markers `=== sha256_file.py ===`
(artifact_invalid) et enveloppe le JSON dans du markdown (json_invalid).

**Recommandation** : utiliser OpenRouter pour ces deux rôles.
Ollama reste acceptable pour scout-research (score 1.0 dans le benchmark).

## Erreur CORS (browser)

**Symptôme** : `Access to fetch at 'http://...' from origin '...' has been blocked by CORS policy`

**Cause** : L'origin du client n'est pas dans la liste autorisée.

**Fix** :
```bash
# Dev local — vérifier que l'origin est dans les defaults :
# http://localhost:3000, http://localhost:8000, http://127.0.0.1:8000

# Pour ajouter une origin :
export BEA_CORS_ORIGINS="http://localhost:3000,http://localhost:4200"

# Production :
export BEA_CORS_ORIGINS="https://app.example.com,https://admin.example.com"
```

**Important** : Ne jamais mettre `BEA_CORS_ORIGINS=*` — le système remplace automatiquement
par les localhost defaults si `*` est détecté.

## Rate limit 429 Too Many Requests

**Symptôme** : API retourne `{"detail": "Too many requests..."}` avec status 429

**Cause** : Plus de `BEA_RATE_LIMIT_PER_MINUTE` (défaut: 60) requêtes/IP/minute.

**Fix dev/test** :
```bash
# Désactiver le rate limit en dev :
export BEA_RATE_LIMIT_ENABLED=false

# Ou augmenter la limite :
export BEA_RATE_LIMIT_PER_MINUTE=200
```

**Note** : Le header `Retry-After: 60` indique combien de secondes attendre.
Les endpoints `/health` et `/api/v3/system/health` sont exemptés du rate limit.
