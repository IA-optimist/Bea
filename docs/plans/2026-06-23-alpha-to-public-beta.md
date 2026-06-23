# Roadmap Alpha → Public Beta
**Date:** 2026-06-23  
**Author:** Claude Opus audit session  
**Status:** NO-GO public beta (P0 items open)

---

## Verdict actuel : NO-GO public beta

Deux P0 bloquants ne sont pas fermés :

1. **P0-SEC-1** — 37 secrets historiques (issue #14) : statut de rotation non confirmé.
2. **P0-TRUTH-1** — Completion truth : la gate artefact est active, mais les missions historiques en état DONE sans artefact vérifiable existent toujours dans la DB.

Tous les autres critères de stabilité technique sont remplis (CI verte, smoke E2E vert, auth correcte, FastAPI CVE résolu).

---

## P0 — Public beta blockers

### P0-SEC-1 : Rotation des secrets historiques
**Issue:** #14  
**Responsable:** Max (action manuelle requise)  
**Critère de fermeture:** Gitleaks full-history scan retourne 0 finding sur les tokens live. Chaque token flaggé est révoqué dans le service émetteur et remplacé dans `.env`.  
**Risque si non fait:** Credentials GitHub/API/DB accessibles dans l'historique git public.

### P0-TRUTH-2 : Completion truth gate active
**Problème:** Le smoke sha256 prouve que la gate est active pour les nouvelles missions. Les missions historiques en DB avec status DONE mais sans artefact vérifiable ne sont pas revalidées.  
**Critère de fermeture:** Script de migration qui marque en NEEDS_REVIEW les sessions DONE sans `files_created` + artefact vérifié. OU décision explicite de les laisser telles quelles et de documenter que completion truth s'applique aux missions post-gate uniquement.  
**Note:** La gate en production empêche tout nouveau DONE sans artefact. Les historiques sont un problème documentaire, pas runtime.

---

## P0 — Runtime crashes

Aucun crash au démarrage confirmé. Tous les imports critiques passent :
- `core.meta_orchestrator.MetaOrchestrator` ✅
- `core.orchestrator_v2.OrchestratorV2` ✅  
- `executor.supervised_executor.SupervisedExecutor` ✅
- `executor.runner.ActionExecutor` ✅
- `risk.engine.RiskEngine` ✅
- `agents.autonomous.devin_agent.DevinAgent` ✅

**Pseudo-crash P1 non bloquant pour beta :**
- `core.memory.MemoryBank` absent de `core.memory.__init__` → DevinAgent.memory_bank = None à l'instanciation. L'agent continue de fonctionner sans mémoire épisodique (dégradé).

---

## P0 — Secrets rotation

Voir P0-SEC-1. Commandes requises pour chaque token flaggé par gitleaks :

```bash
# Lister les findings actuels
gitleaks detect --source . --config=.gitleaks.toml --no-banner --redact --verbose

# Pour chaque token valide détecté :
# 1. Révoquer dans le service d'origine (GitHub, OpenRouter, Telegram, etc.)
# 2. Générer un nouveau token
# 3. Mettre à jour .env local (gitignored)
# 4. Mettre à jour GitHub Secrets si utilisé en CI
```

---

## P1 — Policy/Risk/Execution guard

### P1-POLICY : tool_executor.py policy check broken
**Fichier:** `core/tool_executor.py:733`  
**Problème:** `from core.policy.policy_engine import get_policy_engine` échoue toujours car :
  1. `core/policy/policy_engine.py` n'existe pas (le fichier est `core/policy_engine.py`)
  2. `core/policy_engine.py` n'exporte pas `get_policy_engine`  

**Impact:** La guardrail économique (budget/rate-limit par session) ne s'exécute jamais. Pour `shell_execute` et `code_execute`, le fallback fail-closed fonctionne, mais pour les 20+ autres tools la policy ne contrôle rien.

**Fix recommandé (mini-fix, P1):**
```python
# core/policy_engine.py — ajouter :
_singleton: PolicyEngine | None = None

def get_policy_engine() -> PolicyEngine:
    global _singleton
    if _singleton is None:
        from config.settings import get_settings
        _singleton = PolicyEngine(get_settings())
    return _singleton
```
Et dans tool_executor.py:733 corriger le chemin :
```python
from core.policy_engine import get_policy_engine  # pas core.policy.policy_engine
```

### P1-DEVIN : MemoryBank absent
**Fichier:** `agents/autonomous/devin_agent.py:64`  
**Fix:** Ajouter MemoryBank à `core/memory/__init__.py` OU entourer de try/except avec fallback None + warning.

### P1-APK : Flutter APK rebuild
**Blocage:** L'APK sur Pixel 7 (User 11) appelle encore les endpoints v1 si non rebuild depuis PR #91.  
**Commande:**
```bash
cd C:\bea_app
flutter build apk --release --no-tree-shake-icons
adb -s <device> install -r Bea_app.apk
```
**Après distribution:** ouvrir PR `claude/remove-v1-endpoints` pour supprimer mission_control.py résiduel.

---

## P1 — API/Auth hardening

| Item | Statut | Action |
|------|--------|--------|
| AccessEnforcementMiddleware | ✅ Active | — |
| JWT HS256 HMAC constant-time | ✅ Active | — |
| Rate limiter Redis-backed | ✅ Active (fallback in-memory) | — |
| BEA_ADMIN_PASSWORD enforce | ✅ RuntimeError si absent | — |
| Routes shadowing modules_v3 / connectors | ⚠️ Fragile | PR distinct : forcer prefix explicite |
| 4 copies _check_auth | ⚠️ Duplicated | Consolider vers `api._deps._check_auth` uniquement |
| Stale issue #13 (FastAPI CVE) | ✅ Résolu (0.137.1) | Fermer l'issue |

---

## P2 — Architecture cleanup

| Item | Effort | Notes |
|------|--------|-------|
| Consolider orchestrateurs (8 fichiers "orch") | Moyen | MetaOrchestrator est unique — nettoyer les shims documentaires |
| Extraire HexStrike v2 en subproject | Fort | Déjà en cours (`subprojects/hexstrike_v2/`) |
| Supprimer `core/_legacy/` si présent | Faible | Vérifier `git ls-files core/_legacy` |
| core.orchestrator shim → DeprecationWarning OK | — | Déjà en place |
| Corriger `core/policy/` vs `core/policy_engine.py` | Faible | Aussi P1, cf. section policy |

---

## P2 — Docs/Stubs cleanup

| Doc | Problème | Fix |
|-----|---------|-----|
| `docs/STATUS.md` | 5 assertions fausses (Flutter v1, deps, versions) | Corrigé dans ce PR |
| `docs/STATUS.md` table Flutter | Affiche "3 (allowlisted)" → doit être "0 ✅" | Corrigé dans ce PR |
| `mcp/hexstrike_v2/` stubs | 17 fichiers template sans implémentation | Garder, documenter clairement comme STUB |
| `api/routes/voice.py`, `browser.py` | Gated derrière ENABLE_STUB_ROUTES | Documenter dans KNOWN_LIMITATIONS |

---

## Definition of Done — Public Beta

Public beta est déclarable quand TOUS ces critères sont verts :

- [ ] **SEC-1** : gitleaks full-history → 0 finding sur tokens live
- [ ] **CI** : `test` + `security-strict-mypy` + `pip-audit` + `bandit` + `gitleaks` → verts sur main
- [ ] **Smoke** : `smoke_e2e_cycle.py --fixture sha256 --skip-bea-eval --json` → PASS
- [ ] **Validate** : `validate_local.py --quick` → ALL PASS
- [ ] **APK** : APK Flutter rebuild + distribué, logs confirmant 0 appel v1 en session réelle
- [ ] **Policy** : `tool_executor.py` policy import corrigé et testé
- [ ] **P0-TRUTH** : Décision documentée sur les missions historiques DONE sans artefact
- [ ] **Issue #13** : Fermée (FastAPI CVE résolu)
- [ ] **Issue #14** : Fermée (secrets rotatés)
- [ ] **Docs** : STATUS.md à jour (aucune assertion fausse)
- [ ] **Observability** : au moins 10 missions réelles avec `provider_used` + `model_used` dans learning_runs.json
- [ ] **Known limits** : KNOWN_LIMITATIONS.md liste complète des stubs actifs (voice, browser, multimodal)
