import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, FlatList, RefreshControl } from 'react-native';
import { useTheme } from '../contexts/ThemeContext';
import { Card } from '../components/Card';
import { Button } from '../components/Button';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { EmptyState } from '../components/EmptyState';
import { useHaptics } from '../hooks/useHaptics';
import { useOfflineStorage } from '../hooks/useOfflineStorage';
import api from '../services/api';
import { Opportunity } from '../types';
import { Ionicons } from '@expo/vector-icons';
import Animated, { FadeInRight } from 'react-native-reanimated';

export const OpportunitiesScreen: React.FC = () => {
  const { colors } = useTheme();
  const haptics = useHaptics();
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const { value: opportunities, setValue: setOpportunities } = useOfflineStorage<Opportunity[]>(
    'opportunities',
    []
  );

  useEffect(() => {
    loadOpportunities();
  }, []);

  const loadOpportunities = async () => {
    try {
      const response = await api.getOpportunities();
      setOpportunities(response.data);
      haptics.success();
    } catch (error) {
      console.error('Error loading opportunities:', error);
      haptics.error();
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const handleScan = async () => {
    setScanning(true);
    haptics.medium();
    try {
      const response = await api.scanOpportunities();
      setOpportunities(response.data);
      haptics.success();
    } catch (error) {
      console.error('Error scanning opportunities:', error);
      haptics.error();
    } finally {
      setScanning(false);
    }
  };

  const onRefresh = () => {
    setRefreshing(true);
    loadOpportunities();
  };

  const renderOpportunity = ({ item, index }: { item: Opportunity; index: number }) => (
    <Animated.View entering={FadeInRight.delay(index * 100)}>
      <Card style={styles.opportunityCard}>
        <View style={styles.opportunityHeader}>
          <View style={styles.opportunityInfo}>
            <Text style={[styles.opportunityTitle, { color: colors.text }]}>{item.title}</Text>
            <Text style={[styles.opportunityMarket, { color: colors.textSecondary }]}>
              {item.market}
            </Text>
          </View>
          <View style={[styles.scoreBadge, { backgroundColor: colors.primary + '20' }]}>
            <Text style={[styles.scoreText, { color: colors.primary }]}>{item.score}</Text>
          </View>
        </View>

        <Text style={[styles.opportunityDescription, { color: colors.textSecondary }]} numberOfLines={2}>
          {item.description}
        </Text>

        <View style={styles.opportunityFooter}>
          <View style={styles.revenueContainer}>
            <Ionicons name="cash-outline" size={16} color={colors.success} />
            <Text style={[styles.revenueText, { color: colors.success }]}>
              ${item.potential_revenue.toLocaleString()}
            </Text>
          </View>
          <View style={[styles.statusBadge, { backgroundColor: getStatusColor(item.status, colors) }]}>
            <Text style={styles.statusText}>{item.status.toUpperCase()}</Text>
          </View>
        </View>
      </Card>
    </Animated.View>
  );

  if (loading) {
    return <LoadingSpinner />;
  }

  return (
    <View style={[styles.container, { backgroundColor: colors.background }]}>
      <View style={styles.header}>
        <Text style={[styles.title, { color: colors.text }]}>Opportunities</Text>
        <Button
          title={scanning ? 'Scanning...' : 'Scan'}
          onPress={handleScan}
          loading={scanning}
          size="small"
        />
      </View>

      {opportunities.length === 0 ? (
        <EmptyState
          icon="search"
          title="No opportunities yet"
          description="Scan the market to discover new business opportunities"
          actionTitle="Start Scanning"
          onAction={handleScan}
        />
      ) : (
        <FlatList
          data={opportunities}
          renderItem={renderOpportunity}
          keyExtractor={(item) => item.id}
          contentContainerStyle={styles.list}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
        />
      )}
    </View>
  );
};

const getStatusColor = (status: string, colors: any) => {
  switch (status) {
    case 'active':
      return colors.success + '20';
    case 'pending':
      return colors.warning + '20';
    case 'completed':
      return colors.primary + '20';
    default:
      return colors.surface;
  }
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 20,
    paddingTop: 60,
  },
  title: {
    fontSize: 32,
    fontWeight: '700',
  },
  list: {
    padding: 20,
    paddingTop: 0,
  },
  opportunityCard: {
    marginBottom: 16,
  },
  opportunityHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 8,
  },
  opportunityInfo: {
    flex: 1,
  },
  opportunityTitle: {
    fontSize: 18,
    fontWeight: '600',
    marginBottom: 4,
  },
  opportunityMarket: {
    fontSize: 14,
  },
  scoreBadge: {
    width: 48,
    height: 48,
    borderRadius: 24,
    justifyContent: 'center',
    alignItems: 'center',
  },
  scoreText: {
    fontSize: 18,
    fontWeight: '700',
  },
  opportunityDescription: {
    fontSize: 14,
    lineHeight: 20,
    marginBottom: 12,
  },
  opportunityFooter: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  revenueContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  revenueText: {
    fontSize: 16,
    fontWeight: '600',
  },
  statusBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 4,
  },
  statusText: {
    fontSize: 12,
    fontWeight: '600',
    color: '#FFFFFF',
  },
});
