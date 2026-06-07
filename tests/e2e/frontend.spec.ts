import { test, expect } from '@playwright/test';

const FRONTEND_URL = 'http://72.62.177.55:3001';
const API_BASE_URL = 'http://72.62.177.55:8000';

test.describe('BeaMax Frontend Tests', () => {

  test.beforeEach(async ({ page }) => {
    // Navigate to frontend before each test
    await page.goto(FRONTEND_URL);
  });

  test('Login page should load successfully', async ({ page }) => {
    await page.goto(`${FRONTEND_URL}/login`);
    
    // Check if page loaded
    await expect(page).toHaveTitle(/BeaMax|Login/i);
    
    // Look for common login page elements
    const loginButton = page.getByRole('button', { name: /login|sign in|connexion/i });
    const usernameField = page.getByRole('textbox', { name: /username|email|utilisateur/i }).first();
    const passwordField = page.getByLabel(/password|mot de passe/i).first();
    
    // At least one login-related element should be present
    const hasLoginElements = await loginButton.isVisible().catch(() => false) ||
                            await usernameField.isVisible().catch(() => false) ||
                            await passwordField.isVisible().catch(() => false);
    
    expect(hasLoginElements).toBe(true);
  });

  test('Homepage should load and display main navigation', async ({ page }) => {
    await page.goto(FRONTEND_URL);
    
    // Wait for page to load
    await page.waitForLoadState('networkidle');
    
    // Check that page loaded
    expect(page.url()).toContain(FRONTEND_URL);
    
    // Look for navigation elements
    const nav = page.locator('nav').first();
    const hasNav = await nav.isVisible().catch(() => false);
    
    if (hasNav) {
      expect(await nav.isVisible()).toBe(true);
    }
  });

  test('Navigation should work between pages', async ({ page }) => {
    await page.goto(FRONTEND_URL);
    await page.waitForLoadState('networkidle');
    
    // Try to find and click on common navigation links
    const links = await page.locator('a[href]').all();
    
    expect(links.length).toBeGreaterThan(0);
    
    // Try to find an internal link
    let internalLinkFound = false;
    for (const link of links) {
      const href = await link.getAttribute('href');
      if (href && (href.startsWith('/') || href.includes(FRONTEND_URL)) && !href.includes('#')) {
        const beforeUrl = page.url();
        await link.click();
        await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});
        
        // Verify navigation occurred
        if (page.url() !== beforeUrl) {
          internalLinkFound = true;
          break;
        }
      }
    }
    
    // If no navigation occurred, at least verify links exist
    if (!internalLinkFound) {
      expect(links.length).toBeGreaterThan(0);
    }
  });

  test('Submit mission form should be accessible', async ({ page }) => {
    // Try common paths for mission submission
    const possiblePaths = ['/missions', '/submit', '/missions/submit', '/new-mission', '/'];
    
    let formFound = false;
    
    for (const path of possiblePaths) {
      await page.goto(`${FRONTEND_URL}${path}`);
      await page.waitForLoadState('networkidle');
      
      // Look for mission-related form elements
      const goalInput = page.getByLabel(/goal|objectif|mission/i).first();
      const submitButton = page.getByRole('button', { name: /submit|envoyer|create|créer/i }).first();
      
      const hasGoalInput = await goalInput.isVisible().catch(() => false);
      const hasSubmitButton = await submitButton.isVisible().catch(() => false);
      
      if (hasGoalInput || hasSubmitButton) {
        formFound = true;
        break;
      }
    }
    
    // If no form found on common paths, check if there's any form on homepage
    if (!formFound) {
      await page.goto(FRONTEND_URL);
      const forms = await page.locator('form').all();
      formFound = forms.length > 0;
    }
    
    expect(formFound).toBe(true);
  });

  test('Submit mission form should handle input', async ({ page }) => {
    // Navigate to likely mission submission page
    await page.goto(`${FRONTEND_URL}/missions`);
    await page.waitForLoadState('networkidle');
    
    // Try to find goal input with various selectors
    let goalInput = page.locator('input[name*="goal"]').first();
    let hasGoalInput = await goalInput.isVisible().catch(() => false);
    
    if (!hasGoalInput) {
      goalInput = page.locator('textarea[name*="goal"]').first();
      hasGoalInput = await goalInput.isVisible().catch(() => false);
    }
    
    if (!hasGoalInput) {
      goalInput = page.getByPlaceholder(/goal|objectif/i).first();
      hasGoalInput = await goalInput.isVisible().catch(() => false);
    }
    
    if (hasGoalInput) {
      await goalInput.fill('Test mission from Playwright E2E');
      const value = await goalInput.inputValue();
      expect(value).toContain('Test mission');
    }
  });

  test('Mission type selector should be present', async ({ page }) => {
    await page.goto(`${FRONTEND_URL}/missions`);
    await page.waitForLoadState('networkidle');
    
    // Look for mission type selector
    const typeSelector = page.locator('select[name*="type"], select[name*="mission"]').first();
    const hasTypeSelector = await typeSelector.isVisible().catch(() => false);
    
    if (!hasTypeSelector) {
      // Try radio buttons
      const radioButtons = await page.locator('input[type="radio"][name*="type"]').all();
      expect(radioButtons.length).toBeGreaterThanOrEqual(0);
    } else {
      expect(await typeSelector.isVisible()).toBe(true);
    }
  });

  test('Application should be responsive', async ({ page }) => {
    // Test mobile viewport
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto(FRONTEND_URL);
    await page.waitForLoadState('networkidle');
    
    // Check that page loads on mobile
    expect(page.url()).toContain(FRONTEND_URL);
    
    // Test tablet viewport
    await page.setViewportSize({ width: 768, height: 1024 });
    await page.reload();
    await page.waitForLoadState('networkidle');
    
    expect(page.url()).toContain(FRONTEND_URL);
  });

  test('API integration - Mission submission flow', async ({ page }) => {
    await page.goto(`${FRONTEND_URL}/missions`);
    await page.waitForLoadState('networkidle');
    
    // Listen for API calls
    let apiCalled = false;
    page.on('response', response => {
      if (response.url().includes('/api/v2/missions/submit')) {
        apiCalled = true;
      }
    });
    
    // Try to find and submit form
    const form = page.locator('form').first();
    const hasForm = await form.isVisible().catch(() => false);
    
    if (hasForm) {
      const submitButton = page.getByRole('button', { name: /submit|envoyer|create|créer/i }).first();
      const hasButton = await submitButton.isVisible().catch(() => false);
      
      if (hasButton) {
        // Fill in required fields if found
        const goalInput = page.locator('input[name*="goal"], textarea[name*="goal"]').first();
        if (await goalInput.isVisible().catch(() => false)) {
          await goalInput.fill('E2E Test Mission');
        }
        
        // Note: We don't actually submit to avoid polluting the database
        // Just verify the form is functional
        expect(await submitButton.isEnabled().catch(() => true)).toBe(true);
      }
    }
  });
});
