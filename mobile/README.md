# BeaMax Mobile

Premium React Native Expo mobile app for BeaMax - Autonomous Business Builder.

## Features

### Core Functionality
- **Dashboard**: Overview of opportunities, products, revenue, and growth metrics
- **Opportunities**: Scan and discover new business opportunities
- **Products**: Deploy and manage products
- **Revenue**: Track revenue with interactive charts and analytics
- **Settings**: Configure app preferences, theme, and security

### Premium Features
- **Biometric Authentication**: Face ID / Touch ID support for secure access
- **Push Notifications**: Real-time alerts for opportunities and revenue updates
- **Haptic Feedback**: Enhanced user experience with tactile feedback
- **Offline Support**: AsyncStorage for offline data persistence
- **Dark Mode**: Auto, light, and dark theme support
- **Animations**: Smooth React Native Reanimated animations

### Technical Stack
- React Native with Expo SDK 50
- TypeScript for type safety
- React Navigation (tabs + stack)
- React Native Reanimated for animations
- Axios for API communication
- AsyncStorage for offline storage
- Expo modules for biometric, notifications, haptics

## Installation

```bash
cd /tmp/beamax-master/mobile
npm install
```

## Running the App

```bash
# Start Expo development server
npm start

# Run on iOS simulator
npm run ios

# Run on Android emulator
npm run android

# Run on web browser
npm run web
```

## Project Structure

```
mobile/
├── src/
│   ├── components/       # Reusable UI components
│   │   ├── Button.tsx
│   │   ├── Card.tsx
│   │   ├── LoadingSpinner.tsx
│   │   └── EmptyState.tsx
│   ├── contexts/         # React contexts
│   │   └── ThemeContext.tsx
│   ├── hooks/            # Custom React hooks
│   │   ├── useHaptics.ts
│   │   └── useOfflineStorage.ts
│   ├── navigation/       # Navigation setup
│   │   ├── RootNavigator.tsx
│   │   └── TabNavigator.tsx
│   ├── screens/          # App screens
│   │   ├── DashboardScreen.tsx
│   │   ├── OpportunitiesScreen.tsx
│   │   ├── ProductsScreen.tsx
│   │   ├── RevenueScreen.tsx
│   │   └── SettingsScreen.tsx
│   ├── services/         # API and service clients
│   │   ├── api.ts
│   │   ├── biometric.ts
│   │   └── notifications.ts
│   └── types/            # TypeScript type definitions
│       └── index.ts
├── App.tsx               # App entry point
├── app.json              # Expo configuration
├── package.json          # Dependencies
├── tsconfig.json         # TypeScript configuration
└── babel.config.js       # Babel configuration
```

## API Configuration

The app connects to the backend API at `http://localhost:8000/api/v2/`. Update the base URL in `src/services/api.ts` for production deployments.

## Building for Production

```bash
# Build for iOS
eas build --platform ios

# Build for Android
eas build --platform android
```

## Design Philosophy

The app follows a Linear.app-inspired design with:
- Clean, minimalist interface
- Smooth animations and transitions
- Consistent spacing and typography
- Premium feel with attention to detail
- Dark mode support throughout

## License

MIT License - see LICENSE file for details
