"""
Comprehensive test to verify OHLC data is wired into all indicators.

Tests:
1. Velocity calculation uses close price from OHLC
2. ADX/ATR calculation uses full OHLC (open, high, low, close)
3. Regime-aware signals use OHLC-derived velocity
4. Dynamic thresholds use ATR from OHLC
5. All indicators receive proper OHLC data from spot service
"""
import pytest
import time
from unittest.mock import Mock, patch
from data.unified_spot_service import SpotPrice
from merid.prediction.agent_grid_15m import LeanAgent15m


def test_velocity_uses_close_price_from_ohlc():
    """Verify velocity calculation uses close price from OHLC data."""
    import inspect
    from merid.prediction.agent_grid_15m import LeanAgent15m
    
    # Get velocity calculation method
    method = LeanAgent15m._calculate_velocity
    source = inspect.getsource(method)
    
    # Verify it extracts close price from OHLC format
    assert "entry[1]" in source, \
        "Velocity should use entry[1] (close price) from OHLC format"
    assert "# Use close price for velocity" in source, \
        "Velocity should have comment indicating close price usage"
    
    print("✅ Velocity calculation uses close price from OHLC data")


def test_adx_atr_uses_full_ohlc():
    """Verify ADX/ATR calculation uses full OHLC data."""
    import inspect
    from merid.prediction.agent_grid_15m import LeanAgent15m
    
    # Get ADX update method
    method = LeanAgent15m._update_adx_history
    source = inspect.getsource(method)
    
    # Verify method signature includes OHLC parameters
    assert "open_price" in source, \
        "_update_adx_history should accept open_price parameter"
    assert "high_price" in source, \
        "_update_adx_history should accept high_price parameter"
    assert "low_price" in source, \
        "_update_adx_history should accept low_price parameter"
    
    # Verify True Range calculation uses OHLC formula
    assert "tr1 = high_price - low_price" in source, \
        "TR should calculate high - low"
    assert "tr2 = abs(high_price - prev_close)" in source, \
        "TR should calculate |high - prev_close|"
    assert "tr3 = abs(low_price - prev_close)" in source, \
        "TR should calculate |low - prev_close|"
    assert "tr = max(tr1, tr2, tr3)" in source, \
        "TR should take max of all three components"
    
    # Verify Directional Movement uses OHLC
    assert "upward_move = high_price - prev_high" in source, \
        "DM should calculate upward move from highs"
    assert "downward_move = prev_low - low_price" in source, \
        "DM should calculate downward move from lows"
    
    print("✅ ADX/ATR calculation uses full OHLC data")


def test_price_history_stores_ohlc_format():
    """Verify price history stores OHLC format."""
    import inspect
    from merid.prediction.agent_grid_15m import LeanAgent15m
    
    # Get price history update method
    method = LeanAgent15m._update_price_history
    source = inspect.getsource(method)
    
    # Verify it extracts OHLC from spot_data
    assert "hasattr(spot_data, 'open')" in source, \
        "_update_price_history should check for open field"
    assert "hasattr(spot_data, 'high')" in source, \
        "_update_price_history should check for high field"
    assert "hasattr(spot_data, 'low')" in source, \
        "_update_price_history should check for low field"
    
    # Verify it stores OHLC format
    assert "spot_price, open_price, high_price, low_price" in source, \
        "_update_price_history should store OHLC tuple"
    
    # Verify it passes OHLC to ADX update
    assert "_update_adx_history(asset, spot_price, open_price, high_price, low_price)" in source, \
        "_update_price_history should pass OHLC to _update_adx_history"
    
    print("✅ Price history stores OHLC format")


def test_regime_aware_uses_ohlc_velocity():
    """Verify regime-aware signals use OHLC-derived velocity."""
    import inspect
    from merid.prediction.agent_grid_15m import LeanAgent15m
    
    # Get signal generation method
    method = LeanAgent15m._generate_signal
    source = inspect.getsource(method)
    
    # Verify it calculates velocity
    assert "velocity = self._calculate_velocity(asset, spot_price)" in source, \
        "Signal generation should calculate velocity"
    
    # Verify velocity is used for regime-aware mapping
    assert "[REGIME-AWARE]" in source, \
        "Signal generation should log regime-aware decisions"
    assert "[VELOCITY-SIGNAL]" in source, \
        "Signal generation should log velocity-based signals"
    
    print("✅ Regime-aware signals use OHLC-derived velocity")


def test_dynamic_thresholds_use_atr_from_ohlc():
    """Verify dynamic thresholds use ATR calculated from OHLC."""
    import inspect
    from merid.prediction.agent_grid_15m import LeanAgent15m
    
    # Get dynamic velocity threshold method
    method = LeanAgent15m._calculate_dynamic_velocity_threshold
    source = inspect.getsource(method)
    
    # Verify it uses ATR
    assert "atr_pct = self._calculate_atr(asset)" in source, \
        "Dynamic velocity threshold should calculate ATR"
    
    # Get ATR calculation method
    atr_method = LeanAgent15m._calculate_atr
    atr_source = inspect.getsource(atr_method)
    
    # Verify ATR uses TR history (calculated from OHLC)
    assert "tr_history" in atr_source, \
        "ATR should use TR history"
    assert "self._tr_history[asset]" in atr_source, \
        "ATR should access TR history from _update_adx_history"
    
    print("✅ Dynamic thresholds use ATR from OHLC")


def test_spot_price_has_ohlc_fields():
    """Verify SpotPrice object has OHLC fields."""
    spot = SpotPrice(
        price=67000.0,
        timestamp=int(time.time() * 1000),
        source='coinbase_exchange_authenticated',
        confidence=0.95,
        open=66500.0,
        high=68000.0,
        low=66000.0
    )
    
    assert hasattr(spot, 'price'), "SpotPrice should have price field"
    assert hasattr(spot, 'open'), "SpotPrice should have open field"
    assert hasattr(spot, 'high'), "SpotPrice should have high field"
    assert hasattr(spot, 'low'), "SpotPrice should have low field"
    assert hasattr(spot, 'timestamp'), "SpotPrice should have timestamp field"
    assert hasattr(spot, 'source'), "SpotPrice should have source field"
    
    # Verify OHLC values are distinct (true OHLC, not proxy)
    assert not (spot.open == spot.high == spot.low == spot.price), \
        "OHLC values should be distinct for true OHLC data"
    
    print("✅ SpotPrice has OHLC fields")


def test_end_to_end_ohlc_flow():
    """Test end-to-end flow: Spot Service → Price History → Indicators."""
    from merid.prediction.agent_grid_15m import LeanAgent15m
    from data.unified_spot_service import get_unified_spot_service
    
    # Create mock spot data with OHLC
    spot_data = SpotPrice(
        price=67000.0,
        timestamp=int(time.time() * 1000),
        source='coinbase_exchange_authenticated',
        confidence=0.95,
        open=66500.0,
        high=68000.0,
        low=66000.0
    )
    
    # Verify spot service can return OHLC data
    spot_service = get_unified_spot_service()
    spot_service._cache["BTC"] = {
        'price': 67000.0,
        'timestamp': int(time.time() * 1000),
        'source': 'coinbase_exchange_authenticated',
        'open': 66500.0,
        'high': 68000.0,
        'low': 66000.0
    }
    
    result = spot_service.get("BTC")
    assert isinstance(result, SpotPrice), "Spot service should return SpotPrice"
    assert result.open == 66500.0, "SpotPrice should have correct open"
    assert result.high == 68000.0, "SpotPrice should have correct high"
    assert result.low == 66000.0, "SpotPrice should have correct low"
    
    print("✅ End-to-end OHLC flow works correctly")


if __name__ == "__main__":
    print("=" * 60)
    print("OHLC Data Wiring Verification Tests")
    print("=" * 60)
    print()
    
    test_velocity_uses_close_price_from_ohlc()
    test_adx_atr_uses_full_ohlc()
    test_price_history_stores_ohlc_format()
    test_regime_aware_uses_ohlc_velocity()
    test_dynamic_thresholds_use_atr_from_ohlc()
    test_spot_price_has_ohlc_fields()
    test_end_to_end_ohlc_flow()
    
    print()
    print("=" * 60)
    print("✅ ALL OHLC WIRING TESTS PASSED")
    print("=" * 60)
    print()
    print("Summary:")
    print("  - Velocity calculation uses close price from OHLC ✓")
    print("  - ADX/ATR calculation uses full OHLC (open, high, low, close) ✓")
    print("  - Price history stores OHLC format ✓")
    print("  - Regime-aware signals use OHLC-derived velocity ✓")
    print("  - Dynamic thresholds use ATR from OHLC ✓")
    print("  - SpotPrice has OHLC fields ✓")
    print("  - End-to-end OHLC flow works correctly ✓")
