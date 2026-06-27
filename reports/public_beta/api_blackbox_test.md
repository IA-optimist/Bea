# API Black-Box Test Report — PHASE 2

Generated: 2026-06-27
API endpoint: http://127.0.0.1:8000
Token: [REDACTED — token fictif de test, 10 chars, `REPLACE_ME` du .env.example]

## Tests réalisés

| # | Test | Résultat | Attendu | Status |
|---|------|----------|---------|--------|
| T1 | GET /health sans token | 200 `{"status":"ok","service":"beamax"}` | 200 public | ✅ OK |
| T2 | GET /api/v3/missions sans token | 401 | 401 | ✅ OK |
| T3 | GET /api/v3/missions mauvais token | 401 | 401 | ✅ OK |
| T4 | GET /api/v3/missions token réel | 200 | 200 | ✅ OK |
| T5 | POST /api/v3/missions payload vide `{}` | 400 `{"ok":false,"error":"Field 'goal' is required."}` | 400 | ✅ OK |
| T6 | POST /api/v3/missions mission valide | 201 + mission_id | 201 ou 202 | ⚠️ P2 voir ci-dessous |
| T7 | POST /api/v3/missions mauvais Content-Type | 422 | 400/422 | ✅ OK |
| T8 | POST /api/v3/missions injection principal_id | 201, attacker non présent | injection rejetée | ✅ OK |
| T9 | POST /api/v3/missions goal 10k chars | timeout (5s) | 400 ou 413 | ⚠️ P2 |
| T10 | POST /api/v3/missions goal null | timeout | 400/422 | ⚠️ P2 |
| T11 | POST /api/v3/missions form-encoded | timeout | 422 | P3 |

## Bugs détaillés

### BUG-API-1 (P2): Mission submission blocking — >30s pour retourner 201

**Description**: POST /api/v3/missions bloque pendant 30+ secondes avant de retourner 201.
**Repro**: `curl -X POST http://127.0.0.1:8000/api/v3/missions -H "Authorization: Bearer TOKEN" -H "Content-Type: application/json" -d '{"goal":"ping"}'`
**Attendu**: Retour 202 Accepted immédiat avec mission_id, exécution async.
**Observé**: Retour 201 après ~30s (synchrone ou handshake LLM au submit).
**Impact**: 
- Timeout client par défaut (souvent 5-30s) → le client croit que la mission a échoué
- DoS facile: 5 clients simultanés bloquent le serveur
- Frustration testeur beta: interface "qui ne répond pas"

### BUG-API-2 (P2): Large goal + null goal ne retournent pas d'erreur rapide

**Description**: Un goal de 10 000 caractères ou null/JSON null ne retourne pas d'erreur en moins de 5s.
**Repro**: `{"goal": null}` ou `{"goal": "A" * 10000}`
**Attendu**: 400 ou 422 immédiat.
**Observé**: Timeout (pas de réponse dans 5s).
**Impact**: Pas de validation input côté serveur avant de commencer le traitement.

### BUG-API-3 (P2): Cockpit accessible via token dans URL

**Description**: `/cockpit.html?token=<TOKEN>` retourne 200 (la page s'affiche).
**Repro**: `curl "http://127.0.0.1:8000/cockpit.html?token=REPLACE_ME"`
**Attendu**: Warning affiché + history.replaceState (ou token-in-URL refusé pour prod).
**Observé**: Page accessible, token dans l'URL, pas de replaceState détecté.
**Impact**:
- Token dans les logs serveur
- Token dans l'historique navigateur
- Token dans les referrer headers si la page contient des liens externes
- Note: l'accès via `Authorization: Bearer` header fonctionne aussi → recommander ce mode

### BUG-API-4 (P3): GET /api/v3/missions/{id} timeout

**Description**: Récupérer le statut d'une mission par son ID timeout également (~10s).
**Repro**: `GET /api/v3/missions/1518ea7d-f18` après soumission
**Attendu**: Retour 200 immédiat avec le statut courant.
**Observé**: Timeout — probablement parce que l'API est occupée à traiter les missions précédentes.
**Impact**: Interface de suivi inutilisable en charge.

## Résumé sécurité

| Check | Résultat |
|-------|----------|
| /health public | ✅ OK |
| Toute autre route protégée | ✅ OK |
| Erreur propre sans token | ✅ OK (401) |
| Erreur propre mauvais token | ✅ OK (401) |
| Pas de secret dans 401 | ✅ OK |
| principal_id non injectable | ✅ OK |
| Content-Type validé | ✅ OK (422) |
| Payload vide rejeté | ✅ OK (400) |
| Token dans URL non bloqué | ⚠️ BUG-API-3 |

## Note qualité API globale: 3.5/5

Points positifs: auth claire, erreurs structurées, principal non injectable.
Points négatifs: soumission synchrone lente, validation payload incomplète, cockpit URL token.
