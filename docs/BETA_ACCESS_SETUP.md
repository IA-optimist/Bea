# Béa — Beta Access Setup

> Guide pour l'owner : comment inviter 5–10 testeurs sans exposer de secrets.

---

## Architecture d'authentification

Béa supporte deux mécanismes d'auth :

1. **JWT admin** : login `admin` + `BEA_ADMIN_PASSWORD` → JWT (30 jours). Réservé à l'owner.
2. **Access tokens** (`jv-xxx`)  : tokens individuels par testeur. Gérés via `TokenManager`.

**Règle** : chaque testeur reçoit son propre access token. L'owner garde le JWT admin pour lui seul.

---

## Étape 1 — Activer l'auth

L'auth est active dès que `BEA_ADMIN_PASSWORD` est défini dans `.env`.

```bash
# Dans .env
BEA_ADMIN_PASSWORD=un-mot-de-passe-fort-ici  # Choisir 20+ caractères
BEA_SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
BEA_API_TOKEN=$(python -c "import secrets; print('bea-' + secrets.token_urlsafe(40))")
```

**Ne jamais committer ces valeurs.** `.env` est dans `.gitignore`.

Vérifier que `/health` est accessible sans auth et que `/api/v3/missions` retourne 401 sans token :
```bash
curl http://localhost:8000/health           # 200 sans auth — OK
curl http://localhost:8000/api/v3/missions  # 401 sans auth — OK
```

---

## Étape 2 — Créer un token pour un testeur

Via l'API (nécessite un JWT admin) :

```bash
# Obtenir le JWT admin
JWT=$(curl -s -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "votre-BEA_ADMIN_PASSWORD"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Créer un access token pour le testeur
curl -X POST http://localhost:8000/api/v3/admin/tokens \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"label": "testeur-alice", "role": "tester"}'
```

Le token généré (format `jv-xxx...`) est à transmettre **en privé** au testeur (DM, email chiffré, canal sécurisé). **Ne jamais le committer, ne pas l'envoyer en clair sur Slack/Discord publics.**

---

## Étape 3 — Limiter à 5–10 personnes

Béa n'a pas de système d'invitation automatique. La limitation est opérationnelle :
- Tenir une liste locale (hors repo) avec : label, date création, date révocation prévue
- Maximum recommandé : **10 tokens actifs simultanément**
- Désactiver rapidement les tokens non utilisés

---

## Étape 4 — Révoquer un testeur

```bash
# Lister les tokens actifs
curl -X GET http://localhost:8000/api/v3/admin/tokens \
  -H "Authorization: Bearer $JWT"

# Révoquer un token spécifique
curl -X DELETE http://localhost:8000/api/v3/admin/tokens/{token_id} \
  -H "Authorization: Bearer $JWT"
```

Après révocation, toute requête avec l'ancien token retourne `401`.

---

## Étape 5 — Couper tout accès (urgence)

```bash
# Arrêter l'API immédiatement
# Windows :
taskkill /F /IM python.exe
# Linux :
pkill -f run_api_local.py
```

Pour une coupure plus ciblée : désactiver uniquement le provider LLM en commentant `OPENROUTER_API_KEY` dans `.env` et redémarrant — les missions échoueront sans accès réseau sensible.

---

## Étape 6 — Vérifier que /health reste public

```bash
# Doit répondre 200 sans token
curl -v http://localhost:8000/health
# HTTP 200

# Doit répondre 401 sans token
curl -v http://localhost:8000/api/v3/missions
# HTTP 401 Unauthorized
```

---

## Étape 7 — Éviter le token partagé

**Ne jamais donner `BEA_API_TOKEN` (le token statique maître) aux testeurs.**
Ce token est l'équivalent d'un accès admin permanent.

Créer un `jv-xxx` par testeur via l'API. Si le système de tokens individuels n'est pas opérationnel, utiliser des JWT avec expiration courte (7 jours) et régénérer.

---

## Checklist avant première invitation

- [ ] `BEA_ADMIN_PASSWORD` fort défini
- [ ] `BEA_SECRET_KEY` aléatoire défini
- [ ] `/health` répond 200 sans auth
- [ ] `/api/v3/missions` répond 401 sans auth
- [ ] Token créé pour le premier testeur
- [ ] Kill switch testé (API peut être arrêtée rapidement)
- [ ] Aucun secret dans le repo (vérifier avec `git log --all -p | grep "sk-or-v1-"`)
