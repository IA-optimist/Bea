import { test, expect } from '@playwright/test';

const API_BASE_URL = 'http://72.62.177.55:8000';

test.describe('JarvisMax API Tests', () => {
  
  test('Health check endpoint should return 200', async ({ request }) => {
    const response = await request.get(`${API_BASE_URL}/health`);
    expect(response.status()).toBe(200);
    
    const data = await response.json();
    expect(data).toHaveProperty('status');
    expect(data.status).toBe('ok');
    expect(data).toHaveProperty('service');
    expect(data.service).toBe('jarvismax');
  });

  test('Mission submit endpoint should accept valid mission', async ({ request }) => {
    const missionData = {
      goal: 'Test mission from Playwright E2E',
      mission_type: 'research'
    };

    const response = await request.post(`${API_BASE_URL}/api/v2/missions/submit`, {
      headers: {
        'Content-Type': 'application/json',
      },
      data: missionData
    });

    expect(response.status()).toBe(200);
    
    const data = await response.json();
    expect(data).toHaveProperty('ok');
    expect(data.ok).toBe(true);
    expect(data).toHaveProperty('data');
    expect(data.data).toHaveProperty('task_id');
    expect(data.data).toHaveProperty('mission_id');
    expect(data.data).toHaveProperty('status');
  });

  test('Mission submit should reject empty goal', async ({ request }) => {
    const missionData = {
      goal: '',
      mission_type: 'research'
    };

    const response = await request.post(`${API_BASE_URL}/api/v2/missions/submit`, {
      headers: {
        'Content-Type': 'application/json',
      },
      data: missionData
    });

    expect([400, 422]).toContain(response.status());
  });

  test('Missions list endpoint should return data', async ({ request }) => {
    const response = await request.get(`${API_BASE_URL}/api/v2/missions`);
    
    expect(response.status()).toBe(200);
    
    const data = await response.json();
    expect(data).toHaveProperty('ok');
    expect(data.ok).toBe(true);
    expect(data).toHaveProperty('data');
    expect(data.data).toHaveProperty('missions');
    expect(Array.isArray(data.data.missions)).toBe(true);
  });

  test('Missions list should include stats', async ({ request }) => {
    const response = await request.get(`${API_BASE_URL}/api/v2/missions`);
    
    expect(response.status()).toBe(200);
    
    const data = await response.json();
    expect(data.data).toHaveProperty('stats');
    expect(data.data.stats).toHaveProperty('total');
    expect(data.data.stats).toHaveProperty('by_status');
  });

  test('API should return 404 for non-existent endpoint', async ({ request }) => {
    const response = await request.get(`${API_BASE_URL}/api/v2/nonexistent`);
    expect(response.status()).toBe(404);
  });

  test('API health check should include version info', async ({ request }) => {
    const response = await request.get(`${API_BASE_URL}/health`);
    const data = await response.json();
    
    expect(data).toHaveProperty('status');
    // Version might be optional, check if exists
    if (data.version) {
      expect(typeof data.version).toBe('string');
    }
  });
});
