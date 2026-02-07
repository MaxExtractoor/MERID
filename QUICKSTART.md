# MERID v2.0 - Quick Start Guide

**Get MERID running in 5 minutes**

---

## Step 1: Install Flutter (5 min)

### Windows
```powershell
# Download Flutter SDK
# https://flutter.dev/docs/get-started/install/windows

# Extract to C:\src\flutter
# Add to PATH
setx PATH "%PATH%;C:\src\flutter\bin"

# Verify
flutter doctor
```

---

## Step 2: Install Fonts (1 min)

1. Download **JetBrains Mono**: https://www.jetbrains.com/lp/mono/
2. Extract and copy to `C:\Dev\MERID\assets\fonts\`:
   - `JetBrainsMono-Regular.ttf`
   - `JetBrainsMono-Bold.ttf`

---

## Step 3: Install Dependencies (1 min)

```powershell
cd C:\Dev\MERID
flutter pub get
```

---

## Step 4: Run MERID (30 sec)

```powershell
# Development mode
flutter run

# Or build release APK
flutter build apk --release
```

**Output**: `build/app/outputs/flutter-apk/app-release.apk`

---

## 🎮 Quick Test

### Test 1: Status Report
1. Launch app
2. Enter "Status Report" in Distillation Gate
3. Press Enter
4. See raw cognition + distilled output + EKG metrics

### Test 2: Market Exploit
1. Tap "Market Exploit" button
2. Tap "Scan for Exploits"
3. See time-gap detection + front-run simulation

### Test 3: Quantum Mode
1. Tap "Quantum Mode" button
2. Tap "Run QAOA"
3. See quantum vs classical comparison

### Test 4: Lockdown
1. Tap red "LOCKDOWN" button
2. See system freeze + red overlay
3. Tap again to release

---

## 📱 Device/Emulator Setup

### Android Studio
```powershell
# List devices
flutter devices

# Run on connected device
flutter run -d <device-id>
```

### iOS (macOS only)
```bash
open -a Simulator
flutter run
```

---

## 🐛 Troubleshooting

### "Flutter not found"
```powershell
# Add to PATH
setx PATH "%PATH%;C:\src\flutter\bin"
# Restart terminal
```

### "Fonts not loading"
```
1. Check files exist: C:\Dev\MERID\assets\fonts\JetBrainsMono-*.ttf
2. Run: flutter pub get
3. Restart app completely
```

### "Build fails"
```powershell
flutter clean
flutter pub get
flutter run
```

---

## 📚 Learn More

- **Full Documentation**: `README.md`
- **Trading System Guide**: `README_TRADING_SYSTEM.md`
- **Deployment Guide**: `BUILD.md`
- **Build Summary**: `PROJECT_SUMMARY.md`
- **Charter v2.0**: Launch app → Tap "CHARTER v2.0" badge

---

## 💰 Trading System Quick Start

### Backend Server
```powershell
# Install Python dependencies
pip install -r requirements.txt

# Start server
python -m uvicorn web.main:app --host 127.0.0.1 --port 8001 --reload
```

### Access Trading Interfaces
- **Main Dashboard**: http://127.0.0.1:8001/
- **Perps Trading**: http://127.0.0.1:8001/trading/perps
- **Prediction Markets**: http://127.0.0.1:8001/trading/markets
- **Consensus Betting**: http://127.0.0.1:8001/betting

### Paper Trading (Default)
- **Safe testing** with virtual $10,000 balance
- **No real capital** at risk
- **Toggle badge** in perps interface (blue = paper, red = live)
- **Full documentation**: See `README_TRADING_SYSTEM.md`

---

## 🎯 Key Features

- **Bus Hierarchy**: Mixer console with 6 agents, 6 layers, master fader
- **Distillation Gate**: Raw cognition → distilled output + EKG
- **Quantum Sim**: QAOA/VQE optimization with comparison gate
- **Market Exploit**: Time-gap detection + front-run simulation
- **Intuition**: Sentiment divergence + gut feel analysis
- **Manifestation**: 1000-scenario multiverse testing
- **Lockdown**: Freeze all execution (SLP-1)

---

## 🔐 Security

- **No Backend**: Fully offline/local
- **No Cloud**: Zero external dependencies
- **Governance**: All execution gated by human approval
- **Lockdown**: One-tap system freeze
- **Hostile-Default**: All ports treated as compromised

---

**You're ready! Launch MERID v2.0 and explore the control room.**

MERID v2.0 // LOCAL ⚡
