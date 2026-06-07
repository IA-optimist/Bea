# Tests E2E Playwright - BeaMax

Suite de tests End-to-End complète pour BeaMax utilisant Playwright.

## Structure

```
tests/e2e/
├── README.md           # Ce fichier
├── api.spec.ts         # Tests API (health, missions, opportunities)
├── frontend.spec.ts    # Tests Frontend (login, navigation, formulaires)
└── reports/           # Rapports HTML générés
```

## Prérequis

- Node.js 18+ installé
- API BeaMax en cours d'exécution sur http://72.62.177.55:8000
- Frontend BeaMax en cours d'exécution sur http://72.62.177.55:3001

## Installation

Depuis la racine du projet :

```bash
npm install
npx playwright install
```

Ou installer uniquement Chromium :

```bash
npx playwright install chromium
```

## Commandes

### Exécuter tous les tests

```bash
npm run test:e2e
```

ou directement :

```bash
npx playwright test
```

### Exécuter les tests API uniquement

```bash
npx playwright test api.spec.ts
```

### Exécuter les tests Frontend uniquement

```bash
npx playwright test frontend.spec.ts
```

### Mode UI interactif

```bash
npx playwright test --ui
```

### Mode debug

```bash
npx playwright test --debug
```

### Exécuter sur un navigateur spécifique

```bash
npx playwright test --project=chromium
npx playwright test --project=firefox
npx playwright test --project=webkit
```

### Générer et ouvrir le rapport HTML

```bash
npx playwright show-report tests/e2e/reports
```

### Mode headed (voir le navigateur)

```bash
npx playwright test --headed
```

### Exécuter un test spécifique

```bash
npx playwright test -g "Health check"
```

## Tests API (api.spec.ts)

### Tests couverts :

1. **Health Check**
   - Vérifie que l'endpoint /health retourne 200
   - Valide la structure de réponse (status, version)

2. **Mission Submit**
   - Teste la soumission d'une mission valide
   - Vérifie le rejet des missions avec goal vide
   - Valide la structure de réponse (task_id, mission_id, status)

3. **Missions List**
   - Teste la récupération de la liste des missions
   - Vérifie la structure de réponse (ok, data, missions)
   - Valide la présence des statistiques (stats, total, by_status)

4. **Error Handling**
   - Vérifie que les endpoints inexistants retournent 404

## Tests Frontend (frontend.spec.ts)

### Tests couverts :

1. **Login Page**
   - Vérifie que la page login se charge
   - Détecte les éléments de connexion (input, boutons)

2. **Navigation**
   - Teste le chargement de la homepage
   - Vérifie la présence de la navigation
   - Teste la navigation entre pages

3. **Mission Submission Form**
   - Vérifie l'accessibilité du formulaire
   - Teste la saisie dans le champ goal
   - Vérifie la présence du sélecteur de type

4. **Responsive Design**
   - Teste l'affichage mobile (375x667)
   - Teste l'affichage tablet (768x1024)

5. **Intégration API**
   - Vérifie que le frontend appelle l'API correctement

## Configuration

La configuration se trouve dans `playwright.config.ts` à la racine du projet.

### Variables importantes :

- **baseURL** : http://72.62.177.55:3001 (Frontend)
- **API_BASE_URL** : http://72.62.177.55:8000 (API)
- **timeout** : 30000ms (30 secondes)
- **retries** : 2 en CI, 0 en local

### Rapports générés :

- HTML : `tests/e2e/reports/index.html`
- JSON : `tests/e2e/results.json`
- Console : Liste des tests avec status

## CI/CD

En mode CI (variable d'env CI=true) :
- 2 retries automatiques en cas d'échec
- Worker unique (pas de parallélisation)
- Tests marqués `.only` sont interdits

```bash
CI=true npx playwright test
```

## Bonnes pratiques

1. **Toujours vérifier que les services tournent** avant de lancer les tests
2. **Utiliser --headed en debug** pour voir ce qui se passe
3. **Consulter les traces** en cas d'échec : `npx playwright show-trace trace.zip`
4. **Ne pas polluer la DB** : les tests n'effectuent pas de vraies soumissions si possible
5. **Vérifier le rapport HTML** après chaque run pour les détails

## Dépannage

### Tests échouent avec timeout

```bash
# Augmenter le timeout
npx playwright test --timeout=60000
```

### Problèmes de connexion API

```bash
# Vérifier que l'API répond
curl http://72.62.177.55:8000/health
```

### Problèmes Frontend

```bash
# Vérifier que le frontend est accessible
curl http://72.62.177.55:3001
```

### Navigateurs non installés

```bash
npx playwright install
```

## Maintenance

- Mettre à jour Playwright régulièrement : `npm update @playwright/test`
- Vérifier les breaking changes : https://playwright.dev/docs/release-notes
- Adapter les sélecteurs si le frontend change

## Support

Pour toute question ou problème :
- Documentation Playwright : https://playwright.dev
- Issues GitHub BeaMax : [lien vers repo]

---

**Dernière mise à jour** : 2026-04-09
**Version Playwright** : ^1.40.0
