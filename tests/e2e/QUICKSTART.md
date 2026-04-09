# Quick Start - Tests E2E Playwright

Guide rapide pour lancer les tests E2E de JarvisMax.

## Installation rapide

```bash
# Installer les dépendances
npm install

# Installer les navigateurs Playwright
npx playwright install chromium
```

## Lancer les tests

### Tous les tests (Chromium uniquement, rapide)
```bash
npx playwright test --project=chromium
```

### Tous les tests (tous navigateurs)
```bash
npm run test:e2e
```

### Tests API seulement
```bash
npm run test:e2e:api
```

### Tests Frontend seulement
```bash
npm run test:e2e:frontend
```

## Voir les résultats

### Rapport HTML
```bash
npm run test:e2e:report
```

### Mode UI (interactif)
```bash
npm run test:e2e:ui
```

## Debug

### Mode debug avec pause
```bash
npm run test:e2e:debug
```

### Voir les navigateurs pendant les tests
```bash
npm run test:e2e:headed
```

## Résumé des tests

### Tests API (7 tests)
- ✓ Health check
- ✓ Mission submit (valid)
- ✓ Mission submit (reject empty)
- ✓ Missions list
- ✓ Missions stats
- ✓ 404 handling
- ✓ Version info

### Tests Frontend (8 tests)
- ✓ Login page load
- ✓ Homepage navigation
- ✓ Page navigation
- ✓ Mission form accessible
- ✓ Form input handling
- ✓ Mission type selector
- ✓ Responsive design
- ✓ API integration

**Total : 15 tests × 3 navigateurs = 45 tests**

## Troubleshooting

### Services non disponibles
```bash
# Vérifier API
curl http://72.62.177.55:8000/health

# Vérifier Frontend
curl http://72.62.177.55:3001
```

### Navigateurs manquants
```bash
npx playwright install
npx playwright install-deps
```

### Tests lents
```bash
# Utiliser uniquement Chromium
npx playwright test --project=chromium

# Paralléliser
npx playwright test --workers=4
```

## CI/CD

Pour CI/CD, utiliser :
```bash
CI=true npx playwright test --project=chromium
```

Cela active :
- 2 retries automatiques
- Worker unique
- Pas de tests `.only`
