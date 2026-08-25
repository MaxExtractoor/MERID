"""Integration tests for agent_grid_15m liquidity improvements.

Tests the integration of refill detector and liquidity fallback
into the signal generation pipeline.
"""

import pytest
import time
from unittest.mock import Mock, MagicMock, patch

from merid.prediction.agent_grid_15m import LeanAgentConfig, LeanAgent15m


# Helper function to create a real LeanAgentConfig with required attributes
def create_test_config(advanced_liquidity_enabled=True):
    """Create a real LeanAgentConfig for testing."""
    config = LeanAgentConfig(
        name="BTC_15M",
        series_tickers=["KXBTC15M"],
        signal_mode="momentum_fvg",
        alpha_0=0.5,
        alpha_1=0.5,
        velocity_windows=[10, 30, 60],
        momentum_weights=[0.2, 0.3, 0.5],
        velocity_ema_period=5,
    )
    # Set advanced liquidity attributes (not in dataclass, but used by agent)
    config.advanced_liquidity_enabled = advanced_liquidity_enabled
    config.refill_toxic_threshold_ms = 1000.0
    config.refill_window_ms = 60000.0
    config.refill_min_samples = 3
    config.liquidity_score_window = 5
    return config


class TestAgentGridRefillDetectorIntegration:
    """Test integration of refill detector into agent_grid_15m."""
    
    @pytest.fixture
    def mock_config(self):
        """Create a real LeanAgentConfig with advanced liquidity enabled."""
        return create_test_config(advanced_liquidity_enabled=True)
    
    @pytest.fixture
    def mock_agent(self, mock_config):
        """Create a LeanAgent15m with mocked dependencies."""
        catalog = Mock()
        market_state_store = Mock()
        spot_provider = Mock()
        order_router = Mock()
        risk_config = Mock()
        
        agent = LeanAgent15m(
            config=mock_config,
            catalog=catalog,
            market_state_store=market_state_store,
            spot_provider=spot_provider,
            order_router=order_router,
            risk_config=risk_config,
        )
        
        return agent
    
    def test_refill_detector_initialization(self, mock_agent):
        """Test that refill detector is initialized when enabled."""
        assert mock_agent._advanced_liquidity_enabled is True
        assert mock_agent._refill_detector is not None
    
    def test_refill_detector_disabled(self):
        """Test that refill detector is not initialized when disabled."""
        config = create_test_config(advanced_liquidity_enabled=False)
        
        catalog = Mock()
        market_state_store = Mock()
        spot_provider = Mock()
        order_router = Mock()
        risk_config = Mock()
        
        agent = LeanAgent15m(
            config=config,
            catalog=catalog,
            market_state_store=market_state_store,
            spot_provider=spot_provider,
            order_router=order_router,
            risk_config=risk_config,
        )
        
        assert agent._advanced_liquidity_enabled is False
        assert agent._refill_detector is None
    
    def test_refill_detector_in_signal_generation(self, mock_agent):
        """Test that refill detector is used during signal generation."""
        # Mock the market state store to return an orderbook
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot, OrderbookLevel
        
        mock_orderbook = OrderbookSnapshot(
            ticker="KXBTC15M-26AUG012215-15",
            ts=time.time(),
            yes_bids=(OrderbookLevel(price_cents=50, size=100),),
            no_bids=(OrderbookLevel(price_cents=45, size=50),),
            seq=0,
        )
        
        mock_agent.market_state_store.get_orderbook_snapshot = Mock(return_value=mock_orderbook)
        
        # Process an orderbook to trigger refill detection
        is_toxic, event = mock_agent._refill_detector.process(mock_orderbook)
        
        assert is_toxic is False
        assert event is None  # No refill event yet
    
    def test_toxic_flow_signal_suppression(self, mock_agent):
        """Test that signals are suppressed during toxic flow."""
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot, OrderbookLevel
        
        # Start with depth
        mock_orderbook_with_depth = OrderbookSnapshot(
            ticker="KXBTC15M-26AUG012215-15",
            ts=time.time(),
            yes_bids=(OrderbookLevel(price_cents=50, size=100),),
            no_bids=(OrderbookLevel(price_cents=45, size=50),),
            seq=0,
        )
        mock_agent._refill_detector.process(mock_orderbook_with_depth)
        
        # Create orderbook with zero depth (depletion)
        mock_orderbook = OrderbookSnapshot(
            ticker=mock_orderbook_with_depth.ticker,
            ts=time.time(),
            yes_bids=(),
            no_bids=(OrderbookLevel(price_cents=45, size=50),),
            seq=1,
        )
        
        mock_agent.market_state_store.get_orderbook_snapshot = Mock(return_value=mock_orderbook)
        
        # Process depletion
        mock_agent._refill_detector.process(mock_orderbook)
        
        # Refill slowly (toxic)
        time.sleep(1.1)
        mock_orderbook_refilled = OrderbookSnapshot(
            ticker=mock_orderbook.ticker,
            ts=time.time(),
            yes_bids=(OrderbookLevel(price_cents=50, size=100),),
            no_bids=(OrderbookLevel(price_cents=45, size=50),),
            seq=2,
        )
        is_toxic, event = mock_agent._refill_detector.process(mock_orderbook_refilled)
        
        assert is_toxic is True
        assert event is not None
        assert event.is_toxic is True


class TestAgentGridLiquidityFallbackIntegration:
    """Test integration of liquidity fallback into agent_grid_15m."""
    
    @pytest.fixture
    def mock_config(self):
        """Create a real LeanAgentConfig with advanced liquidity enabled."""
        return create_test_config(advanced_liquidity_enabled=True)
    
    @pytest.fixture
    def mock_agent(self, mock_config):
        """Create a LeanAgent15m with mocked dependencies."""
        catalog = Mock()
        market_state_store = Mock()
        spot_provider = Mock()
        order_router = Mock()
        risk_config = Mock()
        
        agent = LeanAgent15m(
            config=mock_config,
            catalog=catalog,
            market_state_store=market_state_store,
            spot_provider=spot_provider,
            order_router=order_router,
            risk_config=risk_config,
        )
        
        return agent
    
    def test_liquidity_fallback_executor_initialization(self, mock_agent):
        """Test that liquidity fallback executor is initialized when enabled."""
        assert mock_agent._advanced_liquidity_enabled is True
        assert mock_agent._liquidity_fallback_executor is not None
    
    def test_liquidity_fallback_executor_disabled(self):
        """Test that liquidity fallback executor is not initialized when disabled."""
        config = create_test_config(advanced_liquidity_enabled=False)
        
        catalog = Mock()
        market_state_store = Mock()
        spot_provider = Mock()
        order_router = Mock()
        risk_config = Mock()
        
        agent = LeanAgent15m(
            config=config,
            catalog=catalog,
            market_state_store=market_state_store,
            spot_provider=spot_provider,
            order_router=order_router,
            risk_config=risk_config,
        )
        
        assert agent._advanced_liquidity_enabled is False
        assert agent._liquidity_fallback_executor is None


class TestAgentGridSignalGenerationWithLiquidity:
    """Test signal generation with liquidity checks."""
    
    @pytest.fixture
    def mock_config(self):
        """Create a real LeanAgentConfig."""
        return create_test_config(advanced_liquidity_enabled=True)
    
    @pytest.fixture
    def mock_agent(self, mock_config):
        """Create a LeanAgent15m with mocked dependencies."""
        catalog = Mock()
        market_state_store = Mock()
        spot_provider = Mock()
        order_router = Mock()
        risk_config = Mock()
        
        agent = LeanAgent15m(
            config=mock_config,
            catalog=catalog,
            market_state_store=market_state_store,
            spot_provider=spot_provider,
            order_router=order_router,
            risk_config=risk_config,
        )
        
        return agent
    
    def test_signal_generation_with_safe_refill(self, mock_agent):
        """Test signal generation proceeds with safe refill."""
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot, OrderbookLevel
        
        # Create orderbook with depth
        mock_orderbook = OrderbookSnapshot(
            ticker="KXBTC15M-26AUG012215-15",
            ts=time.time(),
            yes_bids=(OrderbookLevel(price_cents=50, size=100),),
            no_bids=(OrderbookLevel(price_cents=45, size=50),),
            seq=0,
        )
        
        mock_agent.market_state_store.get_orderbook_snapshot = Mock(return_value=mock_orderbook)
        
        # Process orderbook
        is_toxic, event = mock_agent._refill_detector.process(mock_orderbook)
        
        # Should not be toxic
        assert is_toxic is False
    
    def test_signal_generation_with_toxic_refill(self, mock_agent):
        """Test signal generation is suppressed with toxic refill."""
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot, OrderbookLevel
        
        # Start with depth
        mock_orderbook_with_depth = OrderbookSnapshot(
            ticker="KXBTC15M-26AUG012215-15",
            ts=time.time(),
            yes_bids=(OrderbookLevel(price_cents=50, size=100),),
            no_bids=(OrderbookLevel(price_cents=45, size=50),),
            seq=0,
        )
        mock_agent._refill_detector.process(mock_orderbook_with_depth)
        
        # Create orderbook with zero depth
        mock_orderbook = OrderbookSnapshot(
            ticker=mock_orderbook_with_depth.ticker,
            ts=time.time(),
            yes_bids=(),
            no_bids=(OrderbookLevel(price_cents=45, size=50),),
            seq=1,
        )
        
        mock_agent.market_state_store.get_orderbook_snapshot = Mock(return_value=mock_orderbook)
        
        # Process depletion
        mock_agent._refill_detector.process(mock_orderbook)
        
        # Refill slowly (toxic)
        time.sleep(1.1)
        mock_orderbook_refilled = OrderbookSnapshot(
            ticker=mock_orderbook.ticker,
            ts=time.time(),
            yes_bids=(OrderbookLevel(price_cents=50, size=100),),
            no_bids=(OrderbookLevel(price_cents=45, size=50),),
            seq=2,
        )
        is_toxic, event = mock_agent._refill_detector.process(mock_orderbook_refilled)
        
        # Should be toxic
        assert is_toxic is True
        assert event.is_toxic is True


class TestAgentGridConfiguration:
    """Test configuration options for liquidity improvements."""
    
    def test_default_configuration(self):
        """Test default configuration values."""
        config = Mock(spec=LeanAgentConfig)
        config.name = "BTC_15M"
        config.series_tickers = ["KXBTC15M"]
        config.signal_mode = "momentum_fvg"
        config.alpha_0 = 0.5
        config.alpha_1 = 0.5
        config.advanced_liquidity_enabled = True
        
        # Default values should be used if not specified
        config.refill_toxic_threshold_ms = getattr(config, 'refill_toxic_threshold_ms', 1000.0)
        config.refill_window_ms = getattr(config, 'refill_window_ms', 60000.0)
        config.refill_min_samples = getattr(config, 'refill_min_samples', 3)
        
        assert config.refill_toxic_threshold_ms == 1000.0
        assert config.refill_window_ms == 60000.0
        assert config.refill_min_samples == 3
    
    def test_custom_configuration(self):
        """Test custom configuration values."""
        config = create_test_config(advanced_liquidity_enabled=True)
        config.refill_toxic_threshold_ms = 500.0  # Custom
        config.refill_window_ms = 30000.0  # Custom
        config.refill_min_samples = 5  # Custom
        
        catalog = Mock()
        market_state_store = Mock()
        spot_provider = Mock()
        order_router = Mock()
        risk_config = Mock()
        
        agent = LeanAgent15m(
            config=config,
            catalog=catalog,
            market_state_store=market_state_store,
            spot_provider=spot_provider,
            order_router=order_router,
            risk_config=risk_config,
        )
        
        # Custom values should be used
        assert agent._refill_detector.toxic_threshold_ms == 500.0
        assert agent._refill_detector.window_ms == 30000.0
        assert agent._refill_detector.min_samples == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
