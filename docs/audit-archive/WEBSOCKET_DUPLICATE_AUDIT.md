# WebSocket Duplicate Services Audit Report

**Date:** 2026-06-24
**Issue:** User observed "two websocket services" in logs
**Scope:** Identify all WebSocket services and conflicts

## Executive Summary

Found 3 distinct WebSocket-related services in the codebase:
1. **KalshiWebSocketService** (LEGACY - should NOT be used in production)
2. **KalshiWebSocketBridge** (PRODUCTION - used for 15m trading)
3. **WebSocketFeedManager** (GENERIC - used for general subscriptions)

## WebSocket Services Inventory

### 1. KalshiWebSocketService (LEGACY)
**File:** `merid/event_venues/kalshi/websocket_service.py`
**Status:** ⚠️ LEGACY - DEV ONLY - NOT FOR PRODUCTION

**Purpose:**
- Background service managing Kalshi WebSocket connections
- Market subscription management
- Orderbook state maintenance
- Event distribution to subscribers

**Singleton Functions:**
- `get_websocket_service()` - Returns singleton instance
- `start_websocket_service()` - Starts and returns service

**Usage in Codebase:**
- `investigate_crypto_markets.py` - Diagnostic script only
- `time_audit_report.md` - Documentation reference
- `docs/WEBSOCKET_ARCHITECTURE.md` - Documentation

**Startup Validation:**
```python
# merid/startup_validations.py line 2773-2779
# Kalshi WS stack: websocket_service trade channel is a stub — live should use ws.py client.
ws_impl = os.getenv("MERID_KALSHI_WS_CLIENT", "ws").strip().lower()
if pm_mode == "live" and ws_impl == "websocket_service":
    errors.append(
        "MERID_KALSHI_WS_CLIENT=websocket_service is unsafe for live trading "
        "(trade events are not fully handled). Set MERID_KALSHI_WS_CLIENT=ws."
    )
```

**Settings:**
```python
# merid/settings.py line 440-443
MERID_KALSHI_WS_CLIENT: str = Field(
    default="ws",
    description="Kalshi websocket implementation: ws (required for live) or websocket_service (dev only)",
)
```

**Production Comment:**
```python
# web/api/kalshi_grid_api.py line 338
# KalshiWebSocketService is a separate monitoring service and should NOT be used for market data
```

### 2. KalshiWebSocketBridge (PRODUCTION)
**File:** `merid/event_venues/kalshi/ws_bridge.py`
**Status:** ✅ PRODUCTION - Used for 15m trading

**Purpose:**
- Pipes Kalshi WS events into MERID's event bus
- Forwards orderbook_delta, orderbook_snapshot, fill events
- Bounded async queue with backpressure
- Health monitoring and circuit breaker

**Usage in Codebase:**
- `web/main_15m_lean.py` - Production 15m startup
- `web/api/kalshi_grid_api.py` - Health checks
- `merid/loop_15m.py` - 15m trading loop

**Startup:**
```python
# web/main_15m_lean.py line 2357
app.state.ws_bridge_task = asyncio.create_task(ws_bridge.start(initial_tickers), name="ws_bridge_start")
```

**Shutdown:**
```python
# web/main_15m_lean.py line 380-385
ws = getattr(app.state, "ws_bridge", None)
if ws is not None:
    logger.info("[SHUTDOWN] Closing WebSocket bridge")
    if hasattr(ws, "close"):
        await ws.close()
```

### 3. WebSocketFeedManager (GENERIC)
**File:** `data/websocket_feed_manager.py`
**Status:** ✅ GENERIC - Used for general subscriptions

**Purpose:**
- Generic WebSocket subscription manager
- Handles multiple WebSocket connections
- Subscription handler management

**Singleton Function:**
- `get_websocket_feed_manager()` - Returns singleton instance

**Usage in Codebase:**
- Used for general WebSocket feed management
- Not specific to Kalshi

### 4. KalshiWebSocket (LOW-LEVEL CLIENT)
**File:** `merid/event_venues/kalshi/ws.py`
**Status:** ✅ LOW-LEVEL CLIENT - Used by both services

**Purpose:**
- Low-level WebSocket client for Kalshi
- Exponential backoff + jitter on reconnect
- Error-type message handling
- Sequence tracking & gap detection
- Async message queue

**Usage:**
- Used by KalshiWebSocketService (legacy)
- Used by KalshiWebSocketBridge (production)

## Conflicts and Issues

### Issue #1: Potential Confusion Between Services
**Problem:** Two services with similar names and purposes can cause confusion.

**Impact:**
- Developers might accidentally use legacy service
- Logs might show both services running
- Diagnostic scripts might start legacy service

**Current Safeguards:**
- Startup validation prevents websocket_service in live mode
- Comments in code warn against using legacy service
- Production code uses ws_bridge exclusively

### Issue #2: Diagnostic Script Starts Legacy Service
**Problem:** `investigate_crypto_markets.py` calls `get_websocket_service()` which starts the legacy service.

**Code:**
```python
# investigate_crypto_markets.py line 163-164
from merid.event_venues.kalshi.websocket_service import get_websocket_service
ws_service = get_websocket_service()
```

**Impact:**
- Running diagnostic script starts legacy WS service
- Could cause confusion if both services are running
- Not a production issue (diagnostic only)

### Issue #3: Settings Allow Legacy Service
**Problem:** `MERID_KALSHI_WS_CLIENT` setting allows "websocket_service" as an option.

**Code:**
```python
MERID_KALSHI_WS_CLIENT: str = Field(
    default="ws",
    description="Kalshi websocket implementation: ws (required for live) or websocket_service (dev only)",
)
```

**Impact:**
- Could be set to "websocket_service" in dev mode
- Startup validation prevents this in live mode
- Still creates confusion and potential for accidental use

## Recommendations

### Immediate Actions

1. **Remove Legacy Service from Production Code**
   - Delete or move `merid/event_venues/kalshi/websocket_service.py` to archive
   - Remove `get_websocket_service()` and `start_websocket_service()` functions
   - Update diagnostic script to use production bridge instead

2. **Remove Legacy Service from Settings**
   - Remove `MERID_KALSHI_WS_CLIENT` setting (only "ws" should be used)
   - Remove startup validation for websocket_service (no longer needed)

3. **Update Diagnostic Script**
   - Change `investigate_crypto_markets.py` to use `ws_bridge` instead
   - Or remove WebSocket service check from diagnostic script

4. **Add Clear Documentation**
   - Document that only `KalshiWebSocketBridge` should be used
   - Remove references to legacy service from documentation
   - Update architecture docs to reflect single WS service

### Future Improvements

1. **Consolidate WebSocket Management**
   - Consider consolidating WebSocketFeedManager and KalshiWebSocketBridge
   - Single unified WebSocket service for all needs

2. **Add Service Registration**
   - Implement service registry to prevent duplicate services
   - Detect and warn if multiple WS services are started

3. **Improve Logging**
   - Add clear service identification in logs
   - Log which WS service is being used at startup
   - Add health check to verify only one WS service is running

## Verification Steps

1. **Check Running Services**
   - Search logs for "KalshiWebSocketService" and "KalshiWebSocketBridge"
   - Verify only ws_bridge is running in production
   - Check for any websocket_service startup logs

2. **Check Settings**
   - Verify `MERID_KALSHI_WS_CLIENT` is not set to "websocket_service"
   - Check .env file for any legacy settings

3. **Check Imports**
   - Search for imports of websocket_service
   - Verify no production code imports legacy service

## Success Criteria

1. Only `KalshiWebSocketBridge` runs in production
2. No references to `KalshiWebSocketService` in production code
3. Settings do not allow legacy service option
4. Diagnostic scripts use production bridge
5. Logs clearly show which WS service is active
6. No confusion between WS services

## Timeline

- **Phase 1:** Remove legacy service from production (30 min)
- **Phase 2:** Update settings and validation (15 min)
- **Phase 3:** Update diagnostic script (15 min)
- **Phase 4:** Update documentation (15 min)
- **Phase 5:** Test and verify (30 min)

Total estimated time: 1.5 hours
