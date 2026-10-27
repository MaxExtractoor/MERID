# Kalshi Execution Path Audit Report

**Audit Date:** 2026-05-14  
**Scope:** Kalshi 15m crypto trading execution pipeline  
**Auditor:** Cascade AI Assistant  
**Profile:** kalshi_crypto_15m_v2

---

## Executive Summary

This audit comprehensively examined the Kalshi 15m crypto trading execution pipeline across four stages:

1. **Upstream:** Signal generation and market data ingestion
2. **Midstream:** Risk enforcement and order building
3. **Downstream:** Order routing, venue adapter, and fills
4. **End-to-End:** Critical path from agent to fill

**Critical Finding:** A P0 series ticker wiring gap prevents 15m trading entirely. The agent grid YAML uses base series tickers (KXBTC) while the catalog discovery uses 15M tickers (KXBTC15M), causing a complete mismatch that blocks market assignment to agents.

**Total Issues Identified:** 22  
- P0 (Critical): 1 (series ticker wiring gap)  
- P1 (High): 8 (risk config consolidation, profile validation, deprecations)  
- P2 (Medium): 9 (sentiment isolation, maintenance window, UTC inconsistencies)  
- P3 (Low): 4 (cleanup, cosmetic)

**Remediation Plan:** 19 changes prioritized P0-P3 (see Third-Pass Change List in Appendix A)

---

## Section 1: Upstream Execution Pipeline

### 1.1 Signal Generation

**Location:** `merid/prediction/agent_grid_15m.py` (LeanAgent15m)

**Findings:**
- ✅ **CORRECT:** LeanAgent15m generates signals via `_execute_signal()` method
- ✅ **CORRECT:** Signal includes market_id, side, price_cents, count, edge_pct, confidence
- ✅ **CORRECT:** Deterministic client_tag generation using bucketed timestamp (60s buckets)
- ✅ **CORRECT:** SpotProvider abstraction for BTC, ETH, SOL, XRP, DOGE
- ✅ **CORRECT:** Crypto15mIndicatorStack for technical indicators
- ✅ **CORRECT:** UnifiedEdgeComputer for edge calculation with profile config

**Issues:**
- None identified

### 1.2 Market Data Ingestion

**Location:** `merid/event_venues/kalshi/market_catalog.py`, `merid/event_venues/kalshi/market_state.py`

**Findings:**
- ✅ **CORRECT:** Market catalog uses `_PRIORITY_SERIES` from `kalshi_agent_grid_catalog_series_tickers()`
- ✅ **CORRECT:** Series ticker extraction fix overrides API's KXBTC with KXBTC15M (regex match)
- ✅ **CORRECT:** Market state singleton for live market data
- ✅ **CORRECT:** WebSocket bridge for real-time orderbook updates
- ✅ **CORRECT:** Data quality tracking (WS_LIVE + GOOD)

**Issues:**
- ⚠️ **P0 CRITICAL:** Series ticker mismatch between catalog and agent grid
  - Catalog uses: KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M
  - Agent grid uses: KXBTC, KXETH, KXSOL, KXXRP, KXDOGE
  - Impact: 15m markets never reach agents
  - Fix: Update `config/kalshi_agent_grid.yaml` series_tickers to use 15M tickers

### 1.3 Unified Spot Service

**Location:** `data/unified_spot_service.py`

**Findings:**
- ✅ **CORRECT:** Unified spot service for all 5 assets
- ✅ **CORRECT:** Staleness detection (90s threshold)
- ✅ **CORRECT:** Fallback mechanisms for spot data

**Issues:**
- None identified

---

## Section 2: Midstream Execution Pipeline

### 2.1 Risk Enforcement

**Location:** `merid/event_venues/kalshi/kalshi_risk.py` (KalshiRiskManager)

**Findings:**
- ✅ **CORRECT:** Pre-trade risk checks via `check_order()` method
- ✅ **CORRECT:** Limits: max_yes_position, max_no_position, max_notional_per_market_usd
- ✅ **CORRECT:** Category exposure tracking for "crypto" category
- ✅ **CORRECT:** Per-asset caps: BTC, ETH, SOL, XRP, DOGE
- ✅ **CORRECT:** Profile gating via `kalshi_crypto_15m_v2` profile
- ✅ **CORRECT:** Drift detection against risk envelope caps

**Issues:**
- ⚠️ **P1 HIGH:** Duplicate KalshiRiskConfig dataclasses
  - Location 1: `merid/event_venues/kalshi/kalshi_risk.py` (venue-specific)
  - Location 2: `merid/prediction/risk/kalshi_risk_engine.py` (PM-specific)
  - Impact: Confusion about which config is actually used
  - Fix: Consolidate to single source of truth (venue config)

- ⚠️ **P2 MEDIUM:** Profile gating redundancy
  - Profile checked 4+ times during risk manager initialization
  - Impact: Over-engineering, potential for inconsistent behavior
  - Fix: Single profile check at initialization, cache result

### 2.2 Order Building

**Location:** `merid/prediction/agent_grid_15m.py` (LeanAgent15m._execute_signal)

**Findings:**
- ✅ **CORRECT:** OrderIntent construction with all required fields
- ✅ **CORRECT:** Client tag for deduplication (bucketed timestamp)
- ✅ **CORRECT:** Coherent risk contract fields (window_resolution_id, exit_policy_id, risk_tier)
- ✅ **CORRECT:** TP/SL targets registration with position cache

**Issues:**
- None identified

### 2.3 Execution Gate

**Location:** `core/execution_gate.py`

**Findings:**
- ✅ **CORRECT:** Unified execution gate with layered checks
- ✅ **CORRECT:** Kill switch check (global kill switch)
- ✅ **CORRECT:** Kalshi venue reconciliation status (critical vs benign)
- ✅ **CORRECT:** Fills ledger reconciliation status
- ✅ **CORRECT:** Dependency health check (added in bug fix)

**Issues:**
- None identified

---

## Section 3: Downstream Execution Pipeline

### 3.1 Order Routing

**Location:** `merid/event_venues/kalshi/order_router.py`

**Findings:**
- ✅ **CORRECT:** `route_order_async()` entry point for live orders
- ✅ **CORRECT:** Caller authorization check (whitelisted modules)
- ✅ **CORRECT:** Agent whitelisting (15m crypto agents only)
- ✅ **CORRECT:** Market scope validation (15m crypto markets only)
- ✅ **CORRECT:** Series ticker extraction and normalization
- ✅ **CORRECT:** Snapshot staleness gate (90s max age)
- ✅ **CORRECT:** Global kill switches (no live data, too many reconnects)
- ✅ **CORRECT:** Deduplication cache for duplicate order prevention
- ✅ **CORRECT:** TP target registration with position cache
- ✅ **CORRECT:** Resting order tracking for edge decay monitoring
- ✅ **CORRECT:** Duplicate order handling (409 status, lookup by client_order_id)
- ✅ **CORRECT:** Exposure release on rejection
- ✅ **CORRECT:** Order group reservation release on rejection

**Issues:**
- None identified

### 3.2 Venue Adapter

**Location:** `merid/event_venues/kalshi/venue_adapter.py`

**Findings:**
- ✅ **CORRECT:** Async order submission via `_submit_live_order()`
- ✅ **CORRECT:** Fills integrity check before submission
- ✅ **CORRECT:** Kill switch check (risk_controller.can_trade())
- ✅ **CORRECT:** Venue gate check (prevent real orders in simulation modes)
- ✅ **CORRECT:** Dry-run mode (log orders instead of submitting)
- ✅ **CORRECT:** VenueGate check (block real orders in paper/sim mode)

**Issues:**
- None identified

### 3.3 Kalshi Client

**Location:** `merid/event_venues/kalshi/client.py`

**Findings:**
- ✅ **CORRECT:** `place_order_result()` for explicit error handling
- ✅ **CORRECT:** Manual order blocking (DEBUG_ALLOW_MANUAL_ORDERS flag)
- ✅ **CORRECT:** GlobalExecutionGuard final safety net
- ✅ **CORRECT:** Ticker validation before API call
- ✅ **CORRECT:** Proper error handling and logging

**Issues:**
- None identified

### 3.4 Fills Ledger

**Location:** `merid/event_venues/kalshi/fills_ledger.py`

**Findings:**
- ✅ **CORRECT:** Canonical source of fills and position truth
- ✅ **CORRECT:** Dual ingestion (WebSocket + HTTP poller)
- ✅ **CORRECT:** WebSocket fill ingestion via `ingest_ws_fill()`
- ✅ **CORRECT:** HTTP fill ingestion via `ingest_http_fills()`
- ✅ **CORRECT:** Fill deduplication (fill_id uniqueness)
- ✅ **CORRECT:** Intent linking (client_order_id to intent)
- ✅ **CORRECT:** Agent resolution from client_order_id patterns
- ✅ **CORRECT:** Hedge fill detection (client_order_id prefix HEDGE_)
- ✅ **CORRECT:** Deep OTM/ITM fill monitoring
- ✅ **CORRECT:** Reconciliation with Kalshi positions
- ✅ **CORRECT:** Exposure tracking via `get_open_exposure_usd()`

**Issues:**
- None identified

### 3.5 Fills Poller

**Location:** `merid/event_venues/kalshi/fills_poller.py`

**Findings:**
- ✅ **CORRECT:** Periodic HTTP polling for fills
- ✅ **CORRECT:** Agent map building from client_order_id patterns
- ✅ **CORRECT:** Reconciliation loop with Kalshi positions
- ✅ **CORRECT:** Position fetching without "nonzero" filter (fixed bug)
- ✅ **CORRECT:** Fill bus publishing for ledger fills

**Issues:**
- None identified

### 3.6 WebSocket Bridge

**Location:** `merid/event_venues/kalshi/ws_bridge.py`

**Findings:**
- ✅ **CORRECT:** Real-time fill ingestion from WebSocket
- ✅ **CORRECT:** Position cache update via `on_fill()`
- ✅ **CORRECT:** Fill bus publishing for ledger fills
- ✅ **CORRECT:** Dead-letter queue for failed fills (max 1000)
- ✅ **CORRECT:** Event queue with backpressure handling
- ✅ **CORRECT:** Sequence number tracking for gap detection

**Issues:**
- None identified

---

## Section 4: End-to-End Critical Path

### 4.1 Agent to Fill Flow

**Flow:**
1. `Kalshi15mLoop.run_forever()` → `run_cycle()`
2. `LeanAgentGrid15m.run_cycle()` → agent loop
3. `LeanAgent15m._execute_signal()` → OrderIntent
4. `route_order_async()` → risk checks
5. `KalshiVenueClient.place_order_result()` → Kalshi API
6. WebSocket fill event → `ws_bridge._handle_fill()`
7. `fills_ledger.ingest_ws_fill()` → canonical fill record
8. `position_cache.on_fill()` → position update

**Findings:**
- ✅ **CORRECT:** Flow is complete and wired correctly
- ✅ **CORRECT:** Each stage has proper error handling
- ✅ **CORRECT:** Deduplication at multiple levels (order gate, fills ledger)
- ✅ **CORRECT:** Reconciliation mechanisms (HTTP poller, position reconciliation)
- ✅ **CORRECT:** Monitoring and alerting (deep OTM/ITM fills, reconciliation status)

**Issues:**
- ⚠️ **P0 CRITICAL:** Series ticker mismatch breaks flow at step 2-3
  - Agent never receives 15m markets from catalog
  - No signal generated, no order submitted
  - Fix: Update agent grid YAML series_tickers

### 4.2 Safety Layers

**Layers (from outermost to innermost):**
1. VenueGate (mode check: paper vs live)
2. Execution gate (kill switch, reconciliation, fills ledger)
3. Order router (caller auth, agent whitelist, market scope)
4. KalshiRiskManager (pre-trade risk checks)
5. Order gate (deduplication, rate limiting)
6. Venue adapter (fills integrity, kill switch, venue gate)
7. Kalshi client (manual order block, GlobalExecutionGuard)
8. GlobalExecutionGuard (final safety net)

**Findings:**
- ✅ **CORRECT:** 8-layer defense in depth
- ✅ **CORRECT:** Each layer has specific purpose
- ✅ **CORRECT:** Fail-closed philosophy (block on error)
- ✅ **CORRECT:** Proper logging at each layer

**Issues:**
- None identified

---

## Section 5: Hardcoded Values and Magic Numbers

### 5.1 Critical Hardcodes

**Location:** `merid/event_venues/kalshi/order_router.py`

**Findings:**
- ⚠️ **P2 MEDIUM:** Hardcoded priority series in kill switch check
  - Line 2352: `priority_series = ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]`
  - Should use: `kalshi_agent_grid_catalog_series_tickers()`
  - Impact: Inconsistent if series tickers change
  - Fix: Use canonical series ticker function

**Location:** `merid/event_venues/kalshi/order_router.py`

**Findings:**
- ⚠️ **P2 MEDIUM:** Hardcoded asset extraction logic
  - Lines 3398-3421: Asset extraction from ticker with if/elif chain
  - Should use: Centralized asset mapping function
  - Impact: Code duplication, maintenance burden
  - Fix: Extract to shared utility function

### 5.2 Thresholds and Timeouts

**Findings:**
- ✅ **CORRECT:** Most thresholds are configurable via profile or environment
- ✅ **CORRECT:** 90s snapshot staleness threshold (KALSHI_ORDER_SNAPSHOT_MAX_AGE_S)
- ✅ **CORRECT:** 80% stale series threshold for kill switch
- ✅ **CORRECT:** 10 reconnects per hour threshold for kill switch
- ✅ **CORRECT:** 60s decision bucket width for deduplication

**Issues:**
- None critical

---

## Section 6: Legacy/Demo Code in Production Paths

### 6.1 Demo Mode Detection

**Findings:**
- ✅ **CORRECT:** KALSHI_USE_DEMO checked at multiple layers
- ✅ **CORRECT:** kalshi_place_order blocks real orders when demo mode enabled
- ✅ **CORRECT:** VenueGate prevents live orders in paper/sim mode
- ✅ **CORRECT:** Startup validations enforce KALSHI_ENV/KALSHI_USE_DEMO consistency

**Issues:**
- ⚠️ **P2 MEDIUM:** KALSHI_USE_DEMO deprecated but still used
  - Location: Multiple files (settings.py, mode_resolver.py, invariants.py)
  - Should use: KALSHI_ENV only
  - Impact: Confusion about which env var to use
  - Fix: Complete migration to KALSHI_ENV

### 6.2 PM Profile Legacy

**Findings:**
- ✅ **CORRECT:** MERID_PM_PROFILE is empty for kalshi_crypto_15m_v2
- ✅ **CORRECT:** PM profile logic is bypassed for 15m profile
- ⚠️ **P2 MEDIUM:** PM profile code still present in codebase
  - Location: `merid/prediction/pm_profiles.py`
  - Impact: Confusion about active profile
  - Fix: Add deprecation warning or remove unused code

### 6.3 KalshiContinuousTrader

**Findings:**
- ⚠️ **P1 HIGH:** KalshiContinuousTrader hard-blocked under kalshi_crypto_15m_v2
  - Location: `merid/trading/kalshi_continuous_trader.py` line 785-798
  - Impact: CT unavailable for research/parity checks
  - Fix: Remove hard assertion, add deprecation warning

---

## Section 7: Wiring Gaps and Mismatches

### 7.1 Series Ticker Mismatch (P0 CRITICAL)

**Issue:** Agent grid YAML uses base series tickers (KXBTC) but catalog uses 15M tickers (KXBTC15M)

**Evidence:**
- `config/kalshi_agent_grid.yaml`: series_tickers: [KXBTC]
- `config/kalshi_universe.py`: kalshi_agent_grid_catalog_series_tickers() returns [KXBTC15M]
- `merid/event_venues/kalshi/market_catalog.py`: _PRIORITY_SERIES uses KXBTC15M

**Impact:**
- 15m markets never reach agents
- No signal generation
- No order submission
- Complete trading failure

**Fix:**
- Update all 5 agents in kalshi_agent_grid.yaml to use 15M series tickers
- Remove _USE_CANONICAL_15M conditional in kalshi_universe.py

### 7.2 Duplicate KalshiRiskConfig (P1 HIGH)

**Issue:** Two different KalshiRiskConfig dataclasses exist

**Evidence:**
- `merid/event_venues/kalshi/kalshi_risk.py` line 145-200 (venue-specific)
- `merid/prediction/risk/kalshi_risk_engine.py` line 144-285 (PM-specific)

**Impact:**
- Confusion about which config is actually used
- PM config imported by KalshiContinuousTrader (deprecated)

**Fix:**
- Consolidate to single source of truth (venue config)
- Update KalshiContinuousTrader to use venue config
- Add deprecation warning to PM config

### 7.3 Risk Limits in Agent YAML (P1 HIGH)

**Issue:** risk_limits sections still in kalshi_agent_grid.yaml despite PROFILE-GATED comments

**Evidence:**
- All 5 agents have risk_limits sections (max_yes_position, max_no_position, max_notional_usd)
- Comments say profile overrides, but values are confusing

**Impact:**
- Confusing which source of truth is active
- Potential for profile not being applied correctly

**Fix:**
- Remove risk_limits from 5 15m agents
- Verify profile config applied via kalshi_crypto_15m.yaml

### 7.4 UTC Inconsistencies (P2 MEDIUM)

**Issue:** Some code uses local time instead of UTC

**Evidence:**
- `utils/utf8_advanced_patterns.py` line 32: time.localtime()
- `utils/utf8_focused_patterns.py` line 258: time.localtime()
- `scripts/monitor_agentgrid_runtime.py` line 159: time.localtime()
- `notifications/notification_manager.py` line 242: time.localtime() (quiet hours)

**Impact:**
- Low risk for log file naming and monitoring
- Medium risk for quiet hours (timezone inconsistency)

**Fix:**
- Standardize on UTC for all timestamps
- Clearly label local time usage for user-facing displays

### 7.5 Maintenance Window Config Duplication (P2 MEDIUM)

**Issue:** Maintenance window values duplicated in config and code

**Evidence:**
- SessionConfig has maintenance_day, maintenance_start_et, maintenance_end_et
- KalshiTradingHoursGuard has hardcoded MAINTENANCE_DAY, MAINTENANCE_START, MAINTENANCE_END

**Impact:**
- Config changes may not affect runtime behavior
- Confusion about which values are used

**Fix:**
- Remove hardcoded values from KalshiTradingHoursGuard
- Use SessionConfig values from agent grid YAML

---

## Section 8: Previous Bug Fixes

### 8.1 Bug Catalog Summary

**Total Bugs Fixed:** 20

**High Priority (6):**
- Bug 1-2: Missing timedelta import + fills_ledger.summary() PnL keys
- Bug 3: TwitterAgent missing get_health()
- Bug 4-6: New dependency health model + execution gate wiring + kill switch reason
- Bug 7-8: Wrong import paths in kalshi_api.py + get_realized_pnl() doesn't exist

**Medium Priority (11):**
- Bug 9: Hardcoded localhost:8000 in reconciliation_alerts.py
- Bug 10: Deprecated datetime.utcnow() in agent_grid.py
- Bug 11: total_open += order_count bug in continuous trader
- Bug 12: /api/v1/system/health missing dependency health
- Bug 13-20: Background tasks missing done-callbacks (8 files)

**Low Priority (3):**
- Bug 15: Hardcoded localhost:8000 in 9 strategy/endpoint files → 8011
- Bug 16: Pre-existing nested triple-quote syntax error in kelly_endpoints.py

**Pattern Established:**
Background tasks across 8 files now use done-callback pattern for error logging.

---

## Section 9: Recommendations

### 9.1 Immediate Actions (P0)

1. **Fix series ticker wiring gap** (Change 1-2)
   - Update kalshi_agent_grid.yaml series_tickers to use 15M tickers
   - Remove _USE_CANONICAL_15M conditional in kalshi_universe.py
   - Verify catalog discovery returns 15m markets for all 5 assets

### 9.2 High Priority Actions (P1)

2. **Consolidate KalshiRiskConfig** (Change 8, 11, 12)
   - Create shared location for single KalshiRiskConfig
   - Update KalshiContinuousTrader to use venue config
   - Add deprecation warning to PM config
   - Update test imports to use venue config

3. **Add profile combination validation** (Change 5)
   - Implement validate_profile_combination() in startup_validations.py
   - Prevent dangerous profile combinations

4. **Remove risk_limits from agent YAML** (Change 9)
   - Remove risk_limits sections from 5 15m agents
   - Verify profile config applied correctly

5. **Remove KalshiContinuousTrader hard-block** (Change 6)
   - Remove hard assertion
   - Add deprecation warning

### 9.3 Medium Priority Actions (P2)

6. **Standardize on UTC** (Change from Part 5)
   - Replace time.localtime() with UTC in critical paths
   - Update notification_manager.py to use UTC/ET for quiet hours

7. **Unify maintenance window config** (Change 16)
   - Remove hardcoded values from KalshiTradingHoursGuard
   - Use SessionConfig values from agent grid YAML

8. **Remove sentiment override redundancy** (Change 13-14)
   - Remove sentiment override from pm_profiles.py
   - Remove sentiment field nulling from trading_agent.py

9. **Complete KALSHI_USE_DEMO deprecation** (from Section 6)
   - Migrate all code to use KALSHI_ENV only
   - Remove KALSHI_USE_DEMO references

### 9.4 Low Priority Actions (P3)

10. **Remove archived agents** (Change 17-19)
    - Remove archived agent comments from kalshi_agent_grid.yaml
    - Remove KALSHI_ARB_SCANNER agent
    - Remove KALSHI_CATCH_ALL agent

---

## Section 10: Filter Logic Deep Audit

### 10.1 Overview

This section provides a comprehensive audit of all filter logic across the execution pipeline, from signal generation to order routing. Filters are critical safety mechanisms that prevent trading under unfavorable conditions, enforce risk limits, and ensure data quality.

**Total Filter Layers Identified:** 25+
- Upstream (Signal Generation): 8 filters
- Midstream (Risk Enforcement): 10 filters
- Downstream (Order Routing): 7 filters
- End-to-End (System-wide): 5 filters

### 10.2 Upstream Filters (Signal Generation)

**Location:** `merid/signals/crypto_15m_indicators.py`, `merid/prediction/agent_grid_15m.py`

#### 10.2.1 Crypto15mIndicatorStack Filters

**Filter 1: Volatility Gate (vol_gate_ok)**
- **Location:** `crypto_15m_indicators.py` lines 937-946
- **Logic:** Classify realized volatility into bands (low/mid/high)
- **Thresholds:**
  - vol_low_threshold: Reject if realized_vol_annualized < threshold (dead market)
  - vol_high_threshold: Reject if realized_vol_annualized > threshold (chaos)
- **Purpose:** Prevent trading in dead or chaotic markets
- **Status:** ✅ CORRECT

**Filter 2: ATR Min-Move Gate (atr_move_ok)**
- **Location:** `crypto_15m_indicators.py` lines 880-890
- **Logic:** Check if ATR/price ratio exceeds minimum threshold
- **Threshold:** atr_min_move_pct = 0.0003 (0.03% of price)
- **Purpose:** Block orders in markets with insufficient price movement
- **Status:** ✅ CORRECT

**Filter 3: Chop Gate (chop_gate_ok)**
- **Location:** `crypto_15m_indicators.py` lines 956-986
- **Logic:** Detect choppy conditions using 3 signals:
  - Consecutive closes: Need N aligned candles (3 for BTC/ETH, 2 for SOL/XRP/DOGE)
  - MACD persistence: Histogram must stay same sign for M bars
  - MACD histogram magnitude: Must exceed threshold
- **Threshold:** 2+ signals = chop detected
- **Purpose:** Prevent trading in directionless markets
- **Status:** ✅ CORRECT

**Filter 4: Bars Available Gate**
- **Location:** `crypto_15m_indicators.py` line 1022
- **Logic:** Require minimum bars for indicator computation
- **Threshold:** min_bars_required = 52 (for EMA(50))
- **Purpose:** Ensure sufficient history for reliable indicators
- **Status:** ⚠️ TEMPORARY BYPASS: Reduced to 1 for warmup (line 5596)

**Filter 5: Composite Trade Gate (trade_allowed)**
- **Location:** `crypto_15m_indicators.py` lines 1018-1023
- **Logic:** AND of vol_gate_ok, atr_move_ok, chop_gate_ok, bars_available
- **Purpose:** Single boolean for quick signal feature layer gating
- **Status:** ✅ CORRECT

**Filter 6: Trend Alignment Gate (trend_aligned)**
- **Location:** `crypto_15m_indicators.py` lines 988-1011
- **Logic:** 
  - Up: price above EMA(50) + RSI 50-70 + MACD histogram positive
  - Down: price below EMA(50) + RSI 30-50 + MACD histogram negative
  - Mean-reversion: RSI extremes (oversold/overbought)
- **Purpose:** Ensure entries align with trend regime
- **Status:** ✅ CORRECT

**Filter 7: Liquidity Gate (liquidity_ok)**
- **Location:** `crypto_15m_indicators.py` lines 948-954
- **Logic:** Check spread and depth
- **Thresholds:**
  - max_spread_cents: Reject if spread exceeds threshold
  - min_depth_at_price: Reject if depth below threshold
- **Purpose:** Ensure sufficient liquidity for execution
- **Status:** ⚠️ REMOVED from composite gate (line 1017) - microstructure handled by unified edge

#### 10.2.2 Agent Grid Signal Gate

**Filter 8: Indicator Gate**
- **Location:** `agent_grid_15m.py` lines 5584-5604
- **Logic:** Check indicator_snapshot.trade_allowed before edge computation
- **Rejection Reasons:** vol_gate, atr_move, chop, insufficient_bars
- **Purpose:** Canonical signal feature layer gating before unified edge
- **Status:** ✅ CORRECT

**Filter 9: Trend Mode Gate**
- **Location:** `agent_grid_15m.py` lines 5606-5627
- **Logic:** 
  - Trend mode: Require trend_aligned=True
  - Mean-reversion mode: Require overextended=True
- **Purpose:** Enforce signal mode (trend vs mean reversion)
- **Status:** ✅ CORRECT

### 10.3 Midstream Filters (Risk Enforcement)

**Location:** `merid/event_venues/kalshi/kalshi_risk.py`, `merid/event_venues/kalshi/dynamic_window.py`, `merid/event_venues/kalshi/market_filter.py`

#### 10.3.1 KalshiRiskManager Filters

**Filter 10: Position Limit Filter**
- **Location:** `kalshi_risk.py` check_order() method
- **Logic:** Check max_yes_position and max_no_position per market
- **Thresholds:** From profile config (kalshi_crypto_15m.yaml)
- **Purpose:** Prevent over-concentration in single market
- **Status:** ✅ CORRECT

**Filter 11: Notional Limit Filter**
- **Location:** `kalshi_risk.py` check_order() method
- **Logic:** Check max_notional_per_market_usd
- **Thresholds:** From profile config
- **Purpose:** Control per-market exposure in USD
- **Status:** ✅ CORRECT

**Filter 12: Category Exposure Filter**
- **Location:** `kalshi_risk.py` check_order() method
- **Logic:** Check category exposure for "crypto" category
- **Thresholds:** From profile config
- **Purpose:** Control total crypto exposure
- **Status:** ✅ CORRECT

**Filter 13: Per-Asset Cap Filter**
- **Location:** `kalshi_risk.py` check_order() method
- **Logic:** Check per-asset caps (BTC, ETH, SOL, XRP, DOGE)
- **Thresholds:** From profile config
- **Purpose:** Control exposure to individual assets
- **Status:** ✅ CORRECT

#### 10.3.2 Dynamic Window Filters

**Filter 14: Cooldown Filter**
- **Location:** `dynamic_window.py` lines 159-177
- **Logic:** Check if cooldown is active from invariant violation
- **Purpose:** Block trading after system invariants violated
- **Status:** ✅ CORRECT

**Filter 15: Drawdown State Filter**
- **Location:** `dynamic_window.py` lines 179-197
- **Logic:** Check if drawdown_state is SEVERE or CRITICAL
- **Purpose:** Block trading during severe drawdowns
- **Status:** ✅ CORRECT

**Filter 16: Stale Market Filter**
- **Location:** `dynamic_window.py` lines 200-218
- **Logic:** Check if market data is stale
- **Threshold:** From profile (venue_invariants_max_book_staleness_ms)
- **Purpose:** Block trading on stale data
- **Status:** ✅ CORRECT

**Filter 17: Spread Filter**
- **Location:** `dynamic_window.py` lines 220-239
- **Logic:** Check spread with tolerance based on depth
- **Thresholds:** 
  - max_spread_cents: From profile
  - tolerance: Up to 50% of max_spread_cents with depth bonus
- **Purpose:** Block trading on wide spreads
- **Status:** ✅ CORRECT

**Filter 18: Time to Expiry Filter**
- **Location:** `dynamic_window.py` lines 240-260
- **Logic:** Check time to expiry against minimum
- **Threshold:** min_time_to_expiry_min from profile
- **Purpose:** Prevent trading too close to expiry
- **Status:** ✅ CORRECT

#### 10.3.3 Market Filter

**Filter 19: Underlying Filter**
- **Location:** `market_filter.py` lines 940-941
- **Logic:** Check if underlying is in allowed_underlyings list
- **Allowed:** BTC, ETH, SOL, XRP, DOGE
- **Purpose:** Restrict to supported assets
- **Status:** ✅ CORRECT

**Filter 20: Timeframe Filter**
- **Location:** `market_filter.py` lines 944-946
- **Logic:** Check if timeframe is in allowed_timeframes list
- **Allowed:** 15m (for 15m crypto profile)
- **Purpose:** Restrict to supported timeframes
- **Status:** ✅ CORRECT

**Filter 21: Volume Floor Filter**
- **Location:** `market_filter.py` lines 949-950
- **Logic:** Check if volume >= min_volume
- **Threshold:** From MarketFilterConfig
- **Purpose:** Ensure sufficient trading volume
- **Status:** ✅ CORRECT

**Filter 22: Open Interest Floor Filter**
- **Location:** `market_filter.py` lines 953-954
- **Logic:** Check if open_interest >= min_open_interest
- **Threshold:** From MarketFilterConfig
- **Purpose:** Ensure sufficient open interest
- **Status:** ✅ CORRECT

**Filter 23: Price Range Filter**
- **Location:** `market_filter.py` lines 963-968
- **Logic:** Check if price is within min_price_cents and max_price_cents
- **Thresholds:** From MarketFilterConfig
- **Purpose:** Filter ultra-low or ultra-high priced contracts
- **Status:** ✅ CORRECT

### 10.4 Downstream Filters (Order Routing)

**Location:** `merid/event_venues/kalshi/order_router.py`, `merid/event_venues/kalshi/order_gate.py`, `merid/prediction/venue_gate.py`

#### 10.4.1 Order Router Filters

**Filter 24: Snapshot Staleness Gate**
- **Location:** `order_router.py` lines 2322-2343
- **Logic:** Check if snapshot age > KALSHI_ORDER_SNAPSHOT_MAX_AGE_S
- **Threshold:** 90 seconds (default)
- **Purpose:** Reject orders based on stale market data
- **Status:** ✅ CORRECT

**Filter 25: Global Kill Switch - No Live Data**
- **Location:** `order_router.py` lines 2345-2383
- **Logic:** Check if >80% of priority series are stale
- **Priority Series:** KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M
- **Threshold:** 80% stale = kill switch
- **Purpose:** Halt trading on system-wide data failure
- **Status:** ✅ CORRECT

**Filter 26: Global Kill Switch - Too Many Reconnects**
- **Location:** `order_router.py` lines 2385-2420
- **Logic:** Check if WebSocket reconnects exceed threshold
- **Threshold:** 10 reconnects per hour
- **Purpose:** Halt trading on connection instability
- **Status:** ✅ CORRECT

**Filter 27: Caller Authorization Filter**
- **Location:** `order_router.py` lines 619-640
- **Logic:** Check if caller module is whitelisted
- **Whitelist:** trading_agent, kalshi_continuous_trader, hedging engine, etc.
- **Purpose:** Prevent unauthorized order submission
- **Status:** ✅ CORRECT

**Filter 28: Agent Whitelist Filter**
- **Location:** `order_router.py` lines 642-660
- **Logic:** Check if agent_id is whitelisted
- **Whitelist:** 15m crypto agents (BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M)
- **Purpose:** Prevent unauthorized agents from trading
- **Status:** ✅ CORRECT

**Filter 29: Market Scope Filter**
- **Location:** `order_router.py` lines 662-680
- **Logic:** Check if market is in allowed scope (15m crypto only)
- **Allowed:** Markets with series_ticker in priority series
- **Purpose:** Prevent trading outside approved scope
- **Status:** ✅ CORRECT

#### 10.4.2 PreTradeGate Filters

**Filter 30: Deduplication Filter**
- **Location:** `order_gate.py` lines 615-632
- **Logic:** Check if order with same client_order_id already exists
- **Block States:** filled, working, expired, canceled
- **Purpose:** Prevent duplicate order submission
- **Status:** ✅ CORRECT

**Filter 31: Fill-Awareness Filter**
- **Location:** `order_gate.py` lines 634-650
- **Logic:** Check if target position already filled
- **Purpose:** Prevent over-filling target position
- **Status:** ✅ CORRECT

#### 10.4.3 Venue Gate Filters

**Filter 32: Mode Filter**
- **Location:** `venue_gate.py` check_can_trade() method
- **Logic:** Check if trading mode allows live orders
- **Allowed Modes:** LIVE_SMALL, LIVE_FULL
- **Blocked Modes:** PAPER, SIM, OBSERVATION
- **Purpose:** Prevent live orders in simulation modes
- **Status:** ✅ CORRECT

### 10.5 End-to-End Filters (System-wide)

**Location:** `core/execution_gate.py`, `merid/guards/global_execution_guard.py`

#### 10.5.1 Execution Gate Filters

**Filter 33: Kill Switch Filter**
- **Location:** `execution_gate.py` (referenced in unified_risk_engine.py)
- **Logic:** Check global kill switch status
- **Purpose:** Final safety net before order submission
- **Status:** ✅ CORRECT

**Filter 34: Venue Reconciliation Filter**
- **Location:** `execution_gate.py`
- **Logic:** Check Kalshi venue reconciliation status
- **Threshold:** Critical reconciliation issues block trading
- **Purpose:** Block trading if venue reconciliation fails
- **Status:** ✅ CORRECT

**Filter 35: Fills Ledger Reconciliation Filter**
- **Location:** `execution_gate.py`
- **Logic:** Check fills ledger reconciliation status
- **Threshold:** Fills ledger reconciliation issues block trading
- **Purpose:** Block trading if fills ledger reconciliation fails
- **Status:** ✅ CORRECT

**Filter 36: Dependency Health Filter**
- **Location:** `execution_gate.py`
- **Logic:** Check health of critical dependencies
- **Purpose:** Block trading if dependencies unhealthy
- **Status:** ✅ CORRECT

#### 10.5.2 Global Execution Guard Filters

**Filter 37: Domain Kill Switch Filter**
- **Location:** `global_execution_guard.py`
- **Logic:** Check domain-specific kill switch
- **Purpose:** Block trading for specific domain
- **Status:** ✅ CORRECT

**Filter 38: Global Kill Switch Filter**
- **Location:** `global_execution_guard.py`
- **Logic:** Check global kill switch
- **Purpose:** Block all trading system-wide
- **Status:** ✅ CORRECT

### 10.6 Filter Logic Analysis

#### 10.6.1 Filter Redundancy

**Identified Redundancies:**
1. **Liquidity Filter:** Present in both Crypto15mIndicatorStack and MarketFilter
   - Indicator stack: Spread and depth checks (removed from composite gate)
   - Market filter: Spread check with volume/OI
   - **Assessment:** Appropriate - different purposes (signal quality vs market quality)

2. **Spread Filter:** Present in Dynamic Window and MarketFilter
   - Dynamic window: Spread with tolerance for execution
   - Market filter: Spread floor for market selection
   - **Assessment:** Appropriate - different stages (execution vs selection)

3. **Kill Switch:** Multiple kill switch checks
   - Order router: No live data, too many reconnects
   - Execution gate: Global kill switch
   - Global execution guard: Domain and global kill switches
   - **Assessment:** Appropriate - defense in depth

#### 10.6.2 Filter Gaps

**Potential Gaps:**
1. **No Position Size Filter Before Edge Computation**
   - Current: Position size calculated after edge computation
   - Risk: Edge computation wasted on markets that would be rejected by position limits
   - **Recommendation:** Consider adding position size pre-check before edge computation

2. **No Latency Filter**
   - Current: No explicit filter for signal-to-execution latency
   - Risk: Stale signals may pass staleness gate but still be too old
   - **Recommendation:** Consider adding signal latency filter

3. **No Market Depth Quality Filter**
   - Current: Depth check in indicator stack (removed from composite gate)
   - Risk: Shallow markets may pass other filters but have poor execution
   - **Recommendation:** Consider adding depth quality filter in execution path

#### 10.6.3 Filter Ordering

**Current Order (Upstream to Downstream):**
1. Indicator stack filters (vol, ATR, chop, bars)
2. Trend alignment gate
3. Market quality filters (volume, OI, spread, price)
4. Risk limits (position, notional, category, asset)
5. Dynamic window (cooldown, drawdown, stale, spread, time to expiry)
6. Snapshot staleness gate
7. Global kill switches
8. Caller authorization
9. Agent whitelist
10. Market scope
11. Deduplication
12. Fill-awareness
13. Mode check
14. Execution gate checks
15. Global execution guard

**Assessment:** ✅ Appropriate ordering - early filters are cheap (indicator checks), later filters are expensive (risk calculations)

### 10.7 Filter Configuration

**Configuration Sources:**
1. **Profile Config:** `config/profiles/kalshi_crypto_15m.yaml`
   - Risk limits (position, notional, category, asset)
   - Guardrails (spread, time to expiry, staleness)
   - Strategy policy (max MD staleness)

2. **Indicator Config:** `Crypto15mIndicatorStack.IndicatorConfig`
   - Volatility thresholds
   - ATR thresholds
   - Chop filter parameters
   - Fee parameters

3. **Market Filter Config:** `MarketFilterConfig`
   - Volume floor
   - Open interest floor
   - Price range
   - Allowed underlyings/timeframes

**Assessment:** ✅ Well-structured configuration with clear separation of concerns

### 10.8 Filter Observability

**Logging:**
- Each filter logs rejection reason
- Gate trace logs in agent grid (lines 5702-5727)
- Rejection counters tracked (indicator_gate_rejections, rejection_details)

**Metrics:**
- PreTradeGate metrics (checks, blocked_duplicate)
- KalshiRiskManager metrics (rejections)
- Agent grid branch counters (diagnostic)

**Assessment:** ✅ Good observability - clear logging and metrics for debugging

### 10.9 Filter Issues

**Critical Issues:** None identified

**Medium Issues:**
1. **Temporary Warmup Bypass:** min_bars reduced from 52 to 1 (line 5596)
   - Impact: May allow trading on insufficient indicator history
   - Recommendation: Remove bypass after warmup period

2. **Liquidity Gate Removed from Composite:** liquidity_ok removed from trade_allowed (line 1017)
   - Impact: Microstructure quality not checked in signal feature layer
   - Recommendation: Verify unified edge handles microstructure adequately

**Low Issues:**
1. **Hardcoded Priority Series:** order_router.py line 2352
   - Impact: Inconsistent if series tickers change
   - Recommendation: Use kalshi_agent_grid_catalog_series_tickers()

### 10.10 Filter Summary

**Total Filters:** 38 (8 upstream, 14 midstream, 9 downstream, 7 end-to-end)

**Filter Status:**
- ✅ Correct: 36
- ⚠️ Temporary bypass: 1 (min_bars warmup)
- ⚠️ Removed from composite: 1 (liquidity_ok)

**Filter Redundancy:** Appropriate (defense in depth)

**Filter Gaps:** 3 potential gaps (position size pre-check, latency filter, depth quality)

**Filter Ordering:** Appropriate (cheap to expensive)

**Filter Configuration:** Well-structured

**Filter Observability:** Good (logging + metrics)

**Overall Assessment:** ✅ Filter logic is comprehensive, well-structured, and appropriately layered. No critical issues identified.

---

## Section 11: Safety Controls Deep Audit

This section audits critical safety controls that catch issues even when filters are "working". These controls prevent mis-wired bugs, dangerous system states, and configuration drift.

### 11.1 Asset/Series Mapping and Gate Accounting

**Canonical Asset Derivation:**

Two implementations of `_get_asset_from_series()` exist in `agent_grid_15m.py`:
- Line 2712: Returns "UNKNOWN" if no series_tickers
- Line 5481: Returns "BTC" if no series_tickers

Both extract asset from series ticker (e.g., KXBTC15M → BTC) by removing "KX" prefix and timeframe suffix (15M, H1, D1, W1, 1M, Y).

**Fallback Defaults:**

Multiple locations fall back to "BTC" when asset derivation fails:
- `agent_grid_15m.py` line 8164: `asset = agent.config.name.split("_")[0] if hasattr(agent, 'config') and "_" in agent.config.name else "BTC"`
- `orderbook.py` line 452: `asset = self.ticker.split("-")[0] if "-" in self.ticker else "BTC"`

**Issue:** Fallback to "BTC" is dangerous - if agent config is malformed, all assets incorrectly map to BTC, causing cross-asset position confusion.

**Gate Accounting Metrics:**

`asset_gate_stats` tracks per-asset gate outcomes:
- `markets`: Total markets seen
- `pass`: Markets passing should_trade
- `blocked_liq`: Blocked by liquidity/depth
- `blocked_spread`: Blocked by spread
- `blocked_risk`: Blocked by risk/capital
- `blocked_cooldown`: Blocked by cooldown
- `blocked_indicator`: Blocked by indicator/edge
- `blocked_lag`: Blocked by lag/stale data
- `blocked_other`: Other rejections

Logged via `[ASSET-GATE-SUMMARY]` per asset.

**Pipeline Metrics:**

- `markets_seen`: Total markets evaluated
- `markets_with_md`: Markets with market data
- `markets_with_spot`: Markets with valid spot price

Logged via `[OPTIMIZER-SUMMARY]` and `[CYCLE-SUMMARY]`.

**Issues:**
1. ❌ Two different `_get_asset_from_series()` implementations with different fallback behavior
2. ❌ Fallback to "BTC" in gate accounting could misattribute blocked markets
3. ⚠️ No validation that agent.config.name matches series_tickers (e.g., BTC_15M should have KXBTC15M)

**Recommendations:**
1. Consolidate to single `_get_asset_from_series()` with consistent fallback (fail-closed, not "BTC")
2. Add validation that agent name matches series ticker at startup
3. Log warning when fallback asset is used

### 11.2 Spot Alignment and Lag Checks

**Canonical Spot Validation:**

`_get_valid_spot()` in `agent_grid_15m.py` (line 2786) enforces spot data quality:
- Uses `get_spot_max_age_seconds(asset, minutes_to_expiry)` from `sla_config.py`
- Timing-aware thresholds: stricter for near-expiry contracts
- Checks asset is in SUPPORTED_ASSETS
- Retries 3 times with error logging
- Returns None (fail-closed) if spot invalid

**SLA Thresholds:**

From `sla_config.py`:
- Timing-aware max age based on minutes_to_expiry
- Shorter expiry → stricter staleness threshold
- Prevents trading on stale spot data for fast-expiring contracts

**Logging:**
- `[SPOT-PRICE-MISSING]`: No spot price after retries
- `[SPOT-STALE-SKIP]`: Spot age exceeds threshold
- `[SPOT-ASSET-INVALID]`: Asset not in supported scope
- `[SPOT-PROVIDER-MISSING]`: Spot provider disabled

**Contract-Spot Alignment:**

`[CONTRACT-SPOT-ALIGN]` logs contract-spot alignment once per strip per asset (line 4739 in agent_grid_15m.py).

**Issue:** Hardcoded 30s threshold in `candidate_optimizer.py` line 566:

```python
return age < 30.0  # Hardcoded, should use SLA config
```

This bypasses the timing-aware SLA thresholds and could allow stale spot data for near-expiry contracts.

**Issues:**
1. ❌ Hardcoded 30s staleness threshold in candidate_optimizer.py ignores SLA config
2. ⚠️ No unified spot staleness logging across all spot checks
3. ⚠️ Spot provider availability not checked at startup (only at runtime)

**Recommendations:**
1. Replace hardcoded 30s with `get_spot_max_age_seconds()` call
2. Add startup validation that spot provider is available
3. Unify spot staleness logging format across all checks

### 11.3 Bankroll and Risk Envelope Consistency

**Canonical Bankroll Source:**

`BankrollServiceV2` is the single source of truth for bankroll:
- Located in `merid/event_venues/kalshi/bankroll_service_v2.py`
- Singleton via `get_bankroll_service()`
- Cached equity with periodic refresh
- Used by: RiskEnvelopeService, KalshiRiskManager, portfolio reconciliation

**Risk Envelope Configuration:**

Profile-based risk config in `config/profiles/kalshi_crypto_15m.yaml`:
- Max notional per market
- Per-asset caps (BTC, ETH, SOL, XRP, DOGE)
- Category limits (crypto)
- Drawdown thresholds
- Kelly fraction

**Profile Gating:**

`kalshi_risk.py` has PROFILE GATING comments at lines 912, 2435, 2537, 3238, indicating profile is checked multiple times during risk manager initialization.

**Issue:** Duplicate KalshiRiskConfig dataclasses:
1. `merid/event_venues/kalshi/kalshi_risk.py` (venue-specific)
2. `merid/prediction/risk/kalshi_risk_engine.py` (PM-specific)

This creates confusion about which config is actually used for risk enforcement.

**Bankroll-Risk Consistency:**

- Risk envelope uses live bankroll from BankrollServiceV2
- Profile config can override bankroll-derived calculations
- No validation that profile config is consistent with actual bankroll

**Issues:**
1. ❌ Duplicate KalshiRiskConfig dataclasses
2. ⚠️ Profile checked 4+ times during initialization (over-engineering)
3. ⚠️ No validation that profile risk limits are consistent with actual bankroll

**Recommendations:**
1. Consolidate to single KalshiRiskConfig (venue config is canonical)
2. Single profile check at initialization, cache result
3. Add validation that profile max_notional is <= actual bankroll

### 11.4 Kill Switches and Execution Gate

**Kill Switch Sources:**

Multiple kill switch implementations:
1. `risk_controller` in `merid/risk/kill_switches.py` - Daily loss limit
2. `portfolio_risk_agent` in `merid/prediction/portfolio_risk_agent.py` - Portfolio risk
3. `integration_validator` in `merid/safety/integration_validator.py` - Integration safety
4. `risk_guard` in `merid/risk/risk_guard.py` - Global risk guard

**Kill Switch Persistence:**

- Persists to disk via `_persist_kill_switch()` in `kill_switches.py`
- Path: `data/risk_kill_switch.json` (configurable via MERID_RISK_KS_FILE)
- Reloaded on startup via `_load_persisted_kill_switch()`
- Fails-closed: defaults to BLOCKED if file corrupt

**Execution Gate:**

Located in `core/execution_gate.py`:
- Checks: kill switch, domain kill, domain enabled, promotion, CQI throttle, caps, cooldown
- Returns `ExecutionGateResult` with `allowed`, `blocked`, `reasons`
- Used by order_router before routing orders

**Kill Switch Integration:**

- `order_router.py` line 2573: Checks execution_gate before routing
- `loop_15m.py`: Checks risk_controller state
- `pm_live_readiness.py`: Checks kill switch in readiness check

**Phantom Kill Switch:**

`merid/reconciliation/venue_reconciler.py` implements phantom kill switch:
- Arms when reconciliation finds positions not in venue
- Cleared only by operator via `clear_phantom_kill_switch()`
- Prevents trading on phantom positions

**Issues:**
1. ⚠️ Multiple kill switch sources - no unified state
2. ⚠️ No validation that all kill switches are checked before trading
3. ⚠️ Phantom kill switch manual-only (no auto-clear after reconciliation fixed)

**Recommendations:**
1. Unify kill switch state into single source of truth
2. Add startup validation that execution_gate is checked in all order paths
3. Add auto-clear option for phantom kill switch after reconciliation passes

### 11.5 Reconciliation and Position Truth

**Dual Fill Ingestion:**

Fills ingested from two sources:
1. WebSocket fill channel (real-time, may be incomplete)
2. HTTP poller `/portfolio/fills` (canonical, complete)

**Idempotent Upserts:**

`fills_ledger.py` implements idempotent upserts:
- `ingest_http_fills()`: HTTP fills upsert over WS fills (enrich without zeroing)
- `ingest_ws_fill()`: WS fills ingested, HTTP completes later
- Duplicate fill_ids rejected

**Position Truth:**

- `position_cache.py`: Real-time position cache from WS fills
- `venue_adapter.py`: Uses position cache for real-time positions
- Reconciliation compares internal state vs venue state

**Reconciliation Metrics:**

`merid/reconciliation/reconciliation_metrics.py` tracks:
- Reconciliation run duration
- Discrepancy counts per venue
- Gate state changes
- Phantom kill switch triggers

**Reconciliation Gating:**

- `has_critical_discrepancies()` blocks trading on discrepancies
- Phantom kill switch arms on phantom positions
- Auto-fix for critical discrepancies (configurable)

**Issues:**
1. ⚠️ No validation that WS + HTTP fill counts match periodically
2. ⚠️ No alert if reconciliation hasn't run recently
3. ⚠️ Position cache not validated against ledger periodically

**Recommendations:**
1. Add periodic WS vs HTTP fill count reconciliation check
2. Add alert if reconciliation hasn't run in X minutes
3. Add periodic position cache vs ledger validation

### 11.6 Safety Against Config Drift and Environment Mistakes

**Profile Validation:**

`validate_profile_combination()` in `startup_validations.py` (line 987):
- Validates MERID_PM_PROFILE + MERID_PROFILE combination
- Prevents dangerous combinations (e.g., kalshi-only + production)
- Allowed: kalshi_crypto_15m_v2 + baseline/production/crypto_low_edge_dev

`validate_15m_profile()` in `profile_resolver.py` (line 44):
- Validates profile is allowed for runtime mode
- Blocks forbidden profiles (test-only, deprecated)
- Requires profile for 15m_live mode

**Environment Variable Validation:**

`KALSHI_ENV_VALIDATION` in `startup_validations.py` (line 2433):
- Blocks KALSHI_USE_DEMO in production
- Validates KALSHI_ENV vs MERID_TRADING_MODE
- Checks MERID_ALLOW_LIVE_TRADES flag

**Demo Mode Checks:**

- `matching_engine.py` line 254: `KALSHI_USE_DEMO` flag
- `order_router_15m.py` line 182: Checks "demo" in base_url
- Blocked in production via startup validation

**Config File Validation:**

`validate_required_config_files()` in `profile_resolver.py` (line 82):
- Checks kalshi_agent_grid.yaml exists
- Checks profile YAML exists
- Validates config file structure

**Issues:**
1. ⚠️ No validation that .env values match config file values
2. ⚠️ No validation that environment variables are set at startup
3. ⚠️ No validation that profile config matches agent grid config

**Recommendations:**
1. Add .env vs config file cross-validation
2. Add required environment variable check at startup
3. Add profile config vs agent grid config validation

### 11.7 Summary of Safety Control Issues

**Critical Issues:**
1. ❌ Fallback to "BTC" in asset derivation could cause cross-asset confusion
2. ❌ Hardcoded 30s spot staleness threshold ignores SLA config
3. ❌ Duplicate KalshiRiskConfig dataclasses

**High Issues:**
1. ⚠️ Two different `_get_asset_from_series()` implementations
2. ⚠️ Multiple kill switch sources without unified state
3. ⚠️ No validation that profile config matches actual bankroll

**Medium Issues:**
1. ⚠️ Profile checked 4+ times during initialization
2. ⚠️ No WS vs HTTP fill count reconciliation check
3. ⚠️ No .env vs config file cross-validation

**Low Issues:**
1. ⚠️ No alert if reconciliation hasn't run recently
2. ⚠️ Spot provider availability not checked at startup
3. ⚠️ Phantom kill switch manual-only

**Overall Assessment:** ⚠️ Safety controls are comprehensive but have gaps in consistency and validation. The most critical issue is the fallback to "BTC" in asset derivation, which could cause cross-asset position confusion. The hardcoded spot staleness threshold is also a significant gap that bypasses timing-aware SLA thresholds.

---

## Appendix A: Third-Pass Change List

**Reference:** `SYSTEM-RETRIEVED-MEMORY[63cf9aee-d031-41d6-954f-62ee3704ab09]`

**Total Changes:** 19
- P0 (Critical): 4
- P1 (High): 8
- P2 (Medium): 4
- P3 (Low): 3

**Files Modified:** 12

### P0 - Critical Changes (Series Ticker Wiring)

**Change 1:** Update kalshi_agent_grid.yaml series_tickers (CRITICAL)
- File: config/kalshi_agent_grid.yaml
- Lines: 17, 100, 150, 185, 249
- Change: Update series_tickers from base tickers (KXBTC) to 15M tickers (KXBTC15M)

**Change 2:** Fix kalshi_universe.py KALSHI_CRYPTO_PRODUCTS (CRITICAL)
- File: config/kalshi_universe.py
- Lines: 105-159
- Change: Remove _USE_CANONICAL_15M conditional, always use 15M tickers

**Change 3:** Update kalshi_ct_default_series_tickers() (LOW)
- File: config/kalshi_universe.py
- Change: Return 15M tickers for KalshiContinuousTrader

**Change 4:** Update dynamic_sizing.py asset_map (LOW)
- File: merid/prediction/dynamic_sizing.py
- Lines: 195-201
- Change: Map 15M series tickers to agents

### P1 - High Changes (Risk Config, Profiles)

**Change 5:** Add validate_profile_combination() (HIGH)
- File: merid/startup_validations.py
- Change: Add validation for profile combinations

**Change 6:** Remove KalshiContinuousTrader hard-block (HIGH)
- File: merid/trading/kalshi_continuous_trader.py
- Lines: 785-798
- Change: Remove hard assertion, add deprecation warning

**Change 7:** Remove test-only profile references (HIGH)
- File: tests/test_mode_resolver.py
- Lines: 225, 241
- Change: Remove references to non-existent profiles

**Change 8:** Add check_single_risk_config() (HIGH)
- File: merid/startup_validations.py
- Change: Add validation for single risk config

**Change 9:** Remove risk_limits from kalshi_agent_grid.yaml (HIGH)
- File: config/kalshi_agent_grid.yaml
- Change: Remove risk_limits sections from 5 agents

**Change 10:** Add deprecation warning in kalshi_15m_crypto_config.py (P2)
- File: config/kalshi_15m_crypto_config.py
- Change: Add deprecation warning

**Change 11:** Add deprecation warning in kalshi_risk_engine.py (P2)
- File: merid/prediction/risk/kalshi_risk_engine.py
- Change: Add deprecation warning

**Change 12:** Update test imports to use venue config (P2)
- Files: tests/test_bankroll_reconciliation_fixes.py, tests/test_fills_ledger_risk_separation.py, tests/test_micro_scalping_44_bankroll.py
- Change: Import from venue config instead of PM config

### P2 - Medium Changes (Sentiment, Maintenance, Backtest)

**Change 13:** Remove sentiment override from pm_profiles.py (P2)
- File: merid/prediction/pm_profiles.py
- Lines: 100-102
- Change: Remove sentiment override logic

**Change 14:** Remove sentiment field nulling from trading_agent.py (P2)
- File: merid/prediction/trading_agent.py
- Change: Remove sentiment field nulling

**Change 15:** Add validate_profile_backtest_eligibility() (P2)
- File: merid/startup_validations.py
- Change: Add validation for profile-backtest cross-validation

**Change 16:** Remove hardcoded maintenance window from KalshiTradingHoursGuard (P2)
- File: merid/guard/trading_hours.py
- Change: Remove hardcoded values, use SessionConfig

### P3 - Low Changes (Cleanup, Research)

**Change 17:** Remove archived agents from kalshi_agent_grid.yaml (P3)
- File: config/kalshi_agent_grid.yaml
- Change: Remove archived agent comments

**Change 18:** Remove KALSHI_ARB_SCANNER agent (P3)
- File: config/kalshi_agent_grid.yaml
- Change: Remove commented-out agent

**Change 19:** Remove KALSHI_CATCH_ALL agent (P3)
- File: config/kalshi_agent_grid.yaml
- Change: Remove placeholder agent

---

## Appendix B: Verification Commands

### B1. Verify Series Ticker Fix

```bash
# Check agent config summary
curl http://localhost:8011/api/v1/kalshi/agents/BTC_15M

# Check catalog discovery
curl http://localhost:8011/api/v1/kalshi/markets?series_ticker=KXBTC15M

# Check log for catalog refresh
grep "CATALOG-REFRESH-ENTRY" logs/merid.log
```

### B2. Verify Profile Combination Validation

```bash
# Set invalid combination
export MERID_PROFILE=kalshi-only
export MERID_PM_PROFILE=production
python -c "from merid.startup_validations import validate_all; validate_all()"
# Should raise ValueError

# Set valid combination
export MERID_PROFILE=kalshi_crypto_15m_v2
export MERID_PM_PROFILE=baseline
python -c "from merid.startup_validations import validate_all; validate_all()"
# Should pass
```

### B3. Verify Risk Config Consolidation

```bash
# Check startup log
grep "RISK-CONFIG-VALIDATION" logs/merid.log

# Verify no PM config import in live code
grep -r "from merid.prediction.risk.kalshi_risk_engine import" merid/event_venues/kalshi/
# Should return no results
```

---

## Appendix C: Audit Methodology

### C1. Code Review

- Systematic review of execution pipeline files
- Traced data flow from signal to fill
- Identified all safety layers and validation points
- Checked for hardcoded values and magic numbers

### C2. Configuration Audit

- Reviewed kalshi_agent_grid.yaml
- Reviewed kalshi_crypto_15m.yaml profile
- Reviewed kalshi_universe.py series ticker configuration
- Verified environment variable usage

### C3. Wiring Verification

- Traced function calls across modules
- Verified data structure consistency
- Checked for duplicate implementations
- Identified configuration mismatches

### C4. Legacy Code Detection

- Searched for deprecated patterns (KALSHI_USE_DEMO, datetime.utcnow)
- Identified demo mode checks in production paths
- Found PM profile legacy code
- Checked for archived/dead code

---

## Conclusion

The Kalshi 15m crypto execution pipeline is well-designed with multiple safety layers and comprehensive error handling. However, a **critical P0 series ticker wiring gap** prevents 15m trading entirely. This gap must be fixed before any live trading can occur.

The audit identified 22 issues across P0-P3 priorities. The third-pass change list provides 19 prioritized fixes to address these issues. The most critical fix (P0) is the series ticker wiring gap, which is a complete blocker for 15m trading.

**Next Steps:**
1. Implement P0 changes immediately (series ticker fixes)
2. Implement P1 changes (risk config consolidation, profile validation)
3. Implement P2 changes (UTC standardization, maintenance window unification)
4. Implement P3 changes (cleanup)

**Estimated Effort:**
- P0: 2-4 hours
- P1: 4-6 hours
- P2: 2-4 hours
- P3: 1-2 hours

**Total Estimated Effort:** 9-16 hours

---

**Audit Completed:** 2026-05-14  
**Auditor:** Cascade AI Assistant  
**Status:** Ready for remediation
