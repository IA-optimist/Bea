import { useEffect, useState } from 'react';
import {
  LineChart,
  Line,
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { DollarSign, TrendingUp, Users, ArrowUpRight, ArrowDownRight } from 'lucide-react';
import { Card } from '../components/Card';
import { StatCard } from '../components/StatCard';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { apiClient } from '../api/client';
import { formatCurrency } from '../utils/format';
import type { RevenueMetrics, RevenueData } from '../types';

export const Revenue = () => {
  const [loading, setLoading] = useState(true);
  const [metrics, setMetrics] = useState<RevenueMetrics | null>(null);
  const [revenueHistory, setRevenueHistory] = useState<RevenueData[]>([]);
  const [timeRange, setTimeRange] = useState<number>(30);

  useEffect(() => {
    loadRevenueData();
  }, [timeRange]);

  const loadRevenueData = async () => {
    try {
      setLoading(true);
      const [metricsData, historyData] = await Promise.all([
        apiClient.getRevenueMetrics(),
        apiClient.getRevenueHistory(timeRange),
      ]);
      setMetrics(metricsData);
      setRevenueHistory(historyData);
    } catch (err) {
      console.error('Failed to load revenue data:', err);
    } finally {
      setLoading(false);
    }
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg p-4">
          <p className="text-sm font-medium text-gray-900 dark:text-white mb-2">{label}</p>
          {payload.map((entry: any, index: number) => (
            <div key={index} className="flex items-center gap-2 text-sm">
              <div
                className="w-3 h-3 rounded-full"
                style={{ backgroundColor: entry.color }}
              ></div>
              <span className="text-gray-600 dark:text-gray-400">{entry.name}:</span>
              <span className="font-medium text-gray-900 dark:text-white">
                {entry.name === 'Customers' ? entry.value : formatCurrency(entry.value)}
              </span>
            </div>
          ))}
        </div>
      );
    }
    return null;
  };

  if (loading) {
    return <LoadingSpinner />;
  }

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Revenue Analytics</h1>
          <p className="text-gray-600 dark:text-gray-400 mt-1">
            Track and analyze your revenue metrics
          </p>
        </div>
        
        {/* Time Range Selector */}
        <div className="flex gap-2">
          {[7, 30, 90, 365].map((days) => (
            <button
              key={days}
              onClick={() => setTimeRange(days)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                timeRange === days
                  ? 'bg-primary-600 text-white'
                  : 'bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-gray-600'
              }`}
            >
              {days}D
            </button>
          ))}
        </div>
      </div>

      {/* Metrics */}
      {metrics && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          <StatCard
            title="Monthly Recurring Revenue"
            value={formatCurrency(metrics.mrr)}
            icon={DollarSign}
            trend={{ value: metrics.monthly_growth, label: 'vs last month' }}
            color="green"
          />
          <StatCard
            title="Annual Recurring Revenue"
            value={formatCurrency(metrics.arr)}
            icon={TrendingUp}
            trend={{ value: metrics.annual_growth, label: 'vs last year' }}
            color="blue"
          />
          <StatCard
            title="Active Subscriptions"
            value={metrics.active_subscriptions}
            icon={ArrowUpRight}
            color="purple"
          />
          <StatCard
            title="Total Customers"
            value={metrics.total_customers}
            icon={Users}
            color="orange"
          />
        </div>
      )}

      {/* Revenue Trend Chart */}
      <Card title="Revenue Trend" subtitle="Historical revenue performance">
        <ResponsiveContainer width="100%" height={400}>
          <AreaChart data={revenueHistory}>
            <defs>
              <linearGradient id="colorRevenue" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#0ea5e9" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#0ea5e9" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" opacity={0.2} />
            <XAxis
              dataKey="date"
              tickFormatter={formatDate}
              stroke="#9ca3af"
              style={{ fontSize: '12px' }}
            />
            <YAxis
              tickFormatter={(value) => `$${(value / 1000).toFixed(0)}k`}
              stroke="#9ca3af"
              style={{ fontSize: '12px' }}
            />
            <Tooltip content={<CustomTooltip />} />
            <Area
              type="monotone"
              dataKey="revenue"
              stroke="#0ea5e9"
              strokeWidth={2}
              fill="url(#colorRevenue)"
              name="Revenue"
            />
          </AreaChart>
        </ResponsiveContainer>
      </Card>

      {/* MRR & ARR Comparison */}
      <Card title="MRR & ARR Comparison" subtitle="Monthly vs Annual recurring revenue">
        <ResponsiveContainer width="100%" height={400}>
          <LineChart data={revenueHistory}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" opacity={0.2} />
            <XAxis
              dataKey="date"
              tickFormatter={formatDate}
              stroke="#9ca3af"
              style={{ fontSize: '12px' }}
            />
            <YAxis
              tickFormatter={(value) => `$${(value / 1000).toFixed(0)}k`}
              stroke="#9ca3af"
              style={{ fontSize: '12px' }}
            />
            <Tooltip content={<CustomTooltip />} />
            <Legend />
            <Line
              type="monotone"
              dataKey="mrr"
              stroke="#10b981"
              strokeWidth={2}
              dot={{ r: 4 }}
              name="MRR"
            />
            <Line
              type="monotone"
              dataKey="arr"
              stroke="#8b5cf6"
              strokeWidth={2}
              dot={{ r: 4 }}
              name="ARR"
            />
          </LineChart>
        </ResponsiveContainer>
      </Card>

      {/* Customer Growth */}
      <Card title="Customer Growth" subtitle="Track customer acquisition over time">
        <ResponsiveContainer width="100%" height={400}>
          <BarChart data={revenueHistory}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" opacity={0.2} />
            <XAxis
              dataKey="date"
              tickFormatter={formatDate}
              stroke="#9ca3af"
              style={{ fontSize: '12px' }}
            />
            <YAxis stroke="#9ca3af" style={{ fontSize: '12px' }} />
            <Tooltip content={<CustomTooltip />} />
            <Bar dataKey="customers" fill="#f59e0b" radius={[8, 8, 0, 0]} name="Customers" />
          </BarChart>
        </ResponsiveContainer>
      </Card>

      {/* Revenue Insights */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card title="Key Insights">
          <div className="space-y-4">
            <div className="flex items-start gap-3 p-4 bg-green-50 dark:bg-green-900/20 rounded-lg">
              <ArrowUpRight className="w-5 h-5 text-green-600 dark:text-green-400 flex-shrink-0 mt-0.5" />
              <div>
                <p className="font-medium text-green-900 dark:text-green-100">
                  Strong Growth Trend
                </p>
                <p className="text-sm text-green-700 dark:text-green-300 mt-1">
                  Revenue has increased by {metrics?.monthly_growth.toFixed(1)}% this month
                </p>
              </div>
            </div>
            
            <div className="flex items-start gap-3 p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
              <Users className="w-5 h-5 text-blue-600 dark:text-blue-400 flex-shrink-0 mt-0.5" />
              <div>
                <p className="font-medium text-blue-900 dark:text-blue-100">
                  Customer Base Expansion
                </p>
                <p className="text-sm text-blue-700 dark:text-blue-300 mt-1">
                  {metrics?.total_customers} total customers with {metrics?.active_subscriptions} active subscriptions
                </p>
              </div>
            </div>

            <div className="flex items-start gap-3 p-4 bg-purple-50 dark:bg-purple-900/20 rounded-lg">
              <TrendingUp className="w-5 h-5 text-purple-600 dark:text-purple-400 flex-shrink-0 mt-0.5" />
              <div>
                <p className="font-medium text-purple-900 dark:text-purple-100">
                  Healthy ARR Multiple
                </p>
                <p className="text-sm text-purple-700 dark:text-purple-300 mt-1">
                  ARR to MRR ratio: {metrics ? (metrics.arr / metrics.mrr).toFixed(2) : '0'}x
                </p>
              </div>
            </div>
          </div>
        </Card>

        <Card title="Revenue Breakdown">
          <div className="space-y-4">
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                  Monthly Recurring Revenue
                </span>
                <span className="text-sm font-semibold text-gray-900 dark:text-white">
                  {metrics ? formatCurrency(metrics.mrr) : '$0'}
                </span>
              </div>
              <div className="h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-green-600 transition-all duration-500"
                  style={{ width: '100%' }}
                ></div>
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                  Annual Recurring Revenue
                </span>
                <span className="text-sm font-semibold text-gray-900 dark:text-white">
                  {metrics ? formatCurrency(metrics.arr) : '$0'}
                </span>
              </div>
              <div className="h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-purple-600 transition-all duration-500"
                  style={{
                    width: metrics
                      ? `${Math.min(100, (metrics.arr / (metrics.mrr * 12)) * 100)}%`
                      : '0%',
                  }}
                ></div>
              </div>
            </div>

            <div className="pt-4 mt-4 border-t border-gray-200 dark:border-gray-700">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                  Average Revenue per Customer
                </span>
                <span className="text-lg font-bold text-gray-900 dark:text-white">
                  {metrics && metrics.total_customers > 0
                    ? formatCurrency(metrics.mrr / metrics.total_customers)
                    : '$0'}
                </span>
              </div>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
};
