# Béa — Beta Incident Runbook

> Pour l'owner. Procédures rapides en cas de problème pendant la bêta privée.

---

## Kill switch — Arrêt immédiat de l'API

```bash
# Windows PowerShell
Stop-Process -Name python -Force

# Windows cmd
taskkill /F /IM python.exe

# Linux / WSL
pkill -f run_api_local.py
# ou
pkill -f "uvicorn"
```

Vérifier l'arrêt :
```bash
curl http://localhost:8000/health
# Connection refused = API arrêtée
```

---

## Désactiver self-improvement

Dans `.env`, s'assurer que :
```bash
BEA_CONTINUOUS_IMPROVEMENT=0   # ou commenté
# BEA_SKIP_IMPROVEMENT_GATE    # ne jamais décommenter
```

Puis redémarrer l'API. La boucle d'amélioration ne se relancera pas.

---

## Couper un token testeur

```bash
JWT=$(curl -s -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "votre-BEA_ADMIN_PASSWORD"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Lister les tokens
curl http://localhost:8000/api/v3/admin/tokens -H "Authorization: Bearer $JWT"

# Révoquer
curl -X DELETE http://localhost:8000/api/v3/admin/tokens/{id} -H "Authorization: Bearer $JWT"
```

---

## Désactiver l'accès distant

Pour une instance Railway ou VPS :
1. Stopper le service Railway : `railway down` ou via le dashboard
2. Ou bloquer le port via pare-feu (iptables / Windows Firewall)
3. Pour Tailscale : désactiver la machine dans la console Tailscale

---

## Récupérer les logs redactés

```bash
# Logs locaux (si structlog → fichier)
cat logs/bea.log | grep -v "sk-or-v1-" | grep -v "Bearer "

# Redacter avant partage
sed 's/sk-or-v1-[A-Za-z0-9_-]*/sk-or-v1-[REDACTED]/g' logs/bea.log \
  | sed 's/Bearer [A-Za-z0-9._-]*/Bearer [REDACTED]/g' \
  > logs/bea_redacted.log
```

---

## Classification des incidents

| Niveau | Description | Action immédiate |
|--------|-------------|-----------------|
| **P0** | Secret leak / auth bypass / action destructive réelle | Arrêt API + rotation secrets + rapport dans l'heure |
| **P1** | Crash récurrent / contournement de policy / comportement non supervisé | Arrêt API + investigation + rapport dans 24h |
| **P2** | Bug fonctionnel / mission échouée / résultat incorrect | Note dans issue GitHub, pas d'urgence |
| **P3** | Docs incorrectes / UI cassée / UX mauvaise | Issue GitHub, priorisation normale |

---

## Ce qu'il faut demander au testeur (P0/P1)

- Commit hash exact (`git rev-parse --short HEAD`)
- Mission ID si visible
- Logs redactés (JAMAIS les logs bruts)
- Séquence d'actions exacte
- Provider et modèle utilisés
- OS et Python version

## Ce qu'il ne faut JAMAIS demander au testeur

- Votre token API complet
- Votre `.env`
- Des logs non redactés
- Des informations sur votre infrastructure personnelle

---

## Procédure de rollback

### Rollback API (version précédente)

```bash
git log --oneline -5        # Identifier le commit stable
git checkout {commit-sha}   # Revenir à ce commit
python scripts/run_api_local.py
```

### Rollback migration base de données

```bash
# Lister les migrations disponibles
python -m core.db.migrate --list

# Revenir à la migration N-1
python -m core.db.migrate --rollback
```

### Rollback complet (dernier recours)

```bash
docker compose down -v      # Supprimer les volumes (perte de données)
git checkout main
docker compose up -d
python -m core.db.migrate
python scripts/seed_bea_memory.py --profile public
python scripts/run_api_local.py
```

---

## Contacts et escalade

| Rôle | Contact |
|------|---------|
| Owner / Opérateur | Max (via Telegram ou email direct) |
| Testeur en difficulté | Issue GitHub avec template `incident_report` |
| Secret exposé | Rotation immédiate + issue security_report (PRIVATE) |
