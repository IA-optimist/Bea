import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, Switch, Alert } from 'react-native';
import { useTheme } from '../contexts/ThemeContext';
import { Card } from '../components/Card';
import { Button } from '../components/Button';
import { useHaptics } from '../hooks/useHaptics';
import biometricService from '../services/biometric';
import notificationService from '../services/notifications';
import { Ionicons } from '@expo/vector-icons';
import Animated, { FadeInLeft } from 'react-native-reanimated';

export const SettingsScreen: React.FC = () => {
  const { colors, theme, setTheme, isDark } = useTheme();
  const haptics = useHaptics();
  const [biometricEnabled, setBiometricEnabled] = useState(false);
  const [biometricAvailable, setBiometricAvailable] = useState(false);
  const [notificationsEnabled, setNotificationsEnabled] = useState(true);

  useEffect(() => {
    loadSettings();
  }, []);

  const loadSettings = async () => {
    const biometricAvail = await biometricService.isAvailable();
    setBiometricAvailable(biometricAvail);

    const biometricEn = await biometricService.isBiometricEnabled();
    setBiometricEnabled(biometricEn);

    const notifEn = await notificationService.isNotificationsEnabled();
    setNotificationsEnabled(notifEn);
  };

  const handleBiometricToggle = async (value: boolean) => {
    if (value) {
      const authenticated = await biometricService.authenticate('Enable biometric authentication');
      if (authenticated) {
        await biometricService.setBiometricEnabled(true);
        setBiometricEnabled(true);
        haptics.success();
        Alert.alert('Success', 'Biometric authentication enabled');
      } else {
        haptics.error();
      }
    } else {
      await biometricService.setBiometricEnabled(false);
      setBiometricEnabled(false);
      haptics.light();
    }
  };

  const handleNotificationsToggle = async (value: boolean) => {
    if (value) {
      const granted = await notificationService.requestPermissions();
      if (granted) {
        await notificationService.setNotificationsEnabled(true);
        setNotificationsEnabled(true);
        haptics.success();
      } else {
        haptics.error();
        Alert.alert('Permission Required', 'Please enable notifications in system settings');
      }
    } else {
      await notificationService.setNotificationsEnabled(false);
      setNotificationsEnabled(false);
      haptics.light();
    }
  };

  const handleThemeChange = (newTheme: 'light' | 'dark' | 'auto') => {
    setTheme(newTheme);
    haptics.light();
  };

  const handleTestNotification = async () => {
    haptics.medium();
    await notificationService.scheduleLocalNotification(
      'BeaMax',
      'This is a test notification!',
      1
    );
    Alert.alert('Success', 'Test notification scheduled');
  };

  const SettingItem: React.FC<{
    icon: keyof typeof Ionicons.glyphMap;
    title: string;
    description?: string;
    children: React.ReactNode;
    delay?: number;
  }> = ({ icon, title, description, children, delay = 0 }) => (
    <Animated.View entering={FadeInLeft.delay(delay)}>
      <Card style={styles.settingCard}>
        <View style={styles.settingHeader}>
          <View style={styles.settingInfo}>
            <View style={styles.settingTitleRow}>
              <Ionicons name={icon} size={20} color={colors.primary} />
              <Text style={[styles.settingTitle, { color: colors.text }]}>{title}</Text>
            </View>
            {description && (
              <Text style={[styles.settingDescription, { color: colors.textSecondary }]}>
                {description}
              </Text>
            )}
          </View>
          {children}
        </View>
      </Card>
    </Animated.View>
  );

  return (
    <ScrollView style={[styles.container, { backgroundColor: colors.background }]}>
      <View style={styles.header}>
        <Text style={[styles.title, { color: colors.text }]}>Settings</Text>
      </View>

      <View style={styles.section}>
        <Text style={[styles.sectionTitle, { color: colors.text }]}>Appearance</Text>
        
        <SettingItem
          icon="color-palette"
          title="Theme"
          description="Choose your preferred color scheme"
          delay={100}
        >
          <View style={styles.themeButtons}>
            <Button
              title="Light"
              onPress={() => handleThemeChange('light')}
              variant={theme === 'light' ? 'primary' : 'outline'}
              size="small"
              style={styles.themeButton}
            />
            <Button
              title="Dark"
              onPress={() => handleThemeChange('dark')}
              variant={theme === 'dark' ? 'primary' : 'outline'}
              size="small"
              style={styles.themeButton}
            />
            <Button
              title="Auto"
              onPress={() => handleThemeChange('auto')}
              variant={theme === 'auto' ? 'primary' : 'outline'}
              size="small"
              style={styles.themeButton}
            />
          </View>
        </SettingItem>
      </View>

      <View style={styles.section}>
        <Text style={[styles.sectionTitle, { color: colors.text }]}>Security</Text>
        
        <SettingItem
          icon="finger-print"
          title="Biometric Authentication"
          description={
            biometricAvailable
              ? 'Use Face ID or Touch ID to unlock the app'
              : 'Biometric authentication not available on this device'
          }
          delay={200}
        >
          <Switch
            value={biometricEnabled}
            onValueChange={handleBiometricToggle}
            disabled={!biometricAvailable}
            trackColor={{ false: colors.border, true: colors.primary }}
            thumbColor="#FFFFFF"
          />
        </SettingItem>
      </View>

      <View style={styles.section}>
        <Text style={[styles.sectionTitle, { color: colors.text }]}>Notifications</Text>
        
        <SettingItem
          icon="notifications"
          title="Push Notifications"
          description="Receive alerts about opportunities and revenue"
          delay={300}
        >
          <Switch
            value={notificationsEnabled}
            onValueChange={handleNotificationsToggle}
            trackColor={{ false: colors.border, true: colors.primary }}
            thumbColor="#FFFFFF"
          />
        </SettingItem>

        {notificationsEnabled && (
          <Animated.View entering={FadeInLeft.delay(400)}>
            <Card style={styles.settingCard}>
              <Button
                title="Test Notification"
                onPress={handleTestNotification}
                variant="outline"
                size="small"
              />
            </Card>
          </Animated.View>
        )}
      </View>

      <View style={styles.section}>
        <Text style={[styles.sectionTitle, { color: colors.text }]}>About</Text>
        
        <SettingItem icon="information-circle" title="Version" delay={500}>
          <Text style={[styles.versionText, { color: colors.textSecondary }]}>1.0.0</Text>
        </SettingItem>

        <SettingItem icon="logo-github" title="Open Source" delay={600}>
          <Ionicons name="chevron-forward" size={20} color={colors.textSecondary} />
        </SettingItem>
      </View>

      <View style={styles.section}>
        <Button title="Sign Out" onPress={() => Alert.alert('Sign Out', 'Are you sure?')} variant="danger" />
      </View>
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
  section: {
    padding: 20,
    paddingTop: 0,
  },
  sectionTitle: {
    fontSize: 20,
    fontWeight: '600',
    marginBottom: 16,
    marginTop: 16,
  },
  settingCard: {
    marginBottom: 12,
  },
  settingHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  settingInfo: {
    flex: 1,
    marginRight: 12,
  },
  settingTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 4,
  },
  settingTitle: {
    fontSize: 16,
    fontWeight: '600',
  },
  settingDescription: {
    fontSize: 14,
    lineHeight: 18,
  },
  themeButtons: {
    flexDirection: 'row',
    gap: 8,
  },
  themeButton: {
    minWidth: 60,
  },
  versionText: {
    fontSize: 14,
    fontWeight: '500',
  },
});
