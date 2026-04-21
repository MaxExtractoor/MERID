# Pipeline Actions Audit

**Date:** 2026-04-18  
**Scope:** `liquidity`, `arb_scan`, `order_groups` actions in `merid/loop.py`  
**Production Status:** Full prod, live trading  

---

## 1. `liquidity` Action (`_refresh_liquidity`)

### Upstream Dependencies
- `merid.event_venues.kalshi.client.get_kalshi_client()` - REST client singleton
- `merid.event_venues.kalshi.liquidity_monitor.OrderBookSnapshot` - Data model
- `merid.prediction.agent_grid.get_agent_grid()` - Agent state for active tickers
- `merid.event_venues.kalshi.ws_bridge` - WebSocket bridge for mid-session subscriptions

### Downstream Dependencies
- `LiquidityMonitor.process()` - Emits alerts on wide spreads/thin books
- Agent grid position stop-loss price updates (`_pos.current_price_cents`)
- Summary metrics (`liquidity_sweep:*markets,*alerts`)

### Trigger/Cadence
- **Interval:** `self._liquidity_refresh_interval = 30.0s` (configurable)
- **Lag-guard skip:** If event-loop lag > 750ms, action is skipped entirely
- **Startup cooldown:** Skipped for first 120 ticks (~10 min)

### Kalshi Touch Points
- **REST:** `client.get_orderbook(ticker)` - Blocking HTTP calls with 2.0s timeout
- **WS:** `self._ws_bridge.subscribe(tickers)` - Mid-session subscription for discovered tickers

### Performance-Sensitive Sections
1. **Ticker collection** (lines 1250-1273): Iterates agent grid, can block if grid is large
2. **Orderbook fetching** (lines 1296-1308): Concurrent fetches with `asyncio.Semaphore(2)`
3. **Orderbook processing** (lines 1312-1346): CPU-heavy, offloaded to thread pool with 3.0s timeout

### Current Safeguards
- Circuit-open fast-path (skips if Kalshi circuit breaker is open)
- Max 3 markets during startup, 5 after (`MAX_TICKERS`)
- 2.0s timeout per orderbook fetch
- 3.0s timeout for processing thread pool work
- Lag-aware skip at >750ms

---

## 2. `arb_scan` Action (`_run_arb_scan`)

### Upstream Dependencies
- `merid.prediction.agent_grid.get_agent_grid()` - For agent states and signals
- `merid.signals.live_feeds.get_live_feed_manager()` - For cross-venue price data
- `merid.prediction.market_snapshot.get_snapshotter()` - For market state

### Downstream Dependencies
- Arbitrage opportunity signals (emitted to event bus)
- Trade plan generation for execution layer

### Trigger/Cadence
- **Interval:** `self.config.arb_scan_interval = 60.0s` (increased from 10s to reduce lag)
- **Lag-guard skip:** If event-loop lag > 500ms (should be tightened to 200ms)
- **Startup cooldown:** Skipped for first 40 ticks (~3.3 min)
- **Slowness skip:** If action was slow recently, skip next invocation

### Kalshi Touch Points
- **REST:** Price fetches via live feed manager (indirect)
- **WS:** Price updates consumed via WS bridge (indirect)

### Performance-Sensitive Sections
1. **Signal scanning loop**: Iterates all agents, examines `signal_log` entries
2. **Cross-venue price comparison**: CPU-heavy when many markets active
3. **Opportunity scoring**: Decimal math, edge calculations

### Current Safeguards
- Offloaded to thread pool (`_get_loop_executor()`)
- Lag-aware skip at >500ms (TOO HIGH - needs reduction)
- Startup cooldown (40 ticks)
- Periodic `await asyncio.sleep(0)` missing - needs insertion in long loops

---

## 3. `order_groups` Action (`_sync_order_groups`)

### Upstream Dependencies
- `merid.prediction.order_group_lifecycle.get_order_group_lifecycle()` - Lifecycle manager
- WebSocket bridge for order group update subscriptions

### Downstream Dependencies
- Order group state summary in tick summary (`order_groups:synced` metrics)
- Triggered group warnings (risk management signal)
- Lifecycle state for risk calculations

### Trigger/Cadence
- **Interval:** `self._order_groups_sync_interval = 120.0s` (increased from 60s)
- **Startup cooldown:** Skipped for first 100 ticks (~8.3 min)
- **WS unavailable skip:** If lifecycle manager WS start previously failed, skip

### Kalshi Touch Points
- **WS:** Order group update subscriptions via lifecycle manager
- **REST:** Fallback to REST API if WS unavailable (in lifecycle manager)

### Performance-Sensitive Sections
1. **Lifecycle manager start** (lines 1907-1914): Can block if WS connection fails
2. **State retrieval** (lines 1917-1921): Offloaded to thread pool, but `get_lifecycle_state()` can be slow
3. **Triggered groups iteration** (lines 1932-1937): Iterates triggered groups for logging

### Current Safeguards
- Startup cooldown (100 ticks)
- WS unavailable circuit (tracks `_og_start_failed`)
- Thread pool offload for state retrieval
- No hard timeout on `og_lifecycle.start()` - **GAP**

---

## Summary: Critical Paths to Harden

| Action | Current Max Duration | Budget Target | Primary Risk |
|--------|---------------------|---------------|--------------|
| `liquidity` | 9.7s observed | 1000ms hard | Orderbook fetch/processing blocking loop |
| `arb_scan` | 2.7s observed | 1000ms hard | CPU-heavy scanning without yield points |
| `order_groups` | 2.6s observed | 1000ms hard | Lifecycle manager start can hang |

---

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `MERID_LOOP_SLOW_ACTION_BUDGET_MS` | Soft budget warning threshold | 1000ms |
| `KALSHI_WS_RECONNECT_LAG_THRESHOLD_MS` | Lag threshold for WS reconnect skip | 1000ms |
| `MERID_PROFILING` | Enable read-only profiling instrumentation | unset (disabled) |
