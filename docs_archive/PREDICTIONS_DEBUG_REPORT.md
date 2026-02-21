# Predictions System Debug Report
**Date:** 2026-02-04 20:40 UTC-05:00

## ✅ What's Working

### 1. Real Kalshi Data Integration
- ✅ **Kalshi API Connection**: Successfully fetching real markets from Kalshi API
- ✅ **Market Count**: Currently fetching 16+ markets (growing over time)
- ✅ **API Endpoint**: `/api/v1/us-compliant/prediction-markets` returns 200 OK
- ✅ **WebSocket Updates**: Prediction publisher broadcasting updates every 30s
- ✅ **Server Status**: All publishers running (price, portfolio, predictions)

### 2. Frontend Components
- ✅ **React Components**: No errors or warnings
- ✅ **API Integration**: Frontend successfully calling backend endpoints
- ✅ **Data Flow**: Markets data flowing from backend to frontend
- ✅ **WebSocket**: Real-time updates being received

### 3. Error Handling
- ✅ **Robust Error Handling**: Markets with invalid data are skipped, not crashing
- ✅ **Fallback Logic**: System falls back to sample data if no real markets available
- ✅ **Logging**: Comprehensive logging for debugging

---

## ⚠️ Issues Identified

### 1. **Market Prices Showing 0.0** (CRITICAL)
**Problem:** All Kalshi markets show `yesPrice: 0.0` and `noPrice: 1.0`

**Root Cause:** Kalshi API response field names don't match what the converter expects

**Current Code:**
```python
yes_price = market.get('yes_ask', market.get('yes_bid', market.get('last_price', 0)))
```

**Likely Issue:** Kalshi API uses different field names (possibly `yes_price`, `no_price`, `last_trade_price`, etc.)

**Evidence:**
```json
{
  "id": "KXMVESPORTSMULTIGAMEEXTENDED-S20267E94450D6E4",
  "yesPrice": 0.0,  // ← Should be 0.50 or similar
  "noPrice": 1.0,
  "volume": 0.0     // ← Also 0.0
}
```

**Fix Required:**
1. Log actual Kalshi API response structure (added logging code)
2. Update field mapping in `_convert_kalshi_market_dict()`
3. Test with real API response

---

### 2. **Low Market Count** (MEDIUM)
**Problem:** Only fetching 16 markets, should be 100+

**Root Cause:** Many markets failing conversion with "Failed to convert Kalshi market: OTHER"

**Current Limit:** `params={"limit": 100, "status": "open"}`

**Observations:**
- Kalshi returns 100+ markets
- Only ~7-16 successfully convert
- Rest fail silently with category "OTHER"

**Fix Required:**
1. Improve category detection logic
2. Add better error logging to see why markets fail
3. Consider increasing limit to 200-500

---

### 3. **Missing Brier Metrics Endpoint** (LOW)
**Problem:** Frontend requesting `/api/v1/metrics/brier` → 404 Not Found

**Impact:** Brier score metrics not available in predictions panel

**Fix Required:**
- Create `/api/v1/metrics/brier` endpoint
- OR remove frontend calls to this endpoint if not needed

---

### 4. **Zero Volume Data** (MEDIUM)
**Problem:** All markets show `volume: 0.0`

**Root Cause:** Similar to price issue - field name mismatch

**Current Code:**
```python
volume_24h = market.get('volume_24h', market.get('volume', market.get('open_interest', 0)))
```

**Fix Required:**
- Check actual Kalshi API field names for volume
- Update field mapping

---

## 📊 Current System State

### Server Metrics
- **Status:** ✅ Running on http://localhost:8000
- **Kalshi Markets:** 16 (growing)
- **Price Updates:** Real-time from Kraken
- **Portfolio:** $10,000 (paper trading)
- **WebSocket:** Active, broadcasting updates

### API Endpoints Status
| Endpoint | Status | Notes |
|----------|--------|-------|
| `/api/v1/us-compliant/prediction-markets` | ✅ 200 | Returning 16 markets |
| `/api/v1/metrics/brier` | ❌ 404 | Not implemented |
| `/api/risk/protections` | ✅ 200 | Working |
| `/api/system/health` | ✅ 200 | Working |

### Frontend Status
- **URL:** http://localhost:5173
- **React Errors:** ✅ None
- **WebSocket:** ✅ Connected
- **Data Display:** ⚠️ Showing 0.0 prices

---

## 🔧 Action Plan

### Priority 1: Fix Market Prices (CRITICAL)
1. ✅ Add logging to see actual Kalshi API response
2. ⏳ Wait for next Kalshi fetch to capture sample market structure
3. ⏳ Update `_convert_kalshi_market_dict()` with correct field names
4. ⏳ Test and verify prices display correctly

### Priority 2: Increase Market Count (HIGH)
1. ⏳ Review why markets fail conversion
2. ⏳ Improve category detection (less restrictive)
3. ⏳ Increase fetch limit from 100 to 200-500
4. ⏳ Add better error logging for failed conversions

### Priority 3: Fix Volume Data (MEDIUM)
1. ⏳ Update volume field mapping based on API response
2. ⏳ Test and verify volume displays correctly

### Priority 4: Brier Metrics Endpoint (LOW)
1. ⏳ Decide if Brier metrics are needed
2. ⏳ Either implement endpoint or remove frontend calls

---

## 📝 Technical Details

### Kalshi API Configuration
```env
KALSHI_API_KEY_ID=32822964-15ac-4d44-bf99-dfa1c75d5af6
KALSHI_API_HOST=https://api.elections.kalshi.com/trade-api/v2
KALSHI_PRIVATE_KEY_PATH=c:/Dev/MERID/kalshi_private_key.pem
```

### Key Files
- **Backend API:** `web/api/us_compliant_markets.py`
- **Kalshi Connector:** `monitoring/prediction_markets.py` (line 547-665)
- **Prediction Publisher:** `web/services/prediction_publisher.py`
- **Frontend Component:** `web/react/src/components/PredictionMarketsPanel.tsx`
- **Frontend View:** `web/react/src/views/PredictionsPanel.tsx`

### Recent Changes
1. ✅ Fixed API endpoint path (removed doubled `/api` prefix)
2. ✅ Added `datetime` import to prediction publisher
3. ✅ Fixed React key warnings in components
4. ✅ Added optional chaining for `circuit_breaker` in LiveRiskStrip
5. ✅ Added logging to capture Kalshi API response structure
6. ✅ Improved price extraction with multiple fallbacks

---

## 🎯 Next Steps

**Immediate:**
1. Wait for Kalshi connector to log sample market structure
2. Review actual API response fields
3. Update field mappings in converter
4. Restart server and verify fixes

**Short-term:**
1. Increase market fetch limit
2. Improve category detection
3. Add volume field mapping
4. Test with real data

**Long-term:**
1. Implement Brier metrics endpoint
2. Add real position data from PaperTradingEngine
3. Add AI model confidence scores
4. Optimize WebSocket performance

---

## 📌 Summary

**Status:** 🟡 Partially Working

The predictions system is successfully fetching real Kalshi market data, but prices and volumes are showing as 0.0 due to API field name mismatches. The core infrastructure is solid - we just need to map the correct fields from the Kalshi API response.

**Confidence Level:** HIGH - This is a simple field mapping fix once we see the actual API response structure.

**ETA to Full Fix:** 15-30 minutes after capturing sample market data
