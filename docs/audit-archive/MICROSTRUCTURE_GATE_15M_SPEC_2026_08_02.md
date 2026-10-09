# 15-Minute Market Microstructure Gate Specification
**Date**: 2026-08-02  
**Version**: v1.0  
**Scope**: BTC, ETH, SOL, XRP, DOGE 15-minute Kalshi markets  
**Status**: Ready for Implementation

## Executive Summary

This specification defines a comprehensive microstructure gate for 15-minute prediction markets with layered guardrails to prevent false rejections while protecting against stale quotes, wide spreads, and thin liquidity. The gate uses asset-specific calibration with time-to-expiry scaling to balance opportunity preservation with risk management.

## Design Principles

1. **Fail Fast**: Reject structural invalidities (crossed books) before expensive economics calculations
2. **Asset-Specific Calibration**: Different thresholds for BTC/ETH (tight) vs SOL/XRP/DOGE (loose)
3. **Time-to-Expiry Awareness**: Thresholds tighten as market approaches expiry using sigmoid decay
4. **Layered Guardrails**: Multiple independent checks to catch different failure modes
5. **Maker Economics**: Maker orders (limit orders) have spread_cost=0, ratio=0, should pass unless other guardrails trigger

## Asset-Specific Calibration Tables

### Ratio Thresholds (Spread-to-Edge Ratio)

| Asset | Max Threshold | Min Threshold | Rationale |
|-------|---------------|---------------|-----------|
| BTC   | 0.6           | 0.3           | High liquidity, tightest spreads, most disciplined |
| ETH   | 0.7           | 0.4           | High liquidity, slightly wider spreads than BTC |
| SOL   | 0.9           | 0.5           | Medium liquidity, more volatile microstructure |
| XRP   | 0.9           | 0.5           | Medium liquidity, similar to SOL |
| DOGE  | 1.0           | 0.6           | Lower liquidity, thin-liquidity behavior, loosest |

**Note**: These are v1 calibration values to be validated against replayed rejection/acceptance behavior.

### Absolute Spread Caps (cents)

| Asset | Base Cap | Time-Scaled Range | Rationale |
|-------|----------|-------------------|-----------|
| BTC   | 10c      | 8c - 10c          | Tightest spreads in production (5-10c typical) |
| ETH   | 12c      | 10c - 12c         | Slightly wider than BTC (6-12c typical) |
| SOL   | 20c      | 16c - 20c         | Medium liquidity, more volatile |
| XRP   | 20c      | 16c - 20c         | Similar to SOL, medium liquidity |
| DOGE  | 30c      | 24c - 30c         | Lowest liquidity, thin-liquidity behavior |

**Time Scaling**: Linear decay from 100% at 15min to 80% at 0min.

### Minimum Depth Thresholds (contracts at best bid/ask)

| Asset | Min Depth | Rationale |
|-------|----------|-----------|
| BTC   | 50       | High liquidity, should have deep orderbook |
| ETH   | 40       | High liquidity, slightly less than BTC |
| SOL   | 25       | Medium liquidity, allow thinner books |
| XRP   | 25       | Similar to SOL, medium liquidity |
| DOGE  | 15       | Lowest liquidity, most permissive |

**Note**: These are v1 heuristics to be validated against live 15-minute data.

## Gate Check Order

The gate applies checks in this order (from fastest to most expensive):

1. **Crossed-book check** - Structural invalidity
2. **Freshness check** - Data quality
3. **Economics ratio check** - Primary value gate
4. **Absolute spread cap** - Secondary guardrail
5. **Minimum depth check** - Liquidity sanity check

## Check Specifications

### Check 1: Crossed-Book Detection

**Purpose**: Detect structural invalidities in orderbook data.

**Logic**:
```python
def check_crossed_book(market_data) -> bool:
    """
    Reject if orderbook is crossed or inverted.
    
    Crossed book conditions:
    - yes_bid > yes_ask (YES side inverted)
    - no_bid > no_ask (NO side inverted)
    
    Returns True if book is valid (not crossed), False if crossed.
    """
    if market_data.yes_bid > market_data.yes_ask:
        return False
    if market_data.no_bid > market_data.no_ask:
        return False
    return True
```

**Rejection Reason**: `"crossed_book"`

**Priority**: Highest - structural invalidity should fail immediately.

### Check 2: Quote Freshness

**Purpose**: Detect stale or outdated market data.

**Logic**:
```python
def check_quote_freshness(market_data, max_age_seconds: int = 30) -> bool:
    """
    Reject if quote is older than max_age_seconds.
    
    Args:
        market_data: Market data with timestamp
        max_age_seconds: Maximum allowed quote age (default 30s)
    
    Returns True if quote is fresh, False if stale.
    """
    quote_age = current_time() - market_data.timestamp
    return quote_age <= max_age_seconds
```

**Rejection Reason**: `"stale_quote"`

**Priority**: High - data quality gate before economics.

### Check 3: Economics Ratio Check (Primary Gate)

**Purpose**: Primary value check using spread-to-edge ratio with time-to-expiry scaling.

**Logic**:
```python
def check_economics_ratio(
    edge_metrics: PerSideEdgeMetrics,
    asset_ticker: str,
    time_to_expiry_seconds: float
) -> bool:
    """
    Reject if spread-to-edge ratio exceeds time-scaled threshold.
    
    Uses sigmoid decay for smooth threshold adjustment:
    - Early in window: threshold near max
    - Middle window: gradual tightening
    - Final minutes: faster tightening toward min
    
    Args:
        edge_metrics: Edge metrics with spread_to_edge_ratio
        asset_ticker: Asset ticker for threshold lookup
        time_to_expiry_seconds: Remaining time in seconds (0-900)
    
    Returns True if ratio passes, False if exceeds threshold.
    """
    threshold = get_time_scaled_threshold(asset_ticker, time_to_expiry_seconds)
    return edge_metrics.spread_to_edge_ratio <= threshold
```

**Sigmoid Function**:
```python
def get_time_scaled_threshold(asset_ticker: str, time_to_expiry_seconds: float) -> float:
    """
    Apply sigmoid decay to threshold based on time-to-expiry.
    
    Args:
        asset_ticker: Asset ticker for threshold lookup
        time_to_expiry_seconds: Remaining time in seconds (0-900 for 15-min markets)
    
    Returns:
        Adjusted threshold based on sigmoid decay
    """
    max_threshold = ASSET_RATIO_THRESHOLDS[asset_ticker]['max']
    min_threshold = ASSET_RATIO_THRESHOLDS[asset_ticker]['min']
    
    # Normalize time to 0-1 range (0 = expiry, 1 = full window)
    normalized_time = time_to_expiry_seconds / 900.0
    
    # Sigmoid function centered at 50% of window with steepness parameter
    # Steepness = 8 gives smooth transition with tightening in final minutes
    sigmoid = 1 / (1 + math.exp(-8 * (normalized_time - 0.5)))
    
    # Scale sigmoid to threshold range
    threshold = min_threshold + (max_threshold - min_threshold) * sigmoid
    
    return threshold
```

**Rejection Reason**: `"spread_cost_too_high"`

**Priority**: Primary - main economics gate.

**Critical Note**: For maker orders, `spread_to_edge_ratio = 0` (since `spread_cost = 0`), so this check should always pass unless the ratio calculation bug reverts.

### Check 4: Absolute Spread Cap (Secondary Guardrail)

**Purpose**: Catch obviously bad books that might pass ratio check.

**Logic**:
```python
def check_absolute_spread_cap(
    edge_metrics: PerSideEdgeMetrics,
    asset_ticker: str,
    time_to_expiry_seconds: float
) -> bool:
    """
    Reject if spread exceeds time-scaled absolute cap.
    
    Uses linear decay (simpler than ratio sigmoid):
    - Early in window: full cap
    - Near expiry: 80% of cap (modest tightening)
    
    Args:
        edge_metrics: Edge metrics with spread_cents
        asset_ticker: Asset ticker for cap lookup
        time_to_expiry_seconds: Remaining time in seconds (0-900)
    
    Returns True if spread within cap, False if exceeds cap.
    """
    spread_cap = get_time_scaled_spread_cap(asset_ticker, time_to_expiry_seconds)
    return edge_metrics.spread_cents <= spread_cap
```

**Linear Decay Function**:
```python
def get_time_scaled_spread_cap(asset_ticker: str, time_to_expiry_seconds: float) -> int:
    """
    Apply simpler time scaling to spread cap (linear decay, not sigmoid).
    
    Early in window: full cap
    Near expiry: 80% of cap (modest tightening)
    
    Args:
        asset_ticker: Asset ticker for cap lookup
        time_to_expiry_seconds: Remaining time in seconds (0-900)
    
    Returns:
        Time-scaled spread cap in cents
    """
    base_cap = ASSET_SPREAD_CAPS[asset_ticker]
    
    # Linear decay: 100% at 15min, 80% at 0min
    decay_factor = 0.8 + 0.2 * (time_to_expiry_seconds / 900.0)
    
    return int(base_cap * decay_factor)
```

**Rejection Reason**: `"spread_too_wide"`

**Priority**: Secondary - guardrail after primary economics check.

### Check 5: Minimum Depth Check (Liquidity Guardrail)

**Purpose**: Ensure orderbook has sufficient liquidity at the execution side's best level.

**Critical Refinement**: Depth is checked on the **execution side only**, not the minimum of both sides. This prevents rejecting valid maker opportunities because the opposite side is thin.

**Logic**:
```python
def check_minimum_depth(
    market_data,
    asset_ticker: str,
    execution_side: str  # "yes" or "no"
) -> bool:
    """
    Reject if orderbook depth at execution side's best bid is below threshold.
    
    CRITICAL: Depth is checked on the execution side only, not min(yes, no).
    This prevents rejecting valid maker opportunities due to thin opposite side.
    
    Args:
        market_data: Market data with depth information
        asset_ticker: Asset ticker for depth threshold lookup
        execution_side: The side being executed ("yes" or "no")
    
    Returns True if depth sufficient, False if insufficient.
    """
    min_depth = ASSET_DEPTH_THRESHOLDS[asset_ticker]
    
    # Check depth on execution side only
    if execution_side == "yes":
        depth_at_best = market_data.yes_bid_depth
    elif execution_side == "no":
        depth_at_best = market_data.no_bid_depth
    else:
        # Fallback to conservative min if side unknown
        depth_at_best = min(market_data.yes_bid_depth, market_data.no_bid_depth)
    
    return depth_at_best >= min_depth
```

**Rejection Reason**: `"insufficient_depth"`

**Priority**: Final - liquidity sanity check after all other checks pass.

## Consolidated Gate Function

```python
def edge_aware_microstructure_gate_15m(
    market_data: MarketData,
    edge_metrics: PerSideEdgeMetrics,
    time_to_expiry_seconds: float,
    asset_ticker: str,
    execution_side: str,  # "yes" or "no"
    use_maker_economics: bool = True
) -> GateDecision:
    """
    Comprehensive gate for 15-minute markets with layered checks.
    
    Check Order (from fastest to most expensive):
    1. Crossed-book check - structural invalidity
    2. Freshness check - data quality
    3. Economics ratio check - primary value gate (side-aware by execution mode)
    4. Absolute spread cap - secondary guardrail
    5. Minimum depth check - liquidity sanity check (execution side only)
    
    CRITICAL: Ratio check is side-aware by execution mode:
    - Maker orders: ratio = 0 (spread_cost = 0)
    - Taker orders: ratio = full spread / raw_edge
    
    CRITICAL: Depth check is on execution side only, not min(yes, no).
    This prevents rejecting valid maker opportunities due to thin opposite side.
    
    Args:
        market_data: Market data with orderbook and timestamp
        edge_metrics: Edge metrics from spread_edge_analytics
        time_to_expiry_seconds: Remaining time in seconds (0-900)
        asset_ticker: Asset ticker for calibration lookup
        execution_side: The side being executed ("yes" or "no")
        use_maker_economics: If True, use maker economics (ratio=0). If False, use taker economics.
    
    Returns:
        GateDecision with accept/reject status and reason
    """
    
    # 1. Crossed-book check (structural invalidity)
    if not check_crossed_book(market_data):
        return GateDecision.REJECT("crossed_book")
    
    # 2. Freshness check (data quality)
    if not check_quote_freshness(market_data):
        return GateDecision.REJECT("stale_quote")
    
    # 3. Economics ratio check (primary gate, side-aware by execution mode)
    if not check_economics_ratio(edge_metrics, asset_ticker, time_to_expiry_seconds):
        return GateDecision.REJECT("spread_cost_too_high")
    
    # 4. Absolute spread cap (secondary guardrail)
    if not check_absolute_spread_cap(edge_metrics, asset_ticker, time_to_expiry_seconds):
        return GateDecision.REJECT("spread_too_wide")
    
    # 5. Minimum depth check (liquidity guardrail, execution side only)
    if not check_minimum_depth(market_data, asset_ticker, execution_side):
        return GateDecision.REJECT("insufficient_depth")
    
    return GateDecision.ACCEPT()
```

## Calibration Tables (Implementation Reference)

```python
ASSET_RATIO_THRESHOLDS = {
    'BTC': {'max': 0.6, 'min': 0.3},
    'ETH': {'max': 0.7, 'min': 0.4},
    'SOL': {'max': 0.9, 'min': 0.5},
    'XRP': {'max': 0.9, 'min': 0.5},
    'DOGE': {'max': 1.0, 'min': 0.6},
}

ASSET_SPREAD_CAPS = {
    'BTC': 10,
    'ETH': 12,
    'SOL': 20,
    'XRP': 20,
    'DOGE': 30,
}

ASSET_DEPTH_THRESHOLDS = {
    'BTC': 50,
    'ETH': 40,
    'SOL': 25,
    'XRP': 25,
    'DOGE': 15,
}
```

## Test Cases

### Time-to-Expiry Scaling Tests

```python
def test_threshold_sigmoid_decay():
    """Test sigmoid decay at four key points."""
    # At 15:00 remaining, threshold should be near max
    threshold_15min = get_time_scaled_threshold('BTC', 900)
    assert threshold_15min == pytest.approx(0.6, abs=0.05)
    
    # Around 10:00 remaining, threshold should have started declining
    threshold_10min = get_time_scaled_threshold('BTC', 600)
    assert 0.4 < threshold_10min < 0.6
    
    # Around 5:00 remaining, threshold should be meaningfully tighter
    threshold_5min = get_time_scaled_threshold('BTC', 300)
    assert 0.3 < threshold_5min < 0.5
    
    # At 0:30 remaining, threshold should be near min
    threshold_30s = get_time_scaled_threshold('BTC', 30)
    assert threshold_30s == pytest.approx(0.3, abs=0.05)
```

### Asset-Specific Threshold Tests

```python
def test_asset_specific_thresholds():
    """Test that each asset has correct max/min thresholds."""
    for asset, expected in ASSET_RATIO_THRESHOLDS.items():
        max_thresh = get_time_scaled_threshold(asset, 900)
        min_thresh = get_time_scaled_threshold(asset, 0)
        assert max_thresh == pytest.approx(expected['max'], abs=0.01)
        assert min_thresh == pytest.approx(expected['min'], abs=0.01)
```

### Maker Order Tests

```python
def test_maker_orders_pass_ratio_check():
    """Maker orders should pass ratio check (ratio=0)."""
    for asset in ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']:
        edge_metrics = create_maker_edge_metrics(asset)
        for time_remaining in [900, 600, 300, 30]:
            assert check_economics_ratio(edge_metrics, asset, time_remaining)
```

### Guardrail Tests

```python
def test_crossed_book_rejection():
    """Crossed books should be rejected immediately before other checks."""
    crossed_book_data = create_crossed_book_data()
    decision = edge_aware_microstructure_gate_15m(
        crossed_book_data, ..., execution_side="yes"
    )
    assert decision.rejected
    assert decision.reason == "crossed_book"

def test_spread_cap_guardrail():
    """Wide spreads should be rejected even if ratio passes."""
    wide_spread_data = create_wide_spread_data()
    decision = edge_aware_microstructure_gate_15m(
        wide_spread_data, ..., execution_side="yes"
    )
    assert decision.rejected
    assert decision.reason == "spread_too_wide"

def test_depth_guardrail():
    """Thin depth on execution side should be rejected even if other checks pass."""
    thin_depth_data = create_thin_depth_data(execution_side="yes")
    decision = edge_aware_microstructure_gate_15m(
        thin_depth_data, ..., execution_side="yes"
    )
    assert decision.rejected
    assert decision.reason == "insufficient_depth"
```

### Side-Specific Depth Tests

```python
def test_side_specific_depth_yes():
    """YES order should check YES-side depth only, not NO-side depth."""
    # YES side has sufficient depth, NO side is thin
    market_data = create_market_data(
        yes_bid_depth=100,  # Sufficient
        no_bid_depth=5      # Thin (should not cause rejection)
    )
    edge_metrics = create_passing_edge_metrics()
    decision = edge_aware_microstructure_gate_15m(
        market_data, edge_metrics, ..., execution_side="yes"
    )
    assert decision.accepted  # Should pass because YES side is deep enough

def test_side_specific_depth_no():
    """NO order should check NO-side depth only, not YES-side depth."""
    # NO side has sufficient depth, YES side is thin
    market_data = create_market_data(
        yes_bid_depth=5,     # Thin (should not cause rejection)
        no_bid_depth=100     # Sufficient
    )
    edge_metrics = create_passing_edge_metrics()
    decision = edge_aware_microstructure_gate_15m(
        market_data, edge_metrics, ..., execution_side="no"
    )
    assert decision.accepted  # Should pass because NO side is deep enough
```

### Maker vs Taker Economics Tests

```python
def test_maker_order_passes_with_thin_opposite_side():
    """Maker order should pass even if opposite side depth is thin."""
    # YES maker order with thin NO side depth
    market_data = create_market_data(
        yes_bid_depth=100,  # Sufficient for YES execution
        no_bid_depth=5      # Thin (should not reject YES maker)
    )
    edge_metrics = create_maker_edge_metrics(asset='BTC')  # ratio=0
    decision = edge_aware_microstructure_gate_15m(
        market_data, edge_metrics, ..., execution_side="yes", use_maker_economics=True
    )
    assert decision.accepted  # Maker should pass despite thin opposite side

def test_taker_order_fails_on_ratio_despite_ample_depth():
    """Taker order should fail on ratio even if depth is ample."""
    market_data = create_market_data(
        yes_bid_depth=1000,  # Ample depth
        no_bid_depth=1000
    )
    edge_metrics = create_taker_edge_metrics_with_high_ratio(asset='SOL')  # ratio > threshold
    decision = edge_aware_microstructure_gate_15m(
        market_data, edge_metrics, ..., execution_side="yes", use_maker_economics=False
    )
    assert decision.rejected
    assert decision.reason == "spread_cost_too_high"  # Ratio should fail despite ample depth
```

### Per-Asset Replay Tests

```python
def test_per_asset_replay_btc():
    """BTC replay test with realistic market data."""
    for scenario in BTC_REPLAY_SCENARIOS:
        decision = edge_aware_microstructure_gate_15m(
            scenario.market_data,
            scenario.edge_metrics,
            scenario.time_to_expiry,
            asset_ticker='BTC',
            execution_side=scenario.side,
            use_maker_economics=scenario.use_maker_economics
        )
        assert decision.accepted == scenario.expected_accept
        if decision.rejected:
            assert decision.reason == scenario.expected_reason

def test_per_asset_replay_eth():
    """ETH replay test with realistic market data."""
    for scenario in ETH_REPLAY_SCENARIOS:
        decision = edge_aware_microstructure_gate_15m(
            scenario.market_data,
            scenario.edge_metrics,
            scenario.time_to_expiry,
            asset_ticker='ETH',
            execution_side=scenario.side,
            use_maker_economics=scenario.use_maker_economics
        )
        assert decision.accepted == scenario.expected_accept

def test_per_asset_replay_sol():
    """SOL replay test with realistic market data (production bug case)."""
    for scenario in SOL_REPLAY_SCENARIOS:
        decision = edge_aware_microstructure_gate_15m(
            scenario.market_data,
            scenario.edge_metrics,
            scenario.time_to_expiry,
            asset_ticker='SOL',
            execution_side=scenario.side,
            use_maker_economics=scenario.use_maker_economics
        )
        assert decision.accepted == scenario.expected_accept

def test_per_asset_replay_xrp():
    """XRP replay test with realistic market data (production bug case)."""
    for scenario in XRP_REPLAY_SCENARIOS:
        decision = edge_aware_microstructure_gate_15m(
            scenario.market_data,
            scenario.edge_metrics,
            scenario.time_to_expiry,
            asset_ticker='XRP',
            execution_side=scenario.side,
            use_maker_economics=scenario.use_maker_economics
        )
        assert decision.accepted == scenario.expected_accept

def test_per_asset_replay_doge():
    """DOGE replay test with realistic market data."""
    for scenario in DOGE_REPLAY_SCENARIOS:
        decision = edge_aware_microstructure_gate_15m(
            scenario.market_data,
            scenario.edge_metrics,
            scenario.time_to_expiry,
            asset_ticker='DOGE',
            execution_side=scenario.side,
            use_maker_economics=scenario.use_maker_economics
        )
        assert decision.accepted == scenario.expected_accept
```

## Implementation Notes

1. **Calibration Values**: All threshold values are v1 calibration and should be validated against replayed data before production deployment.

2. **Time Scaling**: The ratio check uses sigmoid decay (smooth transition), while the spread cap uses linear decay (simpler, less aggressive).

3. **Maker Economics**: The gate assumes `spread_edge_analytics.compute_per_side_edges` is called with `use_maker_economics=True` for maker orders, resulting in `spread_cost=0` and `ratio=0`.

4. **Performance**: Check order is optimized for performance - cheap checks (crossed book, freshness) run before expensive checks (depth inspection).

5. **Rejection Reasons**: Each check has a distinct rejection reason for debugging and monitoring.

## Future Enhancements

1. **Gate Structure Separation**: Split into eligibility, economics, policy, and threshold modules for clearer separation of concerns.

2. **Dynamic Calibration**: Auto-tune thresholds based on recent market behavior and rejection rates.

3. **Volatility Adjustment**: Adjust thresholds based on 15-minute volatility estimates.

4. **Side-Specific Depth**: Different depth thresholds for YES vs NO sides if orderbook asymmetry is common.

## References

- Original bug fix: `MICROSTRUCTURE_GATE_AUDIT_2026_08_02.md`
- Spread edge analytics: `merid/event_venues/kalshi/spread_edge_analytics.py`
- Order router integration: `merid/event_venues/kalshi/order_router.py`
