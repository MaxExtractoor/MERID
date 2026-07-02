# Depth/Quality Filter Audit Checklist

This document enumerates all depth/quality filters that can block trading even when orderbook data looks healthy.

## 1. Orderbook Quality Functions

### 1.1 Liquidity Status Classification
**Location:** `merid/event_venues/kalshi/market_state.py:4014-4025`

**Function:** `_classify_liquidity_status()`

**Inputs:**
- `has_bid`: boolean - whether bid exists
- `has_ask`: boolean - whether ask exists
- `depth_10c`: number - depth within 10 cents of best price

**Conditions:**
- `liquidity_status = MISSING` if `not has_bid and not has_ask`
- `liquidity_status = ONE_SIDED` if `has_bid xor has_ask`
- `liquidity_status = DEPTH_TOO_LOW` if `depth_10c < 5`
- `liquidity_status = OK` if `depth_10c >= 5`

**Output:** `LiquidityStatus` enum (MISSING, ONE_SIDED, DEPTH_TOO_LOW, OK)

**Logging:** Logs in `STATE-AFTER-WRITE` with `liquidity_status` field

---

### 1.2 Executable Flag
**Location:** `merid/event_venues/kalshi/market_state.py:3931-3942`

**Function:** `_set_executable_flag()`

**Inputs:**
- `best_bid`: best bid price in cents
- `best_ask`: best ask price in cents

**Conditions:**
- `executable = True` if `best_bid is not None and best_ask is not None`
- `executable = False` if `best_bid == 0 and best_ask == 100` (anomaly override)

**Output:** boolean `executable` flag on market state

**Logging:** Logs in `STATE-AFTER-WRITE` with `executable` field

---

### 1.3 Market State Validation for Entry
**Location:** `merid/prediction/agent_grid_15m.py:1628-1707`

**Function:** `validate_market_state_for_entry()`

**Inputs:**
- `asset`: asset ticker (e.g., "BTC", "ETH")
- `market_id`: Kalshi market ticker
- `state`: KalshiMarketState object
- `minutes_to_expiry`: time to expiry in minutes
- `min_depth_yes`: minimum yes depth from profile
- `min_depth_no`: minimum no depth from profile
- `max_md_staleness_sec`: maximum allowed staleness in seconds

**Conditions:**
- Returns `False` with reason `STATE-NONE` if `state is None`
- Returns `False` with reason `BOOK-NOT-INITIALIZED` if `not state.book_initialized`
- Returns `False` with reason `NOT-EXECUTABLE` if `not state.executable`
- Returns `False` with reason `MD-STALE` if staleness > `max_md_staleness_sec`
- Returns `False` with reason `PATTERN-0100` if `best_bid == 0 and best_ask == 100`
- Returns `False` with reason `NO-BIDASK` if `best_bid == 0 or best_ask == 0`

**Output:** `MarketValidationResult` with `ok` boolean and `reason` string

**Logging:** Logs warning with `[AGENT-SKIP]`, `[MD-GATE]`, or `[LIQUIDITY-REJECT]` prefix

---

## 2. Depth Thresholds (Profile-Based)

### 2.1 Per-Asset Depth Thresholds
**Location:** `config/profiles/kalshi_crypto_15m_v2.yaml:208-305`

**Configuration:**
- **BTC:** `min_depth_yes: 1`, `min_depth_no: 1`
- **ETH:** `min_depth_yes: 1`, `min_depth_no: 1`
- **SOL:** `min_depth_yes: 1`, `min_depth_no: 1`
- **XRP:** `min_depth_yes: 1`, `min_depth_no: 1`
- **DOGE:** `min_depth_yes: 1`, `min_depth_no: 1`

**Usage:** These are loaded by `validate_market_state_for_entry()` but currently deleted from that function (line 1706 comment says handled by risk envelope profile and enforced downstream)

---

### 2.2 Guardrails Depth Thresholds
**Location:** `config/profiles/kalshi_crypto_15m_v2.yaml:368`

**Configuration:**
- `min_depth_contracts: 5` - Minimum depth at target price

**Usage:** Used in guardrails validation

---

### 2.3 Tier-Based Depth Thresholds
**Location:** `config/profiles/kalshi_crypto_15m_v2.yaml:405-408`

**Configuration:**
- **Tier 1 (BTC/ETH):** `min_depth_yes_tier1: 10`, `min_depth_no_tier1: 10`
- **Tier 2 (SOL/XRP/DOGE):** `min_depth_yes_tier2: 5`, `min_depth_no_tier2: 5`

**Usage:** Used in risk envelope for tier-based depth validation

---

### 2.4 Microstructure Invariants
**Location:** `merid/event_venues/kalshi/microstructure_invariants.py:235-245`

**Function:** `check_depth_invariant()`

**Inputs:**
- `asset`: asset ticker
- `depth_yes`: yes depth at best price
- `depth_no`: no depth at best price
- `thresholds`: depth thresholds from profile

**Conditions:**
- Returns violation if `depth_yes < thresholds.min_depth_yes` or `depth_no < thresholds.min_depth_no`

**Output:** `InvariantViolation` with `violated` boolean and message

**Logging:** Logs error with severity based on violation

---

## 3. Spread / BBO Sanity

### 3.1 Spread Guard
**Location:** `config/profiles/kalshi_crypto_15m_v2.yaml:410-413`

**Configuration:**
- `spread_guard_enabled: true`
- `spread_guard_edge_multiplier: 1.1` - Require edge >= 1.1x spread
- `min_spread_gate_cents: 40` - Minimum spread gate at 40 cents

**Usage:** Used in candidate optimizer to filter based on spread vs edge

---

## 4. Temporal Freshness

### 4.1 MD Staleness Gate
**Location:** `merid/prediction/agent_grid_15m.py:1675-1688`

**Function:** Part of `validate_market_state_for_entry()`

**Inputs:**
- `state.last_update` or `state.last_update_ts`
- `max_md_staleness_sec` from profile

**Conditions:**
- Returns `False` with reason `MD-STALE` if staleness > threshold

**Output:** Blocks signal generation if market data is too stale

**Logging:** Logs warning with `[MD-GATE]` prefix showing actual staleness vs threshold

---

### 4.2 Stale MD Queue Warning
**Location:** `merid/event_venues/kalshi/market_state.py`

**Function:** `[STALE-MD-QUEUE]` logging

**Inputs:**
- `age_ms`: time since last update
- `threshold`: 120000ms (2 minutes)
- `expiry`: time to expiry

**Conditions:**
- Logs warning if `age_ms > threshold`

**Output:** Warning log (does not block, informational only)

**Logging:** Logs with `[STALE-MD-QUEUE]` prefix

---

## 5. Market State Flags

### 5.1 Execution Mode (15m Loop)
**Location:** `merid/loop_15m.py:404-2215`

**Function:** `_compute_execution_mode()`

**Inputs:**
- `md_fresh_count`: number of assets with fresh market data
- `spot_fresh_count`: number of assets with fresh spot prices
- `ready_assets_count`: number of assets ready for trading

**Conditions:**
- `execution_mode = RUN_NORMAL` if all assets healthy
- `execution_mode = RUN_DEGRADED` if some assets stale but >=1 has good MD/spot
- `execution_mode = NO_NEW_ENTRIES` if degraded but allow position management
- `execution_mode = HALT_CRITICAL` if critical failure

**Output:** Global execution mode that affects all trading

**Logging:** Logs with `[15M-EXECUTION-MODE]` prefix

---

### 5.2 Time to Expiry Gate
**Location:** `config/profiles/kalshi_crypto_15m_v2.yaml:370`

**Configuration:**
- `min_time_to_expiry_min: 2.5` - Minimum 2.5 minutes to expiry

**Usage:** Blocks trading too close to expiry

---

## 6. Global Venue Health / Mode

### 6.1 WebSocket Health
**Location:** `merid/event_venues/kalshi/ws_bridge.py`

**Function:** `[WS-FORWARD-HEALTH]` logging

**Inputs:**
- `events_processed`: number of events processed
- `queue_size`: current queue size

**Conditions:**
- Logs `IDLE: never received events` if no events processed
- Logs health status with events/sec and queue size

**Output:** Health status (does not directly block, but may influence execution mode)

**Logging:** Logs with `[WS-FORWARD-HEALTH]` prefix

---

## 7. Redundant / Legacy Layers

### 7.1 Order Router Validation
**Location:** `merid/event_venues/kalshi/order_router.py:421, 4173, 4839`

**Function:** `validate_market_for_trading()`

**Usage:** Called in order router before order submission

**Note:** Function is imported but implementation not found in search - may be in another module

---

## 8. Decision Boundary Logging Gaps

### Current Logging Coverage:
- ✅ `STATE-AFTER-WRITE` - logs liquidity_status, executable, depth
- ✅ `validate_market_state_for_entry` - logs validation failures with reasons
- ✅ `WS-FORWARD-HEALTH` - logs WebSocket health
- ✅ `[STALE-MD-QUEUE]` - logs stale market data warnings
- ✅ Execution mode transitions - logs mode changes

### Missing Logging:
- ❌ No explicit log when a ticker is deemed "tradable" vs "not tradable" at the agent decision boundary
- ❌ No log showing which specific depth/quality filter blocked trading when `liquidity_status=OK` but still no trades
- ❌ No log at order-send path showing why an order was blocked (if blocked)
- ❌ No log showing the final tradable decision before signal generation

---

## 9. Recommended Instrumentation

### 9.1 Add TICKER-NOT-TRADABLE Logging
**Location:** In `validate_market_state_for_entry()` after all checks

**Format:**
```python
if not validation.ok:
    logger.info(
        "[TICKER-NOT-TRADABLE] ticker=%s reason=%s depth_yes=%s depth_no=%s "
        "levels_yes=%s levels_no=%s update_age_ms=%.0f ws_healthy=%s",
        market_id,
        validation.reason,
        state.min_depth_yes if state else 0,
        state.min_depth_no if state else 0,
        total_yes_levels if state else 0,
        total_no_levels if state else 0,
        staleness if 'staleness' in locals() else 0,
        ws_healthy,
    )
```

**Reason Tags:**
- `STATE-NONE`
- `BOOK-NOT-INITIALIZED`
- `NOT-EXECUTABLE`
- `MD-STALE`
- `PATTERN-0100`
- `NO-BIDASK`
- `INSUFFICIENT_DEPTH`
- `SPREAD_TOO_WIDE`
- `BOOK_TOO_STALE`
- `WS_UNHEALTHY`
- `GLOBAL_RUN_DEGRADED`
- `MARKET_CLOSED`
- `RISK_LIMITS_ZERO`

---

### 9.2 Add AGENT-TICKER-STATUS Logging
**Location:** In agent signal generation before calling strategy

**Format:**
```python
logger.info(
    "[AGENT-TICKER-STATUS] agent=%s ticker=%s tradable=%s reason=%s",
    agent_name,
    market_id,
    is_tradable,
    reason if not is_tradable else "OK",
)
```

---

### 9.3 Add ORDER-BLOCKED Logging
**Location:** In order router at order-send path

**Format:**
```python
if not can_send_order:
    logger.info(
        "[ORDER-BLOCKED] ticker=%s reason=%s side=%s count=%d",
        intent.ticker,
        block_reason,
        intent.side,
        intent.count,
    )
```

**Reason Tags:**
- `LIQUIDITY`
- `WS_UNHEALTHY`
- `RISK_LIMIT`
- `EXECUTION_MODE`
- `MARKET_CLOSED`
- `POSITION_LIMIT`

---

## 10. Live System Testing Results

### 10.1 Current Blocker: Catalog Staleness
**Observation from live logs (2026-06-13 23:08:53):**
```
[15M-EXECUTION-NOT_READY] mode=HALT_CRITICAL loop_state=HALT ready_assets=4/5 cycle=33 
no_trade_reason=CATALOG_STALE catalog_fresh=False catalog_age=73.8s catalog_age_ok=False 
md_fresh=4/5 depth_sufficient=5/5 ws_forwarder_healthy=True bankroll_valid=True bankroll=15.51
```

**Analysis:**
- System is in HALT_CRITICAL mode due to catalog_age=73.8s exceeding 60.0s threshold
- Despite catalog staleness, all other indicators are healthy:
  - Market data fresh: md_fresh=4/5 assets
  - Depth sufficient: depth_sufficient=5/5 assets
  - WS forwarder healthy: ws_forwarder_healthy=True
  - Bankroll valid: bankroll=15.51 USD
  - Individual books show: liquidity_status=OK, executable=True, depth_yes=61-1020, depth_no=38-726

**Issue:**
This is a classic example of the "overlapping layers" problem. The catalog freshness check is blocking trading even when:
- Actual market data is flowing and fresh
- Orderbooks show healthy liquidity
- All other subsystems are operational

**Recommendation:**
- Relax catalog staleness threshold from 60s to 120s or higher
- Or make catalog staleness a warning (RUN_DEGRADED) rather than a hard halt (HALT_CRITICAL)
- Consider whether catalog freshness is truly necessary for 15m crypto markets where individual market state is the primary source of truth

### 10.2 New Logging Visibility
The new structured logging is now active:
- `[TICKER-NOT-TRADABLE]` - Shows when tickers are rejected with reason tags
- `[TICKER-TRADABLE]` - Shows when tickers pass validation
- `[AGENT-TICKER-STATUS]` - Shows agent decision boundary with execution_mode
- `[ORDER-BLOCKED]` - Shows when orders are blocked at router level

These logs will help identify which specific filter is blocking trades once the catalog staleness issue is resolved.

## 11. Next Steps

1. **Immediate:** Relax catalog staleness threshold to unblock trading
2. **Monitor:** Observe new logging to identify next blocking filter
3. **Consolidate:** Implement single tiered depth definition across all layers
4. **Audit:** Review spread guard parameters for Kalshi 15m markets
5. **Simplify:** Design clear precedence order for all quality filters
