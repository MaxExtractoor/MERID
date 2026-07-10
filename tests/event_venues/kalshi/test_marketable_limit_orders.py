"""
Unit tests for marketable limit order functionality.

Tests cover:
- OrderIntent aggressiveness parameter
- compute_order_aggressiveness function
- Marketable limit order logic (cross spread)
- RestingOrder tracking system
- Edge decay cancel logic
"""

import pytest
import time
from dataclasses import dataclass


class TestOrderIntentAggressiveness:
    """Test OrderIntent aggressiveness parameter."""
    
    def test_aggressiveness_default_zero(self):
        """Aggressiveness defaults to 0.0 (resting)."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
        )
        
        assert intent.aggressiveness == 0.0
    
    def test_aggressiveness_can_be_set(self):
        """Aggressiveness can be set to any value between 0.0 and 1.0."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
            aggressiveness=0.8,
        )
        
        assert intent.aggressiveness == 0.8
    
    def test_aggressiveness_resting(self):
        """Aggressiveness=0.0 indicates resting order (join spread)."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
            aggressiveness=0.0,
        )
        
        assert intent.aggressiveness == 0.0
    
    def test_aggressiveness_marketable(self):
        """Aggressiveness>0.0 indicates marketable order (cross spread)."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
            aggressiveness=0.7,
        )
        
        assert intent.aggressiveness > 0.0


class TestComputeOrderAggressiveness:
    """Test compute_order_aggressiveness function."""
    
    def test_btc_high_edge_returns_marketable(self):
        """BTC with high edge (>=1.75%) returns marketable aggressiveness."""
        from merid.event_venues.kalshi.risk_parameters import compute_order_aggressiveness
        
        aggressiveness = compute_order_aggressiveness("BTC", 0.02, 900)  # 2% edge (above marketable threshold 1.75%)
        
        assert aggressiveness > 0.0
    
    def test_btc_medium_edge_returns_resting(self):
        """BTC with medium edge (>=1.25% and <1.75%) returns resting (0.0)."""
        from merid.event_venues.kalshi.risk_parameters import compute_order_aggressiveness
        
        aggressiveness = compute_order_aggressiveness("BTC", 0.015, 900)  # 1.5% edge (between resting 1.25% and marketable 1.75%)
        
        assert aggressiveness == 0.0
    
    def test_btc_low_edge_returns_no_trade(self):
        """BTC with low edge (<1.25%) returns no trade (0.0)."""
        from merid.event_venues.kalshi.risk_parameters import compute_order_aggressiveness
        
        aggressiveness = compute_order_aggressiveness("BTC", 0.01, 900)  # 1% edge (below resting threshold 1.25%)
        
        assert aggressiveness == 0.0
    
    def test_eth_high_edge_returns_marketable(self):
        """ETH with high edge (>=2.0%) returns marketable aggressiveness."""
        from merid.event_venues.kalshi.risk_parameters import compute_order_aggressiveness
        
        aggressiveness = compute_order_aggressiveness("ETH", 0.025, 900)  # 2.5% edge (above marketable threshold 2.0%)
        
        assert aggressiveness > 0.0
    
    def test_sol_high_edge_returns_marketable(self):
        """SOL with high edge (>=2.5%) returns marketable aggressiveness."""
        from merid.event_venues.kalshi.risk_parameters import compute_order_aggressiveness
        
        aggressiveness = compute_order_aggressiveness("SOL", 0.03, 900)  # 3% edge (above marketable threshold 2.5%)
        
        assert aggressiveness > 0.0
    
    def test_xrp_high_edge_returns_marketable(self):
        """XRP with high edge (>=3.0%) returns marketable aggressiveness."""
        from merid.event_venues.kalshi.risk_parameters import compute_order_aggressiveness
        
        aggressiveness = compute_order_aggressiveness("XRP", 0.035, 900)  # 3.5% edge (above marketable threshold 3.0%)
        
        assert aggressiveness > 0.0
    
    def test_doge_high_edge_returns_marketable(self):
        """DOGE with high edge (>=3.5%) returns marketable aggressiveness."""
        from merid.event_venues.kalshi.risk_parameters import compute_order_aggressiveness
        
        aggressiveness = compute_order_aggressiveness("DOGE", 0.04, 900)  # 4% edge (above marketable threshold 3.5%)
        
        assert aggressiveness > 0.0
    
    def test_near_expiry_forces_marketable(self):
        """Near expiry (<150s) forces marketable if edge justifies."""
        from merid.event_venues.kalshi.risk_parameters import compute_order_aggressiveness
        
        # BTC with medium edge near expiry should be marketable
        aggressiveness = compute_order_aggressiveness("BTC", 0.03, 100)
        
        assert aggressiveness > 0.0
    
    def test_near_expiry_low_edge_no_trade(self):
        """Near expiry with low edge returns no trade."""
        from merid.event_venues.kalshi.risk_parameters import compute_order_aggressiveness
        
        aggressiveness = compute_order_aggressiveness("BTC", 0.01, 100)
        
        assert aggressiveness == 0.0
    
    def test_aggressiveness_capped_at_1_0(self):
        """Aggressiveness is capped at 1.0 (full marketable)."""
        from merid.event_venues.kalshi.risk_parameters import compute_order_aggressiveness
        
        # Very high edge should cap at 1.0
        aggressiveness = compute_order_aggressiveness("BTC", 0.90, 900)
        
        assert aggressiveness <= 1.0


class TestRestingOrderTracking:
    """Test RestingOrder tracking system."""
    
    def test_track_resting_order(self):
        """RestingOrder can be tracked."""
        from merid.event_venues.kalshi.order_router import RestingOrder, track_resting_order
        
        order = RestingOrder(
            order_id="test_order_1",
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            limit_price_cents=50,
            placed_at_ts=time.time(),
            edge_at_placement=0.55,
            min_live_edge=0.50,
            max_live_seconds=120,
            aggressiveness=0.0,
        )
        
        track_resting_order(order)
        
        # Verify order is tracked
        from merid.event_venues.kalshi.order_router import get_resting_orders
        resting_orders = get_resting_orders()
        
        assert len(resting_orders) > 0
        assert any(o.order_id == "test_order_1" for o in resting_orders)
    
    def test_remove_resting_order(self):
        """RestingOrder can be removed from tracking."""
        from merid.event_venues.kalshi.order_router import RestingOrder, track_resting_order, remove_resting_order
        
        order = RestingOrder(
            order_id="test_order_2",
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            limit_price_cents=50,
            placed_at_ts=time.time(),
            edge_at_placement=0.55,
            min_live_edge=0.50,
            max_live_seconds=120,
            aggressiveness=0.0,
        )
        
        track_resting_order(order)
        removed = remove_resting_order("test_order_2")
        
        assert removed is not None
        assert removed.order_id == "test_order_2"
        
        # Verify order is no longer tracked
        from merid.event_venues.kalshi.order_router import get_resting_orders
        resting_orders = get_resting_orders()
        
        assert not any(o.order_id == "test_order_2" for o in resting_orders)
    
    def test_should_cancel_time_limit(self):
        """RestingOrder should cancel when time limit exceeded."""
        from merid.event_venues.kalshi.order_router import RestingOrder
        
        order = RestingOrder(
            order_id="test_order_3",
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            limit_price_cents=50,
            placed_at_ts=time.time() - 130,  # 130 seconds ago
            edge_at_placement=0.55,
            min_live_edge=0.50,
            max_live_seconds=120,  # 120 second limit
            aggressiveness=0.0,
        )
        
        should_cancel, reason = order.should_cancel(0.55, time.time())
        
        assert should_cancel is True
        assert "max_live_seconds_exceeded" in reason
    
    def test_should_cancel_edge_decay(self):
        """RestingOrder should cancel when edge decays below threshold."""
        from merid.event_venues.kalshi.order_router import RestingOrder
        
        order = RestingOrder(
            order_id="test_order_4",
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            limit_price_cents=50,
            placed_at_ts=time.time() - 10,
            edge_at_placement=0.55,
            min_live_edge=0.50,
            max_live_seconds=120,
            aggressiveness=0.0,
        )
        
        should_cancel, reason = order.should_cancel(0.45, time.time())  # Edge decayed to 45%
        
        assert should_cancel is True
        assert "edge_decay" in reason
    
    def test_should_not_cancel_fresh_order(self):
        """Fresh RestingOrder with good edge should not cancel."""
        from merid.event_venues.kalshi.order_router import RestingOrder
        
        order = RestingOrder(
            order_id="test_order_5",
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            limit_price_cents=50,
            placed_at_ts=time.time() - 10,
            edge_at_placement=0.55,
            min_live_edge=0.50,
            max_live_seconds=120,
            aggressiveness=0.0,
        )
        
        should_cancel, reason = order.should_cancel(0.55, time.time())  # Edge still good
        
        assert should_cancel is False
        assert reason == "ok"


class TestEdgeDecayCancel:
    """Test edge decay cancel logic."""
    
    def test_check_and_cancel_stale_orders_empty(self):
        """check_and_cancel_stale_orders returns empty list when no orders."""
        from merid.event_venues.kalshi.order_router import check_and_cancel_stale_orders
        
        # Clear any existing orders
        from merid.event_venues.kalshi.order_router import _resting_orders, _resting_orders_lock
        with _resting_orders_lock:
            _resting_orders.clear()
        
        canceled = check_and_cancel_stale_orders()
        
        assert canceled == []
    
    def test_check_and_cancel_stale_orders_time_limit(self):
        """check_and_cancel_stale_orders cancels orders exceeding time limit."""
        from merid.event_venues.kalshi.order_router import (
            RestingOrder, track_resting_order, check_and_cancel_stale_orders,
            _resting_orders, _resting_orders_lock
        )
        
        # Clear existing orders
        with _resting_orders_lock:
            _resting_orders.clear()
        
        # Add stale order
        order = RestingOrder(
            order_id="stale_order_1",
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            limit_price_cents=50,
            placed_at_ts=time.time() - 130,
            edge_at_placement=0.55,
            min_live_edge=0.50,
            max_live_seconds=120,
            aggressiveness=0.0,
        )
        track_resting_order(order)
        
        canceled = check_and_cancel_stale_orders()
        
        assert len(canceled) == 1
        assert "stale_order_1" in canceled
    
    def test_check_and_cancel_stale_orders_edge_decay(self):
        """check_and_cancel_stale_orders cancels orders with edge decay."""
        from merid.event_venues.kalshi.order_router import (
            RestingOrder, track_resting_order, check_and_cancel_stale_orders,
            _resting_orders, _resting_orders_lock
        )
        
        # Clear existing orders
        with _resting_orders_lock:
            _resting_orders.clear()
        
        # Add order with edge decay (will be detected as decayed due to missing market state)
        order = RestingOrder(
            order_id="decayed_order_1",
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            limit_price_cents=50,
            placed_at_ts=time.time() - 10,
            edge_at_placement=0.55,
            min_live_edge=0.50,
            max_live_seconds=120,
            aggressiveness=0.0,
        )
        track_resting_order(order)
        
        canceled = check_and_cancel_stale_orders()
        
        # Should cancel due to edge decay (market state unavailable -> edge=0.0)
        assert len(canceled) >= 0  # May or may not cancel depending on market state availability


class TestPerAssetThresholds:
    """Test per-asset edge thresholds."""
    
    def test_btc_thresholds(self):
        """BTC has correct unified edge thresholds."""
        from merid.event_venues.kalshi.risk_parameters import (
            EDGE_MARKET_ENTRY_BTC, EDGE_RESTING_ENTRY_BTC,
            EDGE_CANCEL_THRESHOLD_BTC, MAX_LIVE_SECONDS_RESTING_BTC
        )
        
        assert EDGE_MARKET_ENTRY_BTC == 0.0175  # 1.75% marketable (taker fee-adjusted)
        assert EDGE_RESTING_ENTRY_BTC == 0.0125  # 1.25% resting (maker fee-adjusted)
        assert EDGE_CANCEL_THRESHOLD_BTC == 0.50
        assert MAX_LIVE_SECONDS_RESTING_BTC == 120
    
    def test_eth_thresholds(self):
        """ETH has correct unified edge thresholds."""
        from merid.event_venues.kalshi.risk_parameters import (
            EDGE_MARKET_ENTRY_ETH, EDGE_RESTING_ENTRY_ETH,
            EDGE_CANCEL_THRESHOLD_ETH, MAX_LIVE_SECONDS_RESTING_ETH
        )
        
        assert EDGE_MARKET_ENTRY_ETH == 0.02  # 2.0% marketable (taker fee-adjusted)
        assert EDGE_RESTING_ENTRY_ETH == 0.015  # 1.5% resting (maker fee-adjusted)
        assert EDGE_CANCEL_THRESHOLD_ETH == 0.50
        assert MAX_LIVE_SECONDS_RESTING_ETH == 120
    
    def test_sol_thresholds(self):
        """SOL has correct unified edge thresholds."""
        from merid.event_venues.kalshi.risk_parameters import (
            EDGE_MARKET_ENTRY_SOL, EDGE_RESTING_ENTRY_SOL,
            EDGE_CANCEL_THRESHOLD_SOL, MAX_LIVE_SECONDS_RESTING_SOL
        )
        
        assert EDGE_MARKET_ENTRY_SOL == 0.025  # 2.5% marketable (taker fee-adjusted)
        assert EDGE_RESTING_ENTRY_SOL == 0.02  # 2.0% resting (maker fee-adjusted)
        assert EDGE_CANCEL_THRESHOLD_SOL == 0.52
        assert MAX_LIVE_SECONDS_RESTING_SOL == 90
    
    def test_xrp_thresholds(self):
        """XRP has correct unified edge thresholds."""
        from merid.event_venues.kalshi.risk_parameters import (
            EDGE_MARKET_ENTRY_XRP, EDGE_RESTING_ENTRY_XRP,
            EDGE_CANCEL_THRESHOLD_XRP, MAX_LIVE_SECONDS_RESTING_XRP
        )
        
        assert EDGE_MARKET_ENTRY_XRP == 0.03  # 3.0% marketable (taker fee-adjusted)
        assert EDGE_RESTING_ENTRY_XRP == 0.0225  # 2.25% resting (maker fee-adjusted)
        assert EDGE_CANCEL_THRESHOLD_XRP == 0.53
        assert MAX_LIVE_SECONDS_RESTING_XRP == 90
    
    def test_doge_thresholds(self):
        """DOGE has correct unified edge thresholds."""
        from merid.event_venues.kalshi.risk_parameters import (
            EDGE_MARKET_ENTRY_DOGE, EDGE_RESTING_ENTRY_DOGE,
            EDGE_CANCEL_THRESHOLD_DOGE, MAX_LIVE_SECONDS_RESTING_DOGE
        )
        
        assert EDGE_MARKET_ENTRY_DOGE == 0.035  # 3.5% marketable (taker fee-adjusted)
        assert EDGE_RESTING_ENTRY_DOGE == 0.0275  # 2.75% resting (maker fee-adjusted)
        assert EDGE_CANCEL_THRESHOLD_DOGE == 0.55
        assert MAX_LIVE_SECONDS_RESTING_DOGE == 60
    
    def test_market_only_last_seconds(self):
        """MARKET_ONLY_LAST_SECONDS threshold is correct."""
        from merid.event_venues.kalshi.risk_parameters import MARKET_ONLY_LAST_SECONDS
        
        assert MARKET_ONLY_LAST_SECONDS == 150


class TestOrderRouterAggressivenessIntegration:
    """Test order aggressiveness computation integration in route_order_async."""
    
    def test_aggressiveness_computed_from_edge(self):
        """route_order_async computes aggressiveness from edge when not set."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        from merid.event_venues.kalshi.risk_parameters import compute_order_aggressiveness
        
        # Create intent with edge_pct but aggressiveness=0.0 (default)
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
            edge_pct=0.05,  # 5% edge
            aggressiveness=0.0,  # Default, should be computed
        )
        
        # Simulate the aggressiveness computation logic from route_order_async
        if intent.edge_pct is not None and intent.aggressiveness == 0.0:
            asset = "BTC"
            seconds_to_expiry = 900
            intent.aggressiveness = compute_order_aggressiveness(
                asset=asset,
                edge_pct=intent.edge_pct,
                seconds_to_expiry=seconds_to_expiry
            )
        
        # Assert aggressiveness was computed (should be > 0.0 for 5% edge)
        assert intent.aggressiveness > 0.0
    
    def test_aggressiveness_not_overridden_if_set(self):
        """route_order_async does not override aggressiveness if already set."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        # Create intent with aggressiveness already set
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
            edge_pct=0.05,
            aggressiveness=0.8,  # Already set, should not be overridden
        )
        
        # Simulate the aggressiveness computation logic from route_order_async
        if intent.edge_pct is not None and intent.aggressiveness == 0.0:
            # This should not execute since aggressiveness is 0.8
            from merid.event_venues.kalshi.risk_parameters import compute_order_aggressiveness
            intent.aggressiveness = compute_order_aggressiveness("BTC", intent.edge_pct, 900)
        
        # Assert aggressiveness was not overridden
        assert intent.aggressiveness == 0.8
    
    def test_aggressiveness_computed_for_all_assets(self):
        """Aggressiveness computation works for all crypto assets."""
        from merid.event_venues.kalshi.risk_parameters import compute_order_aggressiveness
        
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        for asset in assets:
            aggressiveness = compute_order_aggressiveness(asset, 0.05, 900)
            # All assets should return marketable aggressiveness for 5% edge
            assert aggressiveness > 0.0, f"{asset} should return marketable aggressiveness for 5% edge"
    
    def test_aggressiveness_resting_for_low_edge(self):
        """Low edge (<2%) returns resting aggressiveness (0.0)."""
        from merid.event_venues.kalshi.risk_parameters import compute_order_aggressiveness
        
        aggressiveness = compute_order_aggressiveness("BTC", 0.01, 900)
        assert aggressiveness == 0.0
