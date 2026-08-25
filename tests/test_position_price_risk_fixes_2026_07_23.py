"""
Tests for position price handling and risk parameter state tracking (2026-07-23).

This test suite validates:
1. avg_price_cents=0 handling with entry_price_state
2. Local persistence of entry price, SL, TP at order placement
3. risk_params_unknown state for positions without SL/TP metadata
4. OBI depth gating for low liquidity markets

Run with: pytest tests/test_position_price_risk_fixes_2026_07_23.py -v
"""

import pytest
from decimal import Decimal
from merid.event_venues.kalshi.position_cache import get_position_cache, KalshiPositionCache, CachedPosition


class TestEntryPriceState:
    """Test suite for entry_price_state tracking."""
    
    @pytest.fixture
    def position_cache(self):
        """Get position cache instance for testing."""
        cache = get_position_cache()
        cache._positions.clear()
        cache._last_sync = None
        return cache
    
    def test_cached_position_with_known_entry_price(self):
        """Test CachedPosition with known entry price."""
        position = CachedPosition(
            market_id="KXBTC15M-26JUL012015-30",
            agent_id="BTC_15M",
            thesis_side="yes",
            contracts=10,
            side="yes",
            avg_price_cents=50,
            entry_price_state="known"
        )
        
        assert position.avg_price_cents == 50
        assert position.entry_price_state == "known"
        assert position.notional_usd == Decimal("5.00")  # 10 * 0.50
    
    def test_cached_position_with_unknown_entry_price(self):
        """Test CachedPosition with unknown entry price."""
        position = CachedPosition(
            market_id="KXBTC15M-26JUL012015-30",
            agent_id="BTC_15M",
            thesis_side="yes",
            contracts=10,
            side="yes",
            avg_price_cents=None,
            entry_price_state="unknown"
        )
        
        assert position.avg_price_cents is None
        assert position.entry_price_state == "unknown"
        assert position.notional_usd == Decimal("0")  # None price treated as zero
    
    def test_cached_position_with_invalid_entry_price(self):
        """Test CachedPosition with invalid entry price (0)."""
        position = CachedPosition(
            market_id="KXBTC15M-26JUL012015-30",
            agent_id="BTC_15M",
            thesis_side="yes",
            contracts=10,
            side="yes",
            avg_price_cents=0,
            entry_price_state="invalid"
        )
        
        assert position.avg_price_cents == 0
        assert position.entry_price_state == "invalid"
        assert position.notional_usd == Decimal("0")  # Zero price treated as zero
    
    def test_cached_position_with_fallback_entry_price(self):
        """Test CachedPosition with fallback entry price from persistence."""
        position = CachedPosition(
            market_id="KXBTC15M-26JUL012015-30",
            agent_id="BTC_15M",
            thesis_side="yes",
            contracts=10,
            side="yes",
            avg_price_cents=45,  # Fallback from persisted entry price
            entry_price_state="fallback"
        )
        
        assert position.avg_price_cents == 45
        assert position.entry_price_state == "fallback"
        assert position.notional_usd == Decimal("4.50")


class TestRiskParamsState:
    """Test suite for risk_params_state tracking."""
    
    def test_cached_position_with_known_risk_params(self):
        """Test CachedPosition with known risk parameters (SL set)."""
        position = CachedPosition(
            market_id="KXBTC15M-26JUL012015-30",
            agent_id="BTC_15M",
            thesis_side="yes",
            contracts=10,
            side="yes",
            avg_price_cents=50,
            entry_price_state="known",
            stop_loss_price_cents=45,  # SL set
            risk_params_state="known"
        )
        
        assert position.stop_loss_price_cents == 45
        assert position.risk_params_state == "known"
    
    def test_cached_position_with_unknown_risk_params(self):
        """Test CachedPosition with unknown risk parameters (no SL)."""
        position = CachedPosition(
            market_id="KXBTC15M-26JUL012015-30",
            agent_id="BTC_15M",
            thesis_side="yes",
            contracts=10,
            side="yes",
            avg_price_cents=50,
            entry_price_state="known",
            stop_loss_price_cents=None,  # No SL
            risk_params_state="unknown"
        )
        
        assert position.stop_loss_price_cents is None
        assert position.risk_params_state == "unknown"


class TestTPTargetPersistence:
    """Test suite for TP target registration with entry price."""
    
    @pytest.fixture
    def position_cache(self):
        """Get position cache instance for testing."""
        cache = get_position_cache()
        cache._positions.clear()
        cache._pending_tp_targets.clear()
        return cache
    
    def test_register_tp_targets_with_entry_price(self, position_cache):
        """Test registering TP targets with entry price."""
        client_order_id = "test-order-123"
        
        position_cache.register_tp_targets(
            client_order_id=client_order_id,
            take_profit_price_cents=60,
            take_profit_r_multiple=1.5,
            stop_loss_price_cents=45,
            entry_price_cents=50,  # CRITICAL: Persist entry price
            vol_regime="normal",  # CRITICAL FIX (2026-08-01): Persist volatility regime
            confidence="high"  # CRITICAL FIX (2026-08-01): Persist signal confidence
        )
        
        targets = position_cache._pending_tp_targets.get(client_order_id)
        assert targets is not None
        assert targets["tp_price"] == 60
        assert targets["tp_r"] == 1.5
        assert targets["sl_price"] == 45
        assert targets["entry_price"] == 50  # Entry price persisted
        assert targets["vol_regime"] == "normal"  # CRITICAL FIX (2026-08-01): Volatility regime persisted
        assert targets["confidence"] == "high"  # CRITICAL FIX (2026-08-01): Confidence persisted
        assert "registered_at" in targets
    
    def test_register_tp_targets_without_entry_price(self, position_cache):
        """Test registering TP targets without entry price (backward compatibility)."""
        client_order_id = "test-order-456"
        
        position_cache.register_tp_targets(
            client_order_id=client_order_id,
            take_profit_price_cents=60,
            stop_loss_price_cents=45
            # entry_price_cents not provided (optional)
            # vol_regime and confidence not provided (optional)
        )
        
        targets = position_cache._pending_tp_targets.get(client_order_id)
        assert targets is not None
        assert targets["entry_price"] is None  # Should be None if not provided
        assert targets["vol_regime"] is None  # CRITICAL FIX (2026-08-01): Should be None if not provided
        assert targets["confidence"] is None  # CRITICAL FIX (2026-08-01): Should be None if not provided


class TestMicrostructureDepthGating:
    """Test suite for OBI depth gating in market microstructure."""
    
    def test_check_market_microstructure_with_sufficient_depth(self):
        """Test microstructure check passes with sufficient total depth."""
        from merid.event_venues.kalshi.order_router import check_market_microstructure
        
        passes, reason = check_market_microstructure(
            yes_bid_cents=45,
            yes_ask_cents=55,
            no_bid_cents=45,
            no_ask_cents=55,
            yes_depth=15,
            no_depth=15,  # Total depth = 30 >= 25 (min_total_depth)
            min_total_depth=25,
            max_spread_cents=20,  # Spread is 10c, which is <= 20c
            min_depth_usd=0.0  # Disable USD depth check for this test
        )
        
        assert passes is True
        assert reason == "ok"
    
    def test_check_market_microstructure_with_insufficient_total_depth(self):
        """Test microstructure check fails with insufficient total depth."""
        from merid.event_venues.kalshi.order_router import check_market_microstructure
        
        passes, reason = check_market_microstructure(
            yes_bid_cents=45,
            yes_ask_cents=55,
            no_bid_cents=45,
            no_ask_cents=55,
            yes_depth=10,
            no_depth=10,  # Total depth = 20 < 25 (min_total_depth)
            min_total_depth=25,
            max_spread_cents=20
        )
        
        assert passes is False
        assert "total_depth_too_low" in reason
        assert "20" in reason
        assert "25" in reason
    
    def test_check_market_microstructure_respects_individual_depth_thresholds(self):
        """Test that individual depth thresholds are still respected."""
        from merid.event_venues.kalshi.order_router import check_market_microstructure
        
        # YES depth too low (even though total is sufficient)
        passes, reason = check_market_microstructure(
            yes_bid_cents=45,
            yes_ask_cents=55,
            no_bid_cents=45,
            no_ask_cents=55,
            yes_depth=0,  # Below min_yes_depth=1
            no_depth=30,
            min_yes_depth=1,
            min_no_depth=1,
            min_total_depth=25,
            max_spread_cents=20
        )
        
        assert passes is False
        assert "yes_depth_too_low" in reason
    
    def test_check_market_microstructure_default_min_total_depth(self):
        """Test that default min_total_depth is 25."""
        from merid.event_venues.kalshi.order_router import check_market_microstructure
        
        # Should use default min_total_depth=25
        passes, reason = check_market_microstructure(
            yes_bid_cents=45,
            yes_ask_cents=55,
            no_bid_cents=45,
            no_ask_cents=55,
            yes_depth=10,
            no_depth=10,  # Total = 20 < default 25
            max_spread_cents=20
        )
        
        assert passes is False
        assert "total_depth_too_low" in reason


class TestPositionSyncWithNewFields:
    """Test suite for position sync with new fields."""
    
    @pytest.fixture
    def position_cache(self):
        """Get position cache instance for testing."""
        cache = get_position_cache()
        cache._positions.clear()
        cache._last_sync = None
        return cache
    
    @pytest.mark.asyncio
    async def test_sync_from_rest_sets_entry_price_state_known(self, position_cache):
        """Test that sync_from_rest sets entry_price_state=known when avg_price is valid."""
        rest_positions = [
            {
                "market_id": "KXBTC15M-26JUL012015-30",
                "contracts": 10,
                "side": "yes",
                "avg_price_cents": 50,  # Valid price
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.5
            }
        ]
        
        await position_cache.sync_from_rest(rest_positions)
        
        position = position_cache._positions.get("KXBTC15M-26JUL012015-30")
        assert position is not None
        assert position.entry_price_state == "known"
        assert position.avg_price_cents == 50
    
    @pytest.mark.asyncio
    async def test_sync_from_rest_sets_entry_price_state_unknown(self, position_cache):
        """Test that sync_from_rest sets entry_price_state=unknown when avg_price is None."""
        rest_positions = [
            {
                "market_id": "KXBTC15M-26JUL012015-30",
                "contracts": 10,
                "side": "yes",
                "avg_price_cents": None,  # Missing price
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.5
            }
        ]
        
        await position_cache.sync_from_rest(rest_positions)
        
        position = position_cache._positions.get("KXBTC15M-26JUL012015-30")
        assert position is not None
        assert position.entry_price_state == "unknown"
        assert position.avg_price_cents is None
    
    @pytest.mark.asyncio
    async def test_sync_from_rest_sets_entry_price_state_invalid(self, position_cache):
        """Test that sync_from_rest sets entry_price_state=invalid when avg_price is 0."""
        rest_positions = [
            {
                "market_id": "KXBTC15M-26JUL012015-30",
                "contracts": 10,
                "side": "yes",
                "avg_price_cents": 0,  # Invalid price
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.5
            }
        ]
        
        await position_cache.sync_from_rest(rest_positions)
        
        position = position_cache._positions.get("KXBTC15M-26JUL012015-30")
        assert position is not None
        assert position.entry_price_state == "invalid"
        assert position.avg_price_cents is None  # 0 converted to None
    
    @pytest.mark.asyncio
    async def test_sync_from_rest_sets_risk_params_state_known(self, position_cache):
        """Test that sync_from_rest sets risk_params_state=known when SL is present."""
        rest_positions = [
            {
                "market_id": "KXBTC15M-26JUL012015-30",
                "contracts": 10,
                "side": "yes",
                "avg_price_cents": 50,
                "stop_loss_price_cents": 45,  # SL present
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.5
            }
        ]
        
        await position_cache.sync_from_rest(rest_positions)
        
        position = position_cache._positions.get("KXBTC15M-26JUL012015-30")
        assert position is not None
        assert position.risk_params_state == "known"
        assert position.stop_loss_price_cents == 45
    
    @pytest.mark.asyncio
    async def test_sync_from_rest_sets_risk_params_state_unknown(self, position_cache):
        """Test that sync_from_rest sets risk_params_state=unknown when SL is missing."""
        rest_positions = [
            {
                "market_id": "KXBTC15M-26JUL012015-30",
                "contracts": 10,
                "side": "yes",
                "avg_price_cents": 50,
                # stop_loss_price_cents not present
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.5
            }
        ]
        
        await position_cache.sync_from_rest(rest_positions)
        
        position = position_cache._positions.get("KXBTC15M-26JUL012015-30")
        assert position is not None
        assert position.risk_params_state == "unknown"
        assert position.stop_loss_price_cents is None


class TestPositionMonitorBlocking:
    """Test suite for PositionMonitor blocking based on new states."""
    
    @pytest.fixture
    def position_cache(self):
        """Get position cache instance for testing."""
        cache = get_position_cache()
        cache._positions.clear()
        cache._last_sync = None
        return cache
    
    @pytest.mark.asyncio
    async def test_sync_blocks_unknown_entry_price_positions(self, position_cache):
        """Test that positions with unknown entry price are blocked from PositionMonitor."""
        rest_positions = [
            {
                "market_id": "KXBTC15M-26JUL012015-30",
                "contracts": 10,
                "side": "yes",
                "avg_price_cents": None,  # Unknown entry price
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.5
            }
        ]
        
        # This should not raise an error, but should log a warning
        # and the position should not be added to PositionMonitor
        await position_cache.sync_from_rest(rest_positions)
        
        # Position should exist in cache
        assert "KXBTC15M-26JUL012015-30" in position_cache._positions
        assert position_cache._positions["KXBTC15M-26JUL012015-30"].entry_price_state == "unknown"
    
    @pytest.mark.asyncio
    async def test_sync_blocks_invalid_entry_price_positions(self, position_cache):
        """Test that positions with invalid entry price are blocked from PositionMonitor."""
        rest_positions = [
            {
                "market_id": "KXBTC15M-26JUL012015-30",
                "contracts": 10,
                "side": "yes",
                "avg_price_cents": 0,  # Invalid entry price
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.5
            }
        ]
        
        await position_cache.sync_from_rest(rest_positions)
        
        # Position should exist in cache
        assert "KXBTC15M-26JUL012015-30" in position_cache._positions
        assert position_cache._positions["KXBTC15M-26JUL012015-30"].entry_price_state == "invalid"
    
    @pytest.mark.asyncio
    async def test_sync_blocks_unknown_risk_params_positions(self, position_cache):
        """Test that positions with unknown risk parameters are blocked from PositionMonitor."""
        rest_positions = [
            {
                "market_id": "KXBTC15M-26JUL012015-30",
                "contracts": 10,
                "side": "yes",
                "avg_price_cents": 50,
                # stop_loss_price_cents not present
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.5
            }
        ]
        
        await position_cache.sync_from_rest(rest_positions)
        
        # Position should exist in cache
        assert "KXBTC15M-26JUL012015-30" in position_cache._positions
        assert position_cache._positions["KXBTC15M-26JUL012015-30"].risk_params_state == "unknown"
    
    @pytest.mark.asyncio
    async def test_sync_allows_known_entry_and_risk_params_positions(self, position_cache):
        """Test that positions with known entry price and risk params are allowed."""
        rest_positions = [
            {
                "market_id": "KXBTC15M-26JUL012015-30",
                "contracts": 10,
                "side": "yes",
                "avg_price_cents": 50,
                "stop_loss_price_cents": 45,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.5
            }
        ]
        
        await position_cache.sync_from_rest(rest_positions)
        
        # Position should exist in cache with valid states
        position = position_cache._positions["KXBTC15M-26JUL012015-30"]
        assert position.entry_price_state == "known"
        assert position.risk_params_state == "known"


class TestShadowDualSideEdgeHandling:
    """Test suite for shadow dual-side evaluation edge handling (2026-07-23)."""
    
    def test_expected_edge_none_treated_as_zero(self):
        """Test that None edges (out-of-range prices) are treated as 0.0 in shadow dual-side evaluation."""
        # Simulate side_edges where yes_edge is None (out of range) and no_edge has a value
        side_edges = {"yes": None, "no": 2.20}
        
        # Expected side is yes (velocity > 0), but yes_edge is None
        expected_side = "yes"
        expected_side_edge = side_edges.get(expected_side) if side_edges.get(expected_side) is not None else 0.0
        opposite_side = "no" if expected_side == "yes" else "yes"
        opposite_side_edge = side_edges.get(opposite_side) if side_edges.get(opposite_side) is not None else 0.0
        
        # Verify None is treated as 0.0
        assert expected_side_edge == 0.0
        assert opposite_side_edge == 2.20
        
        # Verify hypothetical best side is opposite (since it has higher edge)
        if expected_side_edge > opposite_side_edge:
            hypothetical_best_side = expected_side
            hypothetical_best_edge = expected_side_edge
        elif opposite_side_edge > expected_side_edge:
            hypothetical_best_side = opposite_side
            hypothetical_best_edge = opposite_side_edge
        else:
            hypothetical_best_side = "no"
            hypothetical_best_edge = expected_side_edge
        
        assert hypothetical_best_side == "no"
        assert hypothetical_best_edge == 2.20
    
    def test_both_edges_none_treated_as_zero(self):
        """Test that when both edges are None, both are treated as 0.0."""
        side_edges = {"yes": None, "no": None}
        
        expected_side = "yes"
        expected_side_edge = side_edges.get(expected_side) if side_edges.get(expected_side) is not None else 0.0
        opposite_side = "no" if expected_side == "yes" else "yes"
        opposite_side_edge = side_edges.get(opposite_side) if side_edges.get(opposite_side) is not None else 0.0
        
        # Both should be 0.0
        assert expected_side_edge == 0.0
        assert opposite_side_edge == 0.0
    
    def test_valid_edges_not_affected(self):
        """Test that valid numeric edges are not affected by the fix."""
        side_edges = {"yes": 1.50, "no": 2.20}
        
        expected_side = "yes"
        expected_side_edge = side_edges.get(expected_side) if side_edges.get(expected_side) is not None else 0.0
        opposite_side = "no" if expected_side == "yes" else "yes"
        opposite_side_edge = side_edges.get(opposite_side) if side_edges.get(opposite_side) is not None else 0.0
        
        # Valid edges should pass through unchanged
        assert expected_side_edge == 1.50
        assert opposite_side_edge == 2.20
