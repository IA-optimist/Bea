import React from 'react';
import { View, Text, StyleSheet, ViewStyle } from 'react-native';
import { useTheme } from '../contexts/ThemeContext';

interface StatusBadgeProps {
  status: 'active' | 'pending' | 'completed' | 'draft' | 'deployed' | 'archived';
  style?: ViewStyle;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, style }) => {
  const { colors } = useTheme();

  const getStatusColor = () => {
    switch (status) {
      case 'active':
      case 'deployed':
        return colors.success;
      case 'pending':
      case 'draft':
        return colors.warning;
      case 'completed':
        return colors.primary;
      case 'archived':
        return colors.textSecondary;
      default:
        return colors.primary;
    }
  };

  const color = getStatusColor();

  return (
    <View style={[styles.badge, { backgroundColor: color + '20' }, style]}>
      <View style={[styles.dot, { backgroundColor: color }]} />
      <Text style={[styles.text, { color }]}>{status.toUpperCase()}</Text>
    </View>
  );
};

const styles = StyleSheet.create({
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 12,
    gap: 4,
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  text: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
});
