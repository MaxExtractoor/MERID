"""Unit tests for Kalshi microstructure utilities.

Tests the canonical microstructure calculation functions that ensure
consistent spread and depth interpretation across all layers.
"""

import pytest
from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot, OrderbookLevel
from merid.event_venues.kalshi.microstructure import (
    compute_side_microstructure,
    compute_effective_spread,
    compute_depth_at_price,
    cents_to_dollars,
    dollars_to_cents,
    MicrostructureView,
)


class TestMicrostructureView:
    """Test MicrostructureView dataclass."""
    
    def test_to_dict(self):
        """Test conversion to dictionary for logging."""
        view = MicrostructureView(
            best_yes_bid=40,
            best_yes_ask=35,
            best_no_bid=65,
            best_no_ask=60,
            spread_cents=5,
            spread_pct=0.05,
            depth_yes_at_best=100,
            depth_no_at_best=50,
            depth_yes_within_10c=200,
            depth_no_within_10c=100,
            book_skew=0.33,
            size=10,
            fillable_yes=True,
            fillable_no=False,
        )
        
        result = view.to_dict()
        
        assert result["best_yes_bid_cents"] == 40
        assert result["best_yes_ask_cents"] == 35
        assert result["spread_cents"] == 5
        assert result["spread_pct"] == 0.05
        assert result["depth_yes_at_best"] == 100
        assert result["fillable_yes"] is True
        assert result["fillable_no"] is False


class TestComputeSideMicrostructure:
    """Test compute_side_microstructure function."""
    
    def test_basic_yes_microstructure(self):
        """Test basic YES microstructure calculation."""
        # Create a simple orderbook:
        # YES bids: 40c (100 contracts), 39c (50 contracts)
        # NO bids: 65c (50 contracts), 64c (30 contracts)
        # Derived YES ask = 100 - 65 = 35c
        # Spread = 40 - 35 = 5c
        
        yes_levels = (
            OrderbookLevel(price_cents=40, size=100),
            OrderbookLevel(price_cents=39, size=50),
        )
        no_levels = (
            OrderbookLevel(price_cents=65, size=50),
            OrderbookLevel(price_cents=64, size=30),
        )
        
        snapshot = OrderbookSnapshot(
            ticker="KXBTC-15M-T50000",
            yes_bids=yes_levels,
            no_bids=no_levels,
            seq=1,
            ts=0.0,
        )
        
        micro = compute_side_microstructure(snapshot, side="yes", size=10)
        
        # Verify best prices
        assert micro.best_yes_bid == 40
        assert micro.best_no_bid == 65
        assert micro.best_yes_ask == 35  # 100 - 65
        assert micro.best_no_ask == 60  # 100 - 40
        
        # Verify spread
        assert micro.spread_cents == 5  # 40 - 35
        assert micro.spread_pct == pytest.approx(0.05 / 0.375, rel=0.01)  # 5c / 37.5c mid
        
        # Verify depth at best
        assert micro.depth_yes_at_best == 100
        assert micro.depth_no_at_best == 50
        
        # Verify depth within 10c window
        # YES: 40c and 39c are within 10c of 40c -> 100 + 50 = 150
        assert micro.depth_yes_within_10c == 150
        # NO: 65c and 64c are within 10c of 65c -> 50 + 30 = 80
        assert micro.depth_no_within_10c == 80
        
        # Verify book skew
        yes_sz = 100 + 50
        no_sz = 50 + 30
        expected_skew = (yes_sz - no_sz) / (yes_sz + no_sz)
        assert micro.book_skew == pytest.approx(expected_skew, rel=0.01)
        
        # Verify fillability
        assert micro.fillable_yes is True  # 100 >= 10
        assert micro.fillable_no is True  # 50 >= 10
    
    def test_no_microstructure(self):
        """Test NO side microstructure calculation."""
        yes_levels = (OrderbookLevel(price_cents=40, size=100),)
        no_levels = (OrderbookLevel(price_cents=65, size=50),)
        
        snapshot = OrderbookSnapshot(
            ticker="KXBTC-15M-T50000",
            yes_bids=yes_levels,
            no_bids=no_levels,
            seq=1,
            ts=0.0,
        )
        
        micro = compute_side_microstructure(snapshot, side="no", size=30)
        
        # For NO side, we check NO depth
        assert micro.fillable_no is True  # 50 >= 30
        assert micro.fillable_yes is True  # 100 >= 30 (but side is no)
    
    def test_insufficient_depth(self):
        """Test fillability when depth is insufficient."""
        yes_levels = (OrderbookLevel(price_cents=40, size=5),)
        no_levels = (OrderbookLevel(price_cents=65, size=3),)
        
        snapshot = OrderbookSnapshot(
            ticker="KXBTC-15M-T50000",
            yes_bids=yes_levels,
            no_bids=no_levels,
            seq=1,
            ts=0.0,
        )
        
        micro = compute_side_microstructure(snapshot, side="yes", size=10)
        
        # Depth at best is 5, but we need 10
        assert micro.fillable_yes is False
        
        # But depth within 10c is still 5 (only one level)
        assert micro.depth_yes_within_10c == 5
    
    def test_depth_within_window(self):
        """Test depth aggregation within price window."""
        # YES bids: 40c (10), 35c (20), 30c (30), 25c (40)
        # Window 10c from best bid (40c): should include 40c and 35c
        yes_levels = (
            OrderbookLevel(price_cents=40, size=10),
            OrderbookLevel(price_cents=35, size=20),
            OrderbookLevel(price_cents=30, size=30),
            OrderbookLevel(price_cents=25, size=40),
        )
        no_levels = (OrderbookLevel(price_cents=65, size=50),)
        
        snapshot = OrderbookSnapshot(
            ticker="KXBTC-15M-T50000",
            yes_bids=yes_levels,
            no_bids=no_levels,
            seq=1,
            ts=0.0,
        )
        
        micro = compute_side_microstructure(snapshot, side="yes", size=25, depth_window_cents=10)
        
        # Within 10c of 40c: 40c (10) + 35c (20) = 30
        assert micro.depth_yes_within_10c == 30
        # Should be fillable now (30 >= 25)
        assert micro.fillable_yes is True
    
    def test_empty_orderbook(self):
        """Test microstructure with empty orderbook."""
        snapshot = OrderbookSnapshot(
            ticker="KXBTC-15M-T50000",
            yes_bids=(),
            no_bids=(),
            seq=1,
            ts=0.0,
        )
        
        micro = compute_side_microstructure(snapshot, side="yes", size=1)
        
        # All fields should be None or zero
        assert micro.best_yes_bid is None
        assert micro.best_no_bid is None
        assert micro.best_yes_ask is None
        assert micro.best_no_ask is None
        assert micro.spread_cents is None
        assert micro.spread_pct is None
        assert micro.depth_yes_at_best == 0
        assert micro.depth_no_at_best == 0
        assert micro.fillable_yes is False
        assert micro.fillable_no is False
    
    def test_one_sided_orderbook(self):
        """Test microstructure with only YES bids (no NO bids)."""
        yes_levels = (OrderbookLevel(price_cents=40, size=100),)
        no_levels = ()  # No NO bids
        
        snapshot = OrderbookSnapshot(
            ticker="KXBTC-15M-T50000",
            yes_bids=yes_levels,
            no_bids=no_levels,
            seq=1,
            ts=0.0,
        )
        
        micro = compute_side_microstructure(snapshot, side="yes", size=10)
        
        # YES bid should be available
        assert micro.best_yes_bid == 40
        # NO bid should be None
        assert micro.best_no_bid is None
        # YES ask should be None (can't derive without NO bid)
        assert micro.best_yes_ask is None
        # Spread should be None
        assert micro.spread_cents is None


class TestComputeEffectiveSpread:
    """Test compute_effective_spread function."""
    
    def test_yes_buy_effective_spread(self):
        """Test effective spread for buying YES."""
        # YES bid = 40c, NO bid = 65c
        # YES ask = 100 - 65 = 35c
        # Buying YES: cross at 35c, MTM at 40c
        # Effective spread = 40 - 35 = 5c
        
        yes_levels = (OrderbookLevel(price_cents=40, size=100),)
        no_levels = (OrderbookLevel(price_cents=65, size=50),)
        
        snapshot = OrderbookSnapshot(
            ticker="KXBTC-15M-T50000",
            yes_bids=yes_levels,
            no_bids=no_levels,
            seq=1,
            ts=0.0,
        )
        
        spread = compute_effective_spread(snapshot, side="yes", action="buy")
        
        assert spread == 5  # 40 - 35
    
    def test_yes_sell_effective_spread(self):
        """Test effective spread for selling YES."""
        # YES bid = 40c, NO bid = 65c
        # YES ask = 100 - 65 = 35c
        # Selling YES: cross at 40c, MTM at 35c
        # Effective spread = 40 - 35 = 5c
        
        yes_levels = (OrderbookLevel(price_cents=40, size=100),)
        no_levels = (OrderbookLevel(price_cents=65, size=50),)
        
        snapshot = OrderbookSnapshot(
            ticker="KXBTC-15M-T50000",
            yes_bids=yes_levels,
            no_bids=no_levels,
            seq=1,
            ts=0.0,
        )
        
        spread = compute_effective_spread(snapshot, side="yes", action="sell")
        
        assert spread == 5  # 40 - 35
    
    def test_no_buy_effective_spread(self):
        """Test effective spread for buying NO."""
        # YES bid = 40c, NO bid = 65c
        # NO ask = 100 - 40 = 60c
        # Buying NO: cross at 60c, MTM at 65c
        # Effective spread = 65 - 60 = 5c
        
        yes_levels = (OrderbookLevel(price_cents=40, size=100),)
        no_levels = (OrderbookLevel(price_cents=65, size=50),)
        
        snapshot = OrderbookSnapshot(
            ticker="KXBTC-15M-T50000",
            yes_bids=yes_levels,
            no_bids=no_levels,
            seq=1,
            ts=0.0,
        )
        
        spread = compute_effective_spread(snapshot, side="no", action="buy")
        
        assert spread == 5  # 65 - 60
    
    def test_no_sell_effective_spread(self):
        """Test effective spread for selling NO."""
        # YES bid = 40c, NO bid = 65c
        # NO ask = 100 - 40 = 60c
        # Selling NO: cross at 65c, MTM at 60c
        # Effective spread = 65 - 60 = 5c
        
        yes_levels = (OrderbookLevel(price_cents=40, size=100),)
        no_levels = (OrderbookLevel(price_cents=65, size=50),)
        
        snapshot = OrderbookSnapshot(
            ticker="KXBTC-15M-T50000",
            yes_bids=yes_levels,
            no_bids=no_levels,
            seq=1,
            ts=0.0,
        )
        
        spread = compute_effective_spread(snapshot, side="no", action="sell")
        
        assert spread == 5  # 65 - 60
    
    def test_empty_orderbook_spread(self):
        """Test effective spread with empty orderbook."""
        snapshot = OrderbookSnapshot(
            ticker="KXBTC-15M-T50000",
            yes_bids=(),
            no_bids=(),
            seq=1,
            ts=0.0,
        )
        
        spread = compute_effective_spread(snapshot, side="yes", action="buy")
        
        assert spread is None


class TestComputeDepthAtPrice:
    """Test compute_depth_at_price function."""
    
    def test_yes_depth_at_price(self):
        """Test YES depth at a specific price."""
        # YES bids: 40c (100), 35c (50), 30c (30)
        # Depth at 35c should include 40c and 35c = 150
        
        yes_levels = (
            OrderbookLevel(price_cents=40, size=100),
            OrderbookLevel(price_cents=35, size=50),
            OrderbookLevel(price_cents=30, size=30),
        )
        no_levels = (OrderbookLevel(price_cents=65, size=50),)
        
        snapshot = OrderbookSnapshot(
            ticker="KXBTC-15M-T50000",
            yes_bids=yes_levels,
            no_bids=no_levels,
            seq=1,
            ts=0.0,
        )
        
        depth = compute_depth_at_price(snapshot, side="yes", price_cents=35)
        
        assert depth == 150  # 100 + 50
    
    def test_yes_depth_at_higher_price(self):
        """Test YES depth at a higher price than best bid."""
        # YES bids: 40c (100), 35c (50)
        # Depth at 45c should include only 40c (since 45 > 40, only 40c qualifies)
        
        yes_levels = (
            OrderbookLevel(price_cents=40, size=100),
            OrderbookLevel(price_cents=35, size=50),
        )
        no_levels = (OrderbookLevel(price_cents=65, size=50),)
        
        snapshot = OrderbookSnapshot(
            ticker="KXBTC-15M-T50000",
            yes_bids=yes_levels,
            no_bids=no_levels,
            seq=1,
            ts=0.0,
        )
        
        depth = compute_depth_at_price(snapshot, side="yes", price_cents=45)
        
        assert depth == 100  # Only 40c qualifies
    
    def test_no_depth_at_price(self):
        """Test NO depth at a specific price."""
        # NO bids: 65c (50), 60c (30), 55c (20)
        # Depth at 60c should include 65c and 60c = 80
        
        yes_levels = (OrderbookLevel(price_cents=40, size=100),)
        no_levels = (
            OrderbookLevel(price_cents=65, size=50),
            OrderbookLevel(price_cents=60, size=30),
            OrderbookLevel(price_cents=55, size=20),
        )
        
        snapshot = OrderbookSnapshot(
            ticker="KXBTC-15M-T50000",
            yes_bids=yes_levels,
            no_bids=no_levels,
            seq=1,
            ts=0.0,
        )
        
        depth = compute_depth_at_price(snapshot, side="no", price_cents=60)
        
        assert depth == 80  # 50 + 30


class TestCentsDollarsConversion:
    """Test cents to dollars conversion utilities."""
    
    def test_cents_to_dollars(self):
        """Test converting cents to dollars."""
        assert cents_to_dollars(50) == 0.5
        assert cents_to_dollars(1) == 0.01
        assert cents_to_dollars(99) == 0.99
        assert cents_to_dollars(0) == 0.0
        assert cents_to_dollars(None) is None
    
    def test_dollars_to_cents(self):
        """Test converting dollars to cents."""
        assert dollars_to_cents(0.5) == 50
        assert dollars_to_cents(0.01) == 1
        assert dollars_to_cents(0.99) == 99
        assert dollars_to_cents(0.0) == 0
        assert dollars_to_cents(None) is None
    
    def test_dollars_to_cents_clamping(self):
        """Test that dollars_to_cents clamps to valid range."""
        # Below minimum should clamp to 1
        assert dollars_to_cents(0.001) == 1
        # Above maximum should clamp to 99
        assert dollars_to_cents(1.5) == 99
        # Exactly at boundaries
        assert dollars_to_cents(0.0) == 0
        assert dollars_to_cents(1.0) == 99  # Clamped to 99 (max valid for binary contracts)


class TestKalshiYesNoDuality:
    """Test Kalshi YES/NO binary duality invariant."""
    
    def test_yes_plus_no_equals_100(self):
        """Test that YES price + NO price = 100 cents."""
        # YES bid = 40c, NO bid = 65c
        # YES ask = 100 - NO bid = 35c
        # NO ask = 100 - YES bid = 60c
        
        yes_levels = (OrderbookLevel(price_cents=40, size=100),)
        no_levels = (OrderbookLevel(price_cents=65, size=50),)
        
        snapshot = OrderbookSnapshot(
            ticker="KXBTC-15M-T50000",
            yes_bids=yes_levels,
            no_bids=no_levels,
            seq=1,
            ts=0.0,
        )
        
        micro = compute_side_microstructure(snapshot, side="yes", size=1)
        
        # YES bid + NO ask = 40 + 60 = 100
        assert micro.best_yes_bid + micro.best_no_ask == 100
        
        # NO bid + YES ask = 65 + 35 = 100
        assert micro.best_no_bid + micro.best_yes_ask == 100
    
    def test_implied_probability_from_mid(self):
        """Test that implied probability = mid / 100."""
        # YES bids: 40c, NO bids: 65c
        # YES ask = 35c, mid = (40 + 35) / 2 = 37.5c
        # Implied prob = 37.5 / 100 = 0.375
        
        yes_levels = (OrderbookLevel(price_cents=40, size=100),)
        no_levels = (OrderbookLevel(price_cents=65, size=50),)
        
        snapshot = OrderbookSnapshot(
            ticker="KXBTC-15M-T50000",
            yes_bids=yes_levels,
            no_bids=no_levels,
            seq=1,
            ts=0.0,
        )
        
        mid_cents = snapshot.mid_cents
        implied_prob = snapshot.implied_prob
        
        assert mid_cents == 37.5
        assert implied_prob == 0.375
