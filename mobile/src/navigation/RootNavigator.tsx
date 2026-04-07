import React, { useEffect, useState } from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createStackNavigator } from '@react-navigation/stack';
import { TabNavigator } from './TabNavigator';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { useTheme } from '../contexts/ThemeContext';
import biometricService from '../services/biometric';
import { View, Text, StyleSheet } from 'react-native';
import { Button } from '../components/Button';

const Stack = createStackNavigator();

const AuthScreen: React.FC<{ onAuthenticate: () => void }> = ({ onAuthenticate }) => {
  const { colors } = useTheme();

  return (
    <View style={[styles.authContainer, { backgroundColor: colors.background }]}>
      <Text style={[styles.authTitle, { color: colors.text }]}>JarvisMax</Text>
      <Text style={[styles.authSubtitle, { color: colors.textSecondary }]}>
        Autonomous Business Builder
      </Text>
      <Button title="Authenticate" onPress={onAuthenticate} style={styles.authButton} />
    </View>
  );
};

export const RootNavigator: React.FC = () => {
  const { colors } = useTheme();
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    checkAuthentication();
  }, []);

  const checkAuthentication = async () => {
    const biometricEnabled = await biometricService.isBiometricEnabled();
    
    if (biometricEnabled) {
      const biometricAvailable = await biometricService.isAvailable();
      
      if (biometricAvailable) {
        const authenticated = await biometricService.authenticate();
        setIsAuthenticated(authenticated);
      } else {
        setIsAuthenticated(true);
      }
    } else {
      setIsAuthenticated(true);
    }
    
    setIsLoading(false);
  };

  const handleAuthenticate = async () => {
    const biometricEnabled = await biometricService.isBiometricEnabled();
    
    if (biometricEnabled) {
      const authenticated = await biometricService.authenticate();
      if (authenticated) {
        setIsAuthenticated(true);
      }
    } else {
      setIsAuthenticated(true);
    }
  };

  if (isLoading) {
    return <LoadingSpinner />;
  }

  return (
    <NavigationContainer
      theme={{
        dark: false,
        colors: {
          primary: colors.primary,
          background: colors.background,
          card: colors.card,
          text: colors.text,
          border: colors.border,
          notification: colors.primary,
        },
      }}
    >
      <Stack.Navigator screenOptions={{ headerShown: false }}>
        {!isAuthenticated ? (
          <Stack.Screen name="Auth">
            {() => <AuthScreen onAuthenticate={handleAuthenticate} />}
          </Stack.Screen>
        ) : (
          <Stack.Screen name="Main" component={TabNavigator} />
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
};

const styles = StyleSheet.create({
  authContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 32,
  },
  authTitle: {
    fontSize: 48,
    fontWeight: '700',
    marginBottom: 8,
  },
  authSubtitle: {
    fontSize: 18,
    marginBottom: 48,
  },
  authButton: {
    paddingHorizontal: 48,
  },
});
