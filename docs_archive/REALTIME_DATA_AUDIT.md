# Real-Time Data Implementation Audit & Fix Plan

**Date:** 2026-02-04 18:58 PM  
**Status:** 🔴 Critical Issues Found - Real Data Not Flowing

---

## 🔍 Current Issues Identified

### 1. **WebSocket Data Not Reaching Frontend** (CRITICAL)
- **Status:** Publishers running, but UI shows "Real data unavailable"
- **Root Cause:** EventStream publishing but messages not reaching WebSocket clients
- **Impact:** No live prices, portfolio updates, or real-time data in UI

### 2. **Missing REST API Endpoints** (HIGH)
- `/api/system/health` - 404
- `/api/risk/pnl-summary` - 404
- `/api/trading/summary` - 404
- `/api/prime/status` - 404
- `/api/agents/summary` - 404
- `/api/risk/protections` - 404

### 3. **Live Trading Page** (HIGH)
- Shows "Real data unavailable"
- No live price updates
- WebSocket status shows "Offline"

### 4. **Social Media Agents** (MEDIUM)
- Twitter agent not enabled
- Telegram agent not enabled

---

## 📋 Priority Fix List

### Priority 1: Fix WebSocket Data Flow (CRITICAL)
1. ✅ Verify publishers are running (CONFIRMED)
2. ⚠️ Check EventStream is publishing messages
3. ⚠️ Verify WebSocket endpoint receives EventStream messages
4. ⚠️ Test message format matches frontend expectations
5. ⚠️ Add logging to track message flow

### Priority 2: Fix Live Prices Display (CRITICAL)
1. Verify frontend WebSocket service connects
2. Check message parsing in websocket.ts
3. Ensure LivePriceStream component receives data
4. Fix data binding in UI components

### Priority 3: Implement Missing REST Endpoints (HIGH)
1. `/api/system/health` - System health status
2. `/api/risk/pnl-summary` - P&L summary
3. `/api/trading/summary` - Trading operations summary
4. `/api/prime/status` - Prime screen status
5. `/api/agents/summary` - Agent status summary
6. `/api/risk/protections` - Risk protection settings

### Priority 4: Enable Social Media Agents (MEDIUM)
1. Enable Twitter agent
2. Configure Twitter API credentials
3. Enable Telegram agent
4. Configure Telegram bot credentials

### Priority 5: End-to-End Testing (LOW)
1. Test all WebSocket connections
2. Verify all REST endpoints
3. Test UI component data binding
4. Performance testing

---

## 🔧 Detailed Fix Plan

### Fix 1: WebSocket Message Flow

**Problem:** Publishers are running but messages not reaching frontend

**Investigation Steps:**
1. Add debug logging to EventStream.publish()
2. Add debug logging to WebSocket endpoint
3. Verify queue.get() receives messages
4. Check message serialization

**Expected Fix:**
- Add logging to track message flow
- Verify EventStream → WebSocket → Frontend path
- Fix any serialization issues

### Fix 2: Frontend WebSocket Integration

**Problem:** UI components show "Real data unavailable"

**Investigation Steps:**
1. Check browser console for WebSocket messages
2. Verify websocketService.subscribe() is called
3. Check message parsing in handleMessage()
4. Verify component state updates

**Expected Fix:**
- Ensure components subscribe to correct message types
- Fix any message parsing issues
- Update component state on message receipt

### Fix 3: REST API Endpoints

**Problem:** Multiple 404 errors for missing endpoints

**Implementation:**
```python
# web/api/system_endpoints.py (NEW FILE)
@router.get("/api/system/health")
async def get_system_health():
    return {
        "status": "healthy",
        "uptime": get_uptime(),
        "services": get_service_status()
    }

@router.get("/api/risk/pnl-summary")
async def get_pnl_summary():
    return {
        "total_pnl": calculate_total_pnl(),
        "daily_pnl": calculate_daily_pnl(),
        "positions": get_active_positions()
    }
```

### Fix 4: Social Media Agents

**Twitter Agent:**
```python
# Enable in main.py or agents config
twitter_agent = TwitterAgent(
    api_key=os.getenv("TWITTER_API_KEY"),
    api_secret=os.getenv("TWITTER_API_SECRET")
)
await twitter_agent.start()
```

**Telegram Agent:**
```python
# Enable in main.py or agents config
telegram_agent = TelegramAgent(
    bot_token=os.getenv("TELEGRAM_BOT_TOKEN")
)
await telegram_agent.start()
```

---

## 🎯 Success Criteria

### WebSocket Data Flow
- ✅ Publishers running and publishing every 5-10 seconds
- ⚠️ EventStream receiving and broadcasting messages
- ⚠️ WebSocket endpoint sending messages to clients
- ⚠️ Frontend receiving and parsing messages
- ⚠️ UI components displaying real-time data

### REST API Endpoints
- ⚠️ All endpoints return 200 OK
- ⚠️ Data is accurate and up-to-date
- ⚠️ Response times < 100ms

### UI Components
- ⚠️ Live Prices showing real-time updates
- ⚠️ Portfolio value updating every 10 seconds
- ⚠️ Trading page showing live data
- ⚠️ No "Real data unavailable" messages

### Social Media Agents
- ⚠️ Twitter agent posting updates
- ⚠️ Telegram bot responding to commands

---

## 📊 Current Status

**Publishers:** ✅ Running  
**EventStream:** ⚠️ Unknown  
**WebSocket Endpoint:** ⚠️ Unknown  
**Frontend WebSocket:** ⚠️ Connected but no data  
**UI Components:** ❌ No real data  
**REST Endpoints:** ❌ Missing  
**Social Agents:** ❌ Disabled  

---

## 🚀 Execution Order

1. **IMMEDIATE:** Debug WebSocket message flow
2. **IMMEDIATE:** Fix frontend data display
3. **HIGH:** Implement missing REST endpoints
4. **MEDIUM:** Enable social media agents
5. **LOW:** End-to-end testing

---

**Next Action:** Start debugging WebSocket message flow to identify where messages are getting lost between publishers and frontend.
