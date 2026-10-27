# Kalshi 15-Minute Crypto Trading Audit Report

**Date:** 2026-05-07  
**Scope:** BTC, ETH, SOL, XRP, DOGE 15-minute prediction market trading  
**Focus:** Sizing, risk management, and high-price (0.80+) contract handling  

---

## Executive Summary

This audit systematically mapped the end-to-end trading pipeline, inventoried all risk control layers, diagnosed exposure mismatches, and evaluated the 15m sizing policy for price awareness. The system has multiple overlapping risk controls with inconsistent thresholds, creating potential conflicts and trade rejections at the venue level.

**Critical Finding:** The system lacks clear authority boundaries - five different components independently size and reject orders, causing trades to pass one layer but fail at another.

**Critical Findings:**
1. **No single sizing authority** - Five components independently size/reject (TopN, PositionSizer, KalshiRiskEngine, CryptoSwarmRisk, GlobalExecutionGuard)
2. **Blunt contract caps** (max_yes_position: 2) are NOT price-aware, causing disproportionate notional risk at high contract prices
3. **Category exposure mismatch** - Three systems enforce crypto caps at 20%, 30%, and 2% (correlated stack)
4. **Multiple sizing layers** with conflicting parameters (Kelly fraction: 0.15-0.30, max_contracts: 2-50)
5. **High-price contracts (0.80+)** can exceed intended risk due to blunt 2-contract cap
6. **DOGE special case** - Wider strike selection (200% vs 15%) but same blunt contract cap

---

## Who's In Charge (Authority Boundaries)

To eliminate conflicts, the system must have clear single sources of truth:

| Function | Authority | Decision Type | Other Components |
|----------|-----------|---------------|------------------|
| **Sizing** | TopNAllocator + GlobalExecutionGuard | **Hard reject** | PositionSizer, KalshiRiskEngine, CryptoSwarmRisk (log/shrink only) |
| **Category Exposure** | CategoryExposureTracker (with unified settings) | **Hard reject** | PredictionMarketRisk, KalshiRiskConfig (read from same source) |
| **Correlated Stack** | CategoryExposureTracker (2% cap) | **Hard reject** | KalshiRiskConfig (read from same source) |
| **Drawdown** | Single drawdown component (settings-derived) | **Hard halt/partial** | All layers read from `core.settings.DRAWDOWN_*` |
| **Venue Caps** | KalshiPositionLimits (Kalshi-native) | **Hard reject** | Advisory only |

**Rule:** Risk rejections only come from GlobalExecutionGuard + CategoryExposureTracker + venue caps. All other layers log and may shrink sizes but never reject.

---

## Current vs Target Behavior (15m Agents)

| Asset | Current 15m Behavior | Target 15m Behavior |
|-------|----------------------|---------------------|
| BTC | Rare trades, 2-contract blunt caps, passes TopN but may fail at venue | Price-band based (4→1 contracts by price), 0.6-1.0% risk per trade, single rejection point |
| ETH | Venue rejections from category cap mismatch, inconsistent sizing | Internal caps aligned with CategoryExposureTracker, no unexpected Kalshi rejects |
| SOL | Similar to BTC with 20% strike width, same blunt caps | Price-band based, 20% strike width preserved, consistent sizing |
| XRP | Similar to BTC with 20% strike width, same blunt caps | Price-band based, 20% strike width preserved, consistent sizing |
| DOGE | Rare due to strict gates, same 2-contract caps as others despite 200% strike width | Stricter price bands (3→1 contracts), looser gates if edge justifies, price-aware sizing for high tail risk |

---

## 1. End-to-End Pipeline Mapping

### 1.1 Signal Generation
- **Agents:** BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M
- **Location:** `config/kalshi_agent_grid.yaml`
- **Strategy:** Micro scalping with relaxed edge thresholds (1.8-2.5%)
- **Entry window:** 30 minutes before expiry, 1-minute cutoff

### 1.2 Cross-Asset Selection
- **Module:** `merid/prediction/crypto_top_edge.py` (Crypto Top Edge Arbiter)
- **Function:** Selects top 3 edges across all 5 assets per cycle
- **Logic:** Dynamic edge floor based on rolling history, deduplication to avoid overlapping positions

### 1.3 Sizing
- **Primary:** `merid/trading/topn_allocator.py` (Top-N Edge Allocator)
  - Max cycle risk: 3% of bankroll (from `core/settings.MAX_CYCLE_RISK_PCT`)
  - Edge #1 gets minimum 1% risk budget
  - Sizes by max loss per trade respecting stop distances
- **Secondary:** `merid/event_venues/kalshi/position_sizer.py` (Fractional Kelly)
  - Kelly fraction: 0.15 default (tightened for small bankrolls)
  - Max bankroll pct: 1% per trade
  - Max contracts: 50
  - Adjusts by profit factor, expectancy, sentiment/volatility

### 1.4 Risk Checks (Sequential)
1. **PredictionMarketRisk** (`merid/prediction/risk/_prediction_risk.py`)
   - Per-market exposure limit
   - Per-side position limit (max_yes_position/max_no_position from YAML)
   - Category exposure (20% max)
   - Daily loss limit (5% of bankroll)
   - Kill switch (10%/15% drawdown)
   - Rate limiting
   - Post-fee edge minimum (0.01)

2. **KalshiRiskEngine** (`merid/prediction/risk/kalshi_risk_engine.py`)
   - Fractional Kelly with hard caps
   - Fee-aware minimum edge by price band
   - Drawdown halt (10%) and reduce (15%)
   - Max risk per trade: 1%
   - Kelly fraction: 0.20

3. **CategoryExposureTracker** (`merid/event_venues/kalshi/category_exposure.py`)
   - Category caps (crypto: 30% when calibrated, $2000 default)
   - Correlated stack cap (20% when calibrated, $800 default)
   - Per-asset caps (USD, default 0)

4. **GlobalExecutionGuard** (`merid/guards/global_execution_guard.py`)
   - 2% bankroll cap (from `MAX_CYCLE_RISK_PCT`)
   - Process-wide singleton
   - Rate limiting (per-minute, per-hour)

5. **KalshiPositionLimits** (`merid_core/kalshi/execution_pipeline.py`)
   - Venue-level position limits (25,000 contracts typical)
   - Accountability threshold (80% of limit)

### 1.5 Order Routing
- **Module:** `merid/event_venues/kalshi/order_router.py`
- **Function:** Routes through mode (mock/paper/live)
- **Gatekeeping:** Caller module whitelist to prevent bypass

### 1.6 Execution
- **API:** Kalshi REST API
- **Mode:** IOC (Immediate-or-Cancel) for near-expiry contracts

---

## 2. Risk Control Layers Inventory

### 2.1 Agent-Level (kalshi_agent_grid.yaml)
| Parameter | BTC_15M | ETH_15M | SOL_15M | XRP_15M | DOGE_15M |
|-----------|---------|---------|---------|---------|----------|
| max_yes_position | 2 | 2 | 2 | 2 | 2 |
| max_no_position | 2 | 2 | 2 | 2 | 2 |
| max_notional_usd | 0 (derive) | 0 (derive) | 0 (derive) | 0 (derive) | 0 (derive) |
| entry_window | 30 min | 30 min | 30 min | 30 min | 30 min |
| strike_max_distance | 15% | 15% | 20% | 20% | 200% |

### 2.2 Global Settings (core/settings.py)
| Parameter | Value | Description |
|-----------|-------|-------------|
| MAX_CYCLE_RISK_PCT | 3% | Max risk per cycle (was 2%) |
| MAX_TOTAL_RISK_PCT | 8% | Max total risk |
| DAILY_LOSS_CAP_PCT | 12% | Daily loss cap |
| CLUSTER_STOP_PCT | 6% | Cluster stop loss |
| USE_TOPN_ALLOCATOR | true | Enable Top-N allocator |
| SCALPER15M_BANKROLL_PCT | 2% | Bankroll allocation for 15m scalper |

### 2.3 PredictionMarketRisk (_prediction_risk.py)
| Parameter | Value | Source |
|-----------|-------|--------|
| CategoryLimit max_notional_usd | 0 (derive from bankroll) | MERID_CAT_CAP_CRYPTO_USD env var |
| CategoryLimit max_pct_of_portfolio | 20% | Hardcoded |
| Daily loss limit | 5% of bankroll | Dynamic |
| Kill switch halt | 10% drawdown | Configurable |
| Kill switch unwind | 15% drawdown | Configurable |
| Max orders per minute | 30 | Configurable |
| Max orders per hour | 300 | Configurable |

### 2.4 KalshiRiskConfig (kalshi_risk.py)
| Parameter | Value | Description |
|-----------|-------|-------------|
| category_notional_pct (crypto) | 30% | Category cap when calibrated |
| correlated_stack_pct | 2% | Single underlying across all timeframes (was 20%) |
| drawdown_halt_pct | 7% | Halt at 7% drawdown (tightened from 10%) |
| drawdown_unwind_pct | 10% | Unwind at 10% drawdown (tightened from 15%) |
| max_single_order_pct | 5% | Max per order (allows 3 contracts at 50¢) |
| max_single_order_contracts | 10 | Scalper max (was 250) |
| kelly_hard_cap | 0.30 | Max Kelly fraction (tightened from 0.50) |
| kelly_min_edge_pct | 1.0% | Minimum edge to trade (tightened from 0.5%) |
| kelly_global_notional_cap_pct | 2.0 | Max 2x equity total exposure |

### 2.5 PositionSizer (position_sizer.py)
| Parameter | Value | Description |
|-----------|-------|-------------|
| Kelly fraction | 0.15 | Default (tightened for small bankrolls) |
| max_bankroll_pct | 1% | Max exposure per trade |
| min_contracts | 1 | Minimum contracts |
| max_contracts | 50 | Maximum contracts |
| profit_factor_min | 1.3 | Minimum profit factor |
| profit_factor_max | 2.0 | Maximum profit factor |
| expectancy_min_cents | 6 | Minimum expectancy |

### 2.6 KalshiRiskEngine (kalshi_risk_engine.py)
| Parameter | Value | Description |
|-----------|-------|-------------|
| max_risk_per_trade_pct | 1% | Max risk per trade |
| Kelly fraction | 0.20 | Default Kelly fraction |
| max_contract_price_cents | 35 | Max contract price |
| min_contract_price_cents | 2 | Min contract price |
| max_position_per_market | 3 | Max positions per market |
| max_open_positions | 5 | Max total open positions |
| drawdown_halt_pct | 10% | Halt at 10% drawdown |
| drawdown_unwind_pct | 15% | Unwind at 15% drawdown |

### 2.7 CryptoSwarmRiskBTC15m (crypto_swarm_risk_btc15m.py)
| Parameter | Value | Description |
|-----------|-------|-------------|
| PER_TRADE_BASE | 0.25 | Per-trade base risk |
| PER_TRADE_HARD_CAP | 0.30 | Per-trade hard cap |
| DAILY_SOFT_STOP_PCT | 10% | Daily soft stop |
| DAILY_HARD_STOP_PCT | 15% | Daily hard stop |
| MAX_OPEN_EXPOSURE_LIVE | 50% | Max open exposure |

### 2.8 GlobalExecutionGuard (global_execution_guard.py)
| Parameter | Value | Description |
|-----------|-------|-------------|
| Bankroll cap | 2% | MAX_CYCLE_RISK_PCT from settings |
| Rate limit per minute | Configurable | From settings |
| Rate limit per hour | Configurable | From settings |

### 2.9 CategoryExposureTracker (category_exposure.py)
| Parameter | Default | Calibrated |
|-----------|---------|------------|
| Crypto category cap | $2000 | 30% of balance |
| Correlated stack cap | $800 | 20% of balance |
| Per-asset caps | $0 (unset) | Configurable via env vars |

---

## 3. Category/Venue Exposure Mismatch (ETH Example)

### 3.1 Diagnosis
Three different systems enforce category exposure caps with **inconsistent values**:

1. **CategoryExposureTracker** (category_exposure.py)
   - Default: $2000 (MERID_CAT_CAP_CRYPTO_USD env var)
   - Calibrated: 30% of bankroll
   - Correlated stack: 20% of bankroll

2. **KalshiRiskConfig** (kalshi_risk.py)
   - Category: 30% (category_notional_pct)
   - Correlated stack: 2% (correlated_stack_pct) - **10× tighter than CategoryExposureTracker!**

3. **PredictionMarketRisk** (_prediction_risk.py)
   - Category: 20% (max_pct_of_portfolio)
   - Derived from MERID_CAT_CAP_CRYPTO_USD (default 0 = 20% of bankroll)

### 3.2 Impact
- **Conflict:** CategoryExposureTracker allows 20% correlated stack, but KalshiRiskConfig caps at 2%
- **Trade rejection:** Orders may pass CategoryExposureTracker but fail at KalshiRiskManager
- **Confusion:** Multiple "source of truth" for the same risk parameter

### 3.3 Root Cause
Historical evolution without consolidation:
- CategoryExposureTracker: Original cross-agent exposure tracker
- KalshiRiskConfig: Later addition for venue-level risk
- PredictionMarketRisk: Legacy per-market risk system

---

## 4. 15m Sizing Policy Evaluation

### 4.1 Current Policy Issues

#### Issue 1: Blunt Contract Caps (NOT Price-Aware)
All 15m agents have `max_yes_position: 2, max_no_position: 2`:
- At 50¢ price: 2 contracts = **$1.00** max position
- At 85¢ price: 2 contracts = **$1.70** max position (70% more notional!)
- At 95¢ price: 2 contracts = **$1.90** max position (90% more notional!)

**Impact:** High-price contracts (0.80+) carry disproportionate notional risk for the same contract count.

#### Issue 2: Multiple Conflicting Sizing Layers
| Layer | Kelly Fraction | Max Contracts | Max Notional |
|-------|----------------|---------------|--------------|
| Agent config | N/A | 2 | Derive from bankroll |
| PositionSizer | 0.15 | 50 | 1% of bankroll |
| KalshiRiskEngine | 0.20 | N/A | 1% per trade |
| TopNAllocator | N/A | N/A | 3% cycle risk |
| GlobalExecutionGuard | N/A | N/A | 2% bankroll cap |

**Impact:** Order may pass one layer but fail at another, causing venue rejections.

#### Issue 3: DOGE Special Case Not Fully Accounted For
- DOGE_15M has wider strike selection (200% vs 15%) due to high volatility
- But uses same blunt 2-contract cap
- Higher volatility + wider strikes = higher tail risk
- Should have tighter sizing, not same cap

### 4.2 Price-Aware Sizing Design

#### Policy: No Blunt "Never Trade Above X¢" Hardcap

**Principle:** Constrain high-price contracts via **price-aware notional/risk limits**, not blunt price bans.

- Keep absolute sanity bound (1-99¢) but within that range, size strictly by notional risk and price bands
- For 0.80-0.99: allow 1 contract, ensure it stays ≤ per-trade risk and venue caps
- Goal: make contract count and contract price converge to existing per-trade/cycle risk caps (1-3% of bankroll)

#### Recommendation: Replace Blunt Caps with Price Bands

**Current:**
```yaml
risk_limits:
  max_yes_position: 2  # Blunt, not price-aware
  max_no_position: 2
```

**Proposed:**
```yaml
risk_limits:
  max_yes_position: 0  # 0 = derive from price bands
  max_no_position: 0
  max_notional_usd: 0  # Derive from bankroll
  price_bands:
    - price_range: [1, 30]    # 1-30¢
      max_contracts: 4
    - price_range: [31, 50]   # 31-50¢
      max_contracts: 3
    - price_range: [51, 70]   # 51-70¢
      max_contracts: 2
    - price_range: [71, 85]   # 71-85¢
      max_contracts: 1
    - price_range: [86, 99]   # 86-99¢
      max_contracts: 1  # High-price scalps: 1 contract max
```

**DOGE-specific bands (higher volatility, tighter caps):**
```yaml
risk_limits:
  price_bands:
    - price_range: [1, 30]    # 1-30¢
      max_contracts: 3  # Tighter than BTC/ETH (4)
    - price_range: [31, 50]   # 31-50¢
      max_contracts: 2  # Tighter than BTC/ETH (3)
    - price_range: [51, 70]   # 51-70¢
      max_contracts: 1  # Tighter than BTC/ETH (2)
    - price_range: [71, 99]   # 71-99¢
      max_contracts: 1
```

**Logic:**
- Low-price contracts (1-30¢): Allow more contracts to achieve meaningful notional
- High-price contracts (71-99¢): Limit to 1 contract to control notional risk
- Mid-range (31-70¢): Graduated sizing
- DOGE: Tighter bands due to higher tail risk from 200% strike width

**Implementation:**
1. Add `price_bands` to `AgentRiskLimits` dataclass in `agent_grid_config.py`
2. Modify `check_order` in `_prediction_risk.py` to look up max contracts by price
3. Fetch actual contract price from `KalshiMarketStateStore` before sizing
4. Define fallback policy if price missing: assume 50¢ (safe midpoint) or block
5. Add DOGE-specific bands to kalshi_agent_grid.yaml

---

## 5. Coverage and Behavior Per Asset

### 5.1 Asset Coverage
All 5 assets have 15m agents configured and enabled:
- ✅ BTC_15M
- ✅ ETH_15M
- ✅ SOL_15M
- ✅ XRP_15M
- ✅ DOGE_15M

### 5.2 Asset-Specific Differences

| Parameter | BTC | ETH | SOL | XRP | DOGE |
|-----------|-----|-----|-----|-----|------|
| Strike max distance | 15% | 15% | 20% | 20% | 200% |
| Target spot band | 6% | 6% | 8% | 8% | N/A |
| Min edge (early) | 2.5% | 2.5% | 2.5% | 2.5% | 1.8-2.5% |
| Min edge (mid) | 2.0% | 2.0% | 2.0% | 2.0% | 1.5-2.0% |
| Min edge (late) | 1.8% | 1.8% | 1.8% | 1.8% | 1.2-1.8% |
| Take-profit R-multiple | 0.5 | 0.5 | 0.6 | 0.65 | N/A |

### 5.3 DOGE Special Case
- **Wider strikes:** 200% max distance (vs 15-20% for others) due to high volatility
- **Relaxed edge thresholds:** 1.8-2.5% (vs 2.5% base for others)
- **Same contract caps:** max_yes_position: 2, max_no_position: 2
- **Risk:** Higher volatility + wider strikes = higher tail risk, but sizing unchanged

---

## 6. Reliability and Data Dependencies

### 6.1 Redis
**Usage:**
- Caching/state storage (production_status.py, risk_routes.py, api_status.py)
- Advisory only (not blocking)
- Connection checked in `check_redis_connection()`

**Risk:** Low - advisory only, system continues if Redis unavailable

### 6.2 Twitter
**Usage:**
- Sentiment analysis (twitter_fetcher.py)
- Social sentiment factor in sizing (strategy.py)
- Advisory only (size_factor multiplier)

**Risk:** Low - sentiment multiplier can default to 1.0 if unavailable

### 6.3 NATS
**Usage:**
- Event bus for orderbook data (nats_adapter.py)
- Execution pipeline (execution_pipeline.py)
- **Required:** MERID_NATS_EXECUTION_ENABLED flag

**Risk:** High - execution blocked if NATS unavailable

### 6.4 Bankroll Service
**Usage:**
- Single source of truth for equity (bankroll_service_v2.py)
- Used by all risk layers for bankroll-based caps
- **Required:** All sizing and risk checks depend on live bankroll

**Risk:** Critical - trading blocked if bankroll unavailable

### 6.5 Kalshi Market State
**Usage:**
- Live market data (market_state.py, KalshiMarketStateStore)
- Price fetching for sizing (dynamic_sizing.py)
- Orderbook data for edge calculation

**Risk:** High - falls back to 50¢ default if unavailable, but may cause sizing errors

---

## 7. Gap List and Prioritized Fixes

### P0 - Critical (Immediate Action Required)

#### Gap 1: Category Exposure Mismatch
**Issue:** Three different systems enforce crypto caps at 20%, 30%, and 2% (correlated stack)
**Impact:** Trade rejections at venue due to conflicting limits (e.g., Kalshi denies with "Category 'crypto' notional $64.95 exceeds cap $10.37" while guard thinks risk is tiny)
**Fix:**
1. Consolidate to single source of truth: `core.settings.MAX_CATEGORY_CRYPTO_PCT = 0.30`, `CORRELATED_STACK_PCT = 0.02`
2. Remove hardcoded $2000 default from CategoryExposureTracker
3. Update all three systems (PredictionMarketRisk, CategoryExposureTracker, KalshiRiskConfig) to read from settings
4. Add startup invariant check: log and abort if category_pct or correlated_stack_pct differ across systems
**Files:** `core/settings.py`, `category_exposure.py`, `kalshi_risk.py`, `_prediction_risk.py`
**Validation:** Run `tests/test_category_caps_endpoint.py`, test with ETH 15m to verify no venue rejections from cap mismatch

#### Gap 2: Blunt Contract Caps Not Price-Aware
**Issue:** max_yes_position: 2 causes disproportionate notional risk at high prices (0.80+)
**Impact:** At 95¢: 2 contracts = $1.90 (90% more notional than at 50¢)
**Fix:**
1. Add `price_bands` to `AgentRiskLimits` dataclass
2. Modify `check_order` to lookup max contracts by actual contract price
3. Fetch price from `KalshiMarketStateStore` before sizing
4. Default bands:
   - 1-30¢: 4 contracts
   - 31-50¢: 3 contracts
   - 51-70¢: 2 contracts
   - 71-99¢: 1 contract
**Files:** `agent_grid_config.py`, `_prediction_risk.py`, `kalshi_agent_grid.yaml`
**Validation:** Test with mock prices at 25¢, 50¢, 75¢, 95¢ to verify contract limits

#### Gap 3: DOGE High Volatility Not Accounted For
**Issue:** DOGE has 200% strike width but same 2-contract cap as less volatile assets
**Impact:** Higher tail risk not reflected in sizing
**Fix:**
1. Add DOGE-specific price bands with tighter caps:
   - 1-30¢: 3 contracts (vs 4 for others)
   - 31-50¢: 2 contracts (vs 3 for others)
   - 51-70¢: 1 contract (vs 2 for others)
   - 71-99¢: 1 contract
2. Or add `volatility_multiplier` to reduce sizing for high-vol assets
**Files:** `kalshi_agent_grid.yaml` (DOGE_15M section)
**Validation:** Backtest DOGE 15m with new caps to verify risk reduction

### P1 - High (This Sprint)

#### Gap 4: Multiple Conflicting Sizing Layers (CRITICAL)
**Issue:** 5 different sizing layers with inconsistent parameters (Kelly: 0.15-0.30, contracts: 2-50)
**Impact:** Orders pass one layer but fail at another, causing venue rejections
**Fix:**
1. **Establish single sizing authority:** TopNAllocator + GlobalExecutionGuard are the ONLY hard reject points
2. Make PositionSizer, KalshiRiskEngine, CryptoSwarmRisk advisory only (log/shrink, never reject)
3. Consolidate Kelly fraction to single setting: `core.settings.KELLY_FRACTION = 0.20`
4. Remove conflicting Kelly caps from PositionSizer and KalshiRiskEngine
5. Document clearly: "Risk rejections only come from GlobalExecutionGuard + CategoryExposureTracker + venue caps"
**Files:** `dynamic_sizing.py`, `position_sizer.py`, `kalshi_risk_engine.py`, `core/settings.py`, `global_execution_guard.py`
**Validation:** End-to-end test with simulated orders to verify single rejection point, log all advisory layer actions

#### Gap 5: Correlated Stack Cap Inconsistency
**Issue:** CategoryExposureTracker uses 20% (calibrated) but KalshiRiskConfig uses 2%
**Impact:** 10× mismatch in cross-timeframe stacking limits
**Fix:**
1. Use 2% as the correct value (2% is safer for cross-timeframe stacking)
2. Update CategoryExposureTracker default corr_fraction to 0.02 when calibrated
3. Update documentation to clarify 2% is for "same underlying across all timeframes"
4. Implement per-asset caps: BTC/ETH 2%, SOL/XRP 1.5%, DOGE 1% (higher volatility = tighter cap)
5. Add MERID_ASSET_CAP_*_USD env vars or settings to configure per-asset caps
**Files:** `category_exposure.py`, `kalshi_risk.py`, `core/settings.py`
**Validation:** Test with BTC 15m + BTC hourly + BTC daily concurrently, verify stack caps hit before category caps

#### Gap 6: Drawdown Threshold Inconsistency
**Issue:** Different drawdown halt/unwind values across layers (7%/10%, 10%/15%)
**Impact:** Unclear which trigger actually halts trading
**Fix:**
1. Consolidate to single source: `core.settings.DRAWDOWN_HALT_PCT = 0.10`, `DRAWDOWN_UNWIND_PCT = 0.15`
2. Remove hardcoded values from KalshiRiskConfig and other layers
3. Update all drawdown checks to read from settings, not local constants
4. Ensure exactly one place can flip system into "halt/partial" with clear logging
**Files:** `core/settings.py`, `kalshi_risk.py`, `kalshi_risk_engine.py`, `_prediction_risk.py`
**Validation:** Simulate drawdown scenarios to verify consistent halting, check logs for single source of truth

### P2 - Medium (Next Sprint)

#### Gap 7: Asset-Specific Caps Implementation
**Issue:** Per-asset caps (MERID_ASSET_CAP_*_USD) default to 0 (unset), no per-asset differentiation
**Impact:** All assets treated identically despite different volatility profiles
**Fix:**
1. Add per-asset caps to settings based on volatility:
   - BTC: 2% of bankroll
   - ETH: 2% of bankroll
   - SOL: 1.5% of bankroll (higher volatility)
   - XRP: 1.5% of bankroll (higher volatility)
   - DOGE: 1% of bankroll (highest volatility, 200% strikes)
2. Implement MERID_ASSET_CAP_*_USD env vars or settings
3. Wire CategoryExposureTracker to use these caps
**Files:** `core/settings.py`, `category_exposure.py`
**Validation:** Test with multi-asset positions, verify per-asset caps enforced, test DOGE with tighter cap

#### Gap 8: NATS Execution Flag Confusion
**Issue:** MERID_NATS_EXECUTION_ENABLED flag required but not well documented
**Impact:** Execution blocked silently if flag not set
**Fix:**
1. Add clear documentation in RUNBOOK.md
2. Add startup check with helpful error message
3. Consider making NATS optional with fallback to direct REST
**Files:** `execution_pipeline.py`, `RUNBOOK.md`
**Validation:** Test with flag unset to verify helpful error message

#### Gap 9: Bankroll Service Failure Mode
**Issue:** Trading blocked if bankroll unavailable, but no graceful degradation
**Impact:** System completely halts on transient bankroll fetch failure
**Fix:**
1. Add retry logic with exponential backoff
2. Add cached bankroll fallback (last known good value)
3. Add circuit breaker after N consecutive failures
**Files:** `bankroll_service_v2.py`
**Validation:** Test with simulated bankroll failures to verify graceful degradation

### P3 - Low (Backlog)

#### Gap 10: Twitter Sentiment Failure Mode
**Issue:** No fallback if Twitter sentiment unavailable
**Impact:** Sizing may be suboptimal but not critical
**Fix:**
1. Add default sentiment multiplier of 1.0 on failure
2. Add retry logic with timeout
3. Log warning but continue trading
**Files:** `twitter_fetcher.py`, `strategy.py`
**Validation:** Test with Twitter disabled to verify default behavior

#### Gap 11: Redis Advisory Status
**Issue:** Redis marked as advisory but not clearly documented
**Impact:** Unclear if Redis is required or optional
**Fix:**
1. Document Redis as advisory in RUNBOOK.md
2. Add clear log messages when Redis unavailable
3. Consider removing Redis dependency if not critical
**Files:** `production_status.py`, `RUNBOOK.md`
**Validation:** Test with Redis disabled to verify system continues

---

## 8. Validation and Rollback Strategies

### 8.1 Validation Strategy
1. **Unit tests:** Add tests for price band sizing logic
2. **Integration tests:** Test end-to-end order flow with mock prices
3. **Backtest:** Run paper trading with new caps for 24 hours
4. **Monitoring:** Track order rejection rates before/after changes
5. **Canary:** Deploy to one asset first (e.g., BTC) before all 5

### 8.2 Rollback Strategy
1. **Git revert:** All changes in separate commits for easy rollback
2. **Feature flags:** Add USE_PRICE_AWARE_SIZING flag to toggle new logic
3. **Config backup:** Backup kalshi_agent_grid.yaml before changes
4. **Monitoring alerts:** Alert on increased rejection rates
5. **Manual override:** Ability to set blunt caps via env vars if needed

---

## 9. Recommended Implementation Order

### Phase 1 (Week 1): Critical Fixes (Authority Boundaries)
1. **Gap 4:** Establish single sizing authority (TopN + GlobalExecutionGuard only reject)
2. **Gap 1:** Fix category exposure mismatch (unified settings source)
3. **Gap 2:** Implement price-aware sizing (price bands in AgentRiskLimits)

### Phase 2 (Week 2): Layer Consolidation
4. **Gap 5:** Fix correlated stack cap (2% unified, implement per-asset caps)
5. **Gap 6:** Unify drawdown thresholds (single settings source)
6. **Gap 3:** Add DOGE-specific caps (stricter bands for high volatility)

### Phase 3 (Week 3): Asset-Specific Tuning
7. **Gap 7:** Implement per-asset caps (BTC/ETH 2%, SOL/XRP 1.5%, DOGE 1%)
8. **Gap 8:** Improve NATS documentation (clear error messages)
9. **Gap 9:** Add bankroll retry logic (graceful degradation)

### Phase 4 (Week 4): Hardening
10. **Gap 10:** Add Twitter fallback (default multiplier on failure)
11. **Gap 11:** Clarify Redis status (document as advisory)

---

## 10. Conclusion

The Kalshi 15m crypto trading system has solid foundations with multiple risk control layers. However, the current implementation has:
- **Blunt contract caps** that are not price-aware
- **Conflicting risk parameters** across multiple layers
- **Category exposure mismatches** causing venue rejections
- **Inadequate sizing** for high-volatility assets like DOGE

The recommended fixes prioritize **price-aware sizing** and **layer consolidation** to reduce complexity and eliminate conflicts. Implementing these changes will:
- Reduce venue rejections due to cap mismatches
- Control notional risk for high-price contracts
- Provide clearer, more consistent risk management
- Improve system reliability and maintainability

**Next Steps:**
1. Review and approve this audit report
2. Prioritize fixes based on business impact
3. Begin Phase 1 implementation (critical fixes)
4. Deploy with feature flags and monitoring
5. Validate with paper trading before live deployment
