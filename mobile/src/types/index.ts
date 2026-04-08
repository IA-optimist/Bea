export interface User {
  id: string;
  email: string;
  name: string;
  avatar?: string;
}

export interface Opportunity {
  id: string;
  title: string;
  description: string;
  market: string;
  score: number;
  potential_revenue: number;
  status: 'active' | 'pending' | 'completed';
  created_at: string;
}

export interface Product {
  id: string;
  name: string;
  description: string;
  status: 'draft' | 'deployed' | 'archived';
  revenue: number;
  users: number;
  created_at: string;
}

export interface RevenueData {
  date: string;
  amount: number;
  source: string;
}

export interface Settings {
  darkMode: boolean;
  biometricEnabled: boolean;
  notificationsEnabled: boolean;
}

export interface ApiResponse<T> {
  success: boolean;
  data: T;
  message?: string;
}
