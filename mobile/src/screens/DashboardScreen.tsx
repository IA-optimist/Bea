import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, RefreshControl } from 'react-native';
import { useTheme } from '../contexts/ThemeContext';
import { Card } from '../components/Card';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { useHaptics } from '../hooks/useHaptics';
import { useOfflineStorage } from '../hooks/useOfflineStorage';
import api from '../services/api';
import { Ionicons } from '@expo/vector-icons';
import Animated, { FadeInDown } from 'react-native-reanimated';

interface DashboardStats {
  opportunities: number;
  products: number;
  revenue: number;
  growth: number;
}

export const DashboardScreen: React.FC = () => {
  const { colors } = useTheme();
  const haptics = useHaptics();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const { value: stats, setValue: setStats } = useOfflineStorage<DashboardStats>('dashboardStats', {
    opportunities: 0,
    products: 0,
    revenue: 0,
    growth: 0,
  });

  useEffect(() => {
    loadDashboard();
  }, []);

  const loadDashboard = async () => {
    try {
      const [opportunitiesRes, productsRes, revenueRes] = await Promise.all([
        api.getOpportunities(),
        api.getProducts(),
        api.getRevenueStats(),
      ]);

      const newStats: DashboardStats = {
        opportunities: opportunitiesRes.data.length,
        products: productsRes.data.length,
        revenue: revenueRes.data.total,
        growth: revenueRes.data.growth,
      };

      setStats(newStats);
      haptics.success();
    } catch (error) {
      console.error('Error loading dashboard:', error);
      haptics.error();
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const onRefresh = () => {
    setRefreshing(true);
    loadDashboard();
  };

  if (loading) {
    return <LoadingSpinner />;
  }

  return (
    <ScrollView
      style={[styles.container, { backgroundColor: colors.background }]}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
    >
      <View style={styles.header}>
        <Text style={[styles.title, { color: colors.text }]}>Dashboard</Text>
        <Text style={[styles.subtitle, { color: colors.textSecondary }]}>
          Welcome back to BeaMax
        </Text>
      </View>

      <View style={styles.statsGrid}>
        <Animated.View entering={FadeInDown.delay(100)} style={styles.statCard}>
          <Card>
            <View style={styles.statContent}>
              <Ionicons name="trending-up" size={24} color={colors.primary} />
              <Text style={[styles.statValue, { color: colors.text }]}>{stats.opportunities}</Text>
              <Text style={[styles.statLabel, { color: colors.textSecondary }]}>Opportunities</Text>
            </View>
          </Card>
        </Animated.View>

        <Animated.View entering={FadeInDown.delay(200)} style={styles.statCard}>
          <Card>
            <View style={styles.statContent}>
              <Ionicons name="cube" size={24} color={colors.success} />
              <Text style={[styles.statValue, { color: colors.text }]}>{stats.products}</Text>
              <Text style={[styles.statLabel, { color: colors.textSecondary }]}>Products</Text>
            </View>
          </Card>
        </Animated.View>

        <Animated.View entering={FadeInDown.delay(300)} style={styles.statCard}>
          <Card>
            <View style={styles.statContent}>
              <Ionicons name="cash" size={24} color={colors.warning} />
              <Text style={[styles.statValue, { color: colors.text }]}>
                ${stats.revenue.toLocaleString()}
              </Text>
              <Text style={[styles.statLabel, { color: colors.textSecondary }]}>Revenue</Text>
            </View>
          </Card>
        </Animated.View>

        <Animated.View entering={FadeInDown.delay(400)} style={styles.statCard}>
          <Card>
            <View style={styles.statContent}>
              <Ionicons name="arrow-up" size={24} color={stats.growth >= 0 ? colors.success : colors.error} />
              <Text style={[styles.statValue, { color: colors.text }]}>
                {stats.growth >= 0 ? '+' : ''}{stats.growth}%
              </Text>
              <Text style={[styles.statLabel, { color: colors.textSecondary }]}>Growth</Text>
            </View>
          </Card>
        </Animated.View>
      </View>

      <Animated.View entering={FadeInDown.delay(500)} style={styles.section}>
        <Text style={[styles.sectionTitle, { color: colors.text }]}>Quick Actions</Text>
        <Card style={styles.actionCard}>
          <View style={styles.actionItem}>
            <Ionicons name="scan" size={20} color={colors.primary} />
            <Text style={[styles.actionText, { color: colors.text }]}>Scan for new opportunities</Text>
          </View>
        </Card>
        <Card style={styles.actionCard}>
          <View style={styles.actionItem}>
            <Ionicons name="rocket" size={20} color={colors.success} />
            <Text style={[styles.actionText, { color: colors.text }]}>Deploy a new product</Text>
          </View>
        </Card>
        <Card style={styles.actionCard}>
          <View style={styles.actionItem}>
            <Ionicons name="analytics" size={20} color={colors.warning} />
            <Text style={[styles.actionText, { color: colors.text }]}>View revenue analytics</Text>
          </View>
        </Card>
      </Animated.View>
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  header: {
    padding: 20,
    paddingTop: 60,
  },
  title: {
    fontSize: 32,
    fontWeight: '700',
    marginBottom: 4,
  },
  subtitle: {
    fontSize: 16,
  },
  statsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    padding: 10,
  },
  statCard: {
    width: '50%',
    padding: 10,
  },
  statContent: {
    alignItems: 'center',
    gap: 8,
  },
  statValue: {
    fontSize: 28,
    fontWeight: '700',
  },
  statLabel: {
    fontSize: 14,
  },
  section: {
    padding: 20,
  },
  sectionTitle: {
    fontSize: 20,
    fontWeight: '600',
    marginBottom: 16,
  },
  actionCard: {
    marginBottom: 12,
  },
  actionItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  actionText: {
    fontSize: 16,
    fontWeight: '500',
  },
});
