# Béa — Security Model

> Developer Preview — ce document décrit l'état actuel, pas un système production-hardened.

## Principes fondamentaux

1. Aucun auto-merge de code généré sans gate opérateur
2. `runtime_enforced=false` invariant pour toutes les routing policies
3. Aucune clé API dans les logs, JSON outputs, ou mémoire vectorielle
4. Paths critiques protégés : `core/self_improvement`, `core/memory`, `api/routes`
5. Provider indisponible ≠ échec qualité modèle

## Gestion des secrets

| Mécanisme | Comportement |
|-----------|-------------|
| Clés API | Lues depuis `.env` uniquement (jamais committées) |
| Erreurs provider | `type(exc).__name__` stocké, jamais `str(exc)` |
| Benchmark advisory | Si clé détectée dans JSON output → `sys.exit(2)` |
| Logs structlog | Champs filtrés avant emission |
| Mémoire Qdrant | Aucune clé injectée dans les embeddings |

`.env` est gitignored. Ne jamais committer de clé, token, ou password.

## Authentification

- API Béa : `BEA_API_TOKEN` (Bearer) sur tous les endpoints `/api/v3/*`
- Endpoints admin : `BEA_ADMIN_PASSWORD` (login cockpit)
- Mobile APK : `JARVIS_API_TOKEN` injecté via `--dart-define` au build

## CORS

La configuration CORS est gérée via les variables d'environnement suivantes :

| Variable | Rôle | Défaut |
|----------|------|--------|
| `BEA_CORS_ORIGINS` | Origins autorisées (comma-separated) | localhost dev defaults |
| `CORS_ORIGINS` | Alias legacy (toujours supporté) | — |

**Règles :**
- Wildcard `*` n'est **jamais** autorisé avec `allow_credentials=True`
- Si `BEA_CORS_ORIGINS=*` est défini, le système remplace par les localhost defaults
- En production (`BEA_PRODUCTION=1`), `BEA_CORS_ORIGINS` DOIT être défini → fail-hard sinon
- En dev local : `http://localhost:3000`, `http://localhost:8000`, `http://127.0.0.1:8000` par défaut

**Example production :**
```bash
BEA_CORS_ORIGINS=https://app.example.com,https://admin.example.com
```

## Rate limiting

L'API intègre un rate limiter via `slowapi` (Redis en prod, in-memory en dev) :

| Variable | Rôle | Défaut |
|----------|------|--------|
| `BEA_RATE_LIMIT_ENABLED` | Active/désactive le rate limit | `true` |
| `BEA_RATE_LIMIT_PER_MINUTE` | Requêtes max par IP par minute | `60` |
| `REDIS_URL` | Backend Redis (recommandé en prod) | in-memory fallback |

**Endpoints exemptés :** `/health`, `/api/v3/system/health`, `/docs`, `/openapi.json`

**En production (`BEA_PRODUCTION=1`) :** Redis est obligatoire — fail-hard si REDIS_URL absent ou Redis injoignable (in-memory ne scale pas horizontalement).

**En test/dev :** `BEA_RATE_LIMIT_ENABLED=false` désactive complètement le rate limit.

## Self-improvement

| Variable | Comportement |
|----------|-------------|
| `BEA_CONTINUOUS_IMPROVEMENT` non défini | Self-improvement désactivé (défaut) |
| `BEA_CONTINUOUS_IMPROVEMENT=1` | Activé, gate kernel R4 requis (approbation opérateur) |
| `BEA_OPERATOR_APPROVE_IMPROVEMENT` | Lève R4 mais garde cooldown 24h et cap d'échecs |
| `BEA_SKIP_IMPROVEMENT_GATE` | **Bypass TOTAL** — ne jamais utiliser en production |

Le démon d'amélioration est câblé dans le lifespan de `api/main.py`. Il ne génère
de signal que via l'exécution réelle de missions (pas juste la soumission).

## Routing policy

- `runtime_enforced=false` invariant dans `core/evaluation/routing_advisor.py`
- Le benchmark produit des recommandations **informatives uniquement**
- Aucune modification automatique du provider runtime
- `confidence` reste `"low"` ou `"experimental"` tant qu'il n'y a pas plusieurs runs indépendants

## Endpoints sensibles

| Endpoint | Risque | Mitigation |
|----------|--------|------------|
| `POST /api/v3/missions` | Exécution de code | Sandbox Docker, chemins bornés |
| `POST /api/v3/improvement` | Auto-amélioration | Gate R4, opt-in uniquement |
| `GET /api/v3/system/*` | Exposition état interne | Auth Bearer requise |
| Workspace file writes | Écriture fichiers | Limité à `workspace/` par défaut |

## Sandbox

L'exécution de code passe par `executor.desktop_env.sandbox.DockerSandbox` :
- Vrai conteneur Debian 12
- FS isolé (`/mnt/c` inaccessible)
- Anti-injection métacaractères

## CORS (APK mobile)

## APK mobile

- Connexion via Tailscale (réseau mesh sécurisé)
- Token injecté à la compilation (`--dart-define`)
- APK utilise `/api/v3` uniquement (0 appel `/api/v1` dans le code Flutter)
- Serveur maintient les endpoints `/api/v1` pour compatibilité descendante

## Public Beta Blockers

Avant toute exposition publique :

- [ ] Rate-limiting sur tous les endpoints API
- [ ] CORS configuré pour origins spécifiques (pas wildcard)
- [ ] Audit complet des endpoints v1 côté serveur
- [ ] Review des file write permissions en sandbox
- [ ] Auth 2FA ou clé forte pour le cockpit admin
- [ ] Rotation automatique des tokens APK
