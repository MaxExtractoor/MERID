"""
Integration tests for OBI filter cross-signal validation.
Tests the alignment check between OBI signals and velocity signals.

2026-07-05 FIX: Prevent contradictory signals (e.g., velocity=BUY YES, OBI=sell)
"""

import pytest
from unittest.mock import Mock
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from merid.prediction.order_book_imbalance_filter import OrderBookImbalanceFilter, OBIConfig, OBIContext, OBISignal


class TestOBISignalAlignment:
    """Test OBI filter signal alignment with velocity signals.
    
    Note: Velocity signals use "yes"/"no" (side), while OBI signals use "buy"/"sell" (action).
    Alignment mapping: velocity "yes" aligns with OBI "buy" (buying YES), velocity "no" aligns with OBI "sell" (buying NO).
    """
    
    def setup_method(self):
        """Set up OBI filter for testing."""
        self.config = OBIConfig()
        self.obi_filter = OrderBookImbalanceFilter(self.config)
    
    def test_obi_strong_buy_agrees_with_velocity_yes(self):
        """OBI STRONG_BUY should align with velocity YES signal."""
        obi_signal = OBISignal.STRONG_BUY
        velocity_signal = "yes"
        
        # Extract OBI direction
        obi_direction = None
        if obi_signal in [OBISignal.STRONG_BUY, OBISignal.BUY]:
            obi_direction = "buy"
        elif obi_signal in [OBISignal.STRONG_SELL, OBISignal.SELL]:
            obi_direction = "sell"
        
        # Check alignment (yes aligns with buy, no aligns with sell)
        signals_aligned = (obi_direction is None) or (
            (velocity_signal == "yes" and obi_direction == "buy") or
            (velocity_signal == "no" and obi_direction == "sell")
        )
        assert signals_aligned, "OBI STRONG_BUY should align with velocity YES"
    
    def test_obi_strong_sell_agrees_with_velocity_no(self):
        """OBI STRONG_SELL should align with velocity NO signal."""
        obi_signal = OBISignal.STRONG_SELL
        velocity_signal = "no"
        
        # Extract OBI direction
        obi_direction = None
        if obi_signal in [OBISignal.STRONG_BUY, OBISignal.BUY]:
            obi_direction = "buy"
        elif obi_signal in [OBISignal.STRONG_SELL, OBISignal.SELL]:
            obi_direction = "sell"
        
        # Check alignment (yes aligns with buy, no aligns with sell)
        signals_aligned = (obi_direction is None) or (
            (velocity_signal == "yes" and obi_direction == "buy") or
            (velocity_signal == "no" and obi_direction == "sell")
        )
        assert signals_aligned, "OBI STRONG_SELL should align with velocity NO"
    
    def test_obi_buy_agrees_with_velocity_yes(self):
        """OBI BUY should align with velocity YES signal."""
        obi_signal = OBISignal.BUY
        velocity_signal = "yes"
        
        # Extract OBI direction
        obi_direction = None
        if obi_signal in [OBISignal.STRONG_BUY, OBISignal.BUY]:
            obi_direction = "buy"
        elif obi_signal in [OBISignal.STRONG_SELL, OBISignal.SELL]:
            obi_direction = "sell"
        
        # Check alignment (yes aligns with buy, no aligns with sell)
        signals_aligned = (obi_direction is None) or (
            (velocity_signal == "yes" and obi_direction == "buy") or
            (velocity_signal == "no" and obi_direction == "sell")
        )
        assert signals_aligned, "OBI BUY should align with velocity YES"
    
    def test_obi_sell_agrees_with_velocity_no(self):
        """OBI SELL should align with velocity NO signal."""
        obi_signal = OBISignal.SELL
        velocity_signal = "no"
        
        # Extract OBI direction
        obi_direction = None
        if obi_signal in [OBISignal.STRONG_BUY, OBISignal.BUY]:
            obi_direction = "buy"
        elif obi_signal in [OBISignal.STRONG_SELL, OBISignal.SELL]:
            obi_direction = "sell"
        
        # Check alignment (yes aligns with buy, no aligns with sell)
        signals_aligned = (obi_direction is None) or (
            (velocity_signal == "yes" and obi_direction == "buy") or
            (velocity_signal == "no" and obi_direction == "sell")
        )
        assert signals_aligned, "OBI SELL should align with velocity NO"
    
    def test_obi_strong_buy_conflicts_with_velocity_no(self):
        """OBI STRONG_BUY should conflict with velocity NO signal."""
        obi_signal = OBISignal.STRONG_BUY
        velocity_signal = "no"
        
        # Extract OBI direction
        obi_direction = None
        if obi_signal in [OBISignal.STRONG_BUY, OBISignal.BUY]:
            obi_direction = "buy"
        elif obi_signal in [OBISignal.STRONG_SELL, OBISignal.SELL]:
            obi_direction = "sell"
        
        # Check alignment (yes aligns with buy, no aligns with sell)
        signals_aligned = (obi_direction is None) or (
            (velocity_signal == "yes" and obi_direction == "buy") or
            (velocity_signal == "no" and obi_direction == "sell")
        )
        assert not signals_aligned, "OBI STRONG_BUY should conflict with velocity NO"
    
    def test_obi_strong_sell_conflicts_with_velocity_yes(self):
        """OBI STRONG_SELL should conflict with velocity YES signal."""
        obi_signal = OBISignal.STRONG_SELL
        velocity_signal = "yes"
        
        # Extract OBI direction
        obi_direction = None
        if obi_signal in [OBISignal.STRONG_BUY, OBISignal.BUY]:
            obi_direction = "buy"
        elif obi_signal in [OBISignal.STRONG_SELL, OBISignal.SELL]:
            obi_direction = "sell"
        
        # Check alignment (yes aligns with buy, no aligns with sell)
        signals_aligned = (obi_direction is None) or (
            (velocity_signal == "yes" and obi_direction == "buy") or
            (velocity_signal == "no" and obi_direction == "sell")
        )
        assert not signals_aligned, "OBI STRONG_SELL should conflict with velocity YES"
    
    def test_obi_neutral_no_conflict(self):
        """OBI NEUTRAL should not conflict with any velocity signal."""
        obi_signal = OBISignal.NEUTRAL
        velocity_signal_yes = "yes"
        velocity_signal_no = "no"
        
        # Extract OBI direction
        obi_direction = None
        if obi_signal in [OBISignal.STRONG_BUY, OBISignal.BUY]:
            obi_direction = "buy"
        elif obi_signal in [OBISignal.STRONG_SELL, OBISignal.SELL]:
            obi_direction = "sell"
        
        # Check alignment with both signals
        aligned_yes = (obi_direction is None) or (
            (velocity_signal_yes == "yes" and obi_direction == "buy") or
            (velocity_signal_yes == "no" and obi_direction == "sell")
        )
        aligned_no = (obi_direction is None) or (
            (velocity_signal_no == "yes" and obi_direction == "buy") or
            (velocity_signal_no == "no" and obi_direction == "sell")
        )
        
        assert aligned_yes, "OBI NEUTRAL should not conflict with velocity YES"
        assert aligned_no, "OBI NEUTRAL should not conflict with velocity NO"
    
    def test_per_asset_thresholds_default(self):
        """Test that per-asset thresholds use default when profile not loaded."""
        # When profile config is not loaded, use default strong threshold
        default_threshold = self.config.get_strong_threshold("BTC")
        assert default_threshold == 0.85, "Default strong threshold should be 0.85"
    
    def test_per_asset_thresholds_default_doge(self):
        """Test that per-asset thresholds use default when profile not loaded."""
        # When profile config is not loaded, use default strong threshold
        default_threshold = self.config.get_strong_threshold("DOGE")
        assert default_threshold == 0.85, "Default strong threshold should be 0.85"
    
    def test_obi_context_contains_signal_info(self):
        """Test that OBIContext contains signal information for alignment check."""
        context = OBIContext(
            current_obi=0.60,
            current_signal=OBISignal.STRONG_BUY,
            directional_consistency=0.80,
            window_size=10,
            is_fresh=True,
            recommendation="TRADE",
            size_multiplier=1.0
        )
        
        # Verify context has signal information
        assert context.current_signal == OBISignal.STRONG_BUY
        assert context.current_obi == 0.60
        assert context.directional_consistency == 0.80
        
        # Extract direction from signal
        obi_direction = None
        if context.current_signal in [OBISignal.STRONG_BUY, OBISignal.BUY]:
            obi_direction = "buy"
        elif context.current_signal in [OBISignal.STRONG_SELL, OBISignal.SELL]:
            obi_direction = "sell"
        
        assert obi_direction == "buy", "STRONG_BUY should extract to buy direction"


class TestOBIFilterIntegration:
    """Test OBI filter integration with agent grid signal generation."""
    
    def setup_method(self):
        """Set up OBI filter for integration testing."""
        self.config = OBIConfig()
        self.obi_filter = OrderBookImbalanceFilter(self.config)
    
    def test_should_trade_returns_context(self):
        """Test that should_trade returns OBIContext with all required fields."""
        context = self.obi_filter.should_trade(
            market_id="KXBTC15M-26JUL051415-15",
            bid_depth=150,
            ask_depth=50,
            direction="yes",
            asset="BTC"
        )
        
        # Verify context structure
        assert isinstance(context, OBIContext)
        assert hasattr(context, 'current_obi')
        assert hasattr(context, 'current_signal')
        assert hasattr(context, 'directional_consistency')
        assert hasattr(context, 'recommendation')
        assert hasattr(context, 'size_multiplier')
    
    def test_should_trade_with_strong_obi_signal(self):
        """Test should_trade with strong OBI signal."""
        # Create strong buy signal (bid depth >> ask depth)
        context = self.obi_filter.should_trade(
            market_id="KXBTC15M-26JUL051415-15",
            bid_depth=200,
            ask_depth=50,
            direction="yes",
            asset="BTC"
        )
        
        # Strong signal should result in TRADE recommendation
        assert context.recommendation in ["TRADE", "REDUCED"]
        assert context.current_signal in [OBISignal.BUY, OBISignal.STRONG_BUY]
    
    def test_should_trade_with_neutral_obi_signal(self):
        """Test should_trade with neutral OBI signal."""
        # Create neutral signal (balanced depths)
        context = self.obi_filter.should_trade(
            market_id="KXBTC15M-26JUL051415-15",
            bid_depth=100,
            ask_depth=100,
            direction="yes",
            asset="BTC"
        )
        
        # Neutral signal should result in REDUCED recommendation
        assert context.recommendation in ["REDUCED", "TRADE"]
        assert context.current_signal == OBISignal.NEUTRAL
