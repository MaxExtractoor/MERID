# P2 Entry Timing Improvements - Deployment Decision

## Status: Code Complete, Gated by Environment Variables

All P2 entry timing improvements have been implemented and are **disabled by default**. They can be enabled via environment variables when data supports their deployment.

## Implementation Summary

### 1. Patience Filter (check_patience_filter)
- **File:** `merid/prediction/entry_timing_filters.py`
- **Function:** Only enter if price is sufficiently favorable relative to spot
- **Enable:** `MERID_PATIENCE_FILTER_ENABLED=true`
- **Config:** `MERID_PATIENCE_DISCOUNT_CENTS` (default: 200 = 2 cents)
- **Wired in:** `agent_grid_15m.py:2604-2616`
- **Log tag:** `[PATIENCE-FILTER-REJECT]`

### 2. Time-Weighted Edge Threshold (get_time_weighted_edge_threshold)
- **File:** `merid/prediction/entry_timing_filters.py`
- **Function:** Require higher edge early in window, relax later
- **Enable:** `MERID_TIME_WEIGHTED_EDGE_ENABLED=true`
- **Logic:** 
  - First 25%: 1.5x base threshold
  - 25-50%: 1.25x base threshold
  - 50-75%: 1.0x base threshold
  - Last 25%: 0.75x base threshold
- **Wired in:** `agent_grid_15m.py:2619-2671`
- **Log tag:** `[TIME-WEIGHTED-EDGE-REJECT]`

### 3. Pullback Condition (check_pullback_condition)
- **File:** `merid/prediction/entry_timing_filters.py`
- **Function:** Require price to move against signal direction before entering
- **Status:** **Placeholder only** - requires price history tracking infrastructure
- **Enable:** `MERID_PULLBACK_CHECK_ENABLED=true`
- **Config:** `MERID_MIN_PULLBACK_CENTS` (default: 100)
- **Wired in:** `agent_grid_15m.py:2674-2681` (logs skipped message)
- **Log tag:** `[PULLBACK-CHECK-SKIPPED]`

### 4. Size Scaling by Entry Timing Quality (scale_size_by_timing_quality)
- **File:** `merid/prediction/entry_timing_filters.py`
- **Function:** Reduce size for early entries with high early entry cost
- **Enable:** `MERID_SIZE_SCALING_ENABLED=true`
- **Logic:**
  - early_entry_cost_r < 0.1: 100% size
  - early_entry_cost_r < 0.3: 75% size
  - early_entry_cost_r < 0.5: 50% size
  - early_entry_cost_r >= 0.5: 25% size
- **Wired in:** `agent_grid_15m.py:2488-2523`
- **Log tag:** `[SIZE-SCALING-APPLIED]`

## Deployment Decision Framework

### Step 1: Run Validation Scripts
Before enabling any P2 improvements, run the validation scripts to gather data:

```bash
# Validate BTC wiring
python scripts/validate_btc_wiring.py

# Analyze recent logs (if available)
python scripts/log_sweep_per_asset.py --log-dir /path/to/logs --hours 24

# Check clock skew
python scripts/check_clock_skew.py
```

### Step 2: Analyze Funnel Data

From `log_sweep_per_asset.py` output, identify the bottleneck:

**If BTC has almost no signals:**
- **Decision:** DEFER P2 - not an entry timing issue
- **Action:** Investigate signal generation logic, spot price feeds, threshold configuration

**If BTC has signals but high scheduler rejections:**
- **Decision:** DEFER P2 - not an entry timing issue
- **Action:** Investigate time window configuration, MD health checks

**If BTC has signals and passes scheduler but high risk rejections:**
- **Decision:** DEFER P2 - not an entry timing issue
- **Action:** Investigate risk limits, sizing configuration

**If BTC has signals, passes scheduler/risk, but low fill rate:**
- **Decision:** DEFER P2 - execution issue, not entry timing
- **Action:** Investigate order book depth, price source classification

**If BTC has signals, passes all checks, fills occur, but poor realized PnL:**
- **Decision:** ENABLE P2 (time-weighted edge threshold first)
- **Action:** Set `MERID_TIME_WEIGHTED_EDGE_ENABLED=true`
- **Rationale:** Poor PnL suggests early entries are leaving PnL on the table

### Step 3: Incremental Deployment

If data supports P2 deployment, follow this order:

**Phase 1: Time-Weighted Edge Threshold (Least Invasive)**
```bash
export MERID_TIME_WEIGHTED_EDGE_ENABLED=true
```
- Monitor for 24-48 hours
- Check if signal count decreases (expected)
- Check if fill rate improves (expected)
- Check if realized PnL improves (expected)

**Phase 2: Patience Filter (If Phase 1 Successful)**
```bash
export MERID_PATIENCE_FILTER_ENABLED=true
export MERID_PATIENCE_DISCOUNT_CENTS=200
```
- Monitor for 24-48 hours
- Check if order count decreases (expected)
- Check if fill rate improves (expected)
- Adjust discount based on results

**Phase 3: Size Scaling (If Phase 2 Successful)**
```bash
export MERID_SIZE_SCALING_ENABLED=true
```
- Monitor for 24-48 hours
- Check if position sizes vary by timing (expected)
- Check if risk-adjusted returns improve (expected)

**Phase 4: Pullback Condition (Requires Infrastructure)**
- NOT READY - requires price history tracking per market
- TODO: Implement sliding window price history in market state store
- TODO: Wire price history into signal generation path

## Current Recommendation

**Status: DEFER P2 until data available**

The P2 code is complete and ready to use, but should not be enabled until:
1. Validation scripts are run and data is collected
2. Funnel analysis identifies early entry timing as the bottleneck
3. Time-weighted edge threshold is tested first (least invasive)

## Rollback Plan

If any P2 improvement causes issues:
1. Set the corresponding env var to `false`
2. Restart the trading system
3. Monitor recovery

Example rollback:
```bash
export MERID_TIME_WEIGHTED_EDGE_ENABLED=false
# Restart system
```

## Monitoring

When P2 is enabled, monitor these metrics:
- Signal count per asset (should decrease with filters)
- Order count per asset (should decrease with filters)
- Fill rate per asset (should improve with better timing)
- Realized PnL per asset (should improve with better timing)
- Early entry cost R (should decrease with filters)

Use `scripts/health_dashboard.py` for real-time monitoring during P2 deployment.
