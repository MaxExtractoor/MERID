"""
Tests for signal generation filters (ADX, volume, multi-timeframe alignment).
"""

import pytest
import collections
from merid.prediction.agent_grid_15m import LeanAgent15m, LeanAgentConfig


class TestADXFilter:
    """Test suite for ADX > 25 regime filter."""
    
    @pytest.fixture
    def agent_config(self):
        """Create a test agent configuration."""
        return LeanAgentConfig(
            name="BTC_15M",
            series_tickers=["KXBTC15M"],
            signal_mode="trend",
            velocity_threshold=0.0002,
            regime_detector_enabled=False  # Disable for simpler testing
        )
    
    @pytest.fixture
    def mock_agent(self, agent_config):
        """Create a mock agent for testing."""
        # Create minimal mock dependencies
        from unittest.mock import MagicMock
        
        agent = LeanAgent15m(
            config=agent_config,
            catalog=MagicMock(),
            market_state_store=MagicMock(),
            spot_provider=MagicMock(),
            order_router=MagicMock(),
            risk_config=MagicMock()
        )
        return agent
    
    def test_adx_calculation_with_sufficient_history(self, mock_agent):
        """Test ADX calculation with sufficient price history."""
        asset = "BTC"
        
        # Populate ADX history with trending data (ADX > 25)
        # Simulate 14 periods of True Range and Directional Movement
        # Note: _adx_history stores tuples (timestamp, dx_value)
        for i in range(20):
            mock_agent._adx_history[asset].append((i * 1000, 30.0 + i))  # ADX values > 25
            mock_agent._tr_history[asset].append((i * 1000, 0.01))
            mock_agent._plus_dm_history[asset].append((i * 1000, 0.005))
            mock_agent._minus_dm_history[asset].append((i * 1000, 0.001))
        
        adx = mock_agent._calculate_adx(asset)
        
        # ADX should be > 25 for trending market
        assert adx > 25.0
    
    def test_adx_calculation_with_insufficient_history(self, mock_agent):
        """Test ADX calculation with insufficient history."""
        asset = "BTC"
        
        # Populate with insufficient data
        for i in range(5):
            mock_agent._adx_history[asset].append((i * 1000, 10.0))
        
        adx = mock_agent._calculate_adx(asset)
        
        # Should return 0.0 during warmup
        assert adx == 0.0
    
    def test_adx_filter_passes_strong_trend(self, mock_agent):
        """Test that ADX filter passes strong trending markets."""
        asset = "BTC"
        
        # Populate with strong trend data (ADX > 25)
        for i in range(20):
            mock_agent._adx_history[asset].append((i * 1000, 30.0 + i))
        
        adx = mock_agent._calculate_adx(asset)
        
        # Should pass filter (ADX >= 25)
        assert adx >= 25.0
    
    def test_adx_filter_blocks_weak_trend(self, mock_agent):
        """Test that ADX filter blocks weak trending markets."""
        asset = "BTC"
        
        # Populate with weak trend data (ADX < 25)
        for i in range(20):
            mock_agent._adx_history[asset].append((i * 1000, 15.0 + i * 0.5))
        
        adx = mock_agent._calculate_adx(asset)
        
        # Should be blocked (ADX < 25)
        assert adx < 25.0


class TestVolumeConfirmation:
    """Test suite for volume confirmation filter."""
    
    @pytest.fixture
    def agent_config(self):
        """Create a test agent configuration."""
        return LeanAgentConfig(
            name="BTC_15M",
            series_tickers=["KXBTC15M"],
            signal_mode="trend",
            velocity_threshold=0.0002,
            regime_detector_enabled=False
        )
    
    @pytest.fixture
    def mock_agent(self, agent_config):
        """Create a mock agent for testing."""
        from unittest.mock import MagicMock
        
        agent = LeanAgent15m(
            config=agent_config,
            catalog=MagicMock(),
            market_state_store=MagicMock(),
            spot_provider=MagicMock(),
            order_router=MagicMock(),
            risk_config=MagicMock()
        )
        return agent
    
    def test_volume_confirmation_with_high_volume(self, mock_agent):
        """Test volume confirmation passes with high volume."""
        asset = "BTC"
        
        # Populate with high volume data (above EMA20 threshold)
        base_volume = 1000.0
        for i in range(25):
            # Gradually increasing volume, ending above 1.2x EMA20
            volume = base_volume + i * 50
            mock_agent._volume_history[asset].append((i * 1000, volume))
        
        confirmed = mock_agent._check_volume_confirmation(asset)
        
        # Should pass (volume > 1.2x EMA20)
        assert confirmed is True
    
    def test_volume_confirmation_with_low_volume(self, mock_agent):
        """Test volume confirmation fails with low volume."""
        asset = "BTC"
        
        # Populate with low volume data (below EMA20 threshold)
        base_volume = 1000.0
        for i in range(25):
            # Decreasing volume, ending below 1.2x EMA20
            volume = base_volume - i * 30
            mock_agent._volume_history[asset].append((i * 1000, max(volume, 100.0)))
        
        confirmed = mock_agent._check_volume_confirmation(asset)
        
        # Should fail (volume < 1.2x EMA20)
        assert confirmed is False
    
    def test_volume_confirmation_bypasses_warmup(self, mock_agent):
        """Test volume confirmation bypasses during warmup."""
        asset = "BTC"
        
        # Insufficient history
        for i in range(5):
            mock_agent._volume_history[asset].append((i * 1000, 100.0))
        
        confirmed = mock_agent._check_volume_confirmation(asset)
        
        # Should bypass during warmup
        assert confirmed is True
    
    def test_volume_extraction_from_spot_data(self, mock_agent):
        """Test volume extraction from spot data with volume field."""
        from data.unified_spot_service import SpotPrice
        import time
        
        asset = "BTC"
        spot_price = 67000.0
        
        # Create SpotPrice with volume data
        spot_data = SpotPrice(
            price=spot_price,
            timestamp=int(time.time() * 1000),
            source="coinbase_public",
            confidence=1.0,
            open=67000.0,
            high=67050.0,
            low=66950.0,
            volume=12345.67  # Volume for volume confirmation filter
        )
        
        # Call _update_price_history which extracts volume
        mock_agent._update_price_history(asset, spot_price, spot_data)
        
        # Verify volume was extracted and stored
        assert len(mock_agent._volume_history[asset]) > 0
        last_volume = mock_agent._volume_history[asset][-1][1]
        assert last_volume == 12345.67
    
    def test_volume_extraction_without_volume_field(self, mock_agent):
        """Test volume extraction defaults to 1.0 when volume field is None."""
        from data.unified_spot_service import SpotPrice
        import time
        
        asset = "BTC"
        spot_price = 67000.0
        
        # Create SpotPrice without volume data (None)
        spot_data = SpotPrice(
            price=spot_price,
            timestamp=int(time.time() * 1000),
            source="coinbase_public",
            confidence=1.0,
            open=67000.0,
            high=67050.0,
            low=66950.0,
            volume=None  # No volume data
        )
        
        # Call _update_price_history which extracts volume
        mock_agent._update_price_history(asset, spot_price, spot_data)
        
        # Verify volume defaults to 1.0 when not available
        assert len(mock_agent._volume_history[asset]) > 0
        last_volume = mock_agent._volume_history[asset][-1][1]
        assert last_volume == 1.0


class TestMultiTimeframeAlignment:
    """Test suite for multi-timeframe alignment filter."""
    
    @pytest.fixture
    def agent_config(self):
        """Create a test agent configuration."""
        return LeanAgentConfig(
            name="BTC_15M",
            series_tickers=["KXBTC15M"],
            signal_mode="trend",
            velocity_threshold=0.0002,
            regime_detector_enabled=False
        )
    
    @pytest.fixture
    def mock_agent(self, agent_config):
        """Create a mock agent for testing."""
        from unittest.mock import MagicMock
        
        agent = LeanAgent15m(
            config=agent_config,
            catalog=MagicMock(),
            market_state_store=MagicMock(),
            spot_provider=MagicMock(),
            order_router=MagicMock(),
            risk_config=MagicMock()
        )
        return agent
    
    def test_mtf_alignment_with_aligned_positive_momentum(self, mock_agent):
        """Test MTF alignment passes with aligned positive momentum."""
        asset = "BTC"
        
        # Populate 1m history with positive momentum
        base_price = 50000.0
        for i in range(15):
            price = base_price + i * 10  # Increasing prices
            mock_agent._price_1m_history[asset].append((i * 1000, price))
        
        # Populate 5m history with positive momentum
        for i in range(15):
            price = base_price + i * 10  # Increasing prices
            mock_agent._price_5m_history[asset].append((i * 1000, price))
        
        aligned = mock_agent._check_multi_timeframe_alignment(asset)
        
        # Should pass (both timeframes showing positive momentum)
        assert aligned is True
    
    def test_mtf_alignment_with_aligned_negative_momentum(self, mock_agent):
        """Test MTF alignment passes with aligned negative momentum."""
        asset = "BTC"
        
        # Populate 1m history with negative momentum
        base_price = 50000.0
        for i in range(15):
            price = base_price - i * 10  # Decreasing prices
            mock_agent._price_1m_history[asset].append((i * 1000, price))
        
        # Populate 5m history with negative momentum
        for i in range(15):
            price = base_price - i * 10  # Decreasing prices
            mock_agent._price_5m_history[asset].append((i * 1000, price))
        
        aligned = mock_agent._check_multi_timeframe_alignment(asset)
        
        # Should pass (both timeframes showing negative momentum)
        assert aligned is True
    
    def test_mtf_alignment_with_conflicting_momentum(self, mock_agent):
        """Test MTF alignment fails with conflicting momentum."""
        asset = "BTC"
        
        # Populate 1m history with positive momentum
        base_price = 50000.0
        for i in range(15):
            price = base_price + i * 10  # Increasing prices
            mock_agent._price_1m_history[asset].append((i * 1000, price))
        
        # Populate 5m history with negative momentum
        for i in range(15):
            price = base_price - i * 10  # Decreasing prices
            mock_agent._price_5m_history[asset].append((i * 1000, price))
        
        aligned = mock_agent._check_multi_timeframe_alignment(asset)
        
        # Should fail (conflicting momentum)
        assert aligned is False
    
    def test_mtf_alignment_bypasses_warmup(self, mock_agent):
        """Test MTF alignment bypasses during warmup."""
        asset = "BTC"
        
        # Insufficient history
        for i in range(5):
            mock_agent._price_1m_history[asset].append((i * 1000, 50000.0))
            mock_agent._price_5m_history[asset].append((i * 1000, 50000.0))
        
        aligned = mock_agent._check_multi_timeframe_alignment(asset)
        
        # Should bypass during warmup
        assert aligned is True
