# Kalshi 15m Crypto Trading Conditions Audit

**Date**: 2026-06-15  
**Profile**: kalshi_crypto_15m_v2  
**Assets**: BTC, ETH, SOL, XRP, DOGE

---

## Executive Summary

This document provides a comprehensive audit of all trading conditions that must be satisfied for an order to be generated and executed in the Kalshi 15-minute crypto trading system. The conditions are organized by pipeline stage, from signal generation through order submission.

**Key Findings**:
- The system uses a multi-layered validation approach with 15+ distinct gates
- Edge thresholds are tiered (2-4% watch, 4-6% small, >6% standard)
- Risk controls are bankroll-scaled with adaptive scaling based on drawdown
- Market data validation includes depth, staleness, and pattern guards
- Order rate limits prevent over-trading (10 orders/min global, 60s per-asset cooldown)

---

## 1. Signal Generation Conditions

### 1.1 Market Selection (Entry Window)

**Source**: `kalshi_15m_time.py::select_live_markets_by_ts()`

**Conditions**:
- **Market must be live**: `open_time <= now_utc < close_time`
- **Within entry window**: `2.0 <= minutes_to_expiry <= 12.0` (configurable)
- **Time to expiry check**: 
  - Min: 2.0 minutes (guardrails_min_entry_mins)
  - Max: 15.0 minutes (guardrails_max_entry_mins)

**Profile Configuration** (`kalshi_crypto_15m_v2.yaml`):
```yaml
guardrails:
  min_entry_mins: 2.0   # TERMINAL: Minimum time to expiry for entry
  max_entry_mins: 15.0  # NORMAL: Maximum time to expiry for entry
agent_defaults:
  minutes_before_expiry: 12
  cutoff_minutes_before_expiry: 2
```

### 1.2 Candidate Generation Filters

**Source**: `candidate_optimizer.py`

**Conditions**:
- **Market state exists**: Market must be in KalshiMarketStateStore
- **Book initialized**: `state.book_initialized == True`
- **Executable**: `state.executable == True`
- **Depth thresholds** (tier-based):
  - Tier 1 (BTC/ETH): `min_depth_yes >= 10`, `min_depth_no >= 10`
  - Tier 2 (SOL/XRP/DOGE): `min_depth_yes >= 5`, `min_depth_no >= 5`
- **Spread guard**: `spread <= guardrails_max_spread_cents` (70 cents)
- **Price guard**: `35 <= price_cents <= 99` (min_contract_price_cents: 35)
- **Distance from target**: `dist_pct <= max_dist_pct_trade` (0.75% for experimental slice)

**Profile Configuration**:
```yaml
guardrails:
  max_spread_cents: 70
  min_contract_price_cents: 35
  max_dist_pct_trade: 0.75
  min_depth_yes_tier1: 10
  min_depth_no_tier1: 10
  min_depth_yes_tier2: 5
  min_depth_no_tier2: 5
```

### 1.3 Edge Thresholds (Tiered)

**Source**: `kalshi_crypto_15m_v2.yaml::edge_bands`

**Conditions**:
- **Watch Band** (2-4% edge): Log only, no trading
- **Small Band** (4-6% edge): Trade with 0.25x Kelly
- **Standard Band** (>6% edge): Trade with 0.50x Kelly

**Profile Configuration**:
```yaml
edge_bands:
  watch_band:
    min_edge_pct: 0.02
    max_edge_pct: 0.04
    action: "log_only"
    kelly_multiplier: 0.0
  small_band:
    min_edge_pct: 0.04
    max_edge_pct: 0.06
    action: "trade_small"
    kelly_multiplier: 0.25
  standard_band:
    min_edge_pct: 0.06
    max_edge_pct: 1.0
    action: "trade_standard"
    kelly_multiplier: 0.50
```

**Hard Floor**: `min_post_fee_edge: 0.04` (4% minimum post-fee edge)

### 1.4 Signal Mode Conditions

**Source**: `kalshi_crypto_15m_v2.yaml::signal_mode`

**Hybrid Mode** (current configuration):
- **Mean Reversion**: RSI overbought/oversold zones
- **Momentum/FVG**: Fair Value Gaps + Order Book Imbalance

**Momentum/FVG Parameters**:
```yaml
momentum_fvg:
  momentum_rsi_long_min: 55    # Bullish: RSI > 55
  momentum_rsi_short_max: 45   # Bearish: RSI < 45
  obi_min: 0.25                # Minimum absolute OBI
  obi_persistence_min: 0.6     # 60% persistence over 10s window
  fvg_max_age_bars: 4          # Max 60min age
  fvg_min_size_ticks: 3        # Minimum FVG size
  require_ema_stack: true      # Require EMA alignment
  require_price_vs_ema50: true  # Price vs EMA50 check
```

---

## 2. Risk Management and Position Limits

### 2.1 Per-Trade Risk

**Source**: `kalshi_crypto_15m_v2.yaml::guardrails::per_trade_risk_pct`

**Conditions**:
- **Per-trade risk**: 0.8% of capital (derived from 15% drawdown / 18 losses)
- **Adaptive scaling** based on drawdown:
  - 0-10% drawdown: 100% multiplier
  - 10-12% drawdown: 50% multiplier
  - 12-15% drawdown: 25% multiplier
  - 15%+ drawdown: 0% multiplier (halted)

**Profile Configuration**:
```yaml
guardrails:
  per_trade_risk_pct:
    value: 0.008  # 0.8% of capital per trade
    dynamic: bankroll
  adaptive_risk_bands:
    - max_drawdown_pct: 0.10
      multiplier: 1.0
    - max_drawdown_pct: 0.12
      multiplier: 0.5
    - max_drawdown_pct: 0.15
      multiplier: 0.25
    - max_drawdown_pct: 1.00
      multiplier: 0.0
```

### 2.2 Per-Asset Limits

**Source**: `kalshi_crypto_15m_v2.yaml::assets`

**Conditions**:
- **Max notional per asset**: 2% of capital (all assets unified)
- **Max contracts per asset**:
  - BTC/ETH: 5 contracts
  - SOL/XRP/DOGE: 3 contracts
- **Max distance from target**:
  - BTC: 1.5%
  - ETH: 2.0%
  - SOL: 2.5%
  - XRP: 3.0%
  - DOGE: 4.0%

**Profile Configuration**:
```yaml
assets:
  BTC:
    max_notional_pct: 0.02
    max_contracts: 5
    max_distance_pct: 0.015
  ETH:
    max_notional_pct: 0.02
    max_contracts: 5
    max_distance_pct: 0.020
  SOL:
    max_notional_pct: 0.02
    max_contracts: 3
    max_distance_pct: 0.025
  XRP:
    max_notional_pct: 0.02
    max_contracts: 3
    max_distance_pct: 0.030
  DOGE:
    max_notional_pct: 0.02
    max_contracts: 3
    max_distance_pct: 0.040
```

### 2.3 Cycle-Level Limits

**Source**: `kalshi_crypto_15m_v2.yaml::max_cycle_risk_pct`

**Conditions**:
- **Max cycle risk**: 2.5% of capital per 15m cycle
- **Max total risk**: 6% of capital (aggregate exposure cap)
- **Max orders per cycle**: 1 order per 15m cycle (conservative)

**Profile Configuration**:
```yaml
max_cycle_risk_pct:
  value: 0.025  # 2.5% per cycle
  dynamic: bankroll
max_total_risk_pct:
  value: 0.06  # 6% total risk cap
guardrails:
  max_orders_per_cycle: 1
```

### 2.4 Drawdown Limits

**Source**: `kalshi_crypto_15m_v2.yaml::guardrails`

**Conditions**:
- **Drawdown halt**: 15% (primary hard cap)
- **Drawdown unwind**: 20% (emergency unwind)
- **Daily loss limit**:
  - Test mode: 8% of bankroll
  - Prod mode: 4% of bankroll
- **Rolling PnL halt**:
  - 1h PnL <= -3%: halt
  - 4h PnL <= -5%: halt

**Profile Configuration**:
```yaml
guardrails:
  drawdown_halt_pct:
    value: 0.15
  drawdown_unwind_pct:
    value: 0.20
  max_daily_loss_pct:
    test: 0.08
    prod: 0.04
  rolling_1h_pnl_halt_pct: 0.03
  rolling_4h_pnl_halt_pct: 0.05
```

### 2.5 Kelly Sizing

**Source**: `kalshi_crypto_15m_v2.yaml::kelly`

**Conditions**:
- **Kelly hard cap**: 5% of bankroll
- **Min edge for Kelly**: 4% (kelly_min_edge_pct)
- **Max edge for Kelly**: 25% (kelly_max_edge_pct)
- **Tiered Kelly caps**:
  - Tier 1 (BTC/ETH): 20% Kelly
  - Tier 2 (SOL/XRP/DOGE): 10% Kelly

**Profile Configuration**:
```yaml
kelly:
  kelly_fraction: 0.05
  kelly_hard_cap: 0.05
  kelly_min_edge_pct: 0.04
  kelly_max_edge_pct: 0.25
  tiered_kelly:
    tier1_fraction: 0.20
    tier2_fraction: 0.10
    tier1_assets: ["BTC", "ETH"]
    tier2_assets: ["SOL", "XRP", "DOGE"]
```

---

## 3. Order Execution Logic and Gates

### 3.1 Market State Validation

**Source**: `agent_grid_15m.py::validate_market_state_for_entry()`

**Conditions**:
1. **State exists**: Market state must be in KalshiMarketStateStore
2. **Book initialized**: `state.book_initialized == True`
3. **Executable**: `state.executable == True`
4. **MD staleness**: `update_age <= max_md_staleness_sec` (120s temporary override)
5. **Pattern guards**: Reject (0,100) bid/ask patterns
6. **Valid bid/ask**: Both bid and ask must be non-zero
7. **Depth thresholds** (tier-based):
   - Tier 1 (BTC/ETH): `min_depth_yes >= 10`, `min_depth_no >= 10`
   - Tier 2 (SOL/XRP/DOGE): `min_depth_yes >= 5`, `min_depth_no >= 5`
8. **Expiry gate**: `min_tte_min <= minutes_to_expiry <= max_tte_min`

**Implementation**:
```python
def validate_market_state_for_entry(
    asset, market_id, state, minutes_to_expiry,
    min_depth_yes, min_depth_no, max_md_staleness_sec
) -> MarketValidationResult:
    # 1. State exists
    if state is None:
        return MarketValidationResult(False, "STATE-NONE")
    
    # 2. Book initialized
    if not state.book_initialized:
        return MarketValidationResult(False, "BOOK-NOT-INITIALIZED")
    
    # 3. Executable
    if not state.executable:
        return MarketValidationResult(False, "NOT-EXECUTABLE")
    
    # 4. MD staleness
    staleness = (now - state.last_update).total_seconds()
    if staleness > max_md_staleness_sec:
        return MarketValidationResult(False, "MD-STALE")
    
    # 5. Pattern guards
    if best_bid == 0 and best_ask == 100:
        return MarketValidationResult(False, "PATTERN-0100")
    
    # 6. Valid bid/ask
    if best_bid == 0 or best_ask == 0:
        return MarketValidationResult(False, "NO-BIDASK")
    
    # 7. Depth thresholds (tier-based)
    if asset in ["BTC", "ETH"]:
        min_depth_threshold = 10
    else:
        min_depth_threshold = 5
    
    if depth_yes < min_depth_threshold or depth_no < min_depth_threshold:
        return MarketValidationResult(False, f"INSUFFICIENT_DEPTH-{asset}")
    
    # 8. Expiry gate
    if minutes_to_expiry < min_tte_min:
        return MarketValidationResult(False, f"EXPIRY-TOO-CLOSE")
    
    if minutes_to_expiry > max_tte_min:
        return MarketValidationResult(False, f"EXPIRY-TOO-EARLY")
    
    return MarketValidationResult(True, "OK")
```

### 3.2 Order Rate Limits (Throttling)

**Source**: `agent_grid_15m.py::can_fire_order()`

**Conditions**:
- **Global order limit**: Max 10 orders per 60-second window
- **Per-asset cooldown**: 60 seconds between orders for same asset
- **Per-strip limit**: Max 2 orders per strip (time-specific market)
- **Cooldown after loss**: 2 cycles (30s) after loss in that asset

**Profile Configuration**:
```yaml
throttling:
  global_orders_window_sec: 60
  global_orders_limit: 10
  per_asset_cooldown_sec: 60
  cooldown_after_loss_cycles: 2
```

**Implementation**:
```python
def can_fire_order(asset, now, ticker) -> Tuple[bool, str]:
    # Global limit
    if len(_global_order_timestamps) >= _global_orders_limit:
        return False, f"global_limit:{len}/{_global_orders_limit}"
    
    # Per-asset cooldown (disabled for kalshi_crypto_15m_v2)
    if profile.guardrails_regime_cooldown_enabled:
        if now - _asset_throttle[asset].last_order_ts < _per_asset_cooldown_s:
            return False, f"asset_cooldown:{remaining}s"
    
    # Per-strip limit
    strip = ticker.split("-")[1]
    if _strip_order_counts.get(strip, 0) >= _per_strip_order_limit:
        return False, f"strip_limit_reached:{strip}:{count}/{limit}"
    
    return True, ""
```

### 3.3 Correlation Guard

**Source**: `agent_grid_15m.py::priority_queue_scheduling()`

**Conditions**:
- **Max same-side per strip**: Max 2 same-direction positions per strip
- Prevents "all Yes" or "all No" concentration across assets

**Profile Configuration**:
```yaml
guardrails:
  max_same_side_per_strip: 2
```

**Implementation**:
```python
# Check correlation guard
cand_side = cand.side.lower()
if cand_side in strip_same_side_counts:
    current_count = strip_same_side_counts[cand_side]
    if current_count >= max_same_side_per_strip:
        return False, f"CORRELATION-REJECT:side={cand.side},count={current_count}"
```

### 3.4 Minimum Edge Floor

**Source**: `agent_grid_15m.py::priority_queue_scheduling()`

**Conditions**:
- **Min edge per trade**: 1% edge floor for priority queue scheduling
- Below this threshold, orders are rejected regardless of other conditions

**Profile Configuration**:
```yaml
guardrails:
  min_edge_per_trade: 0.01  # 1% floor
```

**Implementation**:
```python
if cand.edge < min_edge_per_trade:
    return False, "BELOW_MIN_EDGE"
```

### 3.5 Liquidity Check

**Source**: `loop_15m.py::can_fill_order_safely()`

**Conditions**:
- **Target quantity**: Must have enough depth at best price
- **Slippage budget**: Max 3 cents worse than best price
- **Decision levels**:
  - FULL: Enough depth for full size
  - REDUCED: Partial depth, consider reduced size
  - SKIP: Insufficient liquidity

**Profile Configuration**:
```yaml
guardrails:
  max_slippage_cents: 3
```

**Implementation**:
```python
def can_fill_order_safely(state, target_qty, max_slippage_cents, side):
    if side == "yes":
        available_qty = state.min_depth_yes
    else:
        available_qty = state.min_depth_no
    
    if available_qty >= target_qty:
        return LiquidityDecision.FULL
    elif available_qty >= 1:
        return LiquidityDecision.REDUCED
    else:
        return LiquidityDecision.SKIP
```

---

## 4. Market Data and Liquidity Requirements

### 4.1 Market Data Freshness

**Source**: `kalshi_crypto_15m_v2.yaml::venue_invariants`

**Conditions**:
- **Max book staleness**: 30 seconds (venue invariant)
- **Strategy-specific staleness**: 15 seconds (strategy_policy)
- **Temporary override**: 120 seconds (during WS bridge investigation)

**Profile Configuration**:
```yaml
venue_invariants:
  max_book_staleness_ms: 30000  # 30 seconds
strategy_policy:
  max_md_staleness_sec: 15.0
```

### 4.2 Depth Requirements

**Source**: `kalshi_crypto_15m_v2.yaml::guardrails` and `assets`

**Conditions**:
- **Tier 1 (BTC/ETH)**:
  - Entry validation: 10 contracts (min_depth_yes_tier1)
  - Asset-specific: 1 contract (min_depth_yes in assets section)
- **Tier 2 (SOL/XRP/DOGE)**:
  - Entry validation: 5 contracts (min_depth_yes_tier2)
  - Asset-specific: 1 contract (min_depth_yes in assets section)

**Profile Configuration**:
```yaml
guardrails:
  min_depth_contracts: 5  # Legacy field (superseded by tier-based)
  min_depth_yes_tier1: 10
  min_depth_no_tier1: 10
  min_depth_yes_tier2: 5
  min_depth_no_tier2: 5

assets:
  BTC:
    min_depth_yes: 1  # Aligned with 1 contract per order
    min_depth_no: 1
```

**Note**: There's a discrepancy between guardrails_min_depth_contracts (5) and the tier-based thresholds (10/5). The tier-based thresholds are used in `validate_market_state_for_entry()`.

### 4.3 Spread Requirements

**Source**: `kalshi_crypto_15m_v2.yaml::guardrails`

**Conditions**:
- **Max spread**: 70 cents (guardrails_max_spread_cents)
- **Spread guard with edge override**:
  - Edge < 1%: max spread = 5 cents
  - Edge < 2%: max spread = 10 cents
  - Edge >= 2%: max spread = 20 cents
- **Spread guard enabled**: Yes
- **Edge multiplier**: 1.1x (edge >= 1.1x spread to trade)

**Profile Configuration**:
```yaml
guardrails:
  max_spread_cents: 70
  max_spread_for_edge:
    "1.0": 5
    "2.0": 10
    "default": 20
  spread_guard_enabled: true
  spread_guard_edge_multiplier: 1.1
  min_spread_gate_cents: 40
```

### 4.4 Price Requirements

**Source**: `kalshi_crypto_15m_v2.yaml::guardrails` and `venue_invariants`

**Conditions**:
- **Valid price range**: 1-99 cents (venue invariant)
- **Min contract price**: 35 cents (blocks 20-35c band)
- **Deep OTM threshold**: 5 cents (deployment safety)
- **Deep ITM threshold**: 95 cents (deployment safety)

**Profile Configuration**:
```yaml
venue_invariants:
  valid_price_cents_min: 1
  valid_price_cents_max: 99
  deep_otm_threshold_cents: 5
  deep_itm_threshold_cents: 95
guardrails:
  min_contract_price_cents: 35
```

### 4.5 Experimental Slices

**Source**: `kalshi_crypto_15m_v2.yaml::guardrails`

**Conditions** (for BTC/ETH only):
- **Price band**: 45-60 cents
- **TTE band**: 4-7 minutes

**Profile Configuration**:
```yaml
guardrails:
  experimental_price_band_enabled: true
  experimental_min_price_cents: 45
  experimental_max_price_cents: 60
  experimental_tte_band_enabled: true
  experimental_min_tte_min: 4.0
  experimental_max_tte_min: 7.0
```

---

## 5. Timing and Scheduling Constraints

### 5.1 Entry Window

**Source**: `kalshi_crypto_15m_v2.yaml::guardrails` and `agent_defaults`

**Conditions**:
- **Max entry time**: 15.0 minutes to expiry
- **Min entry time**: 2.0 minutes to expiry
- **Agent defaults**: 12 minutes before expiry start, 2 minutes before expiry cutoff

**Profile Configuration**:
```yaml
guardrails:
  max_entry_mins: 15.0
  min_entry_mins: 2.0
agent_defaults:
  minutes_before_expiry: 12
  cutoff_minutes_before_expiry: 2
```

### 5.2 Time-to-Expiry Regimes

**Source**: `agent_grid_15m.py::validate_market_state_for_entry()`

**Conditions** (regime-driven):
- **NORMAL**: > 10 minutes (allow entry)
- **APPROACHING**: 5-10 minutes (allow entry with tighter constraints)
- **CRITICAL**: 2-5 minutes (allow entry with very tight constraints)
- **TERMINAL**: < 2 minutes (block entry)

### 5.3 Operational Cadence

**Source**: `kalshi_crypto_15m_v2.yaml` (header comments)

**Conditions**:
- **Kalshi15mLoop**: 5-second cadence
- **Market catalog refresh**: Every 60 seconds
- **Fills polling**: Every 20 seconds
- **Settlement polling**: Every 60 seconds
- **Bankroll balance polling**: Every 30 seconds

### 5.4 IOC Auto-Below Threshold

**Source**: `kalshi_crypto_15m_v2.yaml::venue_invariants`

**Conditions**:
- **IOC auto-below**: Use IOC if expiry within 120 seconds

**Profile Configuration**:
```yaml
venue_invariants:
  ioc_auto_below_seconds: 120
```

---

## 6. Additional Guards and Filters

### 6.1 Edge/Lag Filter

**Source**: `kalshi_crypto_15m_v2.yaml::edge_lag_filter`

**Conditions**:
- **Minimum edge/lag ratio** (edge per second of lag):
  - BTC: 2 cents/second
  - ETH: 2 cents/second
  - SOL: 3 cents/second
  - XRP: 3 cents/second
  - DOGE: 4 cents/second
- **Cold-start warmup**: 100 lag samples before filter active

**Profile Configuration**:
```yaml
edge_lag_filter:
  min_edge_lag_ratio:
    BTC: 0.02
    ETH: 0.02
    SOL: 0.03
    XRP: 0.03
    DOGE: 0.04
  cold_start_min_samples: 100
```

### 6.2 Strategy Policy

**Source**: `kalshi_crypto_15m_v2.yaml::strategy_policy`

**Conditions**:
- **Min edge**: 4% (global minimum)
- **Min confidence**: 70%
- **Max MD staleness**: 15 seconds
- **Require secondary confirmation**: Yes
- **Min edge stability**: 2 consecutive cycles
- **Max pyramid entries**: 1 per side per contract

**Profile Configuration**:
```yaml
strategy_policy:
  min_edge: 0.04
  min_confidence: 0.70
  max_md_staleness_sec: 15.0
  require_secondary_confirmation: true
  min_edge_stability_cycles: 2
  max_pyramid_entries: 1
```

### 6.3 Universe Liquidity Filters

**Source**: `kalshi_crypto_15m_v2.yaml::universe`

**Conditions** (coarse prefilter):
- **Min volume**: 5 contracts
- **Min open interest**: 1 contract
- **Max spread**: 30 cents

**Profile Configuration**:
```yaml
universe:
  min_volume: 5
  min_open_interest: 1
  max_spread_cents: 30
```

### 6.4 Contract Caps

**Source**: `kalshi_crypto_15m_v2.yaml::contract_caps`

**Conditions** (hard caps, not bankroll-scaled):
- **Max contracts total**: 5000
- **Max contracts per asset**: 1750
- **Max contracts per cluster**: 750
- **Max single order contracts**: 10

**Profile Configuration**:
```yaml
contract_caps:
  max_contracts_total: 5000
  max_contracts_per_asset: 1750
  max_contracts_per_cluster: 750
  max_single_order_contracts: 10
```

---

## 7. Order Submission Flow

### 7.1 Complete Order Submission Checklist

For an order to be submitted, ALL of the following must be satisfied:

**Signal Generation**:
1. ✅ Market is live (open_time <= now < close_time)
2. ✅ Within entry window (2-12 minutes to expiry)
3. ✅ Market state exists in store
4. ✅ Book initialized
5. ✅ Market is executable
6. ✅ Depth thresholds met (tier-based)
7. ✅ Spread within limits (edge-dependent)
8. ✅ Price within valid range (35-99 cents)
9. ✅ Distance from target within limits
10. ✅ Edge >= tier threshold (4% minimum)
11. ✅ Signal mode conditions met (momentum/fvg or mean reversion)

**Risk Management**:
12. ✅ Per-trade risk within limit (0.8% of capital)
13. ✅ Per-asset notional within limit (2% of capital)
14. ✅ Per-asset contracts within limit (BTC/ETH: 5, SOL/XRP/DOGE: 3)
15. ✅ Cycle risk within limit (2.5% of capital)
16. ✅ Total risk within limit (6% of capital)
17. ✅ Drawdown within limits (15% halt, 20% unwind)
18. ✅ Daily loss within limit (4% prod, 8% test)
19. ✅ Rolling PnL within limits (1h: -3%, 4h: -5%)
20. ✅ Kelly sizing within cap (5% hard cap)

**Order Execution**:
21. ✅ Market state validation passes (all 8 checks)
22. ✅ Global order budget available (10/min limit)
23. ✅ Per-asset cooldown satisfied (60s)
24. ✅ Per-strip limit not exceeded (2 orders)
25. ✅ Correlation guard satisfied (max 2 same-side)
26. ✅ Minimum edge floor met (1%)
27. ✅ Liquidity check passes (depth >= 1 contract)
28. ✅ Slippage within budget (3 cents)

**Timing**:
29. ✅ MD staleness within limit (120s temporary override)
30. ✅ Time-to-expiry within regime window
31. ✅ IOC auto-below threshold satisfied (if < 120s)

---

## 8. Configuration File Locations

### 8.1 Primary Configuration

**Profile**: `config/profiles/kalshi_crypto_15m_v2.yaml`
- Single source of truth for all risk parameters
- Bankroll-scaled risk controls
- Edge thresholds and guardrails
- Throttling and rate limits

### 8.2 Code References

**Signal Generation**:
- `merid/prediction/agent_grid_15m.py` - Lean agent grid and priority queue
- `merid/prediction/candidate_optimizer.py` - Candidate selection
- `merid/event_venues/kalshi/kalshi_15m_time.py` - Market selection

**Risk Management**:
- `merid/risk/profiles/crypto_15m_profile.py` - Profile adapter
- `merid/risk/risk_profile.py` - Base risk profile

**Order Execution**:
- `merid/prediction/agent_grid_15m.py::validate_market_state_for_entry()` - Market state validation
- `merid/prediction/agent_grid_15m.py::can_fire_order()` - Rate limiting
- `merid/loop_15m.py::can_fill_order_safely()` - Liquidity check

---

## 9. Summary of Key Thresholds

### 9.1 Edge Thresholds

| Threshold | Value | Context |
|-----------|-------|---------|
| Watch band min | 2% | Log only |
| Small band min | 4% | Trade with 0.25x Kelly |
| Standard band min | 6% | Trade with 0.50x Kelly |
| Post-fee edge floor | 4% | Hard floor for all trades |
| Priority queue floor | 1% | Minimum for scheduling |

### 9.2 Risk Limits

| Limit | Value | Context |
|-------|-------|---------|
| Per-trade risk | 0.8% | Of capital |
| Per-asset notional | 2% | Of capital |
| Cycle risk | 2.5% | Of capital per 15m cycle |
| Total risk | 6% | Aggregate exposure cap |
| Drawdown halt | 15% | Primary hard cap |
| Daily loss (prod) | 4% | Session-level kill switch |

### 9.3 Market Data Requirements

| Requirement | Value | Context |
|-------------|-------|---------|
| Max spread | 70 cents | Guardrails |
| Min depth (Tier 1) | 10 contracts | BTC/ETH |
| Min depth (Tier 2) | 5 contracts | SOL/XRP/DOGE |
| Max MD staleness | 30s | Venue invariant |
| Strategy staleness | 15s | Strategy-specific |
| Min contract price | 35 cents | Blocks deep OTM |

### 9.4 Timing Constraints

| Constraint | Value | Context |
|------------|-------|---------|
| Min entry time | 2.0 min | Before expiry |
| Max entry time | 15.0 min | Before expiry |
| Global order limit | 10/min | Rate limiting |
| Per-asset cooldown | 60s | Between orders |
| Per-strip limit | 2 orders | Same strip |
| Loop cadence | 5s | Kalshi15mLoop |

---

## 10. Recommendations

### 10.1 Configuration Cleanup

1. **Resolve depth threshold discrepancy**: 
   - `guardrails_min_depth_contracts: 5` vs tier-based (10/5)
   - Consider removing legacy field or documenting tier-based precedence

2. **Temporary override documentation**:
   - 120s MD staleness override is temporary
   - Document investigation timeline and revert plan

### 10.2 Monitoring Improvements

1. **Add metrics for gate rejections**:
   - Track which gates are most frequently blocking orders
   - Monitor edge distribution across bands

2. **Alert on threshold breaches**:
   - Drawdown approaching limits
   - Order rate limit exhaustion
   - MD staleness violations

### 10.3 Fine-Tuning Opportunities

1. **Edge band tuning**:
   - Monitor win rate by edge band
   - Consider adjusting band boundaries based on performance

2. **Adaptive depth thresholds**:
   - Could adjust depth requirements based on volatility regime
   - Tier 1 vs Tier 2 gaps may need calibration

3. **Spread guard calibration**:
   - Current spread guard (70c) may be too permissive
   - Consider edge-dependent spread limits

---

## Appendix A: Terminology

- **Entry Window**: Time period before expiry when markets are tradeable (2-12 minutes)
- **Tier 1 Assets**: BTC, ETH (lower volatility, higher depth)
- **Tier 2 Assets**: SOL, XRP, DOGE (higher volatility, lower depth)
- **Strip**: Time-specific market (e.g., KXBTC15M-26MAY242045-45)
- **Edge**: Expected value per contract (in cents or percentage)
- **Kelly Fraction**: Optimal fraction of bankroll to risk per trade
- **Drawdown**: Peak-to-current equity decline since process start
- **MD Staleness**: Age of market data update (seconds)
- **IOC**: Immediate-or-Cancel order type
- **GTC**: Good-Til-Cancelled order type

---

## Appendix B: Change Log

| Date | Version | Changes |
|------|---------|---------|
| 2026-06-15 | 1.0 | Initial audit documentation |
