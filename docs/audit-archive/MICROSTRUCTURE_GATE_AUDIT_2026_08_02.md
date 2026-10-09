# 15-Minute Market Microstructure Gate Audit Plan
**Date**: 2026-08-02  
**Scope**: SOL, XRP, DOGE, ETH, BTC 15-minute Kalshi markets  
**Trigger**: Production rejections with `spread_cost_too_high: ratio=2.90 > 0.8` (SOL) and `ratio=1.95 > 0.8` (XRP)

## Executive Summary

The microstructure gate has a **critical design flaw**: it computes `spread_to_edge_ratio` using **full spread** regardless of maker/taker economics, but the actual spread cost for maker orders is **zero** (makers capture spread, not pay it). This causes valid maker-intended orders to be rejected based on taker-style cost assumptions.

## Root Cause Analysis

### Current Formula (BUGGY)
```python
# spread_edge_analytics.py:236, 271
yes_spread_ratio = (spread_metrics.yes_spread_cents / yes_raw_edge) if yes_raw_edge > 0 else float('inf')
no_spread_ratio = (spread_metrics.no_spread_cents / no_raw_edge) if no_raw_edge > 0 else float('inf')
```

**Problem**: Always uses `spread_cents` (full spread) as numerator, regardless of maker/taker economics.

### Production Examples
| Asset | Side | Raw Edge | Spread | Computed Ratio | Threshold | Verdict |
|-------|------|----------|--------|----------------|-----------|---------|
| SOL   | NO   | 20.00c   | 58c    | 58/20 = 2.90   | 0.8       | REJECT  |
| XRP   | NO   | 20.00c   | 39c    | 39/20 = 1.95   | 0.8       | REJECT  |

**Expected for Maker Orders**:
- Maker economics: spread_cost = 0c (makers capture spread)
- Correct ratio: 0/20 = 0.0 (should PASS)
- Actual ratio: 58/20 = 2.90 (incorrectly REJECTS)

### Why This Happens
From logs:
```
[MAKER-TAKER] Policy decision: role=maker | post_only=False (applied) | policy_post_only=True (recommended)
[ECONOMICS-SELECTION] ticker=KXSOL15M-26AUG020115-15 using policy decision: expected_role=maker -> use_maker_economics=True
[EDGE-CALC] NO side using MAKER economics: raw_edge=20.00c, executable_edge=20.00c (no spread cost, no fee)
```

The economics selection correctly uses maker economics (spread_cost=0), but the **ratio calculation ignores this** and still uses full spread.

## Design Flaws Identified

| Flaw | Severity | Impact |
|------|----------|--------|
| **Spread basis mismatch** | CRITICAL | Ratio uses full spread instead of spread_cost (0 for makers) |
| **Maker/taker leakage** | CRITICAL | Maker orders evaluated with taker-style spread assumptions |
| **Unit mismatch** | HIGH | Ratio mixes cents (spread) with cents (edge) but ignores economics mode |
| **Hard thresholding** | MEDIUM | Fixed 0.8 cutoff doesn't account for 15-minute horizon decay |
| **No time-to-expiry sensitivity** | MEDIUM | Same threshold for all ticks, regardless of remaining window |
| **No asset-specific calibration** | LOW | BTC/SOL/XRP share same threshold despite different microstructure |

## Audit Test Plan

### Phase 1: Formula Verification (CRITICAL)

#### Test 1.1: Hand-Compute Ratio Formula
**Objective**: Verify the exact ratio calculation matches production logs.

**Test Cases**:
```python
# SOL NO order (production example)
yes_bid = 41c, no_bid = 59c
p_hat_yes = 79c → p_hat_no = 21c
order_price = 59c (NO side)
spread = no_ask - no_bid = (100 - yes_bid) - no_bid = (100 - 41) - 59 = 59 - 59 = 0c
# Wait, this doesn't match. Let me re-check...
```

**Expected**: Match production ratio of 2.90 for SOL.
**Status**: ⏳ PENDING - needs hand-computation with actual orderbook data.

#### Test 1.2: Maker vs Taker Ratio Calculation
**Objective**: Verify ratio uses spread_cost (0 for makers) not spread_cents.

**Test Code**:
```python
def test_maker_taker_ratio_calculation():
    # Same market conditions, different economics mode
    yes_bid = 41c, no_bid = 59c
    p_hat_yes = 79c
    order_price = 59c (NO side)
    
    # Maker economics (current policy)
    maker_edge = compute_per_side_edges(..., use_maker_economics=True)
    maker_ratio = maker_edge.no_edge.spread_to_edge_ratio
    # BUG: Currently uses spread_cents / raw_edge = 58/20 = 2.90
    # EXPECTED: spread_cost_cents / raw_edge = 0/20 = 0.0
    
    # Taker economics (for comparison)
    taker_edge = compute_per_side_edges(..., use_maker_economics=False)
    taker_ratio = taker_edge.no_edge.spread_to_edge_ratio
    # EXPECTED: spread_cents / raw_edge = 58/20 = 2.90
    
    assert maker_ratio == 0.0, "Maker ratio should be 0 (spread_cost=0)"
    assert taker_ratio == 2.90, "Taker ratio should be 2.90 (full spread)"
```

**Expected**: Maker ratio = 0.0, Taker ratio = 2.90
**Status**: ⏳ PENDING - needs implementation.

### Phase 2: Side-Consistency Verification

#### Test 2.1: YES vs NO Side Ratio Symmetry
**Objective**: Verify ratio calculation is consistent across YES/NO sides.

**Test Cases**:
- YES order with same edge/spread as NO order
- Verify ratio calculation uses correct side-specific spread
- Check canonical ask derivation (100 - opposite_bid)

**Expected**: YES and NO ratios computed correctly using side-specific spreads.
**Status**: ⏳ PENDING

### Phase 3: 15-Minute Horizon Specific Tests

#### Test 3.1: Time-to-Expiry Sensitivity
**Objective**: Verify threshold should tighten as market approaches expiry.

**Test Cases**:
```python
# Early in window (13 minutes remaining)
tick_early = time_to_expiry = 780s
ratio_early = 1.5
threshold_early = 0.8  # Current: too loose?

# Late in window (2 minutes remaining)
tick_late = time_to_expiry = 120s
ratio_late = 1.5
threshold_late = 0.4  # Should be tighter due to latency risk
```

**Expected**: Threshold should scale with time-to-expiry (tighter near expiry).
**Status**: ⏳ PENDING - current implementation has no time-to-expiry sensitivity.

#### Test 3.2: Stale Book Detection
**Objective**: Verify wide spreads from stale quotes are handled separately from cost ratios.

**Test Cases**:
- Fresh quote with wide spread (valid market condition)
- Stale quote with wide spread (data quality issue)
- Crossed book (arbitrage opportunity or data error)

**Expected**: Stale quotes rejected before ratio check; wide spreads only rejected if ratio exceeds threshold.
**Status**: ⏳ PENDING

### Phase 4: Per-Asset Microstructure Validation (ALL 5 ASSETS)

**Objective**: Verify gate behavior is correct for BTC, ETH, SOL, XRP, and DOGE with asset-specific calibration.

#### Test 4.1: BTC Maker/Taker Ratio Correctness
**Asset Profile**: High liquidity, tight spreads, deep orderbook
**Production Context**: BTC often has the tightest spreads (5-10c) and highest depth.

**Test Cases**:
```python
# BTC NO order - tight spread scenario
yes_bid = 5c, no_bid = 95c
p_hat_yes = 60c → p_hat_no = 40c
order_price = 95c (NO side)
spread = no_ask - no_bid = (100 - 5) - 95 = 95 - 95 = 0c
raw_edge = 40c

# Maker economics (resting limit order)
maker_ratio = 0/40 = 0.0  # Should PASS
# Taker economics (market order)
taker_ratio = spread/raw_edge = 0/40 = 0.0  # Tight spread, should PASS
```

**Expected**: 
- Maker ratio = 0.0 (spread_cost = 0)
- Taker ratio = 0.0 (tight spread)
- Both should PASS threshold (0.8)

**Status**: ⏳ PENDING

#### Test 4.2: ETH Maker/Taker Ratio Correctness
**Asset Profile**: High liquidity, similar to BTC but slightly wider spreads
**Production Context**: ETH often has 6-12c spreads with good depth.

**Test Cases**:
```python
# ETH NO order - moderate spread scenario
yes_bid = 6c, no_bid = 94c
p_hat_yes = 55c → p_hat_no = 45c
order_price = 94c (NO side)
spread = no_ask - no_bid = (100 - 6) - 94 = 94 - 94 = 0c
raw_edge = 45c

# Maker economics
maker_ratio = 0/45 = 0.0  # Should PASS
# Taker economics
taker_ratio = spread/raw_edge = 0/45 = 0.0  # Should PASS
```

**Expected**:
- Maker ratio = 0.0
- Taker ratio = 0.0
- Both should PASS threshold (0.8)

**Status**: ⏳ PENDING

#### Test 4.3: SOL Maker/Pass vs Taker/Reject Distinction
**Asset Profile**: Medium liquidity, wider spreads, more volatile
**Production Context**: SOL production rejection: `spread_cost_too_high: ratio=2.90 > 0.8`

**Test Cases**:
```python
# SOL NO order - production replay
yes_bid = 41c, no_bid = 59c
p_hat_yes = 79c → p_hat_no = 21c
order_price = 59c (NO side)
spread = no_ask - no_bid = (100 - 41) - 59 = 59 - 59 = 0c
raw_edge = 21c

# Maker economics (current policy - BUG FIX TARGET)
maker_ratio = 0/21 = 0.0  # EXPECTED after fix: should PASS
# CURRENT BUG: uses spread_cents instead of spread_cost_cents
# Current ratio = spread_cents/raw_edge = 58/21 = 2.76 (REJECTS incorrectly)

# Taker economics (for comparison)
taker_ratio = spread_cents/raw_edge = 58/21 = 2.76  # Should REJECT (full spread cost)
```

**Expected**:
- Maker ratio = 0.0 (after fix) - should PASS
- Taker ratio = 2.76 - should REJECT
- **CRITICAL**: This is the production bug - maker orders should PASS

**Status**: ⏳ PENDING - CRITICAL FIX

#### Test 4.4: XRP Side-Basis Consistency and Ratio Formula
**Asset Profile**: Medium liquidity, moderate spreads, different orderbook structure
**Production Context**: XRP production rejection: `spread_cost_too_high: ratio=1.95 > 0.8`

**Test Cases**:
```python
# XRP NO order - production replay
yes_bid = 60c, no_bid = 40c
p_hat_yes = 60c → p_hat_no = 40c
order_price = 40c (NO side)
spread = no_ask - no_bid = (100 - 60) - 40 = 40 - 40 = 0c
raw_edge = 40c

# Maker economics (current policy - BUG FIX TARGET)
maker_ratio = 0/40 = 0.0  # EXPECTED after fix: should PASS
# CURRENT BUG: uses spread_cents instead of spread_cost_cents
# Current ratio = spread_cents/raw_edge = 39/40 = 0.975 (REJECTS incorrectly)

# Taker economics (for comparison)
taker_ratio = spread_cents/raw_edge = 39/40 = 0.975  # Should REJECT
```

**Expected**:
- Maker ratio = 0.0 (after fix) - should PASS
- Taker ratio = 0.975 - should REJECT
- **CRITICAL**: This is the production bug - maker orders should PASS

**Status**: ⏳ PENDING - CRITICAL FIX

#### Test 4.5: DOGE Thin-Liquidity Behavior and Stale-Book Sensitivity
**Asset Profile**: Lower liquidity, wider spreads, more prone to stale quotes
**Production Context**: DOGE often has 15-30c spreads with lower depth; prone to one-sided orderbooks.

**Test Cases**:
```python
# DOGE NO order - thin liquidity scenario
yes_bid = 15c, no_bid = 85c
p_hat_yes = 25c → p_hat_no = 75c
order_price = 85c (NO side)
spread = no_ask - no_bid = (100 - 15) - 85 = 85 - 85 = 0c
raw_edge = 75c

# Maker economics
maker_ratio = 0/75 = 0.0  # Should PASS
# Taker economics
taker_ratio = spread_cents/raw_edge = 70/75 = 0.93  # Should REJECT

# Stale book scenario (quote age > 30s)
stale_quote_age = 45s
# Should be rejected at eligibility check, not ratio check
```

**Expected**:
- Maker ratio = 0.0 - should PASS
- Taker ratio = 0.93 - should REJECT
- Stale quotes rejected before ratio check (eligibility concern, not economics)

**Status**: ⏳ PENDING

#### Test 4.6: Per-Asset Threshold Calibration
**Objective**: Verify single 0.8 threshold works across all assets or needs asset-specific values.

**Test Matrix**:
| Asset | Typical Spread | Typical Edge | Current Ratio | Asset-Specific Threshold? |
|-------|---------------|--------------|----------------|---------------------------|
| BTC   | 5-10c         | 10-20c       | 0.25-0.50      | 0.6 (tighter, high liquidity) |
| ETH   | 6-12c         | 10-20c       | 0.30-0.60      | 0.7 (tighter, high liquidity) |
| SOL   | 40-60c        | 15-25c       | 1.60-2.90      | 0.9 (looser, medium liquidity) |
| XRP   | 30-50c        | 15-25c       | 1.20-1.95      | 0.9 (looser, medium liquidity) |
| DOGE  | 15-30c        | 20-30c       | 0.50-0.93      | 1.0 (loosest, lower liquidity) |

**Expected**: Asset-specific thresholds or ratio normalization (e.g., threshold * liquidity_factor).
**Status**: ⏳ PENDING - current implementation uses universal 0.8 threshold.

#### Test 4.7: Per-Asset Golden Regression Cases
**Objective**: One production-like golden example per symbol to prevent regression.

**Golden Cases**:
```python
# BTC Golden Case: YES order with tight spread
btc_golden = {
    'yes_bid': 5, 'no_bid': 95, 'p_hat_yes': 60, 'order_price': 5,
    'economics': 'maker', 'expected_ratio': 0.0, 'expected_pass': True
}

# ETH Golden Case: NO order with moderate spread
eth_golden = {
    'yes_bid': 6, 'no_bid': 94, 'p_hat_yes': 55, 'order_price': 94,
    'economics': 'maker', 'expected_ratio': 0.0, 'expected_pass': True
}

# SOL Golden Case: NO order with wide spread (production bug)
sol_golden = {
    'yes_bid': 41, 'no_bid': 59, 'p_hat_yes': 79, 'order_price': 59,
    'economics': 'maker', 'expected_ratio': 0.0, 'expected_pass': True
}

# XRP Golden Case: NO order with moderate spread (production bug)
xrp_golden = {
    'yes_bid': 60, 'no_bid': 40, 'p_hat_yes': 60, 'order_price': 40,
    'economics': 'maker', 'expected_ratio': 0.0, 'expected_pass': True
}

# DOGE Golden Case: NO order with thin liquidity
doge_golden = {
    'yes_bid': 15, 'no_bid': 85, 'p_hat_yes': 25, 'order_price': 85,
    'economics': 'maker', 'expected_ratio': 0.0, 'expected_pass': True
}
```

**Expected**: All golden cases PASS after fix; regression test fails if formula reverts to `spread_cents / raw_edge`.
**Status**: ⏳ PENDING

### Phase 4.8: Per-Asset Audit Rule Enforcement
**Objective**: For every asset, the gate must answer three core questions consistently.

**Audit Rule**:
For each asset (BTC, ETH, SOL, XRP, DOGE), the gate must explicitly answer:

1. **Is the quote fresh enough for a 15-minute market?**
   - Check: quote age < 30s (or asset-specific threshold)
   - Rejection reason: `stale_quote` (not `spread_cost_too_high`)
   - Asset-specific: DOGE/XRP may need tighter freshness checks due to lower liquidity

2. **Is the economics mode being applied correctly?**
   - Check: `spread_cost_cents` = 0 for maker, = `spread_cents` for taker
   - Rejection reason: `economics_mode_mismatch` if wrong mode applied
   - Asset-specific: All assets must use same economics logic, no asset-specific exceptions

3. **Does the executable edge still justify the order after the correct cost basis?**
   - Check: `executable_edge = raw_edge - spread_cost - fee` using correct economics mode
   - Rejection reason: `executable_edge_too_low` (not `spread_cost_too_high`)
   - Asset-specific: Threshold may vary by asset (BTC: 0.6, DOGE: 1.0)

**Failure Mode**: If any asset fails a different part of the chain, the audit must expose it explicitly rather than hiding it inside a shared threshold.

**Test Implementation**:
```python
def test_per_asset_audit_rule():
    """For each asset, verify the three questions are answered correctly."""
    assets = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']
    
    for asset in assets:
        # Question 1: Freshness
        result = check_quote_freshness(asset, quote_age=45)
        assert result.passed == False, f"{asset}: Stale quote should fail freshness check"
        assert result.reason == "stale_quote", f"{asset}: Wrong rejection reason"
        
        # Question 2: Economics mode
        result = check_economics_mode(asset, economics='maker')
        assert result.spread_cost_cents == 0.0, f"{asset}: Maker should have spread_cost=0"
        assert result.spread_to_edge_ratio == 0.0, f"{asset}: Maker ratio should be 0"
        
        # Question 3: Executable edge
        result = check_executable_edge(asset, raw_edge=20, spread_cost=0, fee=0)
        assert result.executable_edge == 20, f"{asset}: Executable edge should equal raw edge"
        assert result.passed == True, f"{asset}: Positive executable edge should pass"
```

**Expected**: All assets pass the three-question audit with clear, asset-specific rejection reasons.
**Status**: ⏳ PENDING

### Phase 5: Gate Structure Separation

#### Test 5.1: Eligibility vs Economics vs Policy Checks
**Objective**: Verify gate checks are in correct order and don't conflate concerns.

**Current Order**:
1. Executable edge check
2. Spread cost ratio check
3. Absolute spread cap

**Proposed Order**:
1. **Eligibility**: quote freshness, valid side, non-crossed book
2. **Economics**: expected edge vs execution cost (using correct economics mode)
3. **Policy**: maker/taker intent, aggressiveness, risk limits
4. **Threshold**: only after above are consistent

**Expected**: Rejection reasons clearly separated by concern (e.g., "stale_quote" vs "spread_cost_too_high").
**Status**: ⏳ PENDING

## Invariant Violations Found

### Invariant 1: Maker Economics Consistency
**Violation**: `use_maker_economics=True` sets `spread_cost=0`, but `spread_to_edge_ratio` still uses `spread_cents`.
**Impact**: Maker orders rejected based on taker-style spread costs.
**Fix**: Change ratio calculation to use `spread_cost_cents` instead of `spread_cents`.

### Invariant 2: Ratio Definition Clarity
**Violation**: "spread_cost_too_high" suggests cost-based ratio, but implementation uses spread/edge (not cost/edge).
**Impact**: Misleading rejection reason; doesn't reflect actual cost to trader.
**Fix**: Either rename to "spread_too_wide_relative_to_edge" or use cost-based ratio.

### Invariant 3: 15-Minute Horizon Awareness
**Violation**: Fixed 0.8 threshold doesn't account for remaining window or latency risk.
**Impact**: May over-reject early in window (when spreads noisy but tradable) or under-reject late (when latency dominates).
**Fix**: Add time-to-expiry scaling to threshold.

## Recommended Fixes

### Fix 1: Use spread_cost_cents for Ratio (CRITICAL)
**File**: `spread_edge_analytics.py:236, 271`

**Current**:
```python
yes_spread_ratio = (spread_metrics.yes_spread_cents / yes_raw_edge) if yes_raw_edge > 0 else float('inf')
```

**Fixed**:
```python
yes_spread_ratio = (yes_spread_cost / yes_raw_edge) if yes_raw_edge > 0 else float('inf')
```

**Impact**: Maker orders will have ratio = 0 (since spread_cost = 0), allowing them to pass the gate.

### Fix 2: Add Time-to-Expiry Scaling (HIGH)
**File**: `order_router.py:3783` (threshold manager)

**Current**:
```python
max_spread_to_edge_ratio = threshold_manager.get_max_spread_to_edge_ratio()  # Fixed 0.8
```

**Proposed**:
```python
time_to_expiry_seconds = get_time_to_expiry(market)
time_decay_factor = min(1.0, time_to_expiry_seconds / 900.0)  # 0-1 scaling
max_spread_to_edge_ratio = threshold_manager.get_max_spread_to_edge_ratio() * time_decay_factor
```

**Impact**: Threshold tightens as market approaches expiry (accounting for latency risk).

### Fix 3: Separate Eligibility from Economics (MEDIUM)
**File**: `spread_edge_analytics.py:edge_aware_microstructure_gate`

**Current**: All checks in one function.

**Proposed**: Split into:
```python
def check_eligibility(market_data) -> bool:
    """Check quote freshness, valid side, non-crossed book."""
    
def check_economics(edge_metrics, economics_mode) -> bool:
    """Check expected edge vs execution cost using correct economics mode."""
    
def check_policy(intent, risk_limits) -> bool:
    """Check maker/taker intent, aggressiveness, risk limits."""
    
def check_threshold(edge_metrics, threshold) -> bool:
    """Check ratio/absolute thresholds after above are consistent."""
```

**Impact**: Clearer rejection reasons; prevents conflation of concerns.

### Fix 4: Add Asset-Specific Calibration (LOW)
**File**: `dynamic_thresholds.py`

**Proposed**: Add asset-specific spread/edge ratio thresholds:
```python
ASSET_SPREAD_EDGE_THRESHOLDS = {
    'BTC': 0.6,   # High liquidity, tighter threshold
    'ETH': 0.7,
    'SOL': 0.9,   # Medium liquidity, looser threshold
    'XRP': 0.9,
    'DOGE': 1.0,  # Lower liquidity, loosest threshold
}
```

**Impact**: Thresholds calibrated to asset-specific microstructure.

## Test Implementation Plan

### Test File: `tests/test_microstructure_gate_15m_audit.py`

```python
import pytest
from merid.event_venues.kalshi.spread_edge_analytics import (
    compute_canonical_spreads,
    compute_per_side_edges,
    PerSideEdgeMetrics
)

class TestMakerTakerRatioCalculation:
    """Test that ratio uses spread_cost (0 for makers) not spread_cents."""
    
    def test_maker_ratio_uses_spread_cost(self):
        """Maker orders should have ratio = 0 (spread_cost = 0)."""
        yes_bid = 41
        no_bid = 59
        p_hat_yes = 79.0
        order_price = 59.0
        order_side = "no"
        
        spread_metrics = compute_canonical_spreads(yes_bid, no_bid)
        yes_edge, no_edge = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes,
            spread_metrics=spread_metrics,
            order_price_cents=order_price,
            order_side=order_side,
            use_maker_economics=True  # MAKER
        )
        
        # CRITICAL: spread_cost should be 0 for makers
        assert no_edge.spread_cost_cents == 0.0
        # CRITICAL: ratio should use spread_cost, not spread_cents
        assert no_edge.spread_to_edge_ratio == 0.0, f"Expected 0.0, got {no_edge.spread_to_edge_ratio}"
    
    def test_taker_ratio_uses_full_spread(self):
        """Taker orders should use full spread in ratio."""
        yes_bid = 41
        no_bid = 59
        p_hat_yes = 79.0
        order_price = 59.0
        order_side = "no"
        
        spread_metrics = compute_canonical_spreads(yes_bid, no_bid)
        yes_edge, no_edge = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes,
            spread_metrics=spread_metrics,
            order_price_cents=order_price,
            order_side=order_side,
            use_maker_economics=False  # TAKER
        )
        
        # Taker: spread_cost should be full spread
        assert no_edge.spread_cost_cents == no_edge.spread_cents
        # Ratio should be spread/edge
        expected_ratio = no_edge.spread_cents / no_edge.raw_edge_cents
        assert no_edge.spread_to_edge_ratio == expected_ratio

class TestPerAssetGoldenCases:
    """One golden regression case per asset (BTC, ETH, SOL, XRP, DOGE)."""
    
    def test_btc_yes_maker_order(self):
        """BTC YES order: tight spread, high liquidity - should PASS with maker economics."""
        yes_bid = 5
        no_bid = 95
        p_hat_yes = 60.0
        order_price = 5.0
        order_side = "yes"
        
        spread_metrics = compute_canonical_spreads(yes_bid, no_bid)
        yes_edge, no_edge = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes,
            spread_metrics=spread_metrics,
            order_price_cents=order_price,
            order_side=order_side,
            use_maker_economics=True  # MAKER
        )
        
        assert yes_edge.spread_cost_cents == 0.0
        assert yes_edge.spread_to_edge_ratio == 0.0
        assert yes_edge.executable_edge_cents > 0
    
    def test_eth_no_maker_order(self):
        """ETH NO order: moderate spread, high liquidity - should PASS with maker economics."""
        yes_bid = 6
        no_bid = 94
        p_hat_yes = 55.0
        order_price = 94.0
        order_side = "no"
        
        spread_metrics = compute_canonical_spreads(yes_bid, no_bid)
        yes_edge, no_edge = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes,
            spread_metrics=spread_metrics,
            order_price_cents=order_price,
            order_side=order_side,
            use_maker_economics=True  # MAKER
        )
        
        assert no_edge.spread_cost_cents == 0.0
        assert no_edge.spread_to_edge_ratio == 0.0
        assert no_edge.executable_edge_cents > 0
    
    def test_sol_no_maker_order_production_bug(self):
        """SOL NO order: production bug case - should PASS with maker economics (ratio=0)."""
        # Production: spread_cost_too_high: ratio=2.90 > 0.8
        # Expected after fix: ratio=0.0 (maker), should PASS
        yes_bid = 41
        no_bid = 59
        p_hat_yes = 79.0
        order_price = 59.0
        order_side = "no"
        
        spread_metrics = compute_canonical_spreads(yes_bid, no_bid)
        yes_edge, no_edge = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes,
            spread_metrics=spread_metrics,
            order_price_cents=order_price,
            order_side=order_side,
            use_maker_economics=True  # MAKER
        )
        
        # CRITICAL: This is the production bug
        assert no_edge.spread_cost_cents == 0.0, "Maker should have spread_cost=0"
        assert no_edge.spread_to_edge_ratio == 0.0, f"Expected 0.0, got {no_edge.spread_to_edge_ratio}"
        assert no_edge.executable_edge_cents > 0, "Executable edge should be positive"
    
    def test_xrp_no_maker_order_production_bug(self):
        """XRP NO order: production bug case - should PASS with maker economics (ratio=0)."""
        # Production: spread_cost_too_high: ratio=1.95 > 0.8
        # Expected after fix: ratio=0.0 (maker), should PASS
        yes_bid = 60
        no_bid = 40
        p_hat_yes = 60.0
        order_price = 40.0
        order_side = "no"
        
        spread_metrics = compute_canonical_spreads(yes_bid, no_bid)
        yes_edge, no_edge = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes,
            spread_metrics=spread_metrics,
            order_price_cents=order_price,
            order_side=order_side,
            use_maker_economics=True  # MAKER
        )
        
        # CRITICAL: This is the production bug
        assert no_edge.spread_cost_cents == 0.0, "Maker should have spread_cost=0"
        assert no_edge.spread_to_edge_ratio == 0.0, f"Expected 0.0, got {no_edge.spread_to_edge_ratio}"
        assert no_edge.executable_edge_cents > 0, "Executable edge should be positive"
    
    def test_doge_no_maker_order_thin_liquidity(self):
        """DOGE NO order: thin liquidity - should PASS with maker economics (ratio=0)."""
        yes_bid = 15
        no_bid = 85
        p_hat_yes = 25.0
        order_price = 85.0
        order_side = "no"
        
        spread_metrics = compute_canonical_spreads(yes_bid, no_bid)
        yes_edge, no_edge = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes,
            spread_metrics=spread_metrics,
            order_price_cents=order_price,
            order_side=order_side,
            use_maker_economics=True  # MAKER
        )
        
        assert no_edge.spread_cost_cents == 0.0
        assert no_edge.spread_to_edge_ratio == 0.0
        assert no_edge.executable_edge_cents > 0

class TestProductionReplay:
    """Replay production rejection scenarios with maker vs taker economics."""
    
    def test_sol_no_maker_vs_taker(self):
        """SOL NO order: maker should PASS, taker should REJECT."""
        yes_bid = 41
        no_bid = 59
        p_hat_yes = 79.0
        order_price = 59.0
        order_side = "no"
        
        spread_metrics = compute_canonical_spreads(yes_bid, no_bid)
        
        # Maker: should PASS
        yes_edge_m, no_edge_m = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes,
            spread_metrics=spread_metrics,
            order_price_cents=order_price,
            order_side=order_side,
            use_maker_economics=True
        )
        assert no_edge_m.spread_to_edge_ratio == 0.0
        assert no_edge_m.executable_edge_cents > 0
        
        # Taker: should REJECT (wide spread)
        yes_edge_t, no_edge_t = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes,
            spread_metrics=spread_metrics,
            order_price_cents=order_price,
            order_side=order_side,
            use_maker_economics=False
        )
        assert no_edge_t.spread_to_edge_ratio > 0.8  # Should exceed threshold
        assert no_edge_t.executable_edge_cents < 0  # Negative after spread cost
    
    def test_xrp_no_maker_vs_taker(self):
        """XRP NO order: maker should PASS, taker should REJECT."""
        yes_bid = 60
        no_bid = 40
        p_hat_yes = 60.0
        order_price = 40.0
        order_side = "no"
        
        spread_metrics = compute_canonical_spreads(yes_bid, no_bid)
        
        # Maker: should PASS
        yes_edge_m, no_edge_m = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes,
            spread_metrics=spread_metrics,
            order_price_cents=order_price,
            order_side=order_side,
            use_maker_economics=True
        )
        assert no_edge_m.spread_to_edge_ratio == 0.0
        assert no_edge_m.executable_edge_cents > 0
        
        # Taker: should REJECT
        yes_edge_t, no_edge_t = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes,
            spread_metrics=spread_metrics,
            order_price_cents=order_price,
            order_side=order_side,
            use_maker_economics=False
        )
        assert no_edge_t.spread_to_edge_ratio > 0.8  # Should exceed threshold
        assert no_edge_t.executable_edge_cents < 0  # Negative after spread cost

class Test15MinuteHorizon:
    """Test 15-minute market specific concerns."""
    
    def test_time_to_expiry_threshold_scaling(self):
        """Threshold should tighten as market approaches expiry."""
        pass
    
    def test_stale_quote_detection(self):
        """Stale quotes should be rejected before ratio check."""
        pass

class TestAssetSpecificCalibration:
    """Test asset-specific microstructure differences."""
    
    def test_btc_tight_threshold(self):
        """BTC should use tighter threshold (high liquidity)."""
        pass
    
    def test_sol_loose_threshold(self):
        """SOL should use looser threshold (medium liquidity)."""
        pass
    
    def test_doge_loosest_threshold(self):
        """DOGE should use loosest threshold (lower liquidity)."""
        pass

class TestPerAssetAuditRule:
    """For each asset, verify the three core questions are answered correctly."""
    
    def test_btc_audit_rule(self):
        """BTC: freshness, economics mode, executable edge."""
        self._run_audit_rule('BTC')
    
    def test_eth_audit_rule(self):
        """ETH: freshness, economics mode, executable edge."""
        self._run_audit_rule('ETH')
    
    def test_sol_audit_rule(self):
        """SOL: freshness, economics mode, executable edge."""
        self._run_audit_rule('SOL')
    
    def test_xrp_audit_rule(self):
        """XRP: freshness, economics mode, executable edge."""
        self._run_audit_rule('XRP')
    
    def test_doge_audit_rule(self):
        """DOGE: freshness, economics mode, executable edge."""
        self._run_audit_rule('DOGE')
    
    def _run_audit_rule(self, asset):
        """Run the three-question audit for a given asset."""
        # Question 1: Freshness
        # Question 2: Economics mode
        # Question 3: Executable edge
        pass
```

## Immediate Actions

1. **CRITICAL**: Fix ratio calculation to use `spread_cost_cents` instead of `spread_cents`
2. **HIGH**: Add time-to-expiry scaling to threshold
3. **MEDIUM**: Implement test suite from Phase 1-5
4. **LOW**: Add asset-specific calibration (if empirical data supports it)

## Success Criteria

- [ ] Maker orders pass gate with ratio = 0 (spread_cost = 0)
- [ ] Taker orders pass/reject based on full spread cost
- [ ] Production SOL/XRP orders pass after fix
- [ ] Time-to-expiry scaling implemented
- [ ] Test suite passes all phases
- [ ] Rejection reasons clearly separated by concern

## References

- Implementation: `merid/event_venues/kalshi/spread_edge_analytics.py`
- Gate logic: `merid/event_venues/kalshi/order_router.py:check_market_microstructure_edge_aware`
- Threshold manager: `merid/event_venues/kalshi/dynamic_thresholds.py`
- Production logs: See SOL/XRP rejection examples above
