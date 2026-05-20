# MERID Live Trading Configuration Status

**Date**: April 28, 2026  
**Status**: CONFIGURED AND READY (Pending API Key)

---

## ✅ What Is Already Fixed

### 1. Environment Variables (.env)
| Setting | Value | Status |
|---------|-------|--------|
| `MERID_ALLOW_LIVE_TRADES` | `true` | ✅ Set |
| `MERID_PM_TRADING_MODE` | `live` | ✅ Set |
| `MERID_PM_LIVE_ENABLED` | `true` | ✅ Set |
| `MERID_TRADE_MODE` | `live` | ✅ Set |
| `MERID_TRADING_MODE` | `live` | ✅ Set |
| `KALSHI_ENV` | `live` | ✅ Set |
| `KALSHI_USE_DEMO` | `false` | ✅ Set |
| `KALSHI_CONFIRM_LIVE` | `1` | ✅ Set |
| `KALSHI_PRIVATE_KEY_PATH` | `c:\Dev\MERID\kalshi_private_key.pem` | ✅ Set |
| `KALSHI_API_KEY_ID` | `550e8400-e29b-41d4-a716-446655440000` | ⚠️ **PLACEHOLDER** |

### 2. Private Key File
- **Path**: `c:\Dev\MERID\kalshi_private_key.pem`
- **Status**: ✅ EXISTS (28 lines, RSA format)
- **Content**: Valid PEM format with RSA PRIVATE KEY header

### 3. Kill Switch
- **File**: `data/risk_kill_switch.json`
- **Status**: ✅ INACTIVE (`"active": false`)
- **Trading**: UNBLOCKED

### 4. Risk Limits
- **MAX_CYCLE_RISK_PCT**: `0.03` (3% per cycle)
- **MAX_TOTAL_RISK_PCT**: `0.08` (8% total exposure)
- **USE_TOPN_ALLOCATOR**: `true` (Top-N allocator enabled)
- **MERID_TOTAL_CAPITAL_USD**: `-1` (Auto-fetches from Kalshi API)

### 5. Mock/Demo Modes Disabled
- `MERID_USE_MOCK_ARB_DATA=false` ✅
- `MERID_USE_DEMO_TRADES=false` ✅
- `MERID_USE_SAMPLE_DATA=false` ✅
- `MERID_USE_MOCK_STREAMS=false` ✅

---

## ⚠️ ONE THING YOU NEED TO DO

### Replace the API Key ID Placeholder

The `.env` file currently has a placeholder API Key ID. You need to replace it with your actual Kalshi API Key ID.

**Current value** (line 45 in `.env`):
```
KALSHI_API_KEY_ID=550e8400-e29b-41d4-a716-446655440000
```

**To get your actual API Key ID**:
1. Go to https://kalshi.com/account
2. Navigate to "API Keys" section
3. Copy your Key ID (looks like a UUID, e.g., `a1b2c3d4-e5f6-7890-abcd-ef1234567890`)

**To fix**:
```bash
# Option 1: Edit .env directly
# Open .env in your editor and replace the placeholder

# Option 2: Use PowerShell to replace it
(Get-Content .env) -replace 'KALSHI_API_KEY_ID=550e8400-e29b-41d4-a716-446655440000', 'KALSHI_API_KEY_ID=YOUR_ACTUAL_KEY_HERE' | Set-Content .env
```

---

## 🔍 Verification Checklist

After you update the API Key ID, verify:

- [ ] `.env` file contains `KALSHI_API_KEY_ID=your_actual_key_here` (not placeholder)
- [ ] `c:\Dev\MERID\kalshi_private_key.pem` exists and contains RSA key
- [ ] All settings in `.env` are correct (see table above)
- [ ] Kill switch is inactive: `data/risk_kill_switch.json` shows `"active": false`

---

## 🚀 How to Start Live Trading

### Step 1: Start the Backend
```bash
python web/main.py
```

### Step 2: Verify Live Readiness
Open browser to:
```
http://127.0.0.1:8011/api/v1/operator/pm-live-readiness
```

Expected response:
```json
{
  "ready_for_live_pm_trading": true,
  "checks": {
    "kalshi_credentials": true,
    "venue_gate": true,
    "risk_limits": true,
    "kill_switch": true
  }
}
```

### Step 3: Start Trading
Once readiness returns `true`, the system will execute **real live orders** when:
- Agent cycles detect valid signals with positive edge
- Risk checks pass (position limits, cycle caps, etc.)
- Kill switch is inactive

---

## 📊 Monitoring Live Trades

When live orders execute, you'll see:

### In Logs:
```
[KALSHI_ORDER_INTENT] ticker=KXBTC... side=yes action=buy count=1 price_cents=52 mode=live
[KALSHI_ORDER_RESULT] ticker=KXBTC... status=filled_live order_id=... filled=1
```

### In UI:
- Dashboard shows LIVE mode badge
- Portfolio shows real positions
- Order history shows live fills

---

## 🛡️ Safety Features Active

The following safety mechanisms are in place:

1. **VenueGate Safety Interlock** - Requires `MERID_ALLOW_LIVE_TRADES=true`
2. **Risk Manager** - 3% cycle risk cap, 8% total exposure cap
3. **Kill Switch** - Can halt all trading instantly via `data/risk_kill_switch.json`
4. **Pre-Trade Gate** - Idempotency and fill awareness
5. **Category Exposure Limits** - Prevents over-concentration
6. **Global Risk Guard** - Shared risk envelope across all callers
7. **Paper Edge Boost Disabled in Live** - Only natural edge used in live mode

---

## 🆘 Emergency Stop

To immediately halt all trading:

```powershell
# Create kill switch file
echo '{"active": true, "reason": "manual_stop", "timestamp": "2026-04-28T00:00:00Z"}' > data/risk_kill_switch.json
```

Or edit `data/risk_kill_switch.json` and set `"active": true`.

---

## 📋 Summary

| Component | Status |
|-----------|--------|
| Environment variables | ✅ All set correctly |
| Private key file | ✅ Exists and valid |
| Kill switch | ✅ Inactive |
| Risk limits | ✅ Configured (3%/8%) |
| API Key ID | ⚠️ **Needs your actual key** |
| **Overall** | **Ready after API key update** |

---

## 📝 Files Modified

1. `.env` - Added Kalshi API credentials section and live trading settings
2. `merid/settings.py` - Added PM trading mode settings
3. `merid/prediction/venue_gate.py` - Updated to use settings
4. `merid/signals/kalshi_signals.py` - Implemented edge signal generation
5. `merid/prediction/model.py` - Fixed edge inclusion and paper boost safety

---

**Next Action**: Update `KALSHI_API_KEY_ID` in `.env` with your actual Kalshi API Key ID, then start the backend and verify readiness.
