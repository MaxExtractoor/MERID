# Module-by-Module Invariant Checklist - 2026-08-01

## Purpose

This checklist provides invariant-driven validation for the 20 bug fixes applied to the 15m crypto trading system. Each module must agree on the same price semantics, execution semantics, and rejection reasons to ensure global consistency.

## Invariant Categories

1. **Price Semantics** - Canonical ranges, side-aware validation, clamping behavior
2. **Execution Semantics** - Maker/taker selection, edge calculation, regime routing
3. **Rejection Reasons** - Categorization, logging, monitoring
4. **Fee Semantics** - Parabolic formulas, maker vs taker, low-price handling
5. **Config Semantics** - Loading order, default overrides, reload safety

---

## Module 1: `binary_price_space.py`

### Invariant 1.1: Canonical Ranges
- **PASS**: YES canonical range is 1c-85c
- **PASS**: NO canonical range is 15c-99c
- **PASS**: YES crisis range is 1c-99c
- **PASS**: NO crisis range is 5c-99c
- **PASS**: FLB trading range minimum is 5c
- **PASS**: FLB edge band minimum is 15c

### Invariant 1.2: Side-Aware Validation
- **PASS**: `is_price_in_canonical_range` uses side parameter
- **PASS**: `is_price_in_crisis_range` uses side parameter
- **PASS**: `CanonicalBinaryMarketState.is_yes_in_range` uses side-aware YES range
- **PASS**: `CanonicalBinaryMarketState.is_no_in_range` uses side-aware NO range

### Invariant 1.3: Clamping Behavior
- **PASS**: `clamp_to_canonical_range` clamps to 5c-85c (not 10c-75c)
- **PASS**: `clamp_to_crisis_range` clamps to 1c-99c for YES, 5c-99c for NO

### Test Scenarios
```python
# Test boundary prices
assert is_price_in_canonical_range(1, "yes") == True
assert is_price_in_canonical_range(85, "yes") == True
assert is_price_in_canonical_range(86, "yes") == False
assert is_price_in_canonical_range(15, "no") == True
assert is_price_in_canonical_range(99, "no") == True
assert is_price_in_canonical_range(14, "no") == False
```

---

## Module 2: `market_regime_detector.py`

### Invariant 2.1: Execution Mode Selection
- **PASS**: Maker-dominated defaults to MAKER (not TAKER)
- **PASS**: Maker-dominated uses TAKER only if spread < 5%
- **PASS**: Taker-dominated uses MAKER execution
- **PASS**: Neutral uses adaptive routing
- **PASS**: Extreme spreads force MAKER regardless of regime

### Invariant 2.2: Regime Classification
- **PASS**: Wide spread + thick depth = MAKER_DOMINATED
- **PASS**: Narrow spread + thin depth = TAKER_DOMINATED
- **PASS**: Balanced metrics = NEUTRAL

### Test Scenarios
```python
# Test maker-dominated defaults to MAKER
metrics = RegimeMetrics(spread_cents=20, bid_depth=1000, ask_depth=1000)
classification = detector.classify(metrics)
assert classification.execution_mode == ExecutionMode.MAKER

# Test maker-dominated uses TAKER for tight spread
metrics = RegimeMetrics(spread_cents=2, bid_depth=1000, ask_depth=1000)
classification = detector.classify(metrics)
assert classification.execution_mode == ExecutionMode.TAKER
```

---

## Module 3: `agent_grid_15m.py`

### Invariant 3.1: Price Range Filters
- **PASS**: YES price filter uses 5c-85c (not 10c-75c)
- **PASS**: NO price filter uses 15c-99c (not 10c-75c)
- **PASS**: NO thesis floor is 15c (not 25c)
- **PASS**: Midpoint bonus peaks at 45c (not 25c or 42c)

### Invariant 3.2: Edge Calculation
- **PASS**: Calculates both maker and taker edge
- **PASS**: Maker edge = raw_edge - maker_fee
- **PASS**: Taker edge = raw_edge - spread - taker_fee
- **PASS**: Allows negative taker edge for MAKER execution
- **PASS**: Requires positive taker edge for TAKER execution

### Invariant 3.3: OBI Zero-Depth Blocking
- **PASS**: Blocks trading when depth_yes == 0
- **PASS**: Blocks trading when depth_no == 0
- **PASS**: Logs zero-depth incidents

### Invariant 3.4: Bid/Ask Validation
- **PASS**: Removed `is_corrupted_ask` check
- **PASS**: Removed `spread_cents_raw > 10` check
- **PASS**: Uses 1c fallback spread only for truly malformed data

### Invariant 3.5: Edge Model Flexibility
- **PASS**: Edge minimum is 0.5% (not 3.0%)
- **PASS**: Edge maximum is 15.0% (not capped at 3.0%)

### Test Scenarios
```python
# Test YES price filter
valid_prices = [p for (p, size) in yes_bids if 5 <= p <= 85 and size >= 1]
assert len(valid_prices) > 0

# Test NO price filter
no_bid = 100 - yes_ask
valid_no = [no_bid for (yes_ask, size) in yes_asks if 15 <= no_bid <= 99 and size >= 1]
assert len(valid_no) > 0

# Test edge calculation
assert executable_edge_maker_pct == edge_pct - maker_fee_pct
assert executable_edge_taker_pct == edge_pct - spread_pct - taker_fee_pct
```

---

## Module 4: `order_router.py`

### Invariant 4.1: Price Adjustment Clamping
- **PASS**: Adjusted price clamped to allocator bounds [10, 75]
- **PASS**: Clamping happens before canonical range validation
- **PASS**: Exit orders bypass clamping
- **PASS**: Canonical range violations suppress adjustment

### Invariant 4.2: Simulation Clamping
- **PASS**: Simulation uses 5c-85c (not 10c-75c)
- **PASS**: Both requested_price and fill_price clamped

### Test Scenarios
```python
# Test price adjustment clamping
adjusted = _adjust_order_price_for_fill_rate(intent, state)
assert 10 <= adjusted <= 75  # Allocator bounds

# Test simulation clamping
requested_price = max(5, min(85, int(intent.price_cents)))
fill_price = max(5, min(85, requested_price + slippage))
```

---

## Module 5: `edge_computer.py`

### Invariant 5.1: Spread Thresholds
- **PASS**: Fallback max_spread_cents is 85c (not 75c)
- **PASS**: Uses dynamic threshold manager when available

### Invariant 5.2: Midpoint Default
- **PASS**: Default price is 45c (not 42c)
- **PASS**: Midpoint of 5c-85c range

### Test Scenarios
```python
# Test spread threshold
assert max_spread_cents == 85  # Fallback

# Test midpoint default
assert price_cents == 45  # Midpoint of 5c-85c
```

---

## Module 6: `unified_edge.py`

### Invariant 6.1: Price Ceiling
- **PASS**: max_price_cents is 85c (not 75c)
- **PASS**: Uses profile value when available

### Invariant 6.2: Price Floor
- **PASS**: min_price_cents is 10c (aligned with allocator)
- **PASS**: Uses profile value when available

### Test Scenarios
```python
# Test price ceiling
assert max_price_cents == 85  # Default fallback

# Test price floor
assert min_price_cents == 10  # Default fallback
```

---

## Module 7: `fees.py` / `parabolic_fees.py`

### Invariant 7.1: Maker Fee Formula
- **PASS**: Uses parabolic formula: ceil(0.0175 × C × P × (1-P))
- **PASS**: Returns 1c minimum for 1 contract at 50c
- **PASS**: Returns 1c minimum for 1 contract at 10c

### Invariant 7.2: Taker Fee Formula
- **PASS**: Uses parabolic formula: ceil(0.07 × C × P × (1-P))
- **PASS**: Returns 1c minimum for 1 contract at 50c
- **PASS**: Returns 1c minimum for 1 contract at 10c

### Test Scenarios
```python
# Test maker fee
fee = kalshi_maker_fee_cents(1, 50)
assert fee == 1

# Test taker fee
fee = kalshi_taker_fee_cents_parabolic(0.50, 1)
assert fee == 1
```

---

## Module 8: `trading_invariants_monitor.py`

### Invariant 8.1: Monitoring Coverage
- **PASS**: Records maker opportunities
- **PASS**: Records taker opportunities
- **PASS**: Records rejections by reason
- **PASS**: Records fallback spread usage
- **PASS**: Records zero-depth incidents
- **PASS**: Records allocator bound rejections
- **PASS**: Records canonical range violations
- **PASS**: Records fee discrepancies

### Invariant 8.2: Alert Thresholds
- **PASS**: Alerts on fallback spread rate > 5%
- **PASS**: Alerts on zero depth rate > 2%
- **PASS**: Alerts on allocator bound rejection rate > 1%
- **PASS**: Alerts on fee discrepancy rate > 1%
- **PASS**: Alerts on any canonical range violation

### Test Scenarios
```python
# Test monitoring
monitor.record_maker_opportunity("KXBTC-TEST", 5.0, "MAKER_DOMINATED")
summary = monitor.get_summary()
assert summary["maker_opportunities"] == 1

# Test alerts
for _ in range(10):
    monitor.record_fallback_spread_usage("KXBTC-TEST", 50.0)
    monitor.record_maker_opportunity("KXBTC-TEST", 5.0, "MAKER_DOMINATED")
alerts = monitor.check_alerts()
assert len(alerts) > 0
```

---

## Module 9: Config Loading (`crypto_15m_profile.py`, `dynamic_thresholds.py`)

### Invariant 9.1: Loading Order
- **PASS**: Profile loads before signal generation
- **PASS**: Dynamic thresholds load after profile
- **PASS**: Module defaults are overridden by profile
- **PASS**: Profile defaults are overridden by config

### Invariant 9.2: Default Override Safety
- **PASS**: Old 10c-75c defaults cannot override new 5c-85c behavior
- **PASS**: Old 25c NO floor cannot override new 15c floor
- **PASS**: Old 3.0% edge minimum cannot override new 0.5% minimum

### Test Scenarios
```python
# Test profile loading
profile = get_active_profile()
assert profile.guardrails_max_contract_price_cents >= 85  # Should be >= 85c

# Test dynamic thresholds
threshold_manager = get_dynamic_threshold_manager()
max_spread = threshold_manager.get_max_spread_cents()
assert max_spread >= 85  # Should be >= 85c
```

---

## Module 10: Reconciliation (`fills_ledger.py`, `position_monitor.py`)

### Invariant 10.1: Fee Reconciliation
- **PASS**: Validates fee vs estimate
- **PASS**: Logs discrepancies
- **PASS**: Handles low-price fees correctly

### Invariant 10.2: PnL Accounting
- **PASS**: Correctly calculates realized PnL
- **PASS**: Correctly calculates unrealized PnL
- **PASS**: Handles partial fills correctly

### Test Scenarios
```python
# Test fee reconciliation
discrepancy = validate_fee_vs_estimate(fill, expected_fee)
assert discrepancy == 0 or discrepancy_logged

# Test PnL accounting
realized_pnl = calculate_realized_pnl(position, fills)
assert realized_pnl is not None
```

---

## End-to-End Test Scenarios

### Scenario 1: Maker-Dominated Market with Positive Maker Edge
**Setup:**
- Wide spread (20c)
- Thick depth (1000 contracts)
- Raw edge: 5%
- Maker fee: 1%
- Taker fee: 2%

**Expected Flow:**
1. Regime detector classifies as MAKER_DOMINATED
2. Execution mode set to MAKER
3. Maker edge = 5% - 1% = 4% (positive)
4. Taker edge = 5% - 20% - 2% = -17% (negative)
5. Signal proceeds with MAKER execution
6. Order submitted as limit order
7. Monitoring records maker opportunity

**Validation:**
- Execution mode is MAKER
- Order type is limit
- Monitoring shows maker opportunity
- No rejection logged

### Scenario 2: Zero-Depth Rejection
**Setup:**
- depth_yes = 0
- depth_no = 1000
- Raw edge: 5%

**Expected Flow:**
1. OBI check detects zero depth
2. Trading blocked immediately
3. Rejection reason: ZERO_DEPTH
4. Monitoring records zero-depth incident
5. No order submitted

**Validation:**
- Signal returns None
- Rejection reason is ZERO_DEPTH
- Monitoring shows zero-depth incident
- No order in order manager

### Scenario 3: Boundary Price (85c YES)
**Setup:**
- YES price: 85c
- Raw edge: 3%
- Regime: NEUTRAL

**Expected Flow:**
1. Price validation: 85c is valid (YES max)
2. Canonical range check: PASS
3. Edge calculation proceeds
4. Order submitted at 85c
5. No clamping needed

**Validation:**
- Price accepted at 85c
- No canonical range violation
- Order submitted successfully

### Scenario 4: Boundary Price (86c YES - Should Reject)
**Setup:**
- YES price: 86c
- Raw edge: 3%
- Regime: NEUTRAL

**Expected Flow:**
1. Price validation: 86c is invalid (YES max is 85c)
2. Canonical range check: FAIL
3. Signal rejected
4. Rejection reason: CANONICAL_RANGE_VIOLATION
5. Monitoring records canonical range violation

**Validation:**
- Signal returns None
- Rejection reason is CANONICAL_RANGE_VIOLATION
- Monitoring shows canonical range violation
- No order submitted

### Scenario 5: Price Adjustment at Allocator Bound
**Setup:**
- Original price: 63c
- Mid price: 100c
- Adjustment: +14c → 77c
- Allocator max: 75c

**Expected Flow:**
1. Price adjustment calculates 77c
2. Clamping detects 77c > 75c
3. Adjusted price clamped to 75c
4. Order submitted at 75c
5. Monitoring records allocator bound clamping

**Validation:**
- Adjusted price is 75c (not 77c)
- Order submitted at 75c
- Monitoring shows allocator bound interaction
- No slot allocation failure

### Scenario 6: Config Reload Safety
**Setup:**
- System running with new ranges
- Config file has old 10c-75c defaults
- Config reload triggered

**Expected Flow:**
1. Config reload detected
2. Profile values take precedence over config defaults
3. New 5c-85c behavior preserved
4. No regression to old behavior

**Validation:**
- Profile values still active
- New ranges still in effect
- No log warnings about old defaults
- Trading continues with new behavior

---

## Audit Execution Checklist

### Phase 1: Upstream Signal Paths
- [ ] Audit all signal paths emitting edge, price, confidence, regime
- [ ] Verify no hardcoded old ranges in signal generation
- [ ] Verify no taker-only execution assumptions
- [ ] Verify sibling fixes updated surrounding logic

### Phase 2: Config Loading
- [ ] Audit config loading order
- [ ] Verify old defaults cannot override new behavior
- [ ] Test config reload scenarios
- [ ] Verify profile values take precedence

### Phase 3: Midstream Order Building
- [ ] Trace spread logic in all order-building paths
- [ ] Trace fee logic in all order-building paths
- [ ] Trace price-adjustment logic in all order-building paths
- [ ] Check for duplicated clamping or validation
- [ ] Verify no double normalization

### Phase 4: Downstream Reconciliation
- [ ] Audit fills accounting
- [ ] Audit cancellations
- [ ] Audit partial fills
- [ ] Audit fee/PnL reconciliation
- [ ] Verify no reconciliation gaps

### Phase 5: End-to-End Scenarios
- [ ] Run maker-opportunity scenario
- [ ] Run zero-depth rejection scenario
- [ ] Run boundary price scenarios
- [ ] Run price adjustment scenario
- [ ] Run config reload scenario

### Phase 6: Non-Core Module Sweep
- [ ] Search for remaining 10c-75c constants
- [ ] Search for remaining 25c NO floor
- [ ] Search for remaining 3.0% edge minimum
- [ ] Search for remaining 42c midpoint
- [ ] Update or document any intentional constants

---

## Pass/Fail Criteria

### Module Pass: All invariants PASS
- All price semantics match
- All execution semantics match
- All rejection reasons are consistent
- All fee semantics are correct
- All config loading is safe

### Module Fail: Any invariant FAIL
- Price semantics mismatch
- Execution semantics mismatch
- Rejection reason inconsistency
- Fee semantics incorrect
- Config loading unsafe

### System Pass: All modules PASS
- Global consistency achieved
- No hidden downstream inconsistencies
- End-to-end scenarios pass
- Config reload safe

### System Fail: Any module FAIL
- Global inconsistency detected
- Downstream inconsistency detected
- End-to-end scenario fails
- Config reload unsafe
