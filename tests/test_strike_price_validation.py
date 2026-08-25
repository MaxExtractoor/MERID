"""
Tests for strike price validation function.

Tests the _is_valid_strike_target function that validates strike prices
for trading operations based on best practices for binary options.
"""

import pytest
import math
from merid.prediction.agent_grid_15m import _is_valid_strike_target


class TestStrikePriceValidation:
    """Test suite for strike price validation function."""

    def test_valid_btc_price(self):
        """Test that valid BTC prices pass validation."""
        # BTC bounds: $1,000 - $200,000
        assert _is_valid_strike_target(50000.0, "BTC") == True
        assert _is_valid_strike_target(1000.0, "BTC") == True  # Lower bound
        assert _is_valid_strike_target(200000.0, "BTC") == True  # Upper bound
        assert _is_valid_strike_target(65000.0, "BTC") == True  # Normal price

    def test_valid_eth_price(self):
        """Test that valid ETH prices pass validation."""
        # ETH bounds: $50 - $10,000
        assert _is_valid_strike_target(3000.0, "ETH") == True
        assert _is_valid_strike_target(50.0, "ETH") == True  # Lower bound
        assert _is_valid_strike_target(10000.0, "ETH") == True  # Upper bound
        assert _is_valid_strike_target(3500.0, "ETH") == True  # Normal price

    def test_valid_sol_price(self):
        """Test that valid SOL prices pass validation."""
        # SOL bounds: $1 - $1,000
        assert _is_valid_strike_target(150.0, "SOL") == True
        assert _is_valid_strike_target(1.0, "SOL") == True  # Lower bound
        assert _is_valid_strike_target(1000.0, "SOL") == True  # Upper bound
        assert _is_valid_strike_target(175.0, "SOL") == True  # Normal price

    def test_valid_xrp_price(self):
        """Test that valid XRP prices pass validation."""
        # XRP bounds: $0.10 - $10
        assert _is_valid_strike_target(1.05, "XRP") == True
        assert _is_valid_strike_target(0.10, "XRP") == True  # Lower bound
        assert _is_valid_strike_target(10.0, "XRP") == True  # Upper bound
        assert _is_valid_strike_target(0.60, "XRP") == True  # Normal price

    def test_valid_doge_price(self):
        """Test that valid DOGE prices pass validation."""
        # DOGE bounds: $0.0001 - $2
        assert _is_valid_strike_target(0.15, "DOGE") == True
        assert _is_valid_strike_target(0.0001, "DOGE") == True  # Lower bound
        assert _is_valid_strike_target(2.0, "DOGE") == True  # Upper bound
        assert _is_valid_strike_target(0.12, "DOGE") == True  # Normal price

    def test_invalid_zero_price(self):
        """Test that zero price fails validation."""
        assert _is_valid_strike_target(0.0, "BTC") == False
        assert _is_valid_strike_target(0.0, "ETH") == False
        assert _is_valid_strike_target(0.0, "XRP") == False

    def test_invalid_negative_price(self):
        """Test that negative prices fail validation."""
        assert _is_valid_strike_target(-1.0, "BTC") == False
        assert _is_valid_strike_target(-0.5, "ETH") == False
        assert _is_valid_strike_target(-100.0, "SOL") == False

    def test_invalid_none_price(self):
        """Test that None price fails validation."""
        assert _is_valid_strike_target(None, "BTC") == False
        assert _is_valid_strike_target(None, "ETH") == False

    def test_btc_out_of_bounds_low(self):
        """Test that BTC prices below lower bound fail validation."""
        assert _is_valid_strike_target(999.0, "BTC") == False
        assert _is_valid_strike_target(500.0, "BTC") == False
        assert _is_valid_strike_target(0.0, "BTC") == False

    def test_btc_out_of_bounds_high(self):
        """Test that BTC prices above upper bound fail validation."""
        assert _is_valid_strike_target(200001.0, "BTC") == False
        assert _is_valid_strike_target(500000.0, "BTC") == False
        assert _is_valid_strike_target(1000000.0, "BTC") == False

    def test_eth_out_of_bounds_low(self):
        """Test that ETH prices below lower bound fail validation."""
        assert _is_valid_strike_target(49.0, "ETH") == False
        assert _is_valid_strike_target(10.0, "ETH") == False
        assert _is_valid_strike_target(0.0, "ETH") == False

    def test_eth_out_of_bounds_high(self):
        """Test that ETH prices above upper bound fail validation."""
        assert _is_valid_strike_target(10001.0, "ETH") == False
        assert _is_valid_strike_target(20000.0, "ETH") == False
        assert _is_valid_strike_target(50000.0, "ETH") == False

    def test_xrp_out_of_bounds_low(self):
        """Test that XRP prices below lower bound fail validation."""
        assert _is_valid_strike_target(0.09, "XRP") == False
        assert _is_valid_strike_target(0.01, "XRP") == False
        assert _is_valid_strike_target(0.0, "XRP") == False

    def test_xrp_out_of_bounds_high(self):
        """Test that XRP prices above upper bound fail validation."""
        assert _is_valid_strike_target(10.01, "XRP") == False
        assert _is_valid_strike_target(20.0, "XRP") == False
        assert _is_valid_strike_target(100.0, "XRP") == False

    def test_nan_price(self):
        """Test that NaN prices fail validation."""
        assert _is_valid_strike_target(float('nan'), "BTC") == False
        assert _is_valid_strike_target(float('nan'), "ETH") == False
        assert _is_valid_strike_target(float('nan'), "XRP") == False

    def test_infinity_price(self):
        """Test that infinity prices fail validation."""
        assert _is_valid_strike_target(float('inf'), "BTC") == False
        assert _is_valid_strike_target(float('-inf'), "ETH") == False
        assert _is_valid_strike_target(float('inf'), "XRP") == False

    def test_unknown_asset_validation(self):
        """Test that unknown assets use default validation (positive check only)."""
        # Unknown assets should pass basic positive validation
        assert _is_valid_strike_target(100.0, "UNKNOWN") == True
        assert _is_valid_strike_target(1.0, "UNKNOWN") == True
        
        # But fail on non-positive values
        assert _is_valid_strike_target(0.0, "UNKNOWN") == False
        assert _is_valid_strike_target(-1.0, "UNKNOWN") == False
        assert _is_valid_strike_target(None, "UNKNOWN") == False

    def test_case_sensitivity(self):
        """Test that asset symbols are case-sensitive."""
        # Uppercase should work
        assert _is_valid_strike_target(50000.0, "BTC") == True
        
        # Lowercase should use default validation (not in bounds dict)
        assert _is_valid_strike_target(50000.0, "btc") == True  # Passes basic validation
        assert _is_valid_strike_target(0.0, "btc") == False  # Fails basic validation

    def test_edge_case_boundary_values(self):
        """Test exact boundary values for each asset."""
        # BTC boundaries
        assert _is_valid_strike_target(1000.0, "BTC") == True  # Exact lower bound
        assert _is_valid_strike_target(200000.0, "BTC") == True  # Exact upper bound
        
        # ETH boundaries
        assert _is_valid_strike_target(50.0, "ETH") == True  # Exact lower bound
        assert _is_valid_strike_target(10000.0, "ETH") == True  # Exact upper bound
        
        # SOL boundaries
        assert _is_valid_strike_target(1.0, "SOL") == True  # Exact lower bound
        assert _is_valid_strike_target(1000.0, "SOL") == True  # Exact upper bound
        
        # XRP boundaries
        assert _is_valid_strike_target(0.10, "XRP") == True  # Exact lower bound
        assert _is_valid_strike_target(10.0, "XRP") == True  # Exact upper bound
        
        # DOGE boundaries
        assert _is_valid_strike_target(0.0001, "DOGE") == True  # Exact lower bound
        assert _is_valid_strike_target(2.0, "DOGE") == True  # Exact upper bound

    def test_realistic_trading_prices(self):
        """Test realistic current market prices."""
        # Current market prices (as of 2026)
        assert _is_valid_strike_target(65000.0, "BTC") == True  # ~$65K BTC
        assert _is_valid_strike_target(3500.0, "ETH") == True  # ~$3.5K ETH
        assert _is_valid_strike_target(175.0, "SOL") == True  # ~$175 SOL
        assert _is_valid_strike_target(0.60, "XRP") == True  # ~$0.60 XRP
        assert _is_valid_strike_target(0.12, "DOGE") == True  # ~$0.12 DOGE

    def test_extreme_but_valid_prices(self):
        """Test extreme but still valid prices (stress testing)."""
        # Very low but valid
        assert _is_valid_strike_target(1001.0, "BTC") == True  # Just above BTC lower bound
        assert _is_valid_strike_target(51.0, "ETH") == True  # Just above ETH lower bound
        assert _is_valid_strike_target(1.1, "SOL") == True  # Just above SOL lower bound
        assert _is_valid_strike_target(0.11, "XRP") == True  # Just above XRP lower bound
        assert _is_valid_strike_target(0.0002, "DOGE") == True  # Just above DOGE lower bound
        
        # Very high but valid
        assert _is_valid_strike_target(199999.0, "BTC") == True  # Just below BTC upper bound
        assert _is_valid_strike_target(9999.0, "ETH") == True  # Just below ETH upper bound
        assert _is_valid_strike_target(999.0, "SOL") == True  # Just below SOL upper bound
        assert _is_valid_strike_target(9.99, "XRP") == True  # Just below XRP upper bound
        assert _is_valid_strike_target(1.99, "DOGE") == True  # Just below DOGE upper bound


if __name__ == "__main__":
    pytest.main([__file__, "-v"])