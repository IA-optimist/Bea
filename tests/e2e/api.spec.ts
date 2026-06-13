import { test, expect } from '@playwright/test';

const API_BASE_URL = process.env.BEA_API_URL ?? 'http://127.0.0.1:8000';
const API_TOKEN = process.env.BEA_API_TOKEN;

function authHeaders(): Record<string, string> {
  return API_TOKEN ? { 'X-Bea-Token': API_TOKEN } : {};
}

test.describe('Bea API', () => {
  test('public health endpoint reports the service as healthy', async ({ request }) => {
    const response = await request.get(`${API_BASE_URL}/health`);
    expect(response.status()).toBe(200);
    await expect(response.json()).resolves.toMatchObject({
      status: 'ok',
      service: 'beamax',
    });
  });

  test('protected endpoint rejects anonymous requests', async ({ request }) => {
    const response = await request.get(`${API_BASE_URL}/api/v3/system/status`);
    expect(response.status()).toBe(401);
  });

  test('authenticated status and readiness endpoints respond', async ({ request }) => {
    test.skip(!API_TOKEN, 'BEA_API_TOKEN is required for authenticated E2E checks');

    for (const path of ['/api/v3/system/status', '/api/v3/system/readiness']) {
      const response = await request.get(`${API_BASE_URL}${path}`, {
        headers: authHeaders(),
      });
      expect(response.status(), path).toBe(200);
      expect((await response.json()).ok, path).toBe(true);
    }
  });

  test('authenticated mission listing returns an array', async ({ request }) => {
    test.skip(!API_TOKEN, 'BEA_API_TOKEN is required for authenticated E2E checks');

    const response = await request.get(`${API_BASE_URL}/api/v3/missions?limit=5`, {
      headers: authHeaders(),
    });
    expect(response.status()).toBe(200);
    const payload = await response.json();
    expect(payload.ok).toBe(true);
    expect(Array.isArray(payload.data.missions)).toBe(true);
  });

  test('unknown API endpoint returns 404', async ({ request }) => {
    test.skip(!API_TOKEN, 'BEA_API_TOKEN is required to reach authenticated routing');

    const response = await request.get(`${API_BASE_URL}/api/v3/nonexistent`, {
      headers: authHeaders(),
    });
    expect(response.status()).toBe(404);
  });
});
