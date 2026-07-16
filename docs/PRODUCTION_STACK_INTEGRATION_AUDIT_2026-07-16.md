# Production Stack Integration Audit Report
**Date:** 2026-07-16  
**Scope:** 15m Kalshi Crypto Trading System (kalshi_crypto_15m_v2 profile)  
**Assets:** BTC, ETH, SOL, XRP, DOGE (5-asset crypto stack)

## Executive Summary

This audit identified **12 critical integration gaps** across the production stack that prevent end-to-end data flow and trading execution. The system has well-designed individual components but lacks proper wiring between layers, causing data islands and dead ends.

**Critical Finding:** The production stack has **no unified startup sequence** that guarantees all services are initialized in the correct order with proper dependencies established. This leads to race conditions, missing data, and silent failures.

---

## Production Stack Architecture

### Entry Point
- **`start_15m.ps1`** → **`web/main_15m_lean.py`** (FastAPI lifespan-based startup)
- Profile: `kalshi_crypto_15m_v2`
- Port: 8011
- Runtime mode: `15m_live`

### Layer 1: Upstream (Market Data)
| Component | File | Purpose | Status |
|-----------|------|---------|--------|
| KalshiWebSocketBridge | `ws_bridge.py` | WebSocket subscriptions | ⚠️ PARTIALLY WIRED |
| KalshiMarketStateStore | `market_state.py` | Orderbook state management | ⚠️ NOT CONNECTED TO AGENTS |
| KalshiMarketCatalog | `market_catalog.py` | Market discovery | ✅ WIRED |
| UnifiedSpotService | `unified_spot_service.py` | Spot price feeds | ✅ WIRED |

### Layer 2: Midstream (Signal Generation & Risk)
| Component | File | Purpose | Status |
|-----------|------|---------|--------|
| Kalshi15mLoop | `loop_15m.py` | Main trading loop (5s cadence) | ✅ CORE |
| LeanAgentGrid15m | `agent_grid_15m.py` | 5 asset agents | ⚠️ MISSING MARKET STATE |
| UnifiedRiskManager | `unified_risk_manager.py` | Risk enforcement | ✅ WIRED |
| PositionMonitor | `position_monitor.py` | Exit signal generation | ⚠️ CALLBACK NOT REGISTERED |

### Layer 3: Downstream (Execution & Reconciliation)
| Component | File | Purpose | Status |
|-----------|------|---------|--------|
| Kalshi15mOrderRouter | `order_router.py` | Order routing | ✅ CORE |
| KalshiFillsLedger | `fills_ledger.py` | Fill tracking | ⚠️ NOT STARTED IN STARTUP |
| FillsPoller | `fills_poller.py` | Fill polling | ⚠️ NOT STARTED IN STARTUP |
| SettlementPoller | `settlement_poller.py` | Settlement tracking | ✅ STARTED |
| BankrollServiceV2 | `bankroll_service_v2.py` | Balance tracking | ✅ STARTED |
| KalshiPositionCache | `position_cache.py` | Position management | ⚠️ NOT STARTED IN STARTUP |
| RestingOrderMonitor | `resting_order_monitor.py` | Resting order tracking | ⚠️ NOT STARTED IN STARTUP |

---

## Critical Integration Gaps

### GAP #1: MarketStateStore Not Connected to Agent Grid
**Severity:** CRITICAL  
**Location:** `loop_15m.py` line 2828-2829

**Issue:**
```python
if agent_grid and hasattr(agent_grid, 'set_market_state_store'):
    agent_grid.set_market_state_store(market_state_store)
```

This connection exists but is **only called during loop warmup**, not during startup. If the loop starts before the market state store is fully initialized, agents will have no access to live orderbook data.

**Impact:**
- Agents cannot access bid/ask/mid prices
- Signal generation uses stale or missing market data
- Trading decisions based on incomplete information

**Fix Required:**
Move `set_market_state_store()` call to **startup phase** in `main_15m_lean.py` after WS bridge is fully initialized and market state store has snapshots.

---

### GAP #2: PositionCache Not Connected to Agent Grid
**Severity:** CRITICAL  
**Location:** `loop_15m.py` line 3164

**Issue:**
```python
agent_grid.set_position_cache(position_cache)
```

This connection exists but is **only called during loop warmup**, not during startup. The position cache is not started in the main startup sequence.

**Impact:**
- Global allocator cannot enforce $1 exposure cap
- Position tracking is inconsistent
- Risk enforcement may fail

**Fix Required:**
1. Start `KalshiPositionCache` in `main_15m_lean.py` startup
2. Call `set_position_cache()` during startup, not warmup
3. Ensure position cache is initialized before agent grid starts

---

### GAP #3: FillsLedger Not Started in Startup
**Severity:** HIGH  
**Location:** `main_15m_lean.py`

**Issue:**
`KalshiFillsLedger` is imported and used but **never explicitly started** in the startup sequence. It relies on lazy initialization which may not happen before trading begins.

**Impact:**
- Fill tracking may be incomplete
- PnL calculations may be inaccurate
- Reconciliation with Kalshi API may fail

**Fix Required:**
Add explicit `fills_ledger.start()` call in `main_15m_lean.py` startup phase after bankroll service is initialized.

---

### GAP #4: FillsPoller Not Started in Startup
**Severity:** HIGH  
**Location:** `main_15m_lean.py` line 2191-2194

**Issue:**
```python
from merid.event_venues.kalshi.fills_poller import get_fills_poller
_fills_poller = get_fills_poller()
await _fills_poller.start()
app.state.fills_poller = _fills_poller
```

This code exists but is **commented out or not executed** in the current startup path. The fills poller is critical for detecting fills via HTTP polling when WebSocket fills are missed.

**Impact:**
- Missed fills if WebSocket fails
- Incomplete position tracking
- Silent execution failures

**Fix Required:**
Ensure fills poller is started in the main startup sequence in `main_15m_lean.py`.

---

### GAP #5: RestingOrderMonitor Not Started in Startup
**Severity:** MEDIUM  
**Location:** `order_router.py` line 332-333

**Issue:**
```python
from merid.event_venues.kalshi.resting_order_monitor import get_resting_order_monitor
monitor = get_resting_order_monitor()
```

The resting order monitor is used to track GTC orders but **never explicitly started** in the startup sequence.

**Impact:**
- GTC orders may rest indefinitely without monitoring
- No fallback to market orders for stuck orders
- Increased risk of unfilled positions

**Fix Required:**
Add explicit `resting_order_monitor.start()` call in `main_15m_lean.py` startup phase.

---

### GAP #6: PositionMonitor Callback Not Registered
**Severity:** CRITICAL  
**Location:** `loop_15m.py` line 1284-1299

**Issue:**
```python
self._position_monitor.register_exit_intent_callback(exit_intent_callback)
```

The callback is registered but the **PositionMonitor is started in the loop, not in startup**. This creates a race condition where the loop may start trading before PositionMonitor is ready.

**Impact:**
- Exit signals may not be generated
- Trailing stops may not trigger
- Positions may ride to settlement without exit

**Fix Required:**
Move PositionMonitor startup to `main_15m_lean.py` and ensure callback is registered before loop starts.

---

### GAP #7: WebSocket Bridge Subscription Race Condition
**Severity:** HIGH  
**Location:** `ws_bridge.py` line 1117-1650

**Issue:**
The WS bridge starts subscriptions immediately upon `start()` call, but the **market state store may not be ready** to receive orderbook messages. There's no synchronization between WS subscription start and market state store readiness.

**Impact:**
- Initial orderbook messages may be dropped
- Market state store may have incomplete data
- Trading may start with stale market data

**Fix Required:**
Add a readiness check in WS bridge to ensure market state store is initialized before starting subscriptions.

---

### GAP #8: UnifiedRiskManager Not Calibrated on Startup
**Severity:** CRITICAL  
**Location:** `main_15m_lean.py` line 3041-3045

**Issue:**
```python
logger.info("[STARTUP] P1.7.7: Calibrating UnifiedRiskManager from bankroll")
```

The calibration happens but **only after bankroll reaches FRESH state**. If bankroll takes too long to initialize, risk manager may not be calibrated when trading starts.

**Impact:**
- Risk checks may fail or be bypassed
- Exposure tracking may be incorrect
- $1 cap enforcement may not work

**Fix Required:**
Add explicit timeout and fallback for risk manager calibration. Ensure it's calibrated before loop starts.

---

### GAP #9: Market Catalog Refresh Not Synchronized with Loop
**Severity:** MEDIUM  
**Location:** `loop_15m.py` and `market_catalog.py`

**Issue:**
The market catalog refreshes every 60 seconds independently of the 15m loop. There's no synchronization to ensure the loop uses the latest catalog when markets roll over.

**Impact:**
- Loop may trade on expired markets
- Market rollover may cause trading gaps
- Candidates may reference invalid tickers

**Fix Required:**
Add catalog refresh trigger on 15m window boundary and ensure loop waits for catalog update before trading new window.

---

### GAP #10: No Unified Health Check Across All Services
**Severity:** MEDIUM  
**Location:** `main_15m_lean.py` health endpoints

**Issue:**
Health checks exist for individual services (WS, catalog, bankroll) but **no unified health check** that verifies all critical services are ready before enabling trading.

**Impact:**
- Trading may start with degraded services
- Silent failures in non-critical services
- Difficult to diagnose system-wide issues

**Fix Required:**
Create a unified health check that verifies:
- WS bridge subscribed to all 5 assets
- Market state store has fresh data for all 5 assets
- Bankroll service is FRESH
- Risk manager is calibrated
- Position cache is initialized
- Fills ledger is started

---

### GAP #11: Coinbase WebSocket Client Not Started
**Severity:** MEDIUM  
**Location:** `loop_15m.py` line 647-652

**Issue:**
```python
if COINBASE_WS_AVAILABLE:
    try:
        self._coinbase_client = get_coinbase_client()
```

The Coinbase WebSocket client for external velocity signals is initialized but **never explicitly started**. It may or may not be running depending on lazy initialization.

**Impact:**
- External velocity signals may be unavailable
- Turbine research #1 winner strategy may not work
- Reduced signal quality

**Fix Required:**
Add explicit Coinbase WS client startup in `main_15m_lean.py` if enabled in profile.

---

### GAP #12: No End-to-End Data Flow Validation
**Severity:** HIGH  
**Location:** Entire stack

**Issue:**
There is **no validation** that data flows correctly from:
- WS bridge → market state store → agents → signals → orders → fills → ledger → position cache

**Impact:**
- Silent data corruption
- Missing fills not detected
- Position drift not caught

**Fix Required:**
Add end-to-end validation probes that:
1. Verify WS messages are received and parsed
2. Verify market state store updates
3. Verify agents receive fresh data
4. Verify orders are submitted
5. Verify fills are recorded
6. Verify position cache updates

---

## Remediation Plan

### Phase 1: Critical Startup Sequence Fixes (Immediate)
1. **Move market_state_store connection to startup**
   - File: `main_15m_lean.py`
   - Add after WS bridge start
   - Call `agent_grid.set_market_state_store()` before loop start

2. **Start PositionCache in startup**
   - File: `main_15m_lean.py`
   - Add explicit `position_cache.start()` call
   - Call `agent_grid.set_position_cache()` before loop start

3. **Start FillsLedger in startup**
   - File: `main_15m_lean.py`
   - Add explicit `fills_ledger.start()` call
   - Ensure it's started before loop start

4. **Start FillsPoller in startup**
   - File: `main_15m_lean.py`
   - Uncomment and ensure fills poller start code executes
   - Add to startup sequence after fills ledger

5. **Start RestingOrderMonitor in startup**
   - File: `main_15m_lean.py`
   - Add explicit `resting_order_monitor.start()` call
   - Add to startup sequence after order router

### Phase 2: Synchronization and Race Condition Fixes (High Priority)
6. **Add WS bridge readiness check**
   - File: `ws_bridge.py`
   - Add `is_market_state_store_ready()` check before subscriptions
   - Wait for market state store initialization

7. **Move PositionMonitor to startup**
   - File: `main_15m_lean.py`
   - Move PositionMonitor start from loop to startup
   - Register callback before loop start

8. **Add risk manager calibration timeout**
   - File: `main_15m_lean.py`
   - Add 30s timeout for risk manager calibration
   - Fail startup if calibration fails

9. **Synchronize catalog refresh with 15m windows**
   - File: `loop_15m.py`
   - Trigger catalog refresh on window boundary
   - Wait for catalog update before trading new window

### Phase 3: Observability and Validation (Medium Priority)
10. **Create unified health check**
    - File: `main_15m_lean.py`
    - Add `/api/v1/health/unified` endpoint
    - Verify all critical services before enabling trading

11. **Start Coinbase WS client if enabled**
    - File: `main_15m_lean.py`
    - Add conditional startup based on profile config
    - Verify connection before loop start

12. **Add end-to-end data flow validation**
    - File: New `merid/diagnostics/e2e_validation.py`
    - Create validation probes for each layer
    - Run validation every 5 minutes
    - Alert on data flow failures

---

## Startup Sequence Redesign

### Proposed New Startup Order

```
1. Load environment and profile
2. Initialize singletons (reset if needed)
3. Start BankrollServiceV2
   - Wait for FRESH state (30s timeout)
4. Start KalshiFillsLedger
5. Start FillsPoller
6. Start SettlementPoller
7. Start KalshiPositionCache
8. Start RestingOrderMonitor
9. Start UnifiedSpotService
10. Start KalshiWebSocketBridge
    - Wait for market state store readiness
    - Subscribe to 5 crypto assets
    - Bootstrap orderbook snapshots
11. Start KalshiMarketCatalog
    - Refresh and validate 5 asset markets
12. Initialize AgentGrid
    - Set market_state_store
    - Set position_cache
13. Calibrate UnifiedRiskManager
    - Wait for calibration (30s timeout)
14. Start PositionMonitor
    - Register exit callback
15. Create Kalshi15mLoop
    - Pass all initialized services
16. Run unified health check
    - Verify all services ready
    - Fail startup if any critical service unhealthy
17. Start Kalshi15mLoop
18. Enable trading
```

---

## Testing Requirements

### Integration Tests
1. **Startup sequence test** - Verify all services start in correct order
2. **Market data flow test** - Verify WS → market state → agents path
3. **Order execution test** - Verify agents → router → Kalshi API path
4. **Fill reconciliation test** - Verify Kalshi API → fills ledger → position cache path
5. **Risk enforcement test** - Verify risk manager checks all orders
6. **Health check test** - Verify unified health check detects failures

### End-to-End Tests
1. **Full trading cycle test** - From market data to fill reconciliation
2. **Market rollover test** - Verify catalog refresh and window transition
3. **WS failure test** - Verify fills poller fallback works
4. **Bankroll failure test** - Verify risk manager handles stale bankroll
5. **Position monitor test** - Verify exit signals trigger orders

---

## Success Criteria

### Critical (Must Have)
- ✅ All 5 assets (BTC/ETH/SOL/XRP/DOGE) subscribed and receiving data
- ✅ Market state store has fresh data for all 5 assets
- ✅ Agents receive fresh market data every cycle
- ✅ Risk manager calibrated and enforcing $1 cap
- ✅ Fills ledger recording all fills
- ✅ Position cache tracking all positions accurately

### High (Should Have)
- ✅ Unified health check passes before trading
- ✅ Position monitor generating exit signals
- ✅ Resting order monitor tracking GTC orders
- ✅ Fills poller catching missed WS fills
- ✅ Catalog synchronized with 15m windows

### Medium (Nice to Have)
- ✅ Coinbase WS client providing velocity signals
- ✅ End-to-end validation probes running
- ✅ Diagnostic endpoints for all layers
- ✅ Automated recovery from service failures

---

## Conclusion

The production stack has solid individual components but lacks the integration wiring to function as a unified system. The 12 gaps identified prevent end-to-end data flow and create race conditions that can lead to silent failures.

**Priority:** Implement Phase 1 fixes immediately to ensure basic trading functionality. Phase 2 fixes should follow to improve reliability. Phase 3 fixes provide observability and long-term maintainability.

**Estimated Effort:**
- Phase 1: 4-6 hours
- Phase 2: 6-8 hours  
- Phase 3: 8-12 hours
- Testing: 4-6 hours

**Total:** 22-32 hours of development + testing
