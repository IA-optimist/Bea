import { test, expect } from '@playwright/test';

const FRONTEND_URL = process.env.BEA_FRONTEND_URL ?? 'http://127.0.0.1:8000';

test.describe('Bea frontend', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(`${FRONTEND_URL}/app.html`);
  });

  test('login screen loads with usable controls', async ({ page }) => {
    await expect(page).toHaveTitle(/Bea/i);
    await expect(page.locator('#login-user')).toBeVisible();
    await expect(page.locator('#login-pass')).toBeVisible();
    await expect(page.locator('#login-token')).toBeVisible();
    await expect(page.locator('#login-btn')).toBeEnabled();
  });

  test('login form accepts input', async ({ page }) => {
    await page.locator('#login-user').fill('admin');
    await page.locator('#login-pass').fill('not-submitted');
    await page.locator('#login-token').fill('token-not-submitted');

    await expect(page.locator('#login-user')).toHaveValue('admin');
    await expect(page.locator('#login-pass')).toHaveValue('not-submitted');
    await expect(page.locator('#login-token')).toHaveValue('token-not-submitted');
  });

  test('dashboard navigation is present in the application shell', async ({ page }) => {
    await expect(page.locator('[data-v="home"]')).toHaveCount(1);
    await expect(page.locator('[data-v="missions"]')).toHaveCount(1);
    await expect(page.locator('[data-v="system"]')).toHaveCount(1);
  });

  test('application shell remains available on mobile and tablet', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await expect(page.locator('#login-page')).toBeVisible();

    await page.setViewportSize({ width: 768, height: 1024 });
    await expect(page.locator('#login-page')).toBeVisible();
  });

  test('page has no uncaught JavaScript errors during load', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.reload();
    await page.waitForLoadState('networkidle');
    expect(errors).toEqual([]);
  });
});
