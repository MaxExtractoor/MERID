# MERID v2.0 - Build & Deployment Guide

## Prerequisites

### 1. Install Flutter
```bash
# Windows
# Download Flutter SDK from https://flutter.dev/docs/get-started/install/windows
# Extract to C:\src\flutter
# Add to PATH: C:\src\flutter\bin

# Verify installation
flutter doctor
```

### 2. Install Android Studio (for Android deployment)
- Download from https://developer.android.com/studio
- Install Android SDK
- Accept licenses: `flutter doctor --android-licenses`

### 3. Install Xcode (for iOS deployment - macOS only)
- Download from Mac App Store
- Install command line tools: `xcode-select --install`

### 4. Install Fonts
Download **JetBrains Mono** from:
https://www.jetbrains.com/lp/mono/

Place TTF files in `assets/fonts/`:
- `JetBrainsMono-Regular.ttf`
- `JetBrainsMono-Bold.ttf`

---

## Development

### Install Dependencies
```bash
cd C:\Dev\MERID
flutter pub get
```

### Run on Emulator/Device
```bash
# List available devices
flutter devices

# Run on connected device
flutter run

# Run with hot reload
flutter run --hot
```

### Debug Mode
```bash
# Run with debug output
flutter run --verbose

# Run with DevTools
flutter run --observatory-port=8888
```

---

## Production Build

### Android APK
```bash
# Build release APK
flutter build apk --release

# Build split APKs by ABI (smaller size)
flutter build apk --split-per-abi --release

# Output location
# build/app/outputs/flutter-apk/app-release.apk
```

### Android App Bundle (for Google Play)
```bash
flutter build appbundle --release

# Output location
# build/app/outputs/bundle/release/app-release.aab
```

### iOS
```bash
# Build iOS app (macOS only)
flutter build ios --release

# Build for App Store
flutter build ipa --release

# Output location
# build/ios/iphoneos/Runner.app
# build/ios/ipa/merid.ipa
```

---

## Testing

### Run Unit Tests
```bash
flutter test
```

### Run Widget Tests
```bash
flutter test test/widget_test.dart
```

### Run Integration Tests
```bash
flutter drive --target=test_driver/app.dart
```

---

## Code Quality

### Analyze Code
```bash
flutter analyze
```

### Format Code
```bash
flutter format lib/
```

### Check for Updates
```bash
flutter pub outdated
flutter pub upgrade
```

---

## Platform-Specific Configuration

### Android
Edit `android/app/src/main/AndroidManifest.xml`:
```xml
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.merid.app">
    
    <uses-permission android:name="android.permission.INTERNET"/>
    
    <application
        android:label="MERID"
        android:icon="@mipmap/ic_launcher">
        ...
    </application>
</manifest>
```

Edit `android/app/build.gradle`:
```gradle
android {
    compileSdkVersion 34
    
    defaultConfig {
        applicationId "com.merid.app"
        minSdkVersion 21
        targetSdkVersion 34
        versionCode 1
        versionName "2.0.0"
    }
}
```

### iOS
Edit `ios/Runner/Info.plist`:
```xml
<key>CFBundleDisplayName</key>
<string>MERID</string>
<key>CFBundleVersion</key>
<string>1</string>
<key>CFBundleShortVersionString</key>
<string>2.0.0</string>
```

---

## Troubleshooting

### Common Issues

**Issue**: Flutter not recognized
```bash
# Windows: Add to PATH
setx PATH "%PATH%;C:\src\flutter\bin"
```

**Issue**: Android licenses not accepted
```bash
flutter doctor --android-licenses
```

**Issue**: Gradle build fails
```bash
cd android
./gradlew clean
cd ..
flutter clean
flutter pub get
```

**Issue**: iOS build fails
```bash
cd ios
pod install
cd ..
flutter clean
flutter build ios
```

**Issue**: Fonts not loading
- Verify font files exist in `assets/fonts/`
- Check `pubspec.yaml` has correct font paths
- Run `flutter pub get`
- Restart app completely

---

## Performance Optimization

### Enable ProGuard (Android)
Edit `android/app/build.gradle`:
```gradle
buildTypes {
    release {
        minifyEnabled true
        proguardFiles getDefaultProguardFile('proguard-android.txt'), 'proguard-rules.pro'
    }
}
```

### Reduce APK Size
```bash
# Split APKs by ABI
flutter build apk --split-per-abi --release

# Enable tree shaking
flutter build apk --release --tree-shake-icons
```

### Profile Performance
```bash
flutter run --profile
```

---

## Deployment

### Google Play Store
1. Build app bundle: `flutter build appbundle --release`
2. Upload to Google Play Console
3. Complete store listing
4. Submit for review

### Apple App Store
1. Build IPA: `flutter build ipa --release`
2. Open `build/ios/archive/Runner.xcarchive` in Xcode
3. Distribute to App Store
4. Submit via App Store Connect

---

## Environment Variables

Create `.env` file (ignored by git):
```env
# API Keys (if needed for future features)
QUANTUM_API_KEY=xxx
BLOCKCHAIN_RPC_URL=xxx
```

---

## Continuous Integration

### GitHub Actions (example)
```yaml
name: Build
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: subosito/flutter-action@v2
      - run: flutter pub get
      - run: flutter analyze
      - run: flutter test
      - run: flutter build apk --release
```

---

**MERID v2.0 - Built for Sovereignty**
