# JarvisMax Mobile - Deployment Guide

## Prerequisites

### Required Tools
- Node.js 18+ and npm
- Expo CLI (`npm install -g expo-cli`)
- EAS CLI (`npm install -g eas-cli`)
- Xcode (for iOS development)
- Android Studio (for Android development)

### Accounts
- Expo account (https://expo.dev)
- Apple Developer account (for iOS)
- Google Play Developer account (for Android)

## Development Setup

### 1. Install Dependencies
```bash
cd /tmp/jarvismax-master/mobile
npm install
```

### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env with your API endpoint
```

### 3. Start Development Server
```bash
npm start
```

### 4. Run on Device/Simulator
```bash
# iOS Simulator
npm run ios

# Android Emulator
npm run android

# Physical device via Expo Go
# Scan QR code from terminal
```

## Building for Production

### iOS Build

#### 1. Configure EAS
```bash
eas login
eas build:configure
```

#### 2. Update app.json
```json
{
  "expo": {
    "ios": {
      "bundleIdentifier": "com.jarvismax.mobile",
      "buildNumber": "1.0.0"
    }
  }
}
```

#### 3. Build for App Store
```bash
# Production build
eas build --platform ios --profile production

# TestFlight build
eas build --platform ios --profile preview
```

#### 4. Submit to App Store
```bash
eas submit --platform ios
```

### Android Build

#### 1. Configure signing
```bash
# Generate keystore
keytool -genkeypair -v -storetype PKCS12 -keystore jarvismax.keystore \
  -alias jarvismax -keyalg RSA -keysize 2048 -validity 10000
```

#### 2. Update app.json
```json
{
  "expo": {
    "android": {
      "package": "com.jarvismax.mobile",
      "versionCode": 1
    }
  }
}
```

#### 3. Build for Play Store
```bash
# Production build
eas build --platform android --profile production

# Internal testing build
eas build --platform android --profile preview
```

#### 4. Submit to Play Store
```bash
eas submit --platform android
```

## Over-the-Air (OTA) Updates

### Publish Update
```bash
# Publish to production
eas update --branch production --message "Bug fixes and improvements"

# Publish to staging
eas update --branch staging --message "New features testing"
```

### Update Strategy
- Minor updates: OTA updates
- Native changes: New build required
- Critical fixes: Fast OTA rollout

## Environment Configuration

### Development
```env
API_BASE_URL=http://localhost:8000/api/v2
ENVIRONMENT=development
```

### Staging
```env
API_BASE_URL=https://staging-api.jarvismax.com/api/v2
ENVIRONMENT=staging
```

### Production
```env
API_BASE_URL=https://api.jarvismax.com/api/v2
ENVIRONMENT=production
```

## Testing

### Manual Testing
1. Test all screens and navigation
2. Verify offline functionality
3. Test biometric authentication
4. Verify push notifications
5. Test on different device sizes
6. Test dark mode

### Automated Testing (Future)
```bash
# Unit tests
npm test

# E2E tests
npm run test:e2e
```

## Monitoring & Analytics

### Crash Reporting
- Setup Sentry for crash tracking
- Monitor error rates
- Track user sessions

### Performance Monitoring
- Track app load time
- Monitor API response times
- Track navigation performance

### Analytics
- Track user engagement
- Monitor feature usage
- A/B testing for new features

## Release Checklist

### Pre-release
- [ ] Update version number in app.json
- [ ] Test on physical devices (iOS and Android)
- [ ] Verify all API endpoints
- [ ] Test offline functionality
- [ ] Verify push notifications
- [ ] Check biometric authentication
- [ ] Test dark mode
- [ ] Review app permissions
- [ ] Update changelog
- [ ] Create release notes

### iOS Release
- [ ] Build with production profile
- [ ] Upload to TestFlight
- [ ] Internal testing
- [ ] External beta testing
- [ ] Submit for App Store review
- [ ] Prepare app store assets (screenshots, description)
- [ ] Submit to App Store

### Android Release
- [ ] Build with production profile
- [ ] Upload to Play Console
- [ ] Internal testing track
- [ ] Closed beta testing
- [ ] Open beta testing (optional)
- [ ] Production rollout (staged)
- [ ] Prepare Play Store assets

### Post-release
- [ ] Monitor crash reports
- [ ] Track analytics
- [ ] Collect user feedback
- [ ] Plan next iteration

## CI/CD Pipeline (GitHub Actions)

### Example Workflow
```yaml
name: Build and Deploy
on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-node@v3
        with:
          node-version: 18
      - run: npm install
      - run: eas build --platform all --non-interactive
```

## Rollback Strategy

### OTA Update Rollback
```bash
# Republish previous version
eas update --branch production --message "Rollback to stable"
```

### Binary Rollback
- Use App Store/Play Console to revert to previous version
- Communicate with users about the issue
- Fix and redeploy

## Best Practices

### Version Management
- Use semantic versioning (MAJOR.MINOR.PATCH)
- Increment buildNumber/versionCode for each build
- Tag releases in Git

### Security
- Never commit .env files
- Rotate API keys regularly
- Use environment-specific credentials
- Enable Play Protect and App Store security

### Performance
- Optimize images before including
- Minimize bundle size
- Use code splitting
- Enable Hermes engine (Android)

### User Experience
- Provide clear update messages
- Test on slow networks
- Handle offline gracefully
- Minimize app size
