import React, { useEffect } from 'react';
import { StatusBar } from 'expo-status-bar';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { ThemeProvider, useTheme } from './src/contexts/ThemeContext';
import { RootNavigator } from './src/navigation/RootNavigator';
import notificationService from './src/services/notifications';
import * as Notifications from 'expo-notifications';

function AppContent() {
  const { isDark } = useTheme();

  useEffect(() => {
    // Request notification permissions
    notificationService.requestPermissions();

    // Setup notification listeners
    const notificationListener = notificationService.setupNotificationListener(
      (notification) => {
        console.log('Notification received:', notification);
      }
    );

    const responseListener = notificationService.setupNotificationResponseListener(
      (response) => {
        console.log('Notification response:', response);
      }
    );

    return () => {
      notificationListener.remove();
      responseListener.remove();
    };
  }, []);

  return (
    <>
      <StatusBar style={isDark ? 'light' : 'dark'} />
      <RootNavigator />
    </>
  );
}

export default function App() {
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <ThemeProvider>
        <AppContent />
      </ThemeProvider>
    </GestureHandlerRootView>
  );
}
