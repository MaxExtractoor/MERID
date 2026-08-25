"""
15-Minute Market Microstructure Gate Tests

Comprehensive test suite for the 15-minute gate with time-to-expiry scaling,
asset-specific calibration, and layered guardrails.

Tests cover:
- Time-to-expiry scaling (sigmoid for ratio, linear for spread cap)
- Asset-specific thresholds (BTC, ETH, SOL, XRP, DOGE)
- Guardrail priority order (crossed book → freshness → ratio → spread cap → depth)
- Side-specific depth checks (execution side only)
- Maker vs taker economics
"""

import math
import pytest
from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timedelta

# Import production functions
from merid.event_venues.kalshi.spread_edge_analytics import (
    get_time_scaled_threshold,
    get_time_scaled_spread_cap,
    get_min_depth_threshold,
    check_crossed_book,
    check_absolute_spread_cap,
    check_minimum_depth,
    ASSET_RATIO_THRESHOLDS,
    ASSET_SPREAD_CAPS,
    ASSET_DEPTH_THRESHOLDS,
)

ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]


# Fake dataclass scaffolds for testing
@dataclass
class MarketData:
    """Fake market data for testing."""
    yes_bid: int = 50
    yes_ask: int = 51
    no_bid: int = 49
    no_ask: int = 50
    yes_bid_depth: int = 100
    no_bid_depth: int = 100
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class PerSideEdgeMetrics:
    """Fake edge metrics for testing."""
    spread_to_edge_ratio: float = 0.0
    spread_cents: int = 0
    raw_edge_cents: float = 20.0
    spread_cost_cents: float = 0.0
    taker_fee_cents: float = 0.0
    executable_edge_cents: float = 20.0
    side: str = "yes"
    p_hat_yes_cents: float = 50.0


@dataclass
class GateDecision:
    """Gate decision result."""
    accepted: bool
    reason: Optional[str] = None
    
    @property
    def rejected(self) -> bool:
        return not self.accepted


# Helper functions for test data
def current_time() -> datetime:
    """Get current time for testing."""
    return datetime.now()


def make_market_data(
    yes_bid=50,
    yes_ask=51,
    no_bid=49,
    no_ask=50,
    yes_bid_depth=100,
    no_bid_depth=100,
    timestamp_age_seconds=1,
) -> MarketData:
    """Create market data for testing."""
    return MarketData(
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        no_bid=no_bid,
        no_ask=no_ask,
        yes_bid_depth=yes_bid_depth,
        no_bid_depth=no_bid_depth,
        timestamp=current_time() - timedelta(seconds=timestamp_age_seconds),
    )


def make_edge_metrics(
    spread_to_edge_ratio=0.0,
    spread_cents=0,
    raw_edge_cents=20.0,
) -> PerSideEdgeMetrics:
    """Create edge metrics for testing."""
    return PerSideEdgeMetrics(
        spread_to_edge_ratio=spread_to_edge_ratio,
        spread_cents=spread_cents,
        raw_edge_cents=raw_edge_cents,
    )


# Helper functions for gate testing (using production functions where available)
def check_quote_freshness(market_data: MarketData, max_age_seconds: int = 30) -> bool:
    """Check if quote is fresh enough."""
    quote_age = (current_time() - market_data.timestamp).total_seconds()
    return quote_age <= max_age_seconds


def check_economics_ratio(
    edge_metrics: PerSideEdgeMetrics,
    asset_ticker: str,
    time_to_expiry_seconds: float,
    use_maker_economics: bool = True
) -> bool:
    """Check if spread-to-edge ratio is within threshold."""
    threshold = get_time_scaled_threshold(asset_ticker, time_to_expiry_seconds)
    return edge_metrics.spread_to_edge_ratio <= threshold


def check_absolute_spread_cap_test(
    edge_metrics: PerSideEdgeMetrics,
    asset_ticker: str,
    time_to_expiry_seconds: float
) -> bool:
    """Check if spread is within absolute cap (test wrapper)."""
    return check_absolute_spread_cap(
        edge_metrics.spread_cents,
        asset_ticker,
        time_to_expiry_seconds
    )


def check_minimum_depth_test(
    market_data: MarketData,
    asset_ticker: str,
    execution_side: str
) -> bool:
    """Check if depth on execution side is sufficient (test wrapper)."""
    return check_minimum_depth(
        market_data.yes_bid_depth,
        market_data.no_bid_depth,
        asset_ticker,
        execution_side
    )


def check_crossed_book_test(market_data: MarketData) -> bool:
    """Check if orderbook is crossed or inverted (test wrapper)."""
    return check_crossed_book(
        market_data.yes_bid,
        market_data.yes_ask,
        market_data.no_bid,
        market_data.no_ask
    )


def edge_aware_microstructure_gate_15m(
    market_data: MarketData,
    edge_metrics: PerSideEdgeMetrics,
    time_to_expiry_seconds: float,
    asset_ticker: str,
    execution_side: str,
    use_maker_economics: bool = True
) -> GateDecision:
    """
    Comprehensive gate for 15-minute markets with layered checks.
    
    Check Order (from fastest to most expensive):
    1. Crossed-book check - structural invalidity
    2. Freshness check - data quality
    3. Economics ratio check - primary value gate
    4. Absolute spread cap - secondary guardrail
    5. Minimum depth check - liquidity sanity check
    """
    
    # 1. Crossed-book check (structural invalidity)
    if not check_crossed_book_test(market_data):
        return GateDecision(accepted=False, reason="crossed_book")
    
    # 2. Freshness check (data quality)
    if not check_quote_freshness(market_data):
        return GateDecision(accepted=False, reason="stale_quote")
    
    # 3. Economics ratio check (primary gate)
    if not check_economics_ratio(edge_metrics, asset_ticker, time_to_expiry_seconds, use_maker_economics):
        return GateDecision(accepted=False, reason="spread_cost_too_high")
    
    # 4. Absolute spread cap (secondary guardrail)
    if not check_absolute_spread_cap_test(edge_metrics, asset_ticker, time_to_expiry_seconds):
        return GateDecision(accepted=False, reason="spread_too_wide")
    
    # 5. Minimum depth check (liquidity guardrail)
    if not check_minimum_depth_test(market_data, asset_ticker, execution_side):
        return GateDecision(accepted=False, reason="insufficient_depth")
    
    return GateDecision(accepted=True)


# =============================================================================
# TESTS
# =============================================================================

@pytest.mark.parametrize("asset", ASSETS)
def test_asset_threshold_bounds(asset):
    """Test that threshold bounds match asset-specific calibration."""
    assert get_time_scaled_threshold(asset, 900) == pytest.approx(ASSET_RATIO_THRESHOLDS[asset]["max"], abs=0.01)
    assert get_time_scaled_threshold(asset, 0) == pytest.approx(ASSET_RATIO_THRESHOLDS[asset]["min"], abs=0.01)


@pytest.mark.parametrize("asset", ASSETS)
@pytest.mark.parametrize("time_remaining", [900, 600, 300, 30])
def test_threshold_is_monotonic_nonincreasing(asset, time_remaining):
    """Test that threshold is monotonic non-increasing as time decreases."""
    t1 = get_time_scaled_threshold(asset, time_remaining)
    t2 = get_time_scaled_threshold(asset, max(time_remaining - 60, 0))
    assert t2 <= t1 + 1e-9


@pytest.mark.parametrize("asset", ASSETS)
def test_spread_cap_bounds(asset):
    """Test that spread cap bounds match asset-specific calibration."""
    early = get_time_scaled_spread_cap(asset, 900)
    late = get_time_scaled_spread_cap(asset, 0)
    assert late <= early
    assert early == ASSET_SPREAD_CAPS[asset]
    assert late == int(ASSET_SPREAD_CAPS[asset] * 0.8)


@pytest.mark.parametrize("asset", ASSETS)
def test_depth_thresholds(asset):
    """Test that depth thresholds match asset-specific calibration."""
    assert get_min_depth_threshold(asset) == ASSET_DEPTH_THRESHOLDS[asset]


@pytest.mark.parametrize(
    "market_data,expected_reason",
    [
        (make_market_data(yes_bid=60, yes_ask=50), "crossed_book"),
        (make_market_data(no_bid=60, no_ask=50), "crossed_book"),
    ],
)
def test_crossed_book_rejection(market_data, expected_reason):
    """Test that crossed books are rejected immediately."""
    decision = edge_aware_microstructure_gate_15m(
        market_data=market_data,
        edge_metrics=make_edge_metrics(),
        time_to_expiry_seconds=900,
        asset_ticker="BTC",
        execution_side="yes",
        use_maker_economics=True,
    )
    assert decision.rejected
    assert decision.reason == expected_reason


def test_stale_quote_rejection():
    """Test that stale quotes are rejected."""
    market_data = make_market_data(timestamp_age_seconds=31)
    decision = edge_aware_microstructure_gate_15m(
        market_data=market_data,
        edge_metrics=make_edge_metrics(),
        time_to_expiry_seconds=900,
        asset_ticker="BTC",
        execution_side="yes",
        use_maker_economics=True,
    )
    assert decision.rejected
    assert decision.reason == "stale_quote"


@pytest.mark.parametrize("asset", ASSETS)
def test_maker_order_passes_ratio_check(asset):
    """Test that maker orders pass ratio check (ratio=0)."""
    edge_metrics = make_edge_metrics(spread_to_edge_ratio=0.0, spread_cents=0, raw_edge_cents=20.0)
    assert check_economics_ratio(edge_metrics, asset, 900, use_maker_economics=True)


@pytest.mark.parametrize("asset", ASSETS)
def test_taker_ratio_respects_thresholds(asset):
    """Test that taker orders respect asset-specific thresholds."""
    edge_metrics = make_edge_metrics(spread_to_edge_ratio=1.5, spread_cents=20, raw_edge_cents=10.0)
    assert not check_economics_ratio(edge_metrics, asset, 900, use_maker_economics=False)


@pytest.mark.parametrize("asset", ASSETS)
def test_side_specific_depth_yes(asset):
    """Test that YES orders check YES-side depth only."""
    market_data = make_market_data(yes_bid_depth=ASSET_DEPTH_THRESHOLDS[asset], no_bid_depth=1)
    assert check_minimum_depth_test(market_data, asset, execution_side="yes")


@pytest.mark.parametrize("asset", ASSETS)
def test_side_specific_depth_no(asset):
    """Test that NO orders check NO-side depth only."""
    market_data = make_market_data(yes_bid_depth=1, no_bid_depth=ASSET_DEPTH_THRESHOLDS[asset])
    assert check_minimum_depth_test(market_data, asset, execution_side="no")


@pytest.mark.parametrize("asset", ASSETS)
def test_maker_order_passes_even_if_opposite_side_thin(asset):
    """Test that maker orders pass even if opposite side depth is thin."""
    depth = ASSET_DEPTH_THRESHOLDS[asset]

    market_data = make_market_data(
        yes_bid_depth=depth,
        no_bid_depth=1,
    )
    decision = edge_aware_microstructure_gate_15m(
        market_data=market_data,
        edge_metrics=make_edge_metrics(spread_to_edge_ratio=0.0, spread_cents=0, raw_edge_cents=20.0),
        time_to_expiry_seconds=900,
        asset_ticker=asset,
        execution_side="yes",
        use_maker_economics=True,
    )
    assert not decision.rejected


@pytest.mark.parametrize("asset", ASSETS)
def test_full_gate_accepts_clean_maker_setup(asset):
    """Test that full gate accepts clean maker setup for all assets."""
    market_data = make_market_data(
        yes_bid=49,
        yes_ask=50,
        no_bid=50,
        no_ask=51,
        yes_bid_depth=max(ASSET_DEPTH_THRESHOLDS[asset], 50),
        no_bid_depth=max(ASSET_DEPTH_THRESHOLDS[asset], 50),
    )
    decision = edge_aware_microstructure_gate_15m(
        market_data=market_data,
        edge_metrics=make_edge_metrics(spread_to_edge_ratio=0.0, spread_cents=0, raw_edge_cents=20.0),
        time_to_expiry_seconds=900,
        asset_ticker=asset,
        execution_side="yes",
        use_maker_economics=True,
    )
    assert not decision.rejected


def test_gate_order_crossed_book_wins_over_freshness():
    """Test that crossed-book rejection wins over freshness rejection."""
    market_data = make_market_data(yes_bid=60, yes_ask=50, timestamp_age_seconds=31)
    decision = edge_aware_microstructure_gate_15m(
        market_data=market_data,
        edge_metrics=make_edge_metrics(),
        time_to_expiry_seconds=900,
        asset_ticker="BTC",
        execution_side="yes",
        use_maker_economics=True,
    )
    assert decision.rejected
    assert decision.reason == "crossed_book"


def test_gate_order_freshness_wins_over_economics():
    """Test that freshness rejection wins over economics rejection."""
    market_data = make_market_data(timestamp_age_seconds=31)
    decision = edge_aware_microstructure_gate_15m(
        market_data=market_data,
        edge_metrics=make_edge_metrics(spread_to_edge_ratio=999.0),
        time_to_expiry_seconds=900,
        asset_ticker="BTC",
        execution_side="yes",
        use_maker_economics=True,
    )
    assert decision.rejected
    assert decision.reason == "stale_quote"


@pytest.mark.parametrize("asset", ASSETS)
def test_spread_cap_rejection(asset):
    """Test that spread cap rejects wide spreads."""
    market_data = make_market_data()
    edge_metrics = make_edge_metrics(
        spread_to_edge_ratio=0.0,
        spread_cents=ASSET_SPREAD_CAPS[asset] + 1,
        raw_edge_cents=20.0,
    )
    decision = edge_aware_microstructure_gate_15m(
        market_data=market_data,
        edge_metrics=edge_metrics,
        time_to_expiry_seconds=900,
        asset_ticker=asset,
        execution_side="yes",
        use_maker_economics=True,
    )
    assert decision.rejected
    assert decision.reason == "spread_too_wide"


@pytest.mark.parametrize("asset", ASSETS)
def test_depth_rejection(asset):
    """Test that depth check rejects thin orderbooks."""
    market_data = make_market_data(
        yes_bid_depth=ASSET_DEPTH_THRESHOLDS[asset] - 1,
        no_bid_depth=100,
    )
    decision = edge_aware_microstructure_gate_15m(
        market_data=market_data,
        edge_metrics=make_edge_metrics(),
        time_to_expiry_seconds=900,
        asset_ticker=asset,
        execution_side="yes",
        use_maker_economics=True,
    )
    assert decision.rejected
    assert decision.reason == "insufficient_depth"


@pytest.mark.parametrize("asset", ASSETS)
def test_time_to_expiry_tightens_threshold(asset):
    """Test that threshold tightens as time-to-expiry decreases."""
    early = get_time_scaled_threshold(asset, 900)
    mid = get_time_scaled_threshold(asset, 450)
    late = get_time_scaled_threshold(asset, 30)
    assert early >= mid >= late
