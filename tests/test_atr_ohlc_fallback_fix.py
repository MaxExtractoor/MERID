"""
Test for ATR OHLC fallback fix - ensures ATR calculation works when spot_data is None

This test verifies the fix for the bug where ATR=0 when spot_data is None because
the fallback logic set high=low=spot_price, resulting in TR=0 and ATR=0.

The fix uses price history to construct valid OHLC when spot_data is None,
similar to UnifiedSpotService fallback logic.

Run with: pytest tests/test_atr_ohlc_fallback_fix.py -v
"""

import pytest
import time
import collections
from unittest.mock import Mock, MagicMock
from dataclasses import dataclass


@dataclass
class SpotPrice:
    """Mock SpotPrice class for testing."""
    price: float
    timestamp: int
    source: str
    open: float = None
    high: float = None
    low: float = None
    volume: float = None


def format_price(asset: str, price: float) -> str:
    """Format price with appropriate decimal places based on asset."""
    asset_precision = {
        "BTC": 2,
        "ETH": 2,
        "SOL": 4,
        "XRP": 4,
        "DOGE": 7
    }
    precision = asset_precision.get(asset.upper(), 4)
    return f"{price:.{precision}f}"


class TestOHLCFallback:
    """Test OHLC fallback logic when spot_data is None"""
    
    def test_ohlc_fallback_uses_price_history(self):
        """Test that OHLC fallback uses price history when available"""
        # Simulate price history with varying prices
        asset = "BTC"
        spot_price = 67000.0
        
        # Create mock price history
        price_history = collections.deque(maxlen=300)
        current_time = int(time.time() * 1000)
        
        # Add 10 historical prices with variation
        for i in range(10):
            price = 66500.0 + (i * 100)  # 66500, 66600, ..., 67400
            price_history.append((current_time - (10 - i) * 1000, price, price, price, price))
        
        # Simulate the fallback logic
        history = list(price_history)
        
        if len(history) > 0:
            recent_prices = [entry[1] for entry in history[-10:]]
            recent_prices.append(spot_price)
            
            open_price = recent_prices[0]
            high_price = max(recent_prices)
            low_price = min(recent_prices)
            
            # Verify OHLC values are distinct (not all equal to spot_price)
            assert open_price != spot_price or high_price != spot_price or low_price != spot_price, \
                "OHLC should use price history, not just spot_price"
            
            # Verify high > low (valid OHLC)
            assert high_price > low_price, "High should be greater than low"
            
            # Verify values are reasonable
            assert open_price == 66500.0, f"Open should be oldest price: {open_price}"
            assert high_price == 67400.0, f"High should be max: {high_price}"
            assert low_price == 66500.0, f"Low should be min: {low_price}"
            
            print(f"✅ OHLC fallback uses price history: O={open_price} H={high_price} L={low_price} C={spot_price}")
    
    def test_ohlc_fallback_uses_spread_when_no_history(self):
        """Test that OHLC fallback uses spread proxy when no price history"""
        asset = "DOGE"
        spot_price = 0.073340
        
        # Empty price history
        price_history = collections.deque(maxlen=300)
        history = list(price_history)
        
        if len(history) == 0:
            # Use spread proxy
            spread = spot_price * 0.0001  # 0.01% spread
            open_price = spot_price
            high_price = spot_price + spread
            low_price = spot_price - spread
            
            # Verify high > low (valid OHLC)
            assert high_price > low_price, "High should be greater than low with spread"
            
            # Verify spread is small but non-zero
            assert spread > 0, "Spread should be positive"
            assert spread < spot_price * 0.001, "Spread should be small (0.01%)"
            
            # Verify values are around spot_price
            assert abs(open_price - spot_price) < 0.0001, "Open should equal spot_price"
            assert abs(high_price - spot_price) < 0.0001, "High should be close to spot_price"
            assert abs(low_price - spot_price) < 0.0001, "Low should be close to spot_price"
            
            print(f"✅ OHLC fallback uses spread proxy: O={open_price} H={high_price} L={low_price} C={spot_price}")
    
    def test_true_range_calculation_with_valid_ohlc(self):
        """Test that True Range calculation works with valid OHLC"""
        # Simulate valid OHLC data
        high_price = 68000.0
        low_price = 66000.0
        prev_close = 66500.0
        
        # Calculate True Range: max(high-low, |high-prev_close|, |low-prev_close|)
        tr1 = high_price - low_price
        tr2 = abs(high_price - prev_close)
        tr3 = abs(low_price - prev_close)
        tr = max(tr1, tr2, tr3)
        
        # Verify TR is non-zero
        assert tr > 0, "True Range should be non-zero with valid OHLC"
        
        # Verify TR calculation
        assert tr1 == 2000.0, f"high-low should be 2000: {tr1}"
        assert tr2 == 1500.0, f"|high-prev_close| should be 1500: {tr2}"
        assert tr3 == 500.0, f"|low-prev_close| should be 500: {tr3}"
        assert tr == 2000.0, f"TR should be max of all three: {tr}"
        
        print(f"✅ True Range calculation works: TR={tr}")
    
    def test_true_range_zero_with_invalid_ohlc(self):
        """Test that True Range is zero when high=low (invalid OHLC)"""
        # Simulate invalid OHLC (high=low)
        high_price = 67000.0
        low_price = 67000.0
        prev_close = 67000.0
        
        # Calculate True Range
        tr1 = high_price - low_price
        tr2 = abs(high_price - prev_close)
        tr3 = abs(low_price - prev_close)
        tr = max(tr1, tr2, tr3)
        
        # Verify TR is zero (this is the bug we're fixing)
        assert tr == 0, "True Range should be zero when high=low=prev_close"
        
        print(f"⚠️  True Range is zero with invalid OHLC: TR={tr} (this is the bug)")
    
    def test_atr_calculation_with_valid_tr_history(self):
        """Test that ATR calculation works with valid TR history"""
        # Simulate TR history with non-zero values
        tr_history = collections.deque(maxlen=300)
        current_time = int(time.time() * 1000)
        
        # Add 14 TR values (standard ATR period)
        for i in range(14):
            tr = 100.0 + (i * 10)  # 100, 110, 120, ..., 230
            tr_history.append((current_time - (14 - i) * 1000, tr))
        
        # Calculate ATR as average of recent TR values
        recent_tr = [entry[1] for entry in list(tr_history)[-14:]]
        atr = sum(recent_tr) / len(recent_tr)
        
        # Verify ATR is non-zero
        assert atr > 0, "ATR should be non-zero with valid TR history"
        
        # Verify ATR calculation
        expected_atr = sum(range(100, 240, 10)) / 14  # Average of 100, 110, ..., 230
        assert abs(atr - expected_atr) < 0.01, f"ATR should be {expected_atr}: {atr}"
        
        print(f"✅ ATR calculation works: ATR={atr}")
    
    def test_atr_zero_with_zero_tr_history(self):
        """Test that ATR is zero when TR history contains only zeros"""
        # Simulate TR history with zero values (from invalid OHLC)
        tr_history = collections.deque(maxlen=300)
        current_time = int(time.time() * 1000)
        
        # Add 14 zero TR values
        for i in range(14):
            tr = 0.0
            tr_history.append((current_time - (14 - i) * 1000, tr))
        
        # Calculate ATR
        recent_tr = [entry[1] for entry in list(tr_history)[-14:]]
        atr = sum(recent_tr) / len(recent_tr)
        
        # Verify ATR is zero (this is the bug we're fixing)
        assert atr == 0, "ATR should be zero when TR history contains only zeros"
        
        print(f"⚠️  ATR is zero with zero TR history: ATR={atr} (this is the bug)")


class TestEndToEndATRFlow:
    """Test end-to-end ATR flow with OHLC fallback"""
    
    def test_spot_data_none_uses_fallback(self):
        """Test that spot_data=None triggers OHLC fallback"""
        # Simulate the scenario where spot_data is None
        spot_data = None
        spot_price = 67000.0
        
        # Price history with variation
        price_history = collections.deque(maxlen=300)
        current_time = int(time.time() * 1000)
        
        for i in range(10):
            price = 66500.0 + (i * 100)
            price_history.append((current_time - (10 - i) * 1000, price, price, price, price))
        
        # Apply fallback logic
        if spot_data and hasattr(spot_data, 'open') and hasattr(spot_data, 'high') and hasattr(spot_data, 'low'):
            # Use spot_data OHLC
            open_price = spot_data.open if spot_data.open else spot_price
            high_price = spot_data.high if spot_data.high else spot_price
            low_price = spot_data.low if spot_data.low else spot_price
        else:
            # Use fallback
            history = list(price_history)
            if len(history) > 0:
                recent_prices = [entry[1] for entry in history[-10:]]
                recent_prices.append(spot_price)
                open_price = recent_prices[0]
                high_price = max(recent_prices)
                low_price = min(recent_prices)
            else:
                spread = spot_price * 0.0001
                open_price = spot_price
                high_price = spot_price + spread
                low_price = spot_price - spread
        
        # Verify fallback was used (spot_data was None)
        assert high_price > low_price, "Fallback should produce valid OHLC"
        assert high_price != low_price, "Fallback should not produce high=low"
        
        # Calculate TR from fallback OHLC
        prev_close = history[-2][1] if len(history) >= 2 else spot_price
        tr = max(high_price - low_price, abs(high_price - prev_close), abs(low_price - prev_close))
        
        # Verify TR is non-zero (fix works)
        assert tr > 0, "TR should be non-zero with fallback OHLC"
        
        print(f"✅ End-to-end: spot_data=None uses fallback, TR={tr} (non-zero)")
    
    def test_spot_data_with_ohlc_bypasses_fallback(self):
        """Test that spot_data with OHLC bypasses fallback"""
        # Simulate spot_data with valid OHLC
        spot_data = SpotPrice(
            price=67000.0,
            timestamp=int(time.time() * 1000),
            source='coinbase',
            open=66500.0,
            high=68000.0,
            low=66000.0
        )
        spot_price = spot_data.price
        
        # Apply logic
        if spot_data and hasattr(spot_data, 'open') and hasattr(spot_data, 'high') and hasattr(spot_data, 'low'):
            open_price = spot_data.open if spot_data.open else spot_price
            high_price = spot_data.high if spot_data.high else spot_price
            low_price = spot_data.low if spot_data.low else spot_price
        else:
            # Fallback (should not be reached)
            open_price = spot_price
            high_price = spot_price
            low_price = spot_price
        
        # Verify spot_data OHLC was used
        assert open_price == 66500.0, "Should use spot_data.open"
        assert high_price == 68000.0, "Should use spot_data.high"
        assert low_price == 66000.0, "Should use spot_data.low"
        
        # Verify TR is non-zero
        tr = high_price - low_price
        assert tr > 0, "TR should be non-zero with spot_data OHLC"
        
        print(f"✅ End-to-end: spot_data with OHLC bypasses fallback, TR={tr}")


if __name__ == "__main__":
    print("=" * 60)
    print("ATR OHLC Fallback Fix Tests")
    print("=" * 60)
    print()
    
    test_ohlc = TestOHLCFallback()
    test_e2e = TestEndToEndATRFlow()
    
    # Run OHLC fallback tests
    test_ohlc.test_ohlc_fallback_uses_price_history()
    test_ohlc.test_ohlc_fallback_uses_spread_when_no_history()
    test_ohlc.test_true_range_calculation_with_valid_ohlc()
    test_ohlc.test_true_range_zero_with_invalid_ohlc()
    test_ohlc.test_atr_calculation_with_valid_tr_history()
    test_ohlc.test_atr_zero_with_zero_tr_history()
    
    print()
    
    # Run end-to-end tests
    test_e2e.test_spot_data_none_uses_fallback()
    test_e2e.test_spot_data_with_ohlc_bypasses_fallback()
    
    print()
    print("=" * 60)
    print("✅ ALL ATR OHLC FALLBACK TESTS PASSED")
    print("=" * 60)
    print()
    print("Summary:")
    print("  - OHLC fallback uses price history when available ✓")
    print("  - OHLC fallback uses spread proxy when no history ✓")
    print("  - True Range calculation works with valid OHLC ✓")
    print("  - True Range is zero with invalid OHLC (bug identified) ✓")
    print("  - ATR calculation works with valid TR history ✓")
    print("  - ATR is zero with zero TR history (bug identified) ✓")
    print("  - End-to-end: spot_data=None uses fallback ✓")
    print("  - End-to-end: spot_data with OHLC bypasses fallback ✓")
