# Build BeaMax Mobile App

## Environment
- Flutter SDK 3.19+ required
- Android Studio OR Android SDK (API 21+)
- Java 17+

## Install Flutter (Windows)
1. Download: https://flutter.dev/docs/get-started/install/windows
2. Extract to C:\flutter
3. Add C:\flutter\bin to your system PATH
4. Restart terminal
5. Run: flutter doctor

## Build APK

### Debug (for testing)
```
cd beamax_app
flutter pub get
flutter build apk --debug
```
APK path: `build/app/outputs/flutter-apk/app-debug.apk`

### Release
```
flutter build apk --release
```
APK path: `build/app/outputs/flutter-apk/app-release.apk`

## Install on device
```
# Via ADB (USB debug mode)
adb install build/app/outputs/flutter-apk/app-release.apk

# Or transfer the APK file to your phone and open it
```

## Backend connection
- Default URL: `http://10.0.2.2:8000` (Android emulator → localhost)
- Real device: change to your machine's local IP (e.g. `http://192.168.1.X:8000`)
- Configure in app Settings screen → API URL

## API keys needed
- Start backend: `uvicorn api.main:app --port 8000`
- Login: username `admin`, password = your `BEA_SECRET_KEY` from `.env`
