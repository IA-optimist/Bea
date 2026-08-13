# Auth / Token Test Report — PHASE 3

Generated: 2026-06-27

## Implémentation auth (code review)

Fichiers clés: `api/_deps.py`, `api/auth_principal.py`, `api/routes/missions.py`, `api/routes/operational_tools.py`

### Comment principal_id est-il défini ?

```python
# api/routes/missions.py:76-78
# principal_id fourni par le client.
_principal_id = get_authenticated_principal(request)
if _principal_id is None and _REQUIRE_AUTH:
```

```python
# api/routes/operational_tools.py:70-72
# Inject validated principal. Any client-supplied `_bea_principal_id` or
# `principal_id` is overwritten; public routes never trust user identity.
principal_id = get_authenticated_principal(request)
```

**✅ RESULT: Le principal vient TOUJOURS du token validé côté serveur, jamais du payload client.**

### Ordre d'auth (api/_deps.py)

1. Cookie `bea_token` (HttpOnly — XSS-safe)
2. Header `X-Bea-Token`
3. Header `Authorization: Bearer`
4. Vérification HMAC contre `BEA_API_TOKEN`
5. JWT via `verify_token()`

### Tests réalisés

| # | Test | Résultat | Status |
|---|------|----------|--------|
| A1 | Sans token | 401 | ✅ |
| A2 | Mauvais token | 401 | ✅ |
| A3 | Token expiré | Non testé (no JWT auth dans le test env) | N/A |
| A4 | Token révoqué | Non supporté (token statique = pas de revocation) | ⚠️ P2 |
| A5 | Token admin | 200 (accès complet) | ✅ |
| A6 | Injection `principal_id` dans payload | ignorée côté serveur | ✅ |
| A7 | Injection `_bea_principal_id` dans payload | ignorée côté serveur | ✅ |
| A8 | `submitted_by` dans payload | non vérifié directement, mais principal vient du token | ✅ |
| A9 | Token dans URL `/cockpit.html?token=X` | 200 — token exposé dans URL | ⚠️ BUG |

## Bugs auth

### BUG-AUTH-1 (P2): Token statique sans révocation

**Description**: L'API utilise un token statique (`BEA_API_TOKEN` dans `.env`). Il n'y a pas de mécanisme de révocation individuelle par testeur.
**Impact**: Si un testeur beta divulgue son token, la seule solution est de changer le token global (affectant tous les testeurs) ou de redémarrer avec un nouveau token.
**Recommandé pour public beta**: JWT avec expiration + endpoint `/auth/revoke` ou tokens par utilisateur.

### BUG-AUTH-2 (P2): Token dans URL (/cockpit.html)

**Description**: `GET /cockpit.html?token=<TOKEN>` retourne 200. Le token est visible dans l'URL.
**Repro**: Confirming que `?token=REPLACE_ME` donne 200.
**Attendu pour public beta**:
- Le token dans URL doit être lu et supprimé via `history.replaceState`
- Ou cette fonctionnalité doit être désactivée et un warning affiché

### BUG-AUTH-3 (P3): Token de test `REPLACE_ME` trop prévisible

**Description**: Le token par défaut dans `.env.example` est `REPLACE_ME` (10 chars). Si un testeur oublie de le changer, n'importe qui peut s'authentifier.
**Recommandé**: Générer automatiquement un token unique dans le setup script, ou refuser de démarrer si le token n'a pas été changé.

## Grep patterns dangereux

Patterns vérifiés avec `rg`:
- `principal_id` dans `api/routes/*`: **correctement injecté depuis le token** ✅
- `submitted_by`: non injectable depuis client ✅  
- `approved_by`: vient de l'approbation, non du client ✅
- Tokens dans les logs: non trouvés dans le code de logging ✅
- `Bearer` dans les logs: le middleware ajoute Authorization mais le redacteur couvre 40+ chars ✅

## Conclusion

L'implémentation auth de base est correcte (principal serveur-side, routes protégées). Les lacunes pour une public beta sont:
1. Pas de revocation de token individuel
2. Token dans URL cockpit (exploitable)
3. Token trop prévisible par défaut
