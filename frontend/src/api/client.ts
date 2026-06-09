import axios, { AxiosInstance, AxiosError } from 'axios';
import type {
  SystemStatus,
  RevenueMetrics,
  Opportunity,
  Product,
  RevenueData,
  Settings,
  ApiResponse,
  PaginatedResponse,
} from '../types';

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

class ApiClient {
  private client: AxiosInstance;

  constructor() {
    this.client = axios.create({
      baseURL: BASE_URL,
      timeout: 30000,
      // withCredentials=true : envoie le cookie HttpOnly `bea_token` sur
      // chaque requête. Le backend (api/_deps.require_auth + middleware)
      // lit le cookie en priorité, fallback headers pour compat legacy.
      withCredentials: true,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    // Request interceptor — fallback legacy : si un token localStorage
    // existe encore (session pré-migration), on l'envoie aussi en header
    // pour maintenir la continuité. Sera retiré après la fin de la période
    // de transition (une session post-migration n'écrit plus dans localStorage).
    this.client.interceptors.request.use(
      (config) => {
        const legacyToken = localStorage.getItem('bea_token');
        if (legacyToken) {
          config.headers.Authorization = `Bearer ${legacyToken}`;
        }
        return config;
      },
      (error) => Promise.reject(error)
    );

    // Response interceptor
    this.client.interceptors.response.use(
      (response) => response,
      (error: AxiosError) => {
        if (error.response?.status === 401) {
          // Nettoie l'éventuel token legacy et l'user cache côté client.
          // Le cookie HttpOnly est déjà invalidé serveur-side via /auth/logout.
          localStorage.removeItem('bea_token');
          localStorage.removeItem('bea_user');
          window.location.href = '/login';
        }
        return Promise.reject(error);
      }
    );
  }

  /**
   * Logout — clear le cookie HttpOnly côté serveur et nettoie le cache user.
   */
  async logout(): Promise<void> {
    try {
      await this.client.post('/auth/logout');
    } catch {
      // Logout doit être idempotent — on nettoie le client même si le
      // serveur ne répond pas.
    }
    localStorage.removeItem('bea_token');
    localStorage.removeItem('bea_user');
  }

  // System endpoints
  async getSystemStatus(): Promise<SystemStatus> {
    const { data } = await this.client.get<ApiResponse<SystemStatus>>('/system/status');
    return data.data;
  }

  // Revenue endpoints
  async getRevenueMetrics(): Promise<RevenueMetrics> {
    const { data } = await this.client.get<ApiResponse<RevenueMetrics>>('/revenue/metrics');
    return data.data;
  }

  async getRevenueHistory(days: number = 30): Promise<RevenueData[]> {
    const { data } = await this.client.get<ApiResponse<RevenueData[]>>('/revenue/history', {
      params: { days },
    });
    return data.data;
  }

  // Opportunities endpoints
  private normalizeOpportunity(item: any): Opportunity {
    const scores = item.scores || {};
    const statusObj = item.status || {};

    let status: 'new' | 'in_progress' | 'completed' | 'rejected' = 'new';
    if (typeof statusObj === 'string') {
      status = statusObj as any;
    } else if (statusObj.deployed) {
      status = 'completed';
    } else if (statusObj.mvp_generated || statusObj.analyzed) {
      status = 'in_progress';
    }

    const src = item.source || '';
    const type = src.includes('hackernews') ? 'product' : 'market';

    return {
      id: String(item.id),
      title: item.title || '',
      description: item.description || '',
      type,
      value: 0,
      confidence: (scores.total || 0) / 100,
      status,
      created_at: item.created_at || '',
      updated_at: item.updated_at || '',
      source: item.source,
      tags: item.tags || [],
      analyzed: typeof statusObj === 'object' ? !!statusObj.analyzed : false,
      mvp_generated: typeof statusObj === 'object' ? !!statusObj.mvp_generated : false,
      deployed: typeof statusObj === 'object' ? !!statusObj.deployed : false,
    };
  }

  async getOpportunities(params?: {
    page?: number;
    per_page?: number;
    status?: string;
    type?: string;
    search?: string;
  }): Promise<PaginatedResponse<Opportunity>> {
    const { per_page, ...rest } = params || {};
    const apiParams: any = { ...rest };
    if (per_page !== undefined) apiParams.page_size = per_page;

    const { data } = await this.client.get<any>('/api/v3/business/opportunities', { params: apiParams });
    const raw = data.data || {};
    return {
      items: (raw.items || []).map((item: any) => this.normalizeOpportunity(item)),
      total: raw.total || 0,
      page: raw.page || 1,
      per_page: raw.page_size || per_page || 10,
      total_pages: raw.pages || 1,
    };
  }

  async getOpportunity(id: string): Promise<Opportunity> {
    const { data } = await this.client.get<any>(`/api/v3/business/opportunities/${id}`);
    return this.normalizeOpportunity(data.data || data);
  }

  async scanOpportunities(): Promise<{ job_id: string; message: string }> {
    const { data } = await this.client.post<any>('/api/v3/business/opportunities/scan', {});
    return {
      job_id: data.data?.job_id || 'background',
      message: data.message || data.data?.message || 'Scan started',
    };
  }

  async updateOpportunityStatus(id: string, status: string): Promise<Opportunity> {
    const { data } = await this.client.patch<any>(`/api/v3/business/opportunities/${id}`, { status });
    return this.normalizeOpportunity(data.data || data);
  }

  async analyzeOpportunity(id: string): Promise<any> {
    const { data } = await this.client.post<any>(`/api/v3/business/opportunities/${id}/analyze`);
    return data;
  }

  async generateMvp(id: string): Promise<any> {
    const { data } = await this.client.post<any>(`/api/v3/business/opportunities/${id}/generate-mvp`);
    return data;
  }

  async deployOpportunityPipeline(id: string): Promise<any> {
    const { data } = await this.client.post<any>(`/api/v3/business/opportunities/${id}/deploy`);
    return data;
  }

  // Products endpoints
  private normalizeProduct(item: any): Product {
    return {
      id: String(item.id),
      name: item.name || '',
      description: item.description || '',
      category: item.category || 'saas',
      status: item.status || 'active',
      version: item.version || '1.0.0',
      price: item.price ?? 0,
      deployment_url: item.deployment_url,
      created_at: item.created_at || '',
      updated_at: item.updated_at || '',
    };
  }

  async getProducts(params?: {
    page?: number;
    per_page?: number;
    category?: string;
    status?: string;
  }): Promise<PaginatedResponse<Product>> {
    const { per_page, ...rest } = params || {};
    const apiParams: any = { ...rest };
    if (per_page !== undefined) apiParams.page_size = per_page;

    const { data } = await this.client.get<any>('/api/v3/business/products', { params: apiParams });
    const raw = data.data || {};
    return {
      items: (raw.items || []).map((item: any) => this.normalizeProduct(item)),
      total: raw.total || 0,
      page: raw.page || 1,
      per_page: raw.page_size || per_page || 20,
      total_pages: raw.pages || 1,
    };
  }

  async getProduct(id: string): Promise<Product> {
    const { data } = await this.client.get<any>(`/api/v3/business/products/${id}`);
    return this.normalizeProduct(data.data || data);
  }

  async deployProduct(id: string): Promise<{ job_id: string; message: string }> {
    const { data } = await this.client.post<any>(`/api/v3/business/products/${id}/deploy`);
    return {
      job_id: data.data?.job_id || `deploy-${id}`,
      message: data.message || 'Deployment started',
    };
  }

  async createProduct(product: Partial<Product>): Promise<Product> {
    const { data } = await this.client.post<any>('/api/v3/business/products', product);
    return this.normalizeProduct(data.data || data);
  }

  async updateProduct(id: string, product: Partial<Product>): Promise<Product> {
    const { data } = await this.client.patch<any>(`/api/v3/business/products/${id}`, product);
    return this.normalizeProduct(data.data || data);
  }

  async deleteProduct(id: string): Promise<void> {
    await this.client.delete(`/api/v3/business/products/${id}`);
  }

  // Settings endpoints
  async getSettings(): Promise<Settings> {
    const { data } = await this.client.get<ApiResponse<Settings>>('/settings');
    return data.data;
  }

  async updateSettings(settings: Partial<Settings>): Promise<Settings> {
    const { data } = await this.client.patch<ApiResponse<Settings>>('/settings', settings);
    return data.data;
  }


  // Missions endpoints
  async getMissions(params?: { limit?: number; status?: string }): Promise<any[]> {
    const { data } = await this.client.get('/api/v3/missions', {
      baseURL: import.meta.env.VITE_API_URL || 'https://bea.beamaxapp.co.uk',
      params,
    });
    return data.data?.missions || [];
  }

  // submitMission / getMission removed in audit phase-11 — Missions.tsx
  // posts directly to /api/v2/chat. Re-add via git history if a future
  // page needs the v3/missions wrapper.

  // MCP endpoints
  async getMcpServers(): Promise<any[]> {
    const { data } = await this.client.get<any>('/api/v3/mcp/servers');
    return data.servers ?? data ?? [];
  }

  async getMcpStats(): Promise<any> {
    const { data } = await this.client.get<any>('/api/v3/mcp/stats');
    return data;
  }

  async enableMcpServer(id: string): Promise<void> {
    await this.client.post(`/api/v3/mcp/servers/${id}/enable`);
  }

  async disableMcpServer(id: string): Promise<void> {
    await this.client.post(`/api/v3/mcp/servers/${id}/disable`);
  }

  // Skills endpoints
  async getLearnedSkills(): Promise<any[]> {
    const { data } = await this.client.get<any>('/api/v2/skills');
    return data.data ?? data.skills ?? data ?? [];
  }

  // Self-improvement endpoints
  async getImprovementStatus(): Promise<any> {
    const { data } = await this.client.get<any>('/api/v2/self-improvement/status');
    return data;
  }

  async getImprovementProposals(): Promise<any> {
    const { data } = await this.client.get<any>('/api/v2/self-improvement/proposals');
    return data.data ?? data;
  }

  async getImprovementFailures(): Promise<any> {
    const { data } = await this.client.get<any>('/api/v2/self-improvement/failures');
    return data.data ?? data;
  }

  async getImprovementReport(): Promise<any> {
    const { data } = await this.client.get<any>('/api/v2/self-improve/report');
    return data;
  }

  async triggerImprovementRun(): Promise<any> {
    const { data } = await this.client.post<any>('/api/v2/self-improve/run', {});
    return data;
  }

  // Memory / RAG endpoints
  async getMemoryStats(): Promise<any> {
    const { data } = await this.client.get<any>('/api/v2/rag/status');
    return data;
  }

  async queryMemory(query: string, top_k = 5): Promise<any> {
    const { data } = await this.client.post<any>('/api/v2/rag/query', { question: query, top_k });
    return data.data ?? data;
  }

  // Generic request method for chat API
  async post<T = any>(url: string, data: any): Promise<{ data: T }> {
    return await this.client.post<T>(url, data);
  }
}

export const apiClient = new ApiClient();
