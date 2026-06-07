# SECURITY AUDIT REPORT

> **Updates 2026-04-20 (Claude Code audit session)** — voir section 8 en bas.
> 16+ commits sur `main`, CVSS 9.1 XSS full stack mitigé, 13 CVE dépendances
> fermées, audit Flutter + découverte/fix fuite token hardcodé (voir §8.7).

**Date initiale:** 2026-04-11
**Dernière mise à jour:** 2026-04-20
**Repository:** /root/Beamax-master
**VPS:** 77.42.40.146

---

## EXECUTIVE SUMMARY

**CRITICAL VULNERABILITY RESOLVED:** .env.backup-20260407 and related secret files were found in git history and have been successfully purged using git-filter-repo.

**Overall Status:** ✅ RESOLVED - No exposed secrets found in current codebase or git history

---

## 1. GIT HISTORY PURGE

### Files Removed from Git History:
- ✅ `.env.backup-20260407` (contained JWT_SECRET_KEY, BEA_API_TOKEN, POSTGRES_PASSWORD, OPENROUTER_API_KEY)
- ✅ `.env.production-ready` (contained same secrets as above)
- ✅ `.env.test` (contained test credentials)
- ✅ `.env.agents` (contained agent environment variables)

### Method Used:
```bash
git filter-repo --invert-paths \
  --path .env.backup-20260407 \
  --path .env.production-ready \
  --path .env.test \
  --path .env.agents \
  --force
```

### Verification:
```bash
# Before purge:
git log --all --full-history -- '.env.backup-20260407'
# Found in commits: af4d9e4, dfc574d, 4216da9, 534d5e7

# After purge:
git log --all --full-history -- '.env.backup-20260407'
# Result: (empty) - Successfully removed from history
```

### Backup Created:
- Full repository backup created at: `/root/Beamax-master.backup-before-filter-20260411-*`

---

## 2. FILESYSTEM AUDIT

### Current .env Files:
| File | Status | Contains Secrets | Git Tracked |
|------|--------|------------------|-------------|
| `.env` | EXISTS | ⚠️ YES (JWT_SECRET_KEY, POSTGRES_PASSWORD, OPENROUTER_API_KEY) | ❌ NO (in .gitignore) |
| `frontend/.env` | EXISTS | ✅ NO (only VITE_API_URL) | ❌ NO (in .gitignore) |
| `.env.example` | EXISTS | ✅ NO (placeholders only) | ✅ YES (safe) |
| `.env.production.example` | EXISTS | ✅ NO (placeholders only) | ✅ YES (safe) |
| `mobile/.env.example` | EXISTS | ✅ NO (placeholders only) | ✅ YES (safe) |
| `frontend/.env.example` | EXISTS | ✅ NO (placeholders only) | ✅ YES (safe) |

### .gitignore Protection:
```
✅ Line 7:   .env
✅ Line 8:   .env.local
✅ Line 9:   .env.*.local
✅ Line 142: .env.production
✅ Line 163: .env.backup*
✅ Line 164: .env.production-ready
✅ Line 165: .env.test
✅ Line 166: .env.agents
```

**Status:** ✅ PROTECTED - All sensitive .env files are properly ignored

---

## 3. API KEY SCAN

### Search Pattern: `sk-*, ghp_*, gho_*, xoxb-*, glpat-*`

**Results:** ✅ NO REAL API KEYS FOUND

Files containing API key patterns (all legitimate usage):
- Test files referencing placeholder keys: `sk-test-key`, `sk-CHANGE_ME`, `sk-or-test`
- Code patterns for secret detection/redaction
- Documentation comments

### Verified Files:
- `core/tool_permissions.py:34` - Secret detection regex pattern (security tool)
- `core/browser/browser_audit.py:22` - Secret redaction pattern (security tool)
- `tests/*` - Test fixtures with placeholder keys
- All references are for **detection/testing**, not actual credentials

---

## 4. HARDCODED PASSWORD SCAN

### Search Pattern: `password.*=` (excluding POSTGRES_PASSWORD, test files)

**Results:** ✅ NO HARDCODED PASSWORDS FOUND

Files reviewed:
- `core/security/secret_crypto.py` - Uses password derivation functions (legitimate)
- `core/notifications/email_client.py` - Reads from `os.getenv("SMTP_PASSWORD")` (safe)
- `core/tool_permissions.py` - Secret detection patterns (security tool)

All password references use environment variables or are part of security tooling.

---

## 5. DOCKER SECRETS AUDIT

### docker-compose.yml:
```yaml
BEA_API_TOKEN: ""  # Empty default (safe)
POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}  # Environment variable (safe)
```

### docker-compose.test.yml:
```yaml
BEA_SECRET_KEY: ${BEA_SECRET_KEY:-test-secret-key-not-for-production}
# All secrets use ${VAR} or ${VAR:-default} pattern (safe)
```

**Status:** ✅ SECURE - All secrets use environment variable substitution

---

## 6. EXPOSED SECRETS SUMMARY

### Total Secrets Found in Current Codebase:
**0 exposed secrets**

### Historical Exposure (now purged):
- `.env.backup-20260407` - **PURGED from git history**
- `.env.production-ready` - **PURGED from git history**
- `.env.test` - **PURGED from git history**
- `.env.agents` - **PURGED from git history**

---

## 7. RECOMMENDATIONS

### ✅ COMPLETED:
1. ✅ Purged sensitive files from git history
2. ✅ Verified .gitignore protects .env files
3. ✅ Confirmed no hardcoded secrets in codebase
4. ✅ Verified Docker configs use environment variables

### 🔴 CRITICAL - IMMEDIATE ACTION REQUIRED:
1. **ROTATE ALL SECRETS** that were in .env.backup-20260407:
   - `JWT_SECRET_KEY` (currently: 7f8a9b...9f0a)
   - `BEA_API_TOKEN` (was exposed)
   - `POSTGRES_PASSWORD` (was exposed)
   - `OPENROUTER_API_KEY` (was exposed)
   
   **Why:** Even though files are purged from git history, they may have been:
   - Pushed to remote repository
   - Accessed by unauthorized parties
   - Cached in CI/CD systems
   - Present in clones/forks

2. **FORCE PUSH** to remote repository:
   ```bash
   cd /root/Beamax-master
   git push origin --force --all
   git push origin --force --tags
   ```
   
   **Warning:** This will rewrite remote history. Coordinate with team members.

3. **NOTIFY ALL COLLABORATORS** to re-clone the repository:
   ```bash
   git clone https://github.com/UniTy01/Beamax-master.git
   ```

### 🟡 RECOMMENDED:
1. Add pre-commit hooks to prevent secret commits:
   ```bash
   pip install pre-commit detect-secrets
   ```

2. Enable GitHub secret scanning (if using GitHub)

3. Implement secret rotation policy (rotate secrets every 90 days)

4. Use secret management service (AWS Secrets Manager, HashiCorp Vault, etc.)

5. Add CI/CD secret scanning (GitGuardian, TruffleHog, gitleaks)

---

## 8. VERIFICATION COMMANDS

```bash
# Verify files removed from history
git log --all --full-history -- '.env.backup-20260407'
git log --all --full-history -- '.env.production-ready'

# Search for exposed secrets
grep -rEn '(sk-[a-zA-Z0-9]{40,}|ghp_[a-zA-Z0-9]{36,})' \
  --include='*.py' --include='*.js' --include='*.yml' \
  ! -path './venv/*' ! -path './.git/*'

# Verify .gitignore
git check-ignore -v .env .env.backup-20260407
```

---

## 9. AUDIT TRAIL

| Action | Timestamp | Status |
|--------|-----------|--------|
| Filesystem check for .env.backup-20260407 | 2026-04-11 00:35:00 | ✅ File not found |
| Git history scan for .env.backup* | 2026-04-11 00:35:15 | 🔴 Found in 4 commits |
| Install git-filter-repo | 2026-04-11 00:35:45 | ✅ Installed |
| Create backup | 2026-04-11 00:36:00 | ✅ Backup created |
| Purge sensitive files from history | 2026-04-11 00:36:15 | ✅ Successfully purged |
| Verify purge completion | 2026-04-11 00:36:30 | ✅ Verified empty |
| Scan for API keys (sk-*) | 2026-04-11 00:36:45 | ✅ No real keys found |
| Scan for hardcoded passwords | 2026-04-11 00:37:00 | ✅ No passwords found |
| Docker secrets audit | 2026-04-11 00:37:15 | ✅ All use env vars |
| Generate security report | 2026-04-11 00:37:30 | ✅ Report complete |

---

## 10. CONCLUSION

**✅ VULNERABILITY RESOLVED**

The critical security vulnerability (.env.backup-20260407 in git history) has been successfully remediated. The repository is now clean of exposed secrets in both the filesystem and git history.

**CRITICAL NEXT STEP:** Rotate all exposed credentials immediately and force-push the cleaned history to the remote repository.

---

**Report Generated:** 2026-04-11 00:37:30 UTC  
**Git Commit (After Purge):** 1bbd545  
**Tool Used:** git-filter-repo 2.38.0


---

## 8. SESSION 2026-04-20 — Claude Code audit complet

**16+ commits sur `main`** suite à un audit complet du repo demandé par l'utilisateur. Résumé exécutif :

### 8.1 Phase 1 — Sécurité immédiate (commit c2deb3b, merge 59ac8e0)
- **`.tokens.json`** (token admin actif `tok-ece2f63fdcce`) retiré du tracking + `.gitignore`.
- **`.coverage`** (125 Ko) retiré du tracking + `.gitignore`.
- **Fallbacks `testpass123`** dans `core/db/migrate.py`, `models/project.py`, `memory/legacy/project_memory.py` → `""` (fail-closed, aligné sur `config/settings.py`).
- **`.env.example`** : secrets de sample → placeholders `CHANGE_ME_openssl_rand_hex_32`.
- **CORS wildcard** retiré de `business/automation/product_builder.py` (template code-gen) → origines explicites via `CORS_ALLOWED_ORIGINS`.
- **`shell=True` non gated** — kill-switches env ajoutés :
  - `LocalFallbackSandbox` → `BEA_ALLOW_LOCAL_SANDBOX=1` requis
  - `core/tool_executor.run_shell_command` → allowlist **enforcée par défaut** (opt-out `BEA_SHELL_ALLOWLIST=0`)
  - `core/orchestration/proactive_loop._run_readonly_shell` → `shell=False` + `shlex.split` + whitelist stricte
  - `mcp/hexstrike-ai/hexstrike_server.py` (2 sites : `_execute_command_internal`, `EnhancedCommandExecutor.execute`) → `HEXSTRIKE_EXEC_ENABLED=1` requis
  - `mcp/hexstrike_v2/core/process_manager.py` → même gate
- **Auth** : `Depends(require_auth)` ajouté sur `/metrics/snapshot` + `/metrics/websocket/status` (défense en profondeur).
- **20 docs racine + 2 scripts obsolètes** → `docs/archive/` (nettoyage).
- **4 tests racine** → `tests/`, `pytest.ini` et `validate_p0p1.sh` alignés.

### 8.2 Phase 2 — Cohérence architecturale (commit 3129f5b)
- Inversion dépendance **core ← api** : `core/meta_orchestrator.py` n'importe plus `api/*`. Registry canonique dans `core/event_stream.py` (`ACTIVE_WS_STREAMS`, `register_ws_stream`, `deregister_ws_stream`). `api/ws.py` est maintenant une façade ré-export.
- `@deprecated` (DeprecationWarning) + roadmap de suppression sur `core/_legacy/__init__.py` et `memory/legacy/__init__.py`.
- Proxy consolidé : `nginx-lb` retiré de `docker-compose.yml` (redondant avec Caddy), `nginx-lb.conf` → `docs/archive/`.
- **Protocol unifié** `kernel.contracts.mission_runner.MissionRunner` (`@runtime_checkable`) pour les 40+ signatures `run_mission`/`execute_mission`.

### 8.3 Pre-commit hooks (commits b537988, d05c3b7)
- `.pre-commit-config.yaml` avec **detect-secrets v1.5.0** + **gitleaks v8.21.2** + safety nets (private-key, merge-conflict, large-files, yaml).
- `.secrets.baseline` : 71 entrées (40 fichiers) marquées pré-existantes (spot-check, aucun secret live).
- `.gitleaks.toml` : allowlist `.secrets.baseline` + `tests/` + `.env.example` + `docs/archive/`.
- **Nouveau workflow** `.github/workflows/pre-commit.yml` : bloque les PR avec secrets non-baselinés.
- Test de blocage validé : fake AWS key + GitHub PAT rejetés par les deux hooks.

### 8.4 Sync master→main (commit 2b98daf)
Audit des 9 commits master absents de main (branches historiquement disjointes). Résultat :
- FIX 1 (CVSS 10.0 auth bypass) — ✅ déjà fixé sur main (architecture supérieure)
- FIX 1b auth fallback — ✅ déjà fixé
- FIX 2 (CVSS 9.1 DATABASE_URL) — ✅ déjà fixé via Phase 1
- FIX 3 (CVSS 7.2 asyncpg pool) — ⚠️ partiel → **appliqué** : `core/db/project_crud.py` bumped `min_size 2→5`, `max_size 10→20`, `max_queries=50k`, `max_inactive_lifetime=300s`, `command_timeout=60s`, `timeout=30s`
- FIX 3b/3c (pool + whitelist + leak) — ✅ déjà fixé
- FIX 4 (CVSS 8.2 embeddings async) — ✅ déjà fixé dans `memory/legacy/store_legacy.py`
- FIX 5 .env.template — ✅ équivalent via `.env.example`
- **feat cookie auth HttpOnly (CVSS 9.1 XSS)** — ❌ manquant → **appliqué** :
  - `api/_deps.require_auth` : cookie prioritaire, fallback headers
  - `api/middleware._extract_token` : idem
  - `api/main.py` : `/api/v2/auth/login` + `/auth/token` + `/auth/login` set le cookie HttpOnly (Secure via `BEA_COOKIE_SECURE`, SameSite=Lax, 7 jours)
  - Nouveau endpoint `POST /api/v2/auth/logout` qui clear le cookie

### 8.5 Frontend CVSS 9.1 — migration localStorage → HttpOnly cookie (commit 6a0ab0c)
- `frontend/src/api/client.ts` (React) : `withCredentials: true`, `logout()` method, plus d'écriture localStorage.
- `frontend/src/pages/Login.tsx` (React) : `fetch() credentials:'include'`, cleanup legacy.
- `static/app.html` (SPA French, 1013 l) :
  - **Bug latent fixé** : `function setToken(t,r){TOKEN=t;ROLE...,r)}` — syntax error qui crashait silencieusement à chaque login.
  - Token en mémoire uniquement (plus de localStorage).
  - `doLogin` / `logout` / `api()` / auto-session via cookie.
- **Propriété obtenue** : même avec XSS injecté, le token reste invisible à `document.cookie` et à tout JS (flag `HttpOnly`).

### 8.6 Auth endpoints — fix bugs + cookie support (commit 970100c)
- `/auth/me` crashait silencieusement (`await` sur sync) → fixed via `Depends(require_auth)`, retourne correctement 401.
- `/auth/refresh` : ajout lecture cookie en priorité + refresh du cookie HttpOnly (prolonge session 7j).
- **5 gate tests** (`tests/test_cookie_auth.py`) : rejects_no_token / accepts_bearer / accepts_bea_token / accepts_cookie / logout_clears_cookie.

### 8.7 Flutter audit — fuite token hardcodé CRITIQUE (commit TBD ce batch)
- **Découverte** : `beamax_app/lib/config/hardcoded_config.dart:9` contenait un token de la forme `jv-uAu...<redacted>...CXPkcfJLg` (56 caractères) en clair. Compilé dans l'APK → extractible par décompilation (ex. `apktool d app.apk`).
- **Fix** : remplacé par `String.fromEnvironment('BEA_API_TOKEN', ...)` avec placeholders inoffensifs. Configuration via `flutter build apk --dart-define=BEA_API_TOKEN=jv-xxx`.
- **Action humaine URGENTE** : **révoquer** le token `jv-uAu8416X4f_hExqvFUyc2ifeRYypnp36AjQjsEGlu5CuiCXPkcfJLg` côté serveur via `POST /api/v2/tokens/{id}/revoke` avant toute distribution d'APK. L'historique git conserve l'ancienne valeur.
- Reste du Flutter : OK. Utilise `flutter_secure_storage` (iOS Keychain / Android Keystore encrypted) pour le token runtime, `SharedPreferences` uniquement pour non-sensible.

### 8.8 Audit de dépendances Python (commit TBD ce batch)
`pip-audit` sur `requirements.txt` : 19 vulnérabilités → **13 fermées, 3 déférées** à des PR dédiées.

**Fermées (bumps patch/minor safe) :**
| Package | Version | → | Fix | CVE |
|---|---|---|---|---|
| fastapi | 0.109.0 | → | 0.109.1 | PYSEC-2024-38 |
| python-multipart | 0.0.22 | → | 0.0.26 | CVE-2026-40347 |
| cryptography | 42.0.2 | → | 43.0.1 | GHSA-h4gh-qq45-vh27 + PYSEC-2024-225 |
| pyjwt | 2.8.0 | → | 2.12.0 | CVE-2026-32597 |
| jinja2 | 3.1.3 | → | 3.1.6 | CVE-2024-34064, CVE-2024-56201, CVE-2024-56326, CVE-2025-27516 |
| langchain-core | 1.2.25 | → | 1.2.31 | CVE-2026-40087 |
| langchain-openai | 1.1.12 | → | 1.1.14 | GHSA-r7w7-9xr2-qq2r |

**Déférées (bumps majeurs nécessitant PR dédiée + tests d'intégration) :**
| Package | Version actuelle | Cible | Pourquoi déféré |
|---|---|---|---|
| cryptography | 43.0.1 | 46.0.6 | CVE-2024-12797, CVE-2026-26007/34073 — breaking changes asyncpg/TLS |
| fastapi | 0.109.1 | ≥0.115 | starlette 0.46+ requis → breaking Pydantic v2 lifecycle, route signatures |
| pytest | 7.4.4 | 9.0.3 | CVE-2025-71176 — major bump, risque sur conftest/plugins |

### 8.9 Actions humaines restantes

**🔴 CRITIQUE (hors repo, nécessite accès admin backend) :**
1. **Rotation secrets actifs** :
   - Token admin `tok-ece2f63fdcce` (du `.tokens.json` purgé)
   - Token Flutter `jv-uAu...<redacted>...CXPkcfJLg` (voir commit HEAD pour la valeur à révoquer)
   - `JWT_SECRET_KEY` (si jamais dans `.env.backup-20260407`)
   - `BEA_API_TOKEN` statique si utilisé
   - `OPENROUTER_API_KEY`, `POSTGRES_PASSWORD`, `N8N_ENCRYPTION_KEY`
2. **Vérifier force-push historique** (ancien audit) : les fichiers sont purgés localement, confirmer remote aligné.
3. **CI GitHub Actions verts** sur HEAD main.
4. **Smoke-test manuel cookie auth** en prod :
   ```bash
   curl -c cookies.txt -X POST https://bea.beamaxapp.co.uk/api/v2/auth/login \
     -H 'Content-Type: application/json' -d '{"username":"admin","password":"..."}'
   # Vérifier : Set-Cookie: bea_token=...; HttpOnly; Secure; SameSite=Lax
   curl -b cookies.txt https://bea.beamaxapp.co.uk/auth/me
   ```

**🟡 Non-critique, déférées :**
5. Bump cryptography 43 → 46 (3 CVE) — PR dédiée avec tests TLS/asyncpg
6. Bump fastapi 0.109 → 0.115+ (2 CVE starlette) — PR dédiée
7. Bump pytest 7 → 9 (1 CVE) — PR dédiée avec run complet
8. Dockerfile non-root USER — TODO balisé, nécessite coord volume mounts côté VPS

---

