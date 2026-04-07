import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, FlatList, RefreshControl, Alert } from 'react-native';
import { useTheme } from '../contexts/ThemeContext';
import { Card } from '../components/Card';
import { Button } from '../components/Button';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { EmptyState } from '../components/EmptyState';
import { useHaptics } from '../hooks/useHaptics';
import { useOfflineStorage } from '../hooks/useOfflineStorage';
import api from '../services/api';
import { Product } from '../types';
import { Ionicons } from '@expo/vector-icons';
import Animated, { FadeInUp } from 'react-native-reanimated';

export const ProductsScreen: React.FC = () => {
  const { colors } = useTheme();
  const haptics = useHaptics();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const { value: products, setValue: setProducts } = useOfflineStorage<Product[]>('products', []);

  useEffect(() => {
    loadProducts();
  }, []);

  const loadProducts = async () => {
    try {
      const response = await api.getProducts();
      setProducts(response.data);
      haptics.success();
    } catch (error) {
      console.error('Error loading products:', error);
      haptics.error();
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const handleDeploy = () => {
    Alert.alert(
      'Deploy Product',
      'Select an opportunity to deploy as a product',
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Deploy', onPress: () => deployProduct() },
      ]
    );
  };

  const deployProduct = async () => {
    haptics.medium();
    try {
      // In a real app, you'd select an opportunity first
      const response = await api.deployProduct('opportunity-id');
      setProducts([...products, response.data]);
      haptics.success();
      Alert.alert('Success', 'Product deployed successfully!');
    } catch (error) {
      console.error('Error deploying product:', error);
      haptics.error();
      Alert.alert('Error', 'Failed to deploy product');
    }
  };

  const onRefresh = () => {
    setRefreshing(true);
    loadProducts();
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'deployed':
        return 'checkmark-circle';
      case 'draft':
        return 'document-text';
      case 'archived':
        return 'archive';
      default:
        return 'cube';
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'deployed':
        return colors.success;
      case 'draft':
        return colors.warning;
      case 'archived':
        return colors.textSecondary;
      default:
        return colors.primary;
    }
  };

  const renderProduct = ({ item, index }: { item: Product; index: number }) => (
    <Animated.View entering={FadeInUp.delay(index * 100)}>
      <Card style={styles.productCard}>
        <View style={styles.productHeader}>
          <View style={styles.productInfo}>
            <View style={styles.titleRow}>
              <Ionicons
                name={getStatusIcon(item.status)}
                size={20}
                color={getStatusColor(item.status)}
              />
              <Text style={[styles.productTitle, { color: colors.text }]}>{item.name}</Text>
            </View>
            <Text style={[styles.productDescription, { color: colors.textSecondary }]} numberOfLines={2}>
              {item.description}
            </Text>
          </View>
        </View>

        <View style={styles.statsContainer}>
          <View style={styles.statItem}>
            <Ionicons name="cash-outline" size={18} color={colors.success} />
            <View>
              <Text style={[styles.statValue, { color: colors.text }]}>
                ${item.revenue.toLocaleString()}
              </Text>
              <Text style={[styles.statLabel, { color: colors.textSecondary }]}>Revenue</Text>
            </View>
          </View>

          <View style={styles.statItem}>
            <Ionicons name="people-outline" size={18} color={colors.primary} />
            <View>
              <Text style={[styles.statValue, { color: colors.text }]}>
                {item.users.toLocaleString()}
              </Text>
              <Text style={[styles.statLabel, { color: colors.textSecondary }]}>Users</Text>
            </View>
          </View>
        </View>

        <View style={styles.footer}>
          <Text style={[styles.dateText, { color: colors.textSecondary }]}>
            Created {new Date(item.created_at).toLocaleDateString()}
          </Text>
          <View style={[styles.statusBadge, { backgroundColor: getStatusColor(item.status) + '20' }]}>
            <Text style={[styles.statusText, { color: getStatusColor(item.status) }]}>
              {item.status.toUpperCase()}
            </Text>
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
        <Text style={[styles.title, { color: colors.text }]}>Products</Text>
        <Button title="Deploy" onPress={handleDeploy} size="small" />
      </View>

      {products.length === 0 ? (
        <EmptyState
          icon="rocket"
          title="No products yet"
          description="Deploy your first product from an opportunity"
          actionTitle="Deploy Product"
          onAction={handleDeploy}
        />
      ) : (
        <FlatList
          data={products}
          renderItem={renderProduct}
          keyExtractor={(item) => item.id}
          contentContainerStyle={styles.list}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
        />
      )}
    </View>
  );
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
  productCard: {
    marginBottom: 16,
  },
  productHeader: {
    marginBottom: 16,
  },
  productInfo: {
    gap: 8,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  productTitle: {
    fontSize: 18,
    fontWeight: '600',
  },
  productDescription: {
    fontSize: 14,
    lineHeight: 20,
  },
  statsContainer: {
    flexDirection: 'row',
    gap: 24,
    marginBottom: 16,
    paddingVertical: 12,
    borderTopWidth: 1,
    borderBottomWidth: 1,
    borderColor: '#E5E5E5',
  },
  statItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  statValue: {
    fontSize: 16,
    fontWeight: '600',
  },
  statLabel: {
    fontSize: 12,
  },
  footer: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  dateText: {
    fontSize: 12,
  },
  statusBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 4,
  },
  statusText: {
    fontSize: 12,
    fontWeight: '600',
  },
});
