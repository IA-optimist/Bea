import axios, { AxiosInstance, AxiosError } from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { ApiResponse, Opportunity, Product, RevenueData, User } from '../types';

const API_BASE_URL = process.env['REACT_NATIVE_API_URL'] || 'https://bea.beamaxapp.co.uk/api/v2';

class ApiClient {
  private client: AxiosInstance;

  constructor() {
    this.client = axios.create({
      baseURL: API_BASE_URL,
      timeout: 10000,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    this.setupInterceptors();
  }

  private setupInterceptors() {
    // Request interceptor
    this.client.interceptors.request.use(
      async (config) => {
        const token = await AsyncStorage.getItem('authToken');
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
      async (error: AxiosError) => {
        if (error.response?.status === 401) {
          await AsyncStorage.removeItem('authToken');
          // Handle unauthorized - navigate to login
        }
        return Promise.reject(error);
      }
    );
  }

  // Auth
  async login(email: string, password: string): Promise<ApiResponse<{ token: string; user: User }>> {
    const response = await this.client.post('/auth/login', { email, password });
    if (response.data.data.token) {
      await AsyncStorage.setItem('authToken', response.data.data.token);
    }
    return response.data;
  }

  async logout(): Promise<void> {
    await AsyncStorage.removeItem('authToken');
  }

  // Opportunities
  async getOpportunities(): Promise<ApiResponse<Opportunity[]>> {
    const response = await this.client.get('/opportunities');
    return response.data;
  }

  async scanOpportunities(): Promise<ApiResponse<Opportunity[]>> {
    const response = await this.client.post('/opportunities/scan');
    return response.data;
  }

  async getOpportunityById(id: string): Promise<ApiResponse<Opportunity>> {
    const response = await this.client.get(`/opportunities/${id}`);
    return response.data;
  }

  // Products
  async getProducts(): Promise<ApiResponse<Product[]>> {
    const response = await this.client.get('/products');
    return response.data;
  }

  async deployProduct(opportunityId: string): Promise<ApiResponse<Product>> {
    const response = await this.client.post('/products/deploy', { opportunityId });
    return response.data;
  }

  async getProductById(id: string): Promise<ApiResponse<Product>> {
    const response = await this.client.get(`/products/${id}`);
    return response.data;
  }

  // Revenue
  async getRevenue(period: 'day' | 'week' | 'month' | 'year' = 'month'): Promise<ApiResponse<RevenueData[]>> {
    const response = await this.client.get(`/revenue?period=${period}`);
    return response.data;
  }

  async getRevenueStats(): Promise<ApiResponse<{ total: number; growth: number; trend: string }>> {
    const response = await this.client.get('/revenue/stats');
    return response.data;
  }

  // User
  async getCurrentUser(): Promise<ApiResponse<User>> {
    const response = await this.client.get('/user/me');
    return response.data;
  }
}

export default new ApiClient();
