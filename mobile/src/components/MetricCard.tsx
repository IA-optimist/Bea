import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Card } from './Card';
import { useTheme } from '../contexts/ThemeContext';
import Animated, { FadeInDown } from 'react-native-reanimated';

interface MetricCardProps {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  value: string | number;
  color?: string;
  change?: number;
  delay?: number;
  onPress?: () => void;
}

export const MetricCard: React.FC<MetricCardProps> = ({
  icon,
  label,
  value,
  color,
  change,
  delay = 0,
  onPress,
}) => {
  const { colors } = useTheme();
  const metricColor = color || colors.primary;

  return (
    <Animated.View entering={FadeInDown.delay(delay)} style={styles.container}>
      <Card onPress={onPress}>
        <View style={styles.content}>
          <View style={[styles.iconContainer, { backgroundColor: metricColor + '20' }]}>
            <Ionicons name={icon} size={24} color={metricColor} />
          </View>
          <Text style={[styles.value, { color: colors.text }]}>{value}</Text>
          <Text style={[styles.label, { color: colors.textSecondary }]}>{label}</Text>
          {change !== undefined && (
            <View style={styles.changeContainer}>
              <Ionicons
                name={change >= 0 ? 'arrow-up' : 'arrow-down'}
                size={14}
                color={change >= 0 ? colors.success : colors.error}
              />
              <Text
                style={[
                  styles.changeText,
                  { color: change >= 0 ? colors.success : colors.error },
                ]}
              >
                {Math.abs(change)}%
              </Text>
            </View>
          )}
        </View>
      </Card>
    </Animated.View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    minWidth: 150,
  },
  content: {
    alignItems: 'center',
    gap: 8,
  },
  iconContainer: {
    width: 48,
    height: 48,
    borderRadius: 24,
    justifyContent: 'center',
    alignItems: 'center',
  },
  value: {
    fontSize: 28,
    fontWeight: '700',
  },
  label: {
    fontSize: 14,
    fontWeight: '500',
  },
  changeContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 2,
  },
  changeText: {
    fontSize: 12,
    fontWeight: '600',
  },
});
