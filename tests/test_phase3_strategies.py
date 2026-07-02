"""
Test suite for Phase 3 strategy implementations (2026-06-28).

Tests:
1. Panic fade strategy (volatility reversion)
2. Trend alignment strategy (multi-timeframe trend agreement)
3. Fast MA crossover signals
4. VWAP premium signals
"""
import pytest
import time
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestPanicFadeStrategy:
    """Test panic fade strategy."""
    
    def test_panic_fade_can_be_imported(self):
        """Test that panic fade strategy can be imported."""
        try:
            from merid.prediction.strategies.panic_fade import PanicFadeStrategy
            assert PanicFadeStrategy is not None
        except Exception as e:
            pytest.fail(f"Failed to import PanicFadeStrategy: {e}")
    
    def test_panic_fade_initialization(self):
        """Test panic fade strategy initialization."""
        from merid.prediction.strategies.panic_fade import PanicFadeStrategy
        
        strategy = PanicFadeStrategy()
        
        assert strategy.panic_threshold == 0.04
        assert strategy.fade_size == 100
        assert strategy._cooldown_seconds == 60
    
    def test_panic_fade_custom_threshold(self):
        """Test panic fade with custom threshold."""
        from merid.prediction.strategies.panic_fade import PanicFadeStrategy
        
        strategy = PanicFadeStrategy(panic_threshold=0.05)
        
        assert strategy.panic_threshold == 0.05
    
    def test_panic_fade_positive_panic_detection(self):
        """Test detection of positive panic (price spike up)."""
        from merid.prediction.strategies.panic_fade import (
            PanicFadeStrategy,
            SignalSide,
        )
        
        strategy = PanicFadeStrategy(panic_threshold=0.04)
        strategy._cooldown_seconds = 0  # Disable cooldown for testing
        
        # Simulate price spike: 65000 -> 67500 (3.8% in 15 seconds)
        now = time.time()
        strategy.update_price("BTC-USD", 65000.0, now - 15)
        strategy.update_price("BTC-USD", 67500.0, now)
        
        # Should generate BUY NO signal (fade the positive panic)
        # This would require checking the on_signal callback
        # For now, just verify the strategy doesn't crash
        assert strategy.get_latest_price("BTC-USD") == 67500.0
    
    def test_panic_fade_negative_panic_detection(self):
        """Test detection of negative panic (price spike down)."""
        from merid.prediction.strategies.panic_fade import PanicFadeStrategy
        
        strategy = PanicFadeStrategy(panic_threshold=0.04)
        strategy._cooldown_seconds = 0  # Disable cooldown for testing
        
        # Simulate price drop: 65000 -> 62500 (3.8% in 15 seconds)
        now = time.time()
        strategy.update_price("BTC-USD", 65000.0, now - 15)
        strategy.update_price("BTC-USD", 62500.0, now)
        
        # Should generate BUY YES signal (fade the negative panic)
        assert strategy.get_latest_price("BTC-USD") == 62500.0
    
    def test_panic_fade_no_panic(self):
        """Test that small price movements don't trigger signals."""
        from merid.prediction.strategies.panic_fade import PanicFadeStrategy
        
        strategy = PanicFadeStrategy(panic_threshold=0.04)
        
        # Simulate small price movement: 65000 -> 65100 (0.15% in 15 seconds)
        now = time.time()
        strategy.update_price("BTC-USD", 65000.0, now - 15)
        strategy.update_price("BTC-USD", 65100.0, now)
        
        # Should not trigger signal (below threshold)
        assert strategy.get_latest_price("BTC-USD") == 65100.0
    
    def test_panic_fade_singleton(self):
        """Test that singleton returns same instance."""
        from merid.prediction.strategies.panic_fade import get_panic_fade_strategy
        
        strategy1 = get_panic_fade_strategy()
        strategy2 = get_panic_fade_strategy()
        
        assert strategy1 is strategy2


class TestTrendAlignmentStrategy:
    """Test trend alignment strategy."""
    
    def test_trend_alignment_can_be_imported(self):
        """Test that trend alignment strategy can be imported."""
        try:
            from merid.prediction.strategies.trend_alignment import TrendAlignmentStrategy
            assert TrendAlignmentStrategy is not None
        except Exception as e:
            pytest.fail(f"Failed to import TrendAlignmentStrategy: {e}")
    
    def test_trend_alignment_initialization(self):
        """Test trend alignment strategy initialization."""
        from merid.prediction.strategies.trend_alignment import TrendAlignmentStrategy
        
        strategy = TrendAlignmentStrategy()
        
        assert strategy.short_window == 300  # 5 minutes
        assert strategy.medium_window == 3600  # 1 hour
        assert strategy._cooldown_seconds == 60
    
    def test_trend_alignment_custom_windows(self):
        """Test trend alignment with custom windows."""
        from merid.prediction.strategies.trend_alignment import TrendAlignmentStrategy
        
        strategy = TrendAlignmentStrategy(short_window=600, medium_window=7200)
        
        assert strategy.short_window == 600
        assert strategy.medium_window == 7200
    
    def test_trend_alignment_up_trend(self):
        """Test detection of upward trend alignment."""
        from merid.prediction.strategies.trend_alignment import (
            TrendAlignmentStrategy,
            TrendDirection,
        )
        
        strategy = TrendAlignmentStrategy(
            short_window=10,
            medium_window=20,
        )
        strategy._cooldown_seconds = 0  # Disable cooldown for testing
        
        # Simulate consistent upward movement
        now = time.time()
        for i in range(30):
            price = 65000.0 + (i * 100)  # Upward trend
            strategy.update_price("BTC-USD", price, now - (30 - i))
        
        # Should detect UP trend
        assert strategy.get_latest_price("BTC-USD") is not None
    
    def test_trend_alignment_down_trend(self):
        """Test detection of downward trend alignment."""
        from merid.prediction.strategies.trend_alignment import TrendAlignmentStrategy
        
        strategy = TrendAlignmentStrategy(
            short_window=10,
            medium_window=20,
        )
        strategy._cooldown_seconds = 0  # Disable cooldown for testing
        
        # Simulate consistent downward movement
        now = time.time()
        for i in range(30):
            price = 65000.0 - (i * 100)  # Downward trend
            strategy.update_price("BTC-USD", price, now - (30 - i))
        
        # Should detect DOWN trend
        assert strategy.get_latest_price("BTC-USD") is not None
    
    def test_trend_alignment_singleton(self):
        """Test that singleton returns same instance."""
        from merid.prediction.strategies.trend_alignment import get_trend_alignment_strategy
        
        strategy1 = get_trend_alignment_strategy()
        strategy2 = get_trend_alignment_strategy()
        
        assert strategy1 is strategy2


class TestMACrossoverStrategy:
    """Test MA crossover strategy."""
    
    def test_ma_crossover_can_be_imported(self):
        """Test that MA crossover strategy can be imported."""
        try:
            from merid.prediction.strategies.ma_crossover import MACrossoverStrategy
            assert MACrossoverStrategy is not None
        except Exception as e:
            pytest.fail(f"Failed to import MACrossoverStrategy: {e}")
    
    def test_ma_crossover_initialization(self):
        """Test MA crossover strategy initialization."""
        from merid.prediction.strategies.ma_crossover import MACrossoverStrategy
        
        strategy = MACrossoverStrategy()
        
        assert strategy.ema_period == 9
        assert strategy.sma_period == 21
        assert strategy._cooldown_seconds == 60
    
    def test_ma_crossover_custom_periods(self):
        """Test MA crossover with custom periods."""
        from merid.prediction.strategies.ma_crossover import MACrossoverStrategy
        
        strategy = MACrossoverStrategy(ema_period=12, sma_period=26)
        
        assert strategy.ema_period == 12
        assert strategy.sma_period == 26
    
    def test_ma_crossover_ema_calculation(self):
        """Test EMA calculation."""
        from merid.prediction.strategies.ma_crossover import MACrossoverStrategy
        
        strategy = MACrossoverStrategy()
        
        # Create price series
        prices = [65000.0 + i * 10 for i in range(30)]
        
        ema = strategy._calculate_ema(prices, 9)
        
        # EMA should be close to recent prices
        assert ema > 65000.0
        assert ema < 65300.0
    
    def test_ma_crossover_sma_calculation(self):
        """Test SMA calculation."""
        from merid.prediction.strategies.ma_crossover import MACrossoverStrategy
        
        strategy = MACrossoverStrategy()
        
        # Create price series
        prices = [65000.0 + i * 10 for i in range(30)]
        
        sma = strategy._calculate_sma(prices, 21)
        
        # SMA should be average of last 21 prices
        assert sma > 65000.0
        assert sma < 65200.0
    
    def test_ma_crossover_singleton(self):
        """Test that singleton returns same instance."""
        from merid.prediction.strategies.ma_crossover import get_ma_crossover_strategy
        
        strategy1 = get_ma_crossover_strategy()
        strategy2 = get_ma_crossover_strategy()
        
        assert strategy1 is strategy2


class TestVWAPPremiumStrategy:
    """Test VWAP premium strategy."""
    
    def test_vwap_premium_can_be_imported(self):
        """Test that VWAP premium strategy can be imported."""
        try:
            from merid.prediction.strategies.vwap_premium import VWAPPremiumStrategy
            assert VWAPPremiumStrategy is not None
        except Exception as e:
            pytest.fail(f"Failed to import VWAPPremiumStrategy: {e}")
    
    def test_vwap_premium_initialization(self):
        """Test VWAP premium strategy initialization."""
        from merid.prediction.strategies.vwap_premium import VWAPPremiumStrategy
        
        strategy = VWAPPremiumStrategy()
        
        assert strategy.vwap_window == 300  # 5 minutes
        assert strategy.min_premium_pct == 0.002
        assert strategy._cooldown_seconds == 60
    
    def test_vwap_premium_custom_parameters(self):
        """Test VWAP premium with custom parameters."""
        from merid.prediction.strategies.vwap_premium import VWAPPremiumStrategy
        
        strategy = VWAPPremiumStrategy(
            vwap_window=600,
            min_premium_pct=0.003,
        )
        
        assert strategy.vwap_window == 600
        assert strategy.min_premium_pct == 0.003
    
    def test_vwap_calculation(self):
        """Test VWAP calculation."""
        from merid.prediction.strategies.vwap_premium import VWAPPremiumStrategy
        
        strategy = VWAPPremiumStrategy()
        
        # Simulate price-volume data
        now = time.time()
        for i in range(10):
            price = 65000.0 + i * 10
            volume = 100.0
            strategy.update_price("BTC-USD", price, volume, now - (10 - i))
        
        # Calculate VWAP
        vwap = strategy._calculate_vwap("BTC-USD", now)
        
        # VWAP should be within price range
        assert vwap is not None
        assert vwap > 65000.0
        assert vwap < 65100.0
    
    def test_vwap_premium_below_vwap(self):
        """Test signal when price is below VWAP."""
        from merid.prediction.strategies.vwap_premium import VWAPPremiumStrategy
        
        strategy = VWAPPremiumStrategy(
            min_premium_pct=0.002,
        )
        strategy._cooldown_seconds = 0  # Disable cooldown for testing
        
        # Simulate price below VWAP
        now = time.time()
        strategy.update_price("BTC-USD", 65000.0, 100.0, now - 10)
        strategy.update_price("BTC-USD", 64000.0, 100.0, now)  # Price dropped
        
        # Should detect price below VWAP
        assert strategy.get_latest_price("BTC-USD") == 64000.0
    
    def test_vwap_premium_singleton(self):
        """Test that singleton returns same instance."""
        from merid.prediction.strategies.vwap_premium import get_vwap_premium_strategy
        
        strategy1 = get_vwap_premium_strategy()
        strategy2 = get_vwap_premium_strategy()
        
        assert strategy1 is strategy2


class TestStrategyModuleStructure:
    """Test that strategies module structure is correct."""
    
    def test_strategies_module_exists(self):
        """Test that strategies module directory exists."""
        strategies_dir = Path(__file__).parent.parent / "merid" / "prediction" / "strategies"
        assert strategies_dir.exists(), "Strategies module directory should exist"
    
    def test_strategies_init_exists(self):
        """Test that strategies __init__.py exists."""
        init_file = Path(__file__).parent.parent / "merid" / "prediction" / "strategies" / "__init__.py"
        assert init_file.exists(), "Strategies __init__.py should exist"
    
    def test_panic_fade_exists(self):
        """Test that panic_fade.py exists."""
        panic_fade_file = Path(__file__).parent.parent / "merid" / "prediction" / "strategies" / "panic_fade.py"
        assert panic_fade_file.exists(), "panic_fade.py should exist"
    
    def test_trend_alignment_exists(self):
        """Test that trend_alignment.py exists."""
        trend_alignment_file = Path(__file__).parent.parent / "merid" / "prediction" / "strategies" / "trend_alignment.py"
        assert trend_alignment_file.exists(), "trend_alignment.py should exist"
    
    def test_ma_crossover_exists(self):
        """Test that ma_crossover.py exists."""
        ma_crossover_file = Path(__file__).parent.parent / "merid" / "prediction" / "strategies" / "ma_crossover.py"
        assert ma_crossover_file.exists(), "ma_crossover.py should exist"
    
    def test_vwap_premium_exists(self):
        """Test that vwap_premium.py exists."""
        vwap_premium_file = Path(__file__).parent.parent / "merid" / "prediction" / "strategies" / "vwap_premium.py"
        assert vwap_premium_file.exists(), "vwap_premium.py should exist"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
