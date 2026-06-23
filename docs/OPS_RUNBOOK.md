# Béa — Ops Runbook

> Operational runbook for the Béa Developer Preview / Public Beta limitée.
> Written for a solo maintainer + technical testers.

---

## 1. Démarrage local

```bash
# 1. Activer l'environnement virtuel
source .venv/bin/activate          # Linux/macOS
.venv\Scripts\Activate.ps1         # Windows

# 2. Démarrer les dépendances Docker
docker compose up -d

# 3. Vérifier que Postgres, Redis, Qdrant sont "running"
docker compose ps

# 4. (Optionnel) Seeder la mémoire publique
python scripts/seed_bea_memory.py --profile public

# 5. Démarrer l'API
python scripts/run_api_local.py
```

## 2. Arrêt propre

```bash
# 1. Arrêter l'API (Ctrl+C dans le terminal)

# 2. Arrêter les conteneurs Docker
docker compose down

# 3. (Optionnel) Nettoyer les artifacts de test
rm -rf workspace/artifacts/*.py
```

**Ne jamais** faire `docker compose down -v` en production — cela supprime les volumes (données).

## 3. Vérifier la santé API

```bash
# Health check
curl -s http://localhost:8000/health | python -m json.tool
# Expected: {"status": "ok"}

# Auth check (remplacez $BEA_API_TOKEN)
curl -s -H "Authorization: Bearer $BEA_API_TOKEN" \
  http://localhost:8000/api/v3/missions | python -m json.tool | head -5
```

## 4. Vérifier la readiness bêta

```bash
# Valider tous les gates locaux
python scripts/validate_local.py --quick

# Vérifier le seed public
python scripts/seed_bea_memory.py --report --profile public

# Vérifier le privacy scan
python scripts/audit_memory_store.py --dry-run --privacy-scan --sample-duplicates 0 --json
```

Tous les checks doivent passer avant d'inviter des testeurs.

## 5. Lire les logs (redacted)

Les logs structurés sont dans `logs/`. Le redacteur (`core/observability/redactor.py`)
masque automatiquement les API keys, tokens, emails.

```bash
# Logs récents (dernières 50 lignes)
tail -50 logs/api.log

# Filtrer par mission_id
grep "mission_id" logs/api.log | tail -20

# Filtrer les erreurs
grep "ERROR" logs/api.log | tail -20

# Exporter un rapport sans données privées
grep -E "(mission_id|status|error_category|provider_used|duration_ms)" \
  logs/api.log > /tmp/bea_report.txt
# Vérifier qu'aucun secret n'est présent:
rg "sk-|Bearer [A-Za-z0-9]|password=" /tmp/bea_report.txt
```

Si un secret apparaît dans les logs, voir [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md).

## 6. Diagnostiquer une mission FAILED

```
Mission status: FAILED
├── error_category: artifact_invalid
│   → Le code généré a une syntax error
│   → Vérifier workspace/artifacts/ pour le fichier
│   → Si Ollama: switcher vers OpenRouter
├── error_category: json_invalid
│   → Le provider n'a pas retourné du JSON valide
│   → Vérifier le provider utilisé dans les logs
│   → Si Ollama gemma4:12b: switcher vers OpenRouter
├── error_category: timeout
│   → Le provider n'a pas répondu à temps
│   → Vérifier la connexion internet
│   → Augmenter MISSION_TIMEOUT si nécessaire
├── error_category: provider_error
│   → Le provider a retourné une erreur (429, 500, etc.)
│   → Vérifier la clé API
│   → Vérifier le statut du provider (status.openrouter.ai)
└── error_category: unknown
    → Consulter les logs complets
    → Ouvrir un incident si reproductible
```

## 7. Diagnostiquer provider unavailable

```bash
# Tester OpenRouter
curl -s -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  https://openrouter.ai/api/v1/models | python -m json.tool | head -5

# Tester Ollama
curl -s http://localhost:11434/api/tags | python -m json.tool | head -5

# Vérifier le statut OpenRouter
# https://status.openrouter.ai
```

Si OpenRouter est down:
- Configurer Ollama comme fallback dans `.env`
- Notifier les testeurs que la qualité peut baisser
- Documenter dans [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md)

## 8. Diagnostiquer rate-limit 429

Symptômes:
- `openrouter.RateLimitError: 429 Too Many Requests`
- Missions qui échouent en rafale

Actions:
1. Vérifier le plan OpenRouter (free tier = limites strictes)
2. Espacer les missions (attendre 60s entre chaque)
3. Configurer `BEA_RATE_LIMIT_PER_MINUTE` pour limiter en local
4. Si critique: passer sur un plan payant OpenRouter

## 9. Diagnostiquer CORS

Symptômes:
- Erreur `Access-Control-Allow-Origin` dans le navigateur
- Requêtes bloquées depuis le frontend

Actions:
```bash
# Vérifier la config CORS
grep BEA_CORS_ORIGINS .env

# Pour le dev local, autoriser localhost:
# BEA_CORS_ORIGINS=http://localhost:3000,http://localhost:8080

# Ne JAMAIS utiliser * en production
```

Voir [docs/SECURITY_MODEL.md](SECURITY_MODEL.md) pour la politique CORS.

## 10. Diagnostiquer APK / client mobile

**Note:** L'APK v3 n'est pas validé en CI. Ne pas rapporter les bugs APK
sauf si vous êtes sur le track mobile.

```bash
# Vérifier que l'API répond aux endpoints v3
curl -s -H "Authorization: Bearer $BEA_API_TOKEN" \
  http://localhost:8000/api/v3/missions | head -5

# Vérifier que les endpoints v1 sont encore présents (rollback Flutter)
curl -s -H "Authorization: Bearer $BEA_API_TOKEN" \
  http://localhost:8000/api/v1/missions | head -5
```

## 11. Checklist quotidienne bêta

- [ ] `curl http://localhost:8000/health` → `{"status": "ok"}`
- [ ] `docker compose ps` → tous les services "running"
- [ ] `grep "ERROR" logs/api.log | tail -5` → pas d'erreur nouvelle
- [ ] `python scripts/seed_bea_memory.py --report --profile public` → `public_safe: True`
- [ ] Vérifier les issues GitHub nouveaux → trier dans les 24h
- [ ] Vérifier le statut OpenRouter (https://status.openrouter.ai)
- [ ] Si des secrets ont été exposés → suivre [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md)
