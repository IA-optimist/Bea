import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, RefreshControl, Dimensions } from 'react-native';
import { LineChart, BarChart } from 'react-native-chart-kit';
import { useTheme } from '../contexts/ThemeContext';
import { Card } from '../components/Card';
import { Button } from '../components/Button';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { useHaptics } from '../hooks/useHaptics';
import { useOfflineStorage } from '../hooks/useOfflineStorage';
import api from '../services/api';
import { RevenueData } from '../types';
import { Ionicons } from '@expo/vector-icons';
import Animated, { FadeIn } from 'react-native-reanimated';

const screenWidth = Dimensions.get('window').width;

export const RevenueScreen: React.FC = () => {
  const { colors, isDark } = useTheme();
  const haptics = useHaptics();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [period, setPeriod] = useState<'day' | 'week' | 'month' | 'year'>('month');
  const { value: revenueData, setValue: setRevenueData } = useOfflineStorage<RevenueData[]>(
    'revenueData',
    []
  );
  const [stats, setStats] = useState({ total: 0, growth: 0, trend: 'up' });

  useEffect(() => {
    loadRevenue();
  }, [period]);

  const loadRevenue = async () => {
    try {
      const [dataResponse, statsResponse] = await Promise.all([
        api.getRevenue(period),
        api.getRevenueStats(),
      ]);
      setRevenueData(dataResponse.data);
      setStats(statsResponse.data);
      haptics.success();
    } catch (error) {
      console.error('Error loading revenue:', error);
      haptics.error();
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const onRefresh = () => {
    setRefreshing(true);
    loadRevenue();
  };

  const chartData = {
    labels: revenueData.slice(0, 6).map((item) => {
      const date = new Date(item.date);
      return `${date.getMonth() + 1}/${date.getDate()}`;
    }),
    datasets: [
      {
        data: revenueData.slice(0, 6).map((item) => item.amount),
      },
    ],
  };

  const chartConfig = {
    backgroundColor: colors.card,
    backgroundGradientFrom: colors.card,
    backgroundGradientTo: colors.card,
    decimalPlaces: 0,
    color: (opacity = 1) => isDark ? `rgba(123, 131, 235, ${opacity})` : `rgba(94, 106, 210, ${opacity})`,
    labelColor: (opacity = 1) => colors.textSecondary,
    style: {
      borderRadius: 16,
    },
    propsForDots: {
      r: '6',
      strokeWidth: '2',
      stroke: colors.primary,
    },
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
        <Text style={[styles.title, { color: colors.text }]}>Revenue</Text>
      </View>

      <Animated.View entering={FadeIn.delay(100)}>
        <Card style={styles.statsCard}>
          <View style={styles.mainStat}>
            <Text style={[styles.mainStatLabel, { color: colors.textSecondary }]}>Total Revenue</Text>
            <Text style={[styles.mainStatValue, { color: colors.text }]}>
              ${stats.total.toLocaleString()}
            </Text>
            <View style={styles.growthContainer}>
              <Ionicons
                name={stats.growth >= 0 ? 'trending-up' : 'trending-down'}
                size={20}
                color={stats.growth >= 0 ? colors.success : colors.error}
              />
              <Text
                style={[
                  styles.growthText,
                  { color: stats.growth >= 0 ? colors.success : colors.error },
                ]}
              >
                {stats.growth >= 0 ? '+' : ''}{stats.growth}%
              </Text>
            </View>
          </View>
        </Card>
      </Animated.View>

      <View style={styles.periodSelector}>
        {['day', 'week', 'month', 'year'].map((p) => (
          <Button
            key={p}
            title={p.charAt(0).toUpperCase() + p.slice(1)}
            onPress={() => {
              setPeriod(p as any);
              haptics.light();
            }}
            variant={period === p ? 'primary' : 'outline'}
            size="small"
            style={styles.periodButton}
          />
        ))}
      </View>

      {revenueData.length > 0 && (
        <Animated.View entering={FadeIn.delay(200)} style={styles.chartContainer}>
          <Card>
            <Text style={[styles.chartTitle, { color: colors.text }]}>Revenue Trend</Text>
            <LineChart
              data={chartData}
              width={screenWidth - 72}
              height={220}
              chartConfig={chartConfig}
              bezier
              style={styles.chart}
              withInnerLines={false}
              withOuterLines={false}
            />
          </Card>
        </Animated.View>
      )}

      <Animated.View entering={FadeIn.delay(300)} style={styles.section}>
        <Text style={[styles.sectionTitle, { color: colors.text }]}>Revenue Sources</Text>
        {revenueData.slice(0, 5).map((item, index) => (
          <Card key={index} style={styles.sourceCard}>
            <View style={styles.sourceItem}>
              <View style={styles.sourceInfo}>
                <Text style={[styles.sourceName, { color: colors.text }]}>{item.source}</Text>
                <Text style={[styles.sourceDate, { color: colors.textSecondary }]}>
                  {new Date(item.date).toLocaleDateString()}
                </Text>
              </View>
              <Text style={[styles.sourceAmount, { color: colors.success }]}>
                ${item.amount.toLocaleString()}
              </Text>
            </View>
          </Card>
        ))}
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
  },
  statsCard: {
    marginHorizontal: 20,
    marginBottom: 20,
  },
  mainStat: {
    alignItems: 'center',
    paddingVertical: 10,
  },
  mainStatLabel: {
    fontSize: 14,
    marginBottom: 8,
  },
  mainStatValue: {
    fontSize: 48,
    fontWeight: '700',
    marginBottom: 8,
  },
  growthContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  growthText: {
    fontSize: 18,
    fontWeight: '600',
  },
  periodSelector: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    marginBottom: 20,
    gap: 8,
  },
  periodButton: {
    flex: 1,
  },
  chartContainer: {
    paddingHorizontal: 20,
    marginBottom: 20,
  },
  chartTitle: {
    fontSize: 18,
    fontWeight: '600',
    marginBottom: 16,
  },
  chart: {
    marginVertical: 8,
    borderRadius: 16,
  },
  section: {
    padding: 20,
  },
  sectionTitle: {
    fontSize: 20,
    fontWeight: '600',
    marginBottom: 16,
  },
  sourceCard: {
    marginBottom: 12,
  },
  sourceItem: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  sourceInfo: {
    flex: 1,
  },
  sourceName: {
    fontSize: 16,
    fontWeight: '600',
    marginBottom: 4,
  },
  sourceDate: {
    fontSize: 14,
  },
  sourceAmount: {
    fontSize: 18,
    fontWeight: '700',
  },
});
