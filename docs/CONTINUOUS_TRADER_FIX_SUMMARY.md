# Continuous Trader Initialization and Event-Loop Issue Fix Summary

**Date**: 2026-03-28
**Issue**: Continuous trader (Kalshi Agent Grid) not initializing, risk limit breaches, event-loop lag, WebSocket timeouts

---

## Issues Identified

### 1. Continuous Trader Not Initializing (CRITICAL - FIXED)

**Root Cause**: The Kalshi Agent Grid was not being started directly in `main.py`. Instead, startup was delegated to `OrchestratorAgentManager` which could fail silently with only a warning.

**Impact**:
- No trading agents were running
- Risk limit breaches occurred because no position management was active
- Critical system functionality was missing

**Fix Applied**:
- Modified `main.py` to directly start Kalshi Agent Grid before OrchestratorAgentManager (lines 215-224)
- Changed error handling from warning to CRITICAL error to ensure visibility
- Added agent_grid to app.state for API access
- Updated OrchestratorAgentManager to only grab reference, not start duplicate instance

**Files Changed**:
- `/home/runner/work/MERID/MERID/main.py`
- `/home/runner/work/MERID/MERID/web/startup_agents.py`

---

### 2. Missing XRP and DOGE Asset Configuration (CRITICAL - FIXED)

**Root Cause**: XRP and DOGE were defined in:
- Market catalog (with ticker patterns)
- Agent grid YAML config (with 20 agents across timeframes)
- Paper session state

But were **missing** from:
- `btc_promotion_config.py` PHASES unlocked_assets
- `btc15m_lane.py` LANE_UNLOCK_REQUIREMENTS

**Impact**:
- Markets were discovered by catalog
- Agents tried to analyze them
- No trading lanes were created (blocked by promotion phase gates)
- Risk management couldn't track these assets
- Risk limit breach alerts fired continuously

**Fix Applied**:
- Added XRP and DOGE to PHASE_3 `unlocked_assets` list
- Added lane unlock requirements for XRP and DOGE at PHASE_3 for both 15m and 1h timeframes

**Files Changed**:
- `/home/runner/work/MERID/MERID/merid/risk/btc_promotion_config.py`
- `/home/runner/work/MERID/MERID/merid/lanes/btc15m_lane.py`

---

### 3. Duplicate PortfolioRiskAgent Startup (FIXED)

**Root Cause**: `main.py` was starting a separate PortfolioRiskAgent instance when one was already started by AgentGrid.

**Impact**:
- Resource duplication
- Potential conflicting risk calculations
- Unnecessary startup complexity

**Fix Applied**:
- Removed separate PortfolioRiskAgent instantiation from main.py
- Store reference to AgentGrid's portfolio risk agent in app.state instead

**Files Changed**:
- `/home/runner/work/MERID/MERID/main.py`

---

### 4. Event-Loop Lag and WebSocket Timeouts (DOCUMENTED - RECOMMENDATIONS PROVIDED)

**Root Cause**: Blocking operations in the main event loop causing:
- Event-loop lag up to 22+ seconds
- Slow actions (liquidity: 26.8s, features: 28.9s) blocking the loop
- WebSocket keepalive ping timeout (needs response within 10s)
- Connection drops and reconnection cascades

**Symptoms from Logs**:
```
2026-03-28 01:13:33 | WARNING | merid.event_venues.kalshi.ws | Event-loop lag: 12187ms
2026-03-28 01:13:42 | WARNING | merid.event_venues.kalshi.ws | Event-loop lag: 7547ms
2026-03-28 01:13:43 | WARNING | merid.loop | Slow action 'liquidity': 26849.8ms (budget 250ms)
2026-03-28 01:13:43 | WARNING | merid.diagnostics.loop_lag | Event-loop lag detected: 22078.0ms
2026-03-28 01:13:45 | WARNING | merid.loop | Slow action 'features': 28936.1ms (budget 250ms)
2026-03-28 01:13:45 | ERROR | merid.event_venues.kalshi.ws_bridge | WS bridge task kalshi-ws-bridge crashed:
...
websockets.exceptions.ConnectionClosedError: sent 1011 (unexpected error) keepalive ping timeout
```

**Contributing Factors**:

1. **Liquidity Refresh Blocking** (26.8s):
   - Polling Kalshi orderbook snapshots for all active markets
   - Network I/O not properly async or rate-limited
   - Should be parallelized or moved to background task

2. **Feature Refresh Blocking** (28.9s):
   - Fetching news, social, and onchain features for all symbols
   - External API calls blocking event loop
   - Should use asyncio.gather() with timeouts

3. **Consensus and Signal Processing**:
   - Multiple agent cycles running synchronously
   - Large position reconciliation operations
   - Alert webhook sends failing (tg_send) - likely timing out and blocking

**Current Mitigations in Place**:
- WebSocket has proper ping settings (ping_interval=20s, ping_timeout=10s)
- Async message queue to prevent handler backpressure
- Staleness detection with auto-reconnect
- Gap detection and monitoring

**Recommendations for Future Fixes**:

1. **Parallelize Liquidity Polling**:
   ```python
   # Instead of sequential polling:
   async def _refresh_liquidity(self, tickers):
       tasks = [client.get_orderbook(t) for t in tickers]
       results = await asyncio.gather(*tasks, return_exceptions=True)
   ```

2. **Add Timeouts to External API Calls**:
   ```python
   async def fetch_with_timeout(coro, timeout=5.0):
       try:
           return await asyncio.wait_for(coro, timeout=timeout)
       except asyncio.TimeoutError:
           logger.warning(f"Operation timed out after {timeout}s")
           return None
   ```

3. **Move Heavy Operations to Background Tasks**:
   - Don't block main loop for feature/liquidity refresh
   - Use dedicated background tasks that update shared state
   - Main loop reads last-known-good values

4. **Rate Limit Alert Webhooks**:
   - tg_send failures are blocking (19 failures in logs)
   - Add circuit breaker pattern
   - Queue alerts and send in batches

5. **Reduce Agent Cycle Stagger**:
   - Current 0.5s stagger per agent × 20+ agents = 10s startup lag
   - Reduce to 0.1s or parallelize with asyncio.gather()

6. **Add Budget Enforcement**:
   - Current "budget 250ms" is just a warning
   - Add actual timeouts to prevent runaway operations

---

## Crypto Asset Configuration Alignment Summary

All crypto assets (BTC, ETH, SOL, XRP, DOGE) are now properly configured across:

### Market Catalog (`merid/event_venues/kalshi/market_catalog.py`)
- ✅ BTC ticker pattern: `^KX(?:BTC|BITCOIN)`
- ✅ ETH ticker pattern: `^KX(?:ETH|ETHEREUM)`
- ✅ SOL ticker pattern: `^KX(?:SOL|SOLANA)`
- ✅ XRP ticker pattern: `^KX(?:XRP|RIPPLE)`
- ✅ DOGE ticker pattern: `^KX(?:DOGE|DOGECOIN)`

### Agent Grid Config (`config/kalshi_agent_grid.yaml`)
All 5 assets × 4 timeframes (15m, 1h, daily, weekly) = 20 crypto agents configured

### Promotion Phases (`merid/risk/btc_promotion_config.py`)
- PHASE_0: BTC only (15m)
- PHASE_1: BTC (15m, 1h)
- PHASE_2: BTC, ETH (15m, 1h, 4h)
- PHASE_3: **BTC, ETH, SOL, XRP, DOGE** (15m, 1h, 4h, 1d) ← FIXED

### Lane Unlock Requirements (`merid/lanes/btc15m_lane.py`)
- ✅ BTC: 15m (PHASE_0), 1h (PHASE_1), 4h (PHASE_2)
- ✅ ETH: 15m (PHASE_2), 1h (PHASE_2)
- ✅ SOL: 15m (PHASE_3), 1h (PHASE_3) ← FIXED
- ✅ XRP: 15m (PHASE_3), 1h (PHASE_3) ← FIXED
- ✅ DOGE: 15m (PHASE_3), 1h (PHASE_3) ← FIXED

### Timeframe Naming Consistency
Current system uses these timeframe identifiers:
- **Agent config**: "15m", "1h", "daily", "weekly"
- **Market catalog**: "15m", "1h", "daily", "weekly", "monthly", "yearly"
- **Data schemas**: "15m", "1h", "4h", "1d", "1w", "1M"
- **Paper session**: "15m", "1h" (stored with agent name like "HOURLY")

**Note**: Some inconsistency exists between "daily"/"1d" and "weekly"/"1w". This is handled by conversion logic in market catalog and doesn't cause issues in practice.

---

## Testing Checklist

### Critical Path Tests
- [ ] Verify Kalshi Agent Grid starts successfully in main.py
- [ ] Verify all 20+ crypto trading agents initialize
- [ ] Verify PortfolioRiskAgent starts once (not duplicated)
- [ ] Verify XRP and DOGE markets are discovered and lanes created at PHASE_3
- [ ] Check that no duplicate WebSocket bridge or agent grid startup occurs

### Integration Tests
- [ ] Verify WebSocket connection stays alive under load
- [ ] Check event-loop lag metrics during normal operation
- [ ] Verify no risk limit breach alerts for XRP/DOGE after fix
- [ ] Test promotion from PHASE_2 → PHASE_3 unlocks XRP/DOGE lanes
- [ ] Verify paper trading PnL tracking works for all 5 assets

### Regression Tests
- [ ] Run existing Kalshi agent grid tests
- [ ] Run Kalshi WebSocket integration tests
- [ ] Run promotion engine tests
- [ ] Run lane orchestrator tests

---

## Deployment Considerations

1. **Environment Variables Required**:
   - `MERID_PM_TRADING_MODE`: Set to "paper" or "live"
   - `MERID_PM_LIVE_ENABLED`: Set to "true" for live trading
   - Kalshi API credentials properly configured

2. **Startup Sequence**:
   - WebSocket bridge starts first
   - Kalshi Agent Grid starts second (CRITICAL)
   - OrchestratorAgentManager starts third (optional components)
   - Portfolio risk monitoring active before any trading

3. **Monitoring**:
   - Watch for "✅ Kalshi Agent Grid started: N trading agents operational"
   - Monitor event-loop lag warnings (should be < 1000ms typically)
   - Check WebSocket connection health
   - Verify no continuous risk limit breach alerts

4. **Rollback Plan**:
   - If agent grid fails to start, system will log CRITICAL error
   - Other components (price feed, consensus, etc.) continue running
   - Can manually restart just the agent grid via API if needed

---

## Memory Storage

Critical facts stored for future sessions:
1. Kalshi Agent Grid must be started directly in main.py before OrchestratorAgentManager
2. XRP and DOGE must be in PHASE_3 unlocked_assets and LANE_UNLOCK_REQUIREMENTS
3. Event-loop blocking operations are the root cause of WebSocket timeouts

---

## Summary

**Critical issues FIXED**:
1. ✅ Continuous trader (Kalshi Agent Grid) now starts directly in main.py
2. ✅ XRP and DOGE properly configured in promotion phases and lane requirements
3. ✅ Duplicate PortfolioRiskAgent startup removed

**Issues DOCUMENTED with recommendations**:
4. ⚠️  Event-loop lag from blocking operations (liquidity/features refresh)
5. ⚠️  WebSocket keepalive timeout due to blocked event loop
6. ⚠️  Alert webhook failures (tg_send) causing additional blocking

**Next Steps**:
- Apply event-loop performance optimizations (parallelize I/O, add timeouts, background tasks)
- Add circuit breaker for alert webhooks
- Reduce agent startup stagger time
- Add comprehensive integration tests
