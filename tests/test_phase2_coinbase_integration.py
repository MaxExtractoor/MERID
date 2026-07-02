"""
Test suite for Phase 2 Coinbase integration (2026-06-28).

Tests:
1. Coinbase WebSocket client initialization and configuration
2. Velocity calculation from spot price data
3. Signal generation from velocity thresholds
4. Integration with Kalshi trading signals
"""
import pytest
import asyncio
import time
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestCoinbaseWebSocketClient:
    """Test Coinbase WebSocket client."""
    
    def test_client_can_be_imported(self):
        """Test that Coinbase client can be imported."""
        try:
            from merid.event_venues.coinbase.ws_client import CoinbaseWebSocketClient
            assert CoinbaseWebSocketClient is not None
        except Exception as e:
            pytest.fail(f"Failed to import CoinbaseWebSocketClient: {e}")
    
    def test_client_initialization(self):
        """Test that client initializes with default assets."""
        from merid.event_venues.coinbase.ws_client import (
            CoinbaseWebSocketClient,
            CoinbaseAsset,
        )
        
        client = CoinbaseWebSocketClient()
        
        # Should have all 5 crypto assets by default
        assert len(client.assets) == 5
        assert CoinbaseAsset.BTC in client.assets
        assert CoinbaseAsset.ETH in client.assets
        assert CoinbaseAsset.SOL in client.assets
        assert CoinbaseAsset.XRP in client.assets
        assert CoinbaseAsset.DOGE in client.assets
    
    def test_client_custom_assets(self):
        """Test that client can be initialized with custom assets."""
        from merid.event_venues.coinbase.ws_client import (
            CoinbaseWebSocketClient,
            CoinbaseAsset,
        )
        
        client = CoinbaseWebSocketClient(assets=[CoinbaseAsset.BTC, CoinbaseAsset.ETH])
        
        assert len(client.assets) == 2
        assert CoinbaseAsset.BTC in client.assets
        assert CoinbaseAsset.ETH in client.assets
        assert CoinbaseAsset.SOL not in client.assets
    
    def test_velocity_thresholds_configured(self):
        """Test that velocity thresholds are configured per research."""
        from merid.event_venues.coinbase.velocity_signal import CoinbaseVelocitySignalGenerator
        
        generator = CoinbaseVelocitySignalGenerator()
        
        # Verify further lowered thresholds (0.0002-0.002 both worked per Turbine research)
        # Updated 2026-06-29: Reduced by 25% to capture more trades in calm market conditions
        assert generator.VELOCITY_THRESHOLDS["BTC-USD"] == 0.00015
        assert generator.VELOCITY_THRESHOLDS["ETH-USD"] == 0.00015
        assert generator.VELOCITY_THRESHOLDS["SOL-USD"] == 0.000225
        assert generator.VELOCITY_THRESHOLDS["XRP-USD"] == 0.000225
        assert generator.VELOCITY_THRESHOLDS["DOGE-USD"] == 0.0003
    
    def test_singleton_client(self):
        """Test that singleton client returns same instance."""
        from merid.event_venues.coinbase.ws_client import get_coinbase_client
        
        client1 = get_coinbase_client()
        client2 = get_coinbase_client()
        
        assert client1 is client2, "Singleton should return same instance"


class TestVelocityCalculation:
    """Test velocity calculation from spot price data."""
    
    def test_spot_price_dataclass(self):
        """Test SpotPrice dataclass."""
        from merid.event_venues.coinbase.ws_client import SpotPrice
        
        spot = SpotPrice(
            asset="BTC-USD",
            price=65000.0,
            timestamp=time.time(),
            sequence=12345,
        )
        
        assert spot.asset == "BTC-USD"
        assert spot.price == 65000.0
        assert spot.sequence == 12345
    
    def test_velocity_signal_dataclass(self):
        """Test VelocitySignal dataclass."""
        from merid.event_venues.coinbase.ws_client import VelocitySignal
        
        signal = VelocitySignal(
            asset="BTC-USD",
            velocity=0.001,
            window_seconds=60,
            timestamp=time.time(),
            signal_type="positive",
        )
        
        assert signal.asset == "BTC-USD"
        assert signal.velocity == 0.001
        assert signal.signal_type == "positive"
    
    def test_velocity_calculation_positive(self):
        """Test velocity calculation for positive price movement."""
        from merid.event_venues.coinbase.ws_client import SpotPrice
        
        # Create price history with upward movement
        now = time.time()
        price1 = SpotPrice(asset="BTC-USD", price=65000.0, timestamp=now - 60, sequence=1)
        price2 = SpotPrice(asset="BTC-USD", price=65100.0, timestamp=now, sequence=2)
        
        # Calculate velocity
        time_diff = price2.timestamp - price1.timestamp
        price_change = (price2.price - price1.price) / price1.price
        velocity = price_change / time_diff
        
        # Should be positive
        assert velocity > 0
        # 100/65000 = 0.001538 over 60 seconds = 0.0000256 per second
        expected_velocity = 0.001538 / 60
        assert abs(velocity - expected_velocity) < 0.000001
    
    def test_velocity_calculation_negative(self):
        """Test velocity calculation for negative price movement."""
        from merid.event_venues.coinbase.ws_client import SpotPrice
        
        # Create price history with downward movement
        now = time.time()
        price1 = SpotPrice(asset="BTC-USD", price=65100.0, timestamp=now - 60, sequence=1)
        price2 = SpotPrice(asset="BTC-USD", price=65000.0, timestamp=now, sequence=2)
        
        # Calculate velocity
        time_diff = price2.timestamp - price1.timestamp
        price_change = (price2.price - price1.price) / price1.price
        velocity = price_change / time_diff
        
        # Should be negative
        assert velocity < 0


class TestSignalGeneration:
    """Test signal generation from velocity."""
    
    def test_kalshi_trading_signal_dataclass(self):
        """Test KalshiTradingSignal dataclass."""
        from merid.event_venues.coinbase.velocity_signal import (
            KalshiTradingSignal,
            SignalSide,
        )
        
        signal = KalshiTradingSignal(
            asset="BTC-USD",
            side=SignalSide.BUY_YES,
            confidence=0.75,
            velocity=0.001,
            timestamp=time.time(),
        )
        
        assert signal.asset == "BTC-USD"
        assert signal.side == SignalSide.BUY_YES
        assert signal.confidence == 0.75
        assert signal.velocity == 0.001
    
    def test_signal_generator_initialization(self):
        """Test signal generator initialization."""
        from merid.event_venues.coinbase.velocity_signal import CoinbaseVelocitySignalGenerator
        
        generator = CoinbaseVelocitySignalGenerator()
        
        assert generator.client is not None
        assert generator._cooldown_seconds == 30
    
    def test_signal_threshold_buy_yes(self):
        """Test that positive velocity above threshold generates BUY YES signal."""
        from merid.event_venues.coinbase.velocity_signal import (
            CoinbaseVelocitySignalGenerator,
            SignalSide,
        )
        from merid.event_venues.coinbase.ws_client import VelocitySignal
        
        generator = CoinbaseVelocitySignalGenerator()
        
        # Create velocity signal above threshold
        velocity_signal = VelocitySignal(
            asset="BTC-USD",
            velocity=0.001,  # Above 0.0005 threshold
            window_seconds=60,
            timestamp=time.time(),
            signal_type="positive",
        )
        
        # Track generated signals
        generated_signals = []
        def on_signal(signal):
            generated_signals.append(signal)
        
        generator.on_signal = on_signal
        
        # Process velocity signal
        generator._on_velocity_signal(velocity_signal)
        
        # Should generate BUY YES signal
        assert len(generated_signals) == 1
        assert generated_signals[0].side == SignalSide.BUY_YES
        assert generated_signals[0].asset == "BTC-USD"
    
    def test_signal_threshold_buy_no(self):
        """Test that negative velocity below threshold generates BUY NO signal."""
        from merid.event_venues.coinbase.velocity_signal import (
            CoinbaseVelocitySignalGenerator,
            SignalSide,
        )
        from merid.event_venues.coinbase.ws_client import VelocitySignal
        
        generator = CoinbaseVelocitySignalGenerator()
        
        # Create velocity signal below negative threshold
        velocity_signal = VelocitySignal(
            asset="BTC-USD",
            velocity=-0.001,  # Below -0.0005 threshold
            window_seconds=60,
            timestamp=time.time(),
            signal_type="negative",
        )
        
        # Track generated signals
        generated_signals = []
        def on_signal(signal):
            generated_signals.append(signal)
        
        generator.on_signal = on_signal
        
        # Process velocity signal
        generator._on_velocity_signal(velocity_signal)
        
        # Should generate BUY NO signal
        assert len(generated_signals) == 1
        assert generated_signals[0].side == SignalSide.BUY_NO
        assert generated_signals[0].asset == "BTC-USD"
    
    def test_signal_threshold_no_trade(self):
        """Test that velocity within threshold generates no signal."""
        from merid.event_venues.coinbase.velocity_signal import CoinbaseVelocitySignalGenerator
        from merid.event_venues.coinbase.ws_client import VelocitySignal
        
        generator = CoinbaseVelocitySignalGenerator()
        
        # Create velocity signal within threshold (new threshold is 0.0002)
        velocity_signal = VelocitySignal(
            asset="BTC-USD",
            velocity=0.0001,  # Within ±0.0002 threshold (lowered from 0.0005)
            window_seconds=60,
            timestamp=time.time(),
            signal_type="positive",
        )
        
        # Track generated signals
        generated_signals = []
        def on_signal(signal):
            generated_signals.append(signal)
        
        generator.on_signal = on_signal
        
        # Process velocity signal
        generator._on_velocity_signal(velocity_signal)
        
        # Should not generate signal
        assert len(generated_signals) == 0
    
    def test_signal_cooldown(self):
        """Test that signals respect cooldown period."""
        from merid.event_venues.coinbase.velocity_signal import CoinbaseVelocitySignalGenerator
        from merid.event_venues.coinbase.ws_client import VelocitySignal
        
        generator = CoinbaseVelocitySignalGenerator()
        generator._cooldown_seconds = 1  # Short cooldown for testing
        
        # Create velocity signal above threshold
        velocity_signal = VelocitySignal(
            asset="BTC-USD",
            velocity=0.001,
            window_seconds=60,
            timestamp=time.time(),
            signal_type="positive",
        )
        
        # Track generated signals
        generated_signals = []
        def on_signal(signal):
            generated_signals.append(signal)
        
        generator.on_signal = on_signal
        
        # Process first signal
        generator._on_velocity_signal(velocity_signal)
        assert len(generated_signals) == 1
        
        # Process second signal immediately (should be blocked by cooldown)
        generator._on_velocity_signal(velocity_signal)
        assert len(generated_signals) == 1  # Still only 1 signal
    
    def test_singleton_signal_generator(self):
        """Test that singleton signal generator returns same instance."""
        from merid.event_venues.coinbase.velocity_signal import get_velocity_signal_generator
        
        gen1 = get_velocity_signal_generator()
        gen2 = get_velocity_signal_generator()
        
        assert gen1 is gen2, "Singleton should return same instance"


class TestModuleStructure:
    """Test that Coinbase module structure is correct."""
    
    def test_coinbase_module_exists(self):
        """Test that Coinbase module directory exists."""
        coinbase_dir = Path(__file__).parent.parent / "merid" / "event_venues" / "coinbase"
        assert coinbase_dir.exists(), "Coinbase module directory should exist"
    
    def test_coinbase_init_exists(self):
        """Test that Coinbase __init__.py exists."""
        init_file = Path(__file__).parent.parent / "merid" / "event_venues" / "coinbase" / "__init__.py"
        assert init_file.exists(), "Coinbase __init__.py should exist"
    
    def test_ws_client_exists(self):
        """Test that ws_client.py exists."""
        ws_client_file = Path(__file__).parent.parent / "merid" / "event_venues" / "coinbase" / "ws_client.py"
        assert ws_client_file.exists(), "ws_client.py should exist"
    
    def test_velocity_signal_exists(self):
        """Test that velocity_signal.py exists."""
        velocity_signal_file = Path(__file__).parent.parent / "merid" / "event_venues" / "coinbase" / "velocity_signal.py"
        assert velocity_signal_file.exists(), "velocity_signal.py should exist"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
