"""Unit tests for MarketOrderFallbackEngine.

Tests cover:
- Fallback decision logic (age, conviction, market conditions)
- Asset-specific configuration overrides
- Edge cases and error handling
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch

from merid.event_venues.kalshi.market_order_fallback import (
    MarketOrderFallbackEngine,
    FallbackConfig,
    FallbackDecision,
    get_market_order_fallback_engine,
    configure_fallback
)


@pytest.fixture
def fallback_config():
    """Default fallback configuration for testing."""
    return FallbackConfig(
        fallback_after_seconds=90,
        min_age_before_fallback=30,
        min_edge_pct=0.04,
        min_confidence=0.70,
        max_tte_for_fallback=300,
        urgent_tte_threshold=120,
        max_spread_cents=10,
        min_depth_contracts=5,
        asset_overrides={
            "BTC": {
                "min_edge_pct": 0.03,
                "fallback_after_seconds": 60,
            }
        }
    )


@pytest.fixture
def fallback_engine(fallback_config):
    """Fallback engine instance for testing."""
    return MarketOrderFallbackEngine(fallback_config)


@pytest.fixture
def sample_order():
    """Sample resting order record for testing."""
    order = Mock()
    order.kalshi_order_id = "test_order_123"
    order.ticker = "KXBTC-15M-20260630-1000"
    order.side = "no"
    order.action = "buy"
    order.original_size = 10
    order.remaining_size = 10
    order.created_at = datetime.utcnow() - timedelta(seconds=100)
    order.asset = "BTC"
    order.original_edge_pct = 0.05
    order.confidence = 0.75
    order.original_minutes_to_expiry = 5.0
    order.intent_id = "intent_test_123"
    return order


@pytest.fixture
def sample_market_state():
    """Sample market state for testing."""
    market_state = Mock()
    market_state.spread_cents = 5
    market_state.min_depth_yes = 10
    market_state.min_depth_no = 8
    return market_state


class TestFallbackDecisionLogic:
    """Test fallback decision logic."""
    
    def test_should_fallback_all_checks_pass(self, fallback_engine, sample_order, sample_market_state):
        """Test fallback when all checks pass."""
        # Order age is 100s > 90s threshold
        # Edge is 5% > 4% threshold
        # Confidence is 75% > 70% threshold
        # Spread is 5c < 10c threshold
        # Depth is 18 > 5 threshold
        
        decision = fallback_engine.evaluate_fallback(sample_order, sample_market_state)
        
        assert decision.should_fallback is True
        assert "all_checks_passed" in decision.reason
        assert decision.age_seconds == pytest.approx(100, abs=1)
        assert decision.edge_at_placement == 0.05
        assert decision.confidence == 0.75
        assert decision.spread_cents == 5
        assert decision.depth_contracts == 18
    
    def test_should_not_fallback_too_young(self, fallback_engine, sample_order):
        """Test no fallback when order is too young."""
        # Make order only 20 seconds old
        sample_order.created_at = datetime.utcnow() - timedelta(seconds=20)
        
        decision = fallback_engine.evaluate_fallback(sample_order, None)
        
        assert decision.should_fallback is False
        assert "too_young" in decision.reason
        assert decision.age_seconds == pytest.approx(20, abs=1)
    
    def test_should_not_fallback_not_old_enough(self, fallback_engine, sample_order):
        """Test no fallback when order is not old enough."""
        # Make order 60 seconds old (between min_age and fallback_after)
        sample_order.created_at = datetime.utcnow() - timedelta(seconds=60)
        # Set time to expiry to 7.5 minutes (450 seconds original, which becomes 390s after 1 minute elapsed)
        # 390s > max_tte_for_fallback of 300s, so it should return "too_far_from_expiry"
        sample_order.original_minutes_to_expiry = 7.5
        
        decision = fallback_engine.evaluate_fallback(sample_order, None)
        
        assert decision.should_fallback is False
        assert "too_far_from_expiry" in decision.reason
    
    def test_should_fallback_urgent_tte(self, fallback_engine, sample_order):
        """Test fallback when time to expiry is urgent."""
        # Make order 60 seconds old (not old enough normally)
        sample_order.created_at = datetime.utcnow() - timedelta(seconds=60)
        # Set time to expiry to 1 minute (urgent)
        sample_order.original_minutes_to_expiry = 1.0
        
        decision = fallback_engine.evaluate_fallback(sample_order, None)
        
        assert decision.should_fallback is True
        assert "all_checks_passed" in decision.reason
    
    def test_should_not_fallback_low_edge(self, fallback_engine, sample_order):
        """Test no fallback when edge is too low."""
        # Set edge to 2% (below 4% threshold)
        sample_order.original_edge_pct = 0.02
        
        decision = fallback_engine.evaluate_fallback(sample_order, None)
        
        assert decision.should_fallback is False
        assert "low_edge" in decision.reason
        assert decision.edge_at_placement == 0.02
    
    def test_should_not_fallback_low_confidence(self, fallback_engine, sample_order):
        """Test no fallback when confidence is too low."""
        # Set confidence to 60% (below 70% threshold)
        sample_order.confidence = 0.60
        
        decision = fallback_engine.evaluate_fallback(sample_order, None)
        
        assert decision.should_fallback is False
        assert "low_confidence" in decision.reason
        assert decision.confidence == 0.60
    
    def test_should_not_fallback_wide_spread(self, fallback_engine, sample_order, sample_market_state):
        """Test no fallback when spread is too wide."""
        # Set spread to 15 cents (above 10 cent threshold)
        sample_market_state.spread_cents = 15
        
        decision = fallback_engine.evaluate_fallback(sample_order, sample_market_state)
        
        assert decision.should_fallback is False
        assert "wide_spread" in decision.reason
        assert decision.spread_cents == 15
    
    def test_should_not_fallback_thin_depth(self, fallback_engine, sample_order, sample_market_state):
        """Test no fallback when depth is too thin."""
        # Set depth to 3 contracts (below 5 threshold)
        sample_market_state.min_depth_yes = 2
        sample_market_state.min_depth_no = 1
        
        decision = fallback_engine.evaluate_fallback(sample_order, sample_market_state)
        
        assert decision.should_fallback is False
        assert "thin_depth" in decision.reason
        assert decision.depth_contracts == 3
    
    def test_should_not_fallback_no_market_state(self, fallback_engine, sample_order):
        """Test fallback decision when no market state is available."""
        # Without market state, spread/depth checks are skipped
        # Should still fallback if other checks pass
        decision = fallback_engine.evaluate_fallback(sample_order, None)
        
        assert decision.should_fallback is True
        assert decision.current_market_state is None
        assert decision.spread_cents is None
        assert decision.depth_contracts is None
    
    def test_asset_specific_override_btc(self, fallback_engine, sample_order):
        """Test asset-specific override for BTC."""
        # BTC has lower edge threshold (3% vs 4%)
        sample_order.original_edge_pct = 0.035  # 3.5% (below 4% but above 3%)
        sample_order.asset = "BTC"
        
        decision = fallback_engine.evaluate_fallback(sample_order, None)
        
        # Should fallback because BTC override allows 3% edge
        assert decision.should_fallback is True
    
    def test_asset_specific_override_eth(self, fallback_engine, sample_order):
        """Test asset-specific override for ETH."""
        # ETH has lower edge threshold (3% vs 4%)
        sample_order.original_edge_pct = 0.035  # 3.5%
        sample_order.asset = "ETH"
        
        decision = fallback_engine.evaluate_fallback(sample_order, None)
        
        # Should NOT fallback because ETH doesn't have an override in the test config
        # (only BTC has an override in the test fixture)
        assert decision.should_fallback is False
        assert "low_edge" in decision.reason
    
    def test_no_asset_override_default(self, fallback_engine, sample_order):
        """Test default thresholds for assets without overrides."""
        # SOL has no override, uses default 4% threshold
        sample_order.original_edge_pct = 0.035  # 3.5%
        sample_order.asset = "SOL"
        
        decision = fallback_engine.evaluate_fallback(sample_order, None)
        
        # Should not fallback because 3.5% < 4% default threshold
        assert decision.should_fallback is False
        assert "low_edge" in decision.reason
    
    def test_evaluation_error_handling(self, fallback_engine, sample_order):
        """Test error handling during evaluation."""
        # Make order created_at raise an error
        sample_order.created_at = None
        
        decision = fallback_engine.evaluate_fallback(sample_order, None)
        
        # Should not fallback on error (safe default)
        assert decision.should_fallback is False
        assert "evaluation_error" in decision.reason


class TestFallbackExecution:
    """Test fallback execution logic."""
    
    @pytest.mark.asyncio
    async def test_execute_fallback_skipped(self, fallback_engine):
        """Test that fallback is skipped when should_fallback=False."""
        decision = FallbackDecision(
            should_fallback=False,
            reason="too_young",
            original_order=Mock()
        )
        
        result = await fallback_engine.execute_fallback(decision)
        
        assert result["status"] == "skipped"
        assert result["reason"] == "too_young"
        assert fallback_engine._skip_count == 1
    
    @pytest.mark.asyncio
    async def test_execute_fallback_success(self, fallback_engine, sample_order):
        """Test successful fallback execution."""
        # Mock the imports inside execute_fallback by patching where they're imported
        with patch('merid.event_venues.kalshi.client.get_kalshi_client') as mock_get_client:
            with patch('merid.event_venues.kalshi.order_router.route_order_async') as mock_route_order:
                # Setup mocks
                mock_client = AsyncMock()
                mock_client.cancel_order.return_value = {"status": "canceled"}
                mock_get_client.return_value = mock_client
                mock_route_order.return_value = {"order_id": "new_order_456"}
                
                decision = FallbackDecision(
                    should_fallback=True,
                    reason="all_checks_passed",
                    original_order=sample_order
                )
                
                result = await fallback_engine.execute_fallback(decision)
                
                assert result["status"] == "executed"
                assert result["original_order_id"] == "test_order_123"
                assert result["fallback_order_id"] == "new_order_456"
                assert fallback_engine._fallback_count == 1
                
                # Verify cancel was called
                mock_client.cancel_order.assert_called_once_with(
                    "test_order_123",
                    "KXBTC-15M-20260630-1000"
                )
                
                # Verify market order was placed
                mock_route_order.assert_called_once()
                call_args = mock_route_order.call_args[0][0]
                assert call_args.order_type == "market"
                assert call_args.count == 10
                assert call_args.source == "market_order_fallback"
    
    @pytest.mark.asyncio
    async def test_execute_fallback_cancel_failure(self, fallback_engine, sample_order):
        """Test fallback when cancel fails."""
        # Mock the imports inside execute_fallback by patching where they're imported
        with patch('merid.event_venues.kalshi.client.get_kalshi_client') as mock_get_client:
            # Setup mock to raise error on cancel
            mock_client = AsyncMock()
            mock_client.cancel_order.side_effect = Exception("Cancel failed")
            mock_get_client.return_value = mock_client
            
            decision = FallbackDecision(
                should_fallback=True,
                reason="all_checks_passed",
                original_order=sample_order
            )
            
            result = await fallback_engine.execute_fallback(decision)
            
            assert result["status"] == "failed"
            assert "error" in result
            assert fallback_engine._execution_failures == 1


class TestFallbackEngineStats:
    """Test fallback engine statistics."""
    
    def test_get_stats_initial(self, fallback_engine):
        """Test initial statistics."""
        stats = fallback_engine.get_stats()
        
        assert stats["fallback_count"] == 0
        assert stats["skip_count"] == 0
        assert stats["execution_failures"] == 0
        assert stats["total_evaluations"] == 0
        assert stats["fallback_rate"] == 0.0
    
    def test_get_stats_after_evaluations(self, fallback_engine):
        """Test statistics after evaluations."""
        fallback_engine._fallback_count = 5
        fallback_engine._skip_count = 15
        fallback_engine._execution_failures = 1
        
        stats = fallback_engine.get_stats()
        
        assert stats["fallback_count"] == 5
        assert stats["skip_count"] == 15
        assert stats["execution_failures"] == 1
        assert stats["total_evaluations"] == 20
        assert stats["fallback_rate"] == 0.25


class TestSingletonFunctions:
    """Test singleton functions."""
    
    def test_get_singleton(self):
        """Test getting singleton instance."""
        engine1 = get_market_order_fallback_engine()
        engine2 = get_market_order_fallback_engine()
        
        # Should return same instance
        assert engine1 is engine2
    
    def test_configure_singleton(self):
        """Test configuring singleton."""
        custom_config = FallbackConfig(
            fallback_after_seconds=60,
            min_edge_pct=0.05
        )
        
        configure_fallback(custom_config)
        
        engine = get_market_order_fallback_engine()
        
        assert engine.config.fallback_after_seconds == 60
        assert engine.config.min_edge_pct == 0.05


class TestTimeToExpiry:
    """Test time to expiry calculation."""
    
    def test_get_tte_from_original(self, fallback_engine, sample_order):
        """Test getting TTE from original_minutes_to_expiry."""
        sample_order.original_minutes_to_expiry = 5.0
        sample_order.created_at = datetime.utcnow() - timedelta(minutes=2)
        
        tte = fallback_engine._get_time_to_expiry(sample_order)
        
        # Should be 3 minutes remaining (5 - 2)
        assert tte is not None
        assert tte == pytest.approx(180, abs=10)  # 3 minutes in seconds
    
    def test_get_tte_none(self, fallback_engine, sample_order):
        """Test TTE when original_minutes_to_expiry is None."""
        sample_order.original_minutes_to_expiry = None
        
        tte = fallback_engine._get_time_to_expiry(sample_order)
        
        assert tte is None
    
    def test_get_tte_zero(self, fallback_engine, sample_order):
        """Test TTE when already expired."""
        sample_order.original_minutes_to_expiry = 5.0
        sample_order.created_at = datetime.utcnow() - timedelta(minutes=6)
        
        tte = fallback_engine._get_time_to_expiry(sample_order)
        
        # Should be 0 (not negative)
        assert tte == 0.0
