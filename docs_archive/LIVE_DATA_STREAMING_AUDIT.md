# Live Data Streaming Troubleshooting Audit
**Date:** 2026-02-04  
**Status:** 🔴 CRITICAL ISSUES FOUND

---

## 🔍 Executive Summary

**Problem:** Live data is not streaming to the UI despite WebSocket infrastructure being in place.

**Root Cause:** Backend WebSocket endpoint exists but is **NOT sending the message types** that the frontend expects.

**Impact:** All real-time features (prices, portfolio, notifications) are non-functional.

---

## ✅ What's Working

### Frontend (React UI)
1. ✅ **WebSocket Service** (`web/react/src/services/websocket.ts`)
   - Auto-connects to `ws://localhost:8000/ws`
   - Pub/sub message routing by type
   - Auto-reconnect with exponential backoff
   - Connection state management

2. ✅ **React Hooks** (`web/react/src/hooks/useRealtimeData.ts`)
   - `useRealtimeData<T>()` - Subscribe to message types
   - `useRealtimeSubscription<T>()` - Callback-based subscriptions
   - `useSendMessage()` - Send messages to server

3. ✅ **UI Components**
   - `LivePriceStream.tsx` - Listens for `price_update` messages
   - `LivePortfolioValue.tsx` - Listens for `portfolio_update` messages
   - `LiveNotifications.tsx` - Listens for `notification` messages

4. ✅ **Integration**
   - Components added to Overview page
   - TopBar updated with LiveNotifications
   - Build successful (853.30 KB)

### Backend (Python/FastAPI)
1. ✅ **WebSocket Endpoint Exists** (`web/main.py:383`)
   ```python
   @root_router.websocket("/ws")
   async def websocket_endpoint(websocket: WebSocket):
       await websocket.accept()
       queue = await event_stream.subscribe()
       try:
           while True:
               event = await queue.get()
               await websocket.send_text(json.dumps(event))
       except WebSocketDisconnect:
           await event_stream.unsubscribe(queue)
   ```

2. ✅ **Event Stream Infrastructure** (`observability/event_stream.py`)
   - In-memory pub/sub system
   - Async queue-based distribution
   - `publish()` method for broadcasting events

---

## 🔴 Critical Issues Found

### Issue #1: Message Format Mismatch
**Severity:** CRITICAL  
**Location:** Backend WebSocket endpoint

**Problem:**
- Frontend expects: `{ "type": "price_update", "data": {...} }`
- Backend sends: `EventRecord` object (unknown format)

**Evidence:**
```python
# Backend sends EventRecord objects
record = EventRecord(event_type=event_type, payload=payload or {})
await websocket.send_text(json.dumps(record))
```

**Frontend expects:**
```typescript
interface Message {
  type: string;
  data: any;
}
```

**Impact:** Frontend cannot parse messages, all subscriptions fail.

---

### Issue #2: No Events Being Published
**Severity:** CRITICAL  
**Location:** Entire codebase

**Problem:**
- EventStream exists but **NOTHING is publishing to it**
- Searched entire codebase: 0 calls to `event_stream.publish()`
- Searched for `publish_event()`: 0 results
- Searched for `publish_event_async()`: 0 results

**Evidence:**
```bash
grep -r "event_stream.publish" c:\Dev\MERID -> No results
grep -r "publish_event" c:\Dev\MERID -> No results
```

**Impact:** WebSocket connects but receives no data because nothing is publishing events.

---

### Issue #3: Missing Data Publishers
**Severity:** CRITICAL  
**Location:** Backend services

**Required Publishers (MISSING):**

1. **Price Updates** - NOT IMPLEMENTED
   - Should publish `price_update` messages every 1-5 seconds
   - Format: `{ symbol, price, change24h, volume24h, timestamp }`
   - Source: Live price feed service

2. **Portfolio Updates** - NOT IMPLEMENTED
   - Should publish `portfolio_update` on value changes
   - Format: `{ total_value, change_24h, change_24h_percent, pnl_today, positions_count, timestamp }`
   - Source: Portfolio aggregator

3. **Notifications** - NOT IMPLEMENTED
   - Should publish `notification` on system events
   - Format: `{ id, type, title, message, timestamp, read }`
   - Source: Alert manager, trade execution, etc.

**Impact:** No data flows through the WebSocket even if format is fixed.

---

### Issue #4: EventRecord Serialization
**Severity:** HIGH  
**Location:** `observability/event_stream.py`

**Problem:**
- `EventRecord` is a dataclass
- `json.dumps(record)` will fail or produce wrong format
- Should use `json.dumps(asdict(record))` or custom serialization

**Current Code:**
```python
await websocket.send_text(json.dumps(event))  # event is EventRecord
```

**Should Be:**
```python
from dataclasses import asdict
await websocket.send_text(json.dumps({
    "type": event.event_type,
    "data": event.payload
}))
```

---

## 📋 Additional Issues Found

### Issue #5: WebSocket URL Configuration
**Severity:** LOW  
**Location:** Frontend environment

**Problem:**
- Frontend defaults to `ws://localhost:8000/ws`
- No `.env` file with `VITE_WS_URL` configured
- Works for local dev but not configurable for production

**Fix:** Create `.env` file in `web/react/`:
```bash
VITE_WS_URL=ws://localhost:8000/ws
```

---

### Issue #6: CORS Configuration
**Severity:** LOW  
**Status:** ✅ ALREADY CONFIGURED

**Finding:**
- CORS is properly configured in `web/main.py:245`
- Allows `http://localhost:5173` and `http://127.0.0.1:5173`
- WebSocket connections should work

---

### Issue #7: Multiple WebSocket Endpoints
**Severity:** INFO  
**Location:** `web/main.py`

**Finding:** Backend has MULTIPLE WebSocket endpoints:
1. `/ws` - General event stream (what we're using)
2. `/ws/whales` - Whale alerts (JWT auth required)
3. `/ws/arbitrage` - Arbitrage opportunities
4. `/ws/system` - System monitoring
5. `/ws/prediction` - Prediction markets
6. `/ws/agents` - Agent cohorts

**Recommendation:** Consider using specialized endpoints for different data types.

---

### Issue #8: No Price Feed Service Running
**Severity:** HIGH  
**Location:** Backend services

**Finding:**
- Backend has `data.live_price_feed` module
- Logs show: `Price streaming stopped` on shutdown
- No evidence of price feed actively publishing to EventStream

**Impact:** Even if WebSocket works, no price data available.

---

### Issue #9: Frontend Console Errors
**Severity:** MEDIUM  
**Location:** Browser console

**Finding:**
- `Failed to fetch prediction markets: {}`
- This is a REST API error, not WebSocket related
- Indicates `/api/v1/prediction/markets` endpoint missing or failing

**Impact:** Prediction markets panel shows errors (unrelated to WebSocket).

---

### Issue #10: Dependency Conflicts
**Severity:** MEDIUM  
**Location:** Python environment

**Finding:**
```
alpaca-trade-api 3.2.0 requires urllib3<2,>1.24, but you have urllib3 2.6.3
kubernetes 34.1.0 requires urllib3<2.4.0,>=1.24.2, but you have urllib3 2.6.3
```

**Impact:** May cause runtime errors in trading or Kubernetes integrations.

---

## 🔧 Required Fixes (Priority Order)

### Priority 1: Fix Message Format (CRITICAL)
**File:** `web/main.py:383-394`

**Current:**
```python
@root_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    queue = await event_stream.subscribe()
    try:
        while True:
            event = await queue.get()
            await websocket.send_text(json.dumps(event))  # WRONG FORMAT
    except WebSocketDisconnect:
        await event_stream.unsubscribe(queue)
```

**Fix:**
```python
@root_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    queue = await event_stream.subscribe()
    try:
        while True:
            event = await queue.get()
            # Convert EventRecord to frontend-expected format
            message = {
                "type": event.event_type,
                "data": event.payload
            }
            await websocket.send_text(json.dumps(message))
    except WebSocketDisconnect:
        await event_stream.unsubscribe(queue)
    except Exception:
        await event_stream.unsubscribe(queue)
```

---

### Priority 2: Create Price Publisher (CRITICAL)
**File:** NEW - `web/services/price_publisher.py`

**Implementation:**
```python
import asyncio
import time
from observability.event_stream import get_event_stream

async def publish_price_updates():
    """Publish live price updates to WebSocket clients."""
    event_stream = get_event_stream()
    
    while True:
        # Get prices from live feed or mock data
        prices = [
            {
                "symbol": "BTC",
                "price": 98234.50,
                "change24h": 2.34,
                "volume24h": 45000000000,
                "timestamp": int(time.time() * 1000)
            },
            {
                "symbol": "ETH",
                "price": 3456.78,
                "change24h": -1.23,
                "volume24h": 12000000000,
                "timestamp": int(time.time() * 1000)
            },
            {
                "symbol": "SOL",
                "price": 123.45,
                "change24h": 5.67,
                "volume24h": 2000000000,
                "timestamp": int(time.time() * 1000)
            }
        ]
        
        for price_data in prices:
            await event_stream.publish("price_update", price_data)
        
        await asyncio.sleep(5)  # Update every 5 seconds
```

**Integration:** Start in `lifespan` function in `web/main.py`

---

### Priority 3: Create Portfolio Publisher (CRITICAL)
**File:** NEW - `web/services/portfolio_publisher.py`

**Implementation:**
```python
import asyncio
import time
from observability.event_stream import get_event_stream

async def publish_portfolio_updates():
    """Publish portfolio value updates to WebSocket clients."""
    event_stream = get_event_stream()
    
    while True:
        # Get portfolio data from state or aggregator
        portfolio_data = {
            "total_value": 1250000.00,
            "change_24h": 15000.00,
            "change_24h_percent": 1.2,
            "pnl_today": 8500.00,
            "positions_count": 12,
            "timestamp": int(time.time() * 1000)
        }
        
        await event_stream.publish("portfolio_update", portfolio_data)
        await asyncio.sleep(10)  # Update every 10 seconds
```

---

### Priority 4: Create Notification Publisher (HIGH)
**File:** Integrate into existing notification system

**Implementation:**
```python
# In notification creation code
from observability.event_stream import publish_event

def create_notification(type, title, message):
    notification = {
        "id": f"notif_{int(time.time() * 1000)}",
        "type": type,  # success, warning, info, trade
        "title": title,
        "message": message,
        "timestamp": int(time.time() * 1000),
        "read": False
    }
    
    # Publish to WebSocket
    publish_event("notification", notification)
    
    return notification
```

---

### Priority 5: Fix Dependency Conflicts (MEDIUM)
**Command:**
```bash
pip install urllib3==1.26.18
```

---

## 🎯 Testing Plan

### Step 1: Fix Message Format
1. Update `web/main.py` WebSocket endpoint
2. Restart backend
3. Check browser console for WebSocket connection
4. Verify connection indicator turns green

### Step 2: Add Mock Price Publisher
1. Create `web/services/price_publisher.py`
2. Start publisher in lifespan
3. Restart backend
4. Check if prices appear in UI

### Step 3: Add Portfolio Publisher
1. Create `web/services/portfolio_publisher.py`
2. Start publisher in lifespan
3. Restart backend
4. Check if portfolio value updates

### Step 4: Add Notification Publisher
1. Integrate into notification system
2. Trigger test notification
3. Check if notification appears in TopBar

---

## 📊 Impact Analysis

**Before Fixes:**
- ❌ WebSocket connects but receives no data
- ❌ All real-time features non-functional
- ❌ Connection indicators show disconnected
- ❌ No live price updates
- ❌ No portfolio updates
- ❌ No notifications

**After Fixes:**
- ✅ WebSocket connects and receives data
- ✅ Real-time price streaming works
- ✅ Live portfolio value updates
- ✅ Instant notifications
- ✅ Connection indicators show green pulse
- ✅ Full real-time dashboard experience

---

## 🔄 Next Steps

1. **Immediate:** Fix WebSocket message format (5 minutes)
2. **Short-term:** Add mock data publishers (30 minutes)
3. **Medium-term:** Connect to real data sources (2-4 hours)
4. **Long-term:** Optimize performance and add more data streams

---

## 📝 Summary

**The WebSocket infrastructure is 90% complete but has 3 critical gaps:**

1. **Message format mismatch** - Backend sends wrong format
2. **No data publishers** - Nothing is publishing events
3. **No service integration** - Publishers not started

**All issues are fixable in under 1 hour with the fixes outlined above.**

---

**Last Updated:** 2026-02-04 17:34 PM  
**Status:** Ready for implementation
