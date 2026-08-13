# Cockpit Security Test Report — PHASE 11

Generated: 2026-06-27

## Tests réalisés

| # | Test | Résultat | Status |
|---|------|----------|--------|
| C1 | GET /cockpit.html sans token | 401 | ✅ OK |
| C2 | GET /cockpit avec Authorization header | 200 | ✅ OK |
| C3 | GET /cockpit.html?token=TOKEN | 200 | ⚠️ BUG-COCKPIT-1 |
| C4 | GET /cockpit.html?bea_token=TOKEN | 401 | ✅ (non supporté) |
| C5 | GET /static/cockpit.html | 404 | INFO |
| C6 | Token dans contenu HTML | Non détecté | ✅ OK |
| C7 | history.replaceState dans HTML | Non vérifié (auth header) | ❓ Non prouvé |

## Bug détaillé

### BUG-COCKPIT-1 (P2): Token dans URL accepté sans nettoyage

**Description**:
- `GET /cockpit.html?token=<TOKEN>` retourne 200 (la page s'affiche)
- Le token est dans l'URL → visible dans:
  - Logs serveur (request line)
  - Historique navigateur
  - Headers `Referer` si des ressources externes sont chargées
  - Screenshots/screen recordings partagés par les testeurs

**Repro**:
```bash
curl "http://127.0.0.1:8000/cockpit.html?token=REPLACE_ME"
# Retourne: 200 OK avec la page HTML
```

**Attendu pour public beta**:
```javascript
// Idéalement dans cockpit.html:
const urlParams = new URLSearchParams(window.location.search);
const tokenFromUrl = urlParams.get('token');
if (tokenFromUrl) {
    // Utiliser le token pour l'auth
    sessionStorage.setItem('bea_token', tokenFromUrl);
    // Nettoyer l'URL IMMÉDIATEMENT
    history.replaceState(null, '', window.location.pathname);
    // Afficher un warning
    console.warn('Token in URL is a security risk. Use Authorization header instead.');
}
```

**Mitigation actuelle**: Non documentée. Les testeurs ne savent pas que le token dans l'URL est risqué.

**Note**: Cette fonctionnalité est probablement intentionnelle pour un accès dev/local facile. Elle doit être:
1. Documentée comme "dev-only"
2. Ou nettoyée via `history.replaceState` immédiatement
3. Ou accompagnée d'un warning visible dans l'UI

## Vérification contenu cockpit

```python
# Token (REPLACE_ME) dans le HTML de la page?
# Non détecté dans le contenu HTML
```
✅ Le token ne se retrouve pas écrit dans le HTML de la page.

## Recommandations

1. **Court terme (P2)**: Ajouter `history.replaceState` dans `static/cockpit.html` après lecture du `?token=`
2. **Moyen terme**: Documenter dans le Quickstart que `?token=` est dev-only et doit être évité en beta
3. **Long terme**: Implémenter une authentification par cookie HttpOnly (déjà supporté dans `api/_deps.py`) avec une page de login dédiée

## Conclusion

| Check | Résultat |
|-------|----------|
| Cockpit protégé sans token | ✅ (401) |
| Cockpit avec Auth header | ✅ (200) |
| Token dans URL accepté | ⚠️ P2 (BUG-COCKPIT-1) |
| Token dans contenu HTML | ✅ Non |
| history.replaceState | ❓ Non prouvé présent |
| Bloque public beta | Non critique mais à documenter |
