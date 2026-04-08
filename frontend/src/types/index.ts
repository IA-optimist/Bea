export interface SystemStatus {
  status: string;
  uptime: number;
  cpu_usage: number;
  memory_usage: number;
  active_services: number;
  timestamp: string;
}

export interface RevenueMetrics {
  mrr: number;
  arr: number;
  monthly_growth: number;
  annual_growth: number;
  total_customers: number;
  active_subscriptions: number;
}

export interface Opportunity {
  id: string;
  title: string;
  description: string;
  type: string;
  value: number;
  confidence: number;
  status: 'new' | 'in_progress' | 'completed' | 'rejected';
  created_at: string;
  updated_at: string;
  source?: string;
  tags?: string[];
}

export interface Product {
  id: string;
  name: string;
  description: string;
  category: string;
  status: 'active' | 'inactive' | 'deploying' | 'deployed';
  version: string;
  price: number;
  deployment_url?: string;
  created_at: string;
  updated_at: string;
}

export interface RevenueData {
  date: string;
  revenue: number;
  mrr: number;
  arr: number;
  customers: number;
}

export interface Settings {
  theme: 'light' | 'dark';
  notifications_enabled: boolean;
  auto_scan_enabled: boolean;
  scan_interval: number;
}

export interface ApiResponse<T> {
  success: boolean;
  data: T;
  message?: string;
  error?: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}
