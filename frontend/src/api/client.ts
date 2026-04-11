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

const BASE_URL = import.meta.env.VITE_API_URL || 'https://jarvis.jarvismaxapp.co.uk/api/v2';

class ApiClient {
  private client: AxiosInstance;

  constructor() {
    this.client = axios.create({
      baseURL: BASE_URL,
      timeout: 30000,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    // Request interceptor
    this.client.interceptors.request.use(
      (config) => {
        // Add auth token if available (consistent with Login.tsx storage key)
        const token = localStorage.getItem('jarvis_token');
        if (token) {
          config.headers.Authorization = `Bearer ${token}`;
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
          // Handle unauthorized (consistent with Login.tsx storage key)
          localStorage.removeItem('jarvis_token');
          localStorage.removeItem('jarvis_user');
          window.location.href = '/login';
        }
        return Promise.reject(error);
      }
    );
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
  async getOpportunities(params?: {
    page?: number;
    per_page?: number;
    status?: string;
    type?: string;
    search?: string;
  }): Promise<PaginatedResponse<Opportunity>> {
    const { data } = await this.client.get<ApiResponse<PaginatedResponse<Opportunity>>>('/opportunities', {
      params,
    });
    return data.data;
  }

  async getOpportunity(id: string): Promise<Opportunity> {
    const { data } = await this.client.get<ApiResponse<Opportunity>>(`/opportunities/${id}`);
    return data.data;
  }

  async scanOpportunities(): Promise<{ job_id: string; message: string }> {
    const { data } = await this.client.post<ApiResponse<{ job_id: string; message: string }>>(
      '/opportunities/scan'
    );
    return data.data;
  }

  async updateOpportunityStatus(id: string, status: string): Promise<Opportunity> {
    const { data } = await this.client.patch<ApiResponse<Opportunity>>(`/opportunities/${id}`, {
      status,
    });
    return data.data;
  }

  // Products endpoints
  async getProducts(params?: {
    page?: number;
    per_page?: number;
    category?: string;
    status?: string;
  }): Promise<PaginatedResponse<Product>> {
    const { data } = await this.client.get<ApiResponse<PaginatedResponse<Product>>>('/products', {
      params,
    });
    return data.data;
  }

  async getProduct(id: string): Promise<Product> {
    const { data } = await this.client.get<ApiResponse<Product>>(`/products/${id}`);
    return data.data;
  }

  async deployProduct(id: string): Promise<{ job_id: string; message: string }> {
    const { data } = await this.client.post<ApiResponse<{ job_id: string; message: string }>>(
      `/products/${id}/deploy`
    );
    return data.data;
  }

  async createProduct(product: Partial<Product>): Promise<Product> {
    const { data } = await this.client.post<ApiResponse<Product>>('/products', product);
    return data.data;
  }

  async updateProduct(id: string, product: Partial<Product>): Promise<Product> {
    const { data } = await this.client.patch<ApiResponse<Product>>(`/products/${id}`, product);
    return data.data;
  }

  async deleteProduct(id: string): Promise<void> {
    await this.client.delete(`/products/${id}`);
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
      baseURL: import.meta.env.VITE_API_URL || 'https://jarvis.jarvismaxapp.co.uk',
      params,
    });
    return data.data?.missions || [];
  }

  async submitMission(goal: string, mode?: string): Promise<any> {
    const { data } = await this.client.post('/api/v3/missions', { goal, mode: mode || 'chat' }, {
      baseURL: import.meta.env.VITE_API_URL || 'https://jarvis.jarvismaxapp.co.uk',
    });
    return data.data;
  }

  async getMission(id: string): Promise<any> {
    const { data } = await this.client.get('/api/v3/missions/' + id, {
      baseURL: import.meta.env.VITE_API_URL || 'https://jarvis.jarvismaxapp.co.uk',
    });
    return data.data;
  }

  // Generic request method for chat API
  async post<T = any>(url: string, data: any): Promise<{ data: T }> {
    return await this.client.post<T>(url, data);
  }
}

export const apiClient = new ApiClient();
