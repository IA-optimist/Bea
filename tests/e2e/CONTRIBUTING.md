# Guide de Contribution - Tests E2E

## Ajouter un nouveau test

### 1. Test API

Dans `tests/e2e/api.spec.ts` :

```typescript
test('Mon nouveau test API', async ({ request }) => {
  const response = await request.get(`${API_BASE_URL}/mon-endpoint`);
  
  expect(response.status()).toBe(200);
  
  const data = await response.json();
  expect(data).toHaveProperty('expected_field');
});
```

### 2. Test Frontend

Dans `tests/e2e/frontend.spec.ts` :

```typescript
test('Mon nouveau test Frontend', async ({ page }) => {
  await page.goto(`${FRONTEND_URL}/ma-page`);
  await page.waitForLoadState('networkidle');
  
  const element = page.locator('#mon-element');
  await expect(element).toBeVisible();
  
  await element.click();
  // Assertions...
});
```

## Structure d'un test

```typescript
test.describe('Groupe de tests', () => {
  test.beforeEach(async ({ page }) => {
    // Setup avant chaque test
  });
  
  test('Description du test', async ({ page, request }) => {
    // Arrange
    const data = { /* ... */ };
    
    // Act
    const response = await request.post(url, { data });
    
    // Assert
    expect(response.status()).toBe(200);
  });
  
  test.afterEach(async () => {
    // Cleanup après chaque test
  });
});
```

## Bonnes pratiques

### ✅ À faire

1. **Tests isolés**
   ```typescript
   // Chaque test doit être indépendant
   test('Test 1', async () => { /* ... */ });
   test('Test 2', async () => { /* ... */ });
   ```

2. **Assertions claires**
   ```typescript
   expect(data).toHaveProperty('id');
   expect(data.id).toBeDefined();
   expect(data.status).toBe('success');
   ```

3. **Timeouts adaptés**
   ```typescript
   await page.waitForSelector('#element', { timeout: 5000 });
   ```

4. **Sélecteurs robustes**
   ```typescript
   // Préférer les sélecteurs sémantiques
   page.getByRole('button', { name: 'Submit' })
   page.getByLabel('Username')
   page.getByText('Welcome')
   
   // Éviter
   page.locator('.btn-primary') // Classes CSS changeantes
   ```

### ❌ À éviter

1. **Dépendances entre tests**
   ```typescript
   // ❌ Mauvais
   let userId;
   test('Create user', () => { userId = createUser(); });
   test('Update user', () => { updateUser(userId); });
   
   // ✅ Bon
   test('Update user', () => {
     const userId = createUser();
     updateUser(userId);
   });
   ```

2. **Hardcoded waits**
   ```typescript
   // ❌ Mauvais
   await page.waitForTimeout(5000);
   
   // ✅ Bon
   await page.waitForSelector('#element');
   await page.waitForLoadState('networkidle');
   ```

3. **Tests trop longs**
   ```typescript
   // Diviser en plusieurs tests si nécessaire
   test('Complete user flow', () => { /* 50 lignes... */ });
   
   // Mieux
   test('User registration', () => { /* ... */ });
   test('User login', () => { /* ... */ });
   test('User profile', () => { /* ... */ });
   ```

## Débugger un test

### Mode UI
```bash
npx playwright test --ui
```

### Mode debug
```bash
npx playwright test --debug
```

### Voir le navigateur
```bash
npx playwright test --headed
```

### Console logs
```typescript
test('Debug test', async ({ page }) => {
  page.on('console', msg => console.log('PAGE LOG:', msg.text()));
  
  await page.goto(url);
  console.log('Current URL:', page.url());
});
```

### Screenshots
```typescript
await page.screenshot({ path: 'debug.png' });
```

## Exécuter un test spécifique

```bash
# Par nom
npx playwright test -g "Health check"

# Par fichier
npx playwright test api.spec.ts

# Par ligne
npx playwright test api.spec.ts:10
```

## Vérifier avant commit

```bash
# Exécuter le script de vérification
./scripts/verify-e2e.sh

# Ou manuellement
npx playwright test --project=chromium
```

## CI/CD

Les tests sont exécutés automatiquement en CI :

```yaml
- run: CI=true npm run test:e2e
```

Avec :
- 2 retries automatiques
- Worker unique
- Pas de tests `.only`

## Ressources

- [Documentation Playwright](https://playwright.dev)
- [Best Practices](https://playwright.dev/docs/best-practices)
- [API Reference](https://playwright.dev/docs/api/class-playwright)
- [Selectors](https://playwright.dev/docs/selectors)

## Questions ?

Consulter :
1. `tests/e2e/README.md` - Documentation complète
2. `tests/e2e/QUICKSTART.md` - Guide rapide
3. Tests existants - Exemples concrets
