import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  DollarSign,
  TrendingUp,
  Package,
  Users,
  ArrowRight,
  AlertCircle,
  Cpu,
  HardDrive,
} from 'lucide-react';
import { Card } from '../components/Card';
import { StatCard } from '../components/StatCard';
import { Badge } from '../components/Badge';
import { Button } from '../components/Button';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { apiClient } from '../api/client';
import { formatCurrency, formatUptime } from '../utils/format';
import type { SystemStatus, RevenueMetrics, Opportunity, Product } from '../types';

export const Dashboard = () => {
  const [loading, setLoading] = useState(true);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [revenue, setRevenue] = useState<RevenueMetrics | null>(null);
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadDashboardData();
  }, []);

  const loadDashboardData = async () => {
    try {
      setLoading(true);
      setError(null);

      const [statusData, revenueData, opportunitiesData, productsData] = await Promise.all([
        apiClient.getSystemStatus().catch(() => null),
        apiClient.getRevenueMetrics().catch(() => null),
        apiClient.getOpportunities({ per_page: 5 }).catch(() => ({ items: [], total: 0, page: 1, per_page: 5, total_pages: 0 })),
        apiClient.getProducts({ per_page: 5 }).catch(() => ({ items: [], total: 0, page: 1, per_page: 5, total_pages: 0 })),
      ]);

      setSystemStatus(statusData);
      setRevenue(revenueData);
      setOpportunities(opportunitiesData.items);
      setProducts(productsData.items);
    } catch (err) {
      setError('Failed to load dashboard data');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return <LoadingSpinner />;
  }

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Dashboard</h1>
        <p className="text-gray-600 dark:text-gray-400 mt-1">
          Welcome to BeaMax AI OS - Your intelligent business automation platform
        </p>
      </div>

      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400" />
          <p className="text-red-800 dark:text-red-300">{error}</p>
        </div>
      )}

      {/* System Status */}
      {systemStatus && (
        <Card title="System Status" subtitle="Real-time system metrics">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600 dark:text-gray-400">Status</span>
                <Badge variant={systemStatus.status === 'operational' ? 'success' : 'error'}>
                  {systemStatus.status}
                </Badge>
              </div>
            </div>
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
                <Cpu className="w-4 h-4" />
                <span>CPU Usage</span>
              </div>
              <div className="flex items-center gap-3">
                <div className="flex-1 h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-primary-600 transition-all duration-300"
                    style={{ width: `${systemStatus.cpu_usage}%` }}
                  ></div>
                </div>
                <span className="text-sm font-medium text-gray-900 dark:text-white">
                  {systemStatus.cpu_usage}%
                </span>
              </div>
            </div>
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
                <HardDrive className="w-4 h-4" />
                <span>Memory</span>
              </div>
              <div className="flex items-center gap-3">
                <div className="flex-1 h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-green-600 transition-all duration-300"
                    style={{ width: `${systemStatus.memory_usage}%` }}
                  ></div>
                </div>
                <span className="text-sm font-medium text-gray-900 dark:text-white">
                  {systemStatus.memory_usage}%
                </span>
              </div>
            </div>
            <div className="space-y-2">
              <span className="text-sm text-gray-600 dark:text-gray-400">Uptime</span>
              <p className="text-lg font-semibold text-gray-900 dark:text-white">
                {formatUptime(systemStatus.uptime)}
              </p>
            </div>
          </div>
        </Card>
      )}

      {/* Revenue Metrics */}
      {revenue && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          <StatCard
            title="Monthly Recurring Revenue"
            value={formatCurrency(revenue.mrr)}
            icon={DollarSign}
            trend={{ value: revenue.monthly_growth, label: 'vs last month' }}
            color="green"
          />
          <StatCard
            title="Annual Recurring Revenue"
            value={formatCurrency(revenue.arr)}
            icon={TrendingUp}
            trend={{ value: revenue.annual_growth, label: 'vs last year' }}
            color="blue"
          />
          <StatCard
            title="Active Subscriptions"
            value={revenue.active_subscriptions}
            icon={Package}
            color="purple"
          />
          <StatCard
            title="Total Customers"
            value={revenue.total_customers}
            icon={Users}
            color="orange"
          />
        </div>
      )}

      {/* Recent Activity Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Opportunities */}
        <Card
          title="Recent Opportunities"
          subtitle={`${opportunities.length} new opportunities found`}
          action={
            <Link to="/opportunities">
              <Button variant="ghost" size="sm">
                View All <ArrowRight className="w-4 h-4" />
              </Button>
            </Link>
          }
        >
          <div className="space-y-3">
            {opportunities.length === 0 ? (
              <p className="text-center text-gray-500 dark:text-gray-400 py-8">
                No opportunities found. Run a scan to discover new opportunities.
              </p>
            ) : (
              opportunities.map((opp) => (
                <div
                  key={opp.id}
                  className="p-4 bg-gray-50 dark:bg-gray-700/50 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                >
                  <div className="flex items-start justify-between mb-2">
                    <h4 className="font-medium text-gray-900 dark:text-white">{opp.title}</h4>
                    <Badge variant={opp.status === 'new' ? 'info' : 'default'}>
                      {opp.status}
                    </Badge>
                  </div>
                  <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">
                    {opp.description}
                  </p>
                  <div className="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
                    <span>Value: {formatCurrency(opp.value)}</span>
                    <span>Confidence: {(opp.confidence * 100).toFixed(0)}%</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </Card>

        {/* Active Products */}
        <Card
          title="Active Products"
          subtitle={`${products.length} products deployed`}
          action={
            <Link to="/products">
              <Button variant="ghost" size="sm">
                View All <ArrowRight className="w-4 h-4" />
              </Button>
            </Link>
          }
        >
          <div className="space-y-3">
            {products.length === 0 ? (
              <p className="text-center text-gray-500 dark:text-gray-400 py-8">
                No products deployed yet. Deploy your first product to get started.
              </p>
            ) : (
              products.map((product) => (
                <div
                  key={product.id}
                  className="p-4 bg-gray-50 dark:bg-gray-700/50 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                >
                  <div className="flex items-start justify-between mb-2">
                    <h4 className="font-medium text-gray-900 dark:text-white">{product.name}</h4>
                    <Badge
                      variant={
                        product.status === 'deployed'
                          ? 'success'
                          : product.status === 'deploying'
                          ? 'warning'
                          : 'default'
                      }
                    >
                      {product.status}
                    </Badge>
                  </div>
                  <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">
                    {product.description}
                  </p>
                  <div className="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
                    <span>{product.category}</span>
                    <span>v{product.version}</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </Card>
      </div>
    </div>
  );
};
