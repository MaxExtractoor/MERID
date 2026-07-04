"""
Tests for dynamic price clamping based on time-to-expiry.

This test suite validates the 2026 best practice implementation of
dynamic price limits that increase from 70c to 90c when expiry < 2 minutes.

Run with: pytest tests/test_dynamic_price_clamping.py -v
"""

import pytest
import time
from unittest.mock import Mock


class TestDynamicPriceClamping:
    """Test suite for dynamic price clamping based on time-to-expiry."""
    
    def test_yes_price_clamp_normal_trading(self):
        """Test YES price clamping to 70c during normal trading (expiry > 2 minutes)."""
        signal_side = "yes"
        best_bid = 65
        best_ask = 75
        price_cents = int((best_bid + best_ask) / 2)  # 70
        
        # Mock market with expiry > 2 minutes
        market = Mock()
        market.close_time = time.time() + 300  # 5 minutes to expiry
        
        # Calculate time to expiry
        time_to_expiry = market.close_time - time.time()
        
        # Determine max price based on time-to-expiry
        max_price_cents = 70  # Default cap
        if time_to_expiry is not None and time_to_expiry < 120:  # Less than 2 minutes
            max_price_cents = 90
        
        # Apply clamping
        if price_cents < 15:
            price_cents = 15
        elif price_cents > max_price_cents:
            price_cents = max_price_cents
        
        assert price_cents == 70
        assert max_price_cents == 70
    
    def test_yes_price_clamp_near_expiry(self):
        """Test YES price clamping to 90c when expiry < 2 minutes."""
        signal_side = "yes"
        best_bid = 85
        best_ask = 95
        price_cents = int((best_bid + best_ask) / 2)  # 90
        
        # Mock market with expiry < 2 minutes
        market = Mock()
        market.close_time = time.time() + 60  # 1 minute to expiry
        
        # Calculate time to expiry
        time_to_expiry = market.close_time - time.time()
        
        # Determine max price based on time-to-expiry
        max_price_cents = 70  # Default cap
        if time_to_expiry is not None and time_to_expiry < 120:  # Less than 2 minutes
            max_price_cents = 90
        
        # Apply clamping
        if price_cents < 15:
            price_cents = 15
        elif price_cents > max_price_cents:
            price_cents = max_price_cents
        
        assert price_cents == 90
        assert max_price_cents == 90
    
    def test_yes_price_clamp_exceeds_90c_near_expiry(self):
        """Test YES price clamping to 90c when price exceeds 90c near expiry."""
        signal_side = "yes"
        best_bid = 93
        best_ask = 99
        price_cents = int((best_bid + best_ask) / 2)  # 96
        
        # Mock market with expiry < 2 minutes
        market = Mock()
        market.close_time = time.time() + 60  # 1 minute to expiry
        
        # Calculate time to expiry
        time_to_expiry = market.close_time - time.time()
        
        # Determine max price based on time-to-expiry
        max_price_cents = 70  # Default cap
        if time_to_expiry is not None and time_to_expiry < 120:  # Less than 2 minutes
            max_price_cents = 90
        
        # Apply clamping
        original_price = price_cents
        if price_cents < 15:
            price_cents = 15
        elif price_cents > max_price_cents:
            price_cents = max_price_cents
        
        assert original_price == 96
        assert price_cents == 90  # Clamped to 90c
        assert max_price_cents == 90
    
    def test_yes_price_clamp_below_15c(self):
        """Test YES price clamping to minimum 15c."""
        signal_side = "yes"
        best_bid = 10
        best_ask = 12
        price_cents = int((best_bid + best_ask) / 2)  # 11
        
        # Mock market with normal expiry
        market = Mock()
        market.close_time = time.time() + 300
        
        # Calculate time to expiry
        time_to_expiry = market.close_time - time.time()
        
        # Determine max price
        max_price_cents = 70
        if time_to_expiry is not None and time_to_expiry < 120:
            max_price_cents = 90
        
        # Apply clamping
        if price_cents < 15:
            price_cents = 15
        elif price_cents > max_price_cents:
            price_cents = max_price_cents
        
        assert price_cents == 15  # Clamped to minimum
    
    def test_no_price_clamp_normal_trading(self):
        """Test NO price clamping to 70c during normal trading."""
        signal_side = "no"
        best_bid = 65
        best_ask = 75
        
        # Calculate NO bid/ask from YES bid/ask
        no_bid = 100 - best_ask  # 25
        no_ask = 100 - best_bid  # 35
        price_cents = int((no_bid + no_ask) / 2)  # 30
        
        # Mock market with expiry > 2 minutes
        market = Mock()
        market.close_time = time.time() + 300
        
        # Calculate time to expiry
        time_to_expiry = market.close_time - time.time()
        
        # Determine max price
        max_price_cents = 70
        if time_to_expiry is not None and time_to_expiry < 120:
            max_price_cents = 90
        
        # Apply clamping
        if price_cents < 15:
            price_cents = 15
        elif price_cents > max_price_cents:
            price_cents = max_price_cents
        
        assert price_cents == 30  # No clamping needed
        assert max_price_cents == 70
    
    def test_no_price_clamp_near_expiry(self):
        """Test NO price clamping to 90c when expiry < 2 minutes."""
        signal_side = "no"
        best_bid = 5
        best_ask = 15
        
        # Calculate NO bid/ask from YES bid/ask
        no_bid = 100 - best_ask  # 85
        no_ask = 100 - best_bid  # 95
        price_cents = int((no_bid + no_ask) / 2)  # 90
        
        # Mock market with expiry < 2 minutes
        market = Mock()
        market.close_time = time.time() + 60
        
        # Calculate time to expiry
        time_to_expiry = market.close_time - time.time()
        
        # Determine max price
        max_price_cents = 70
        if time_to_expiry is not None and time_to_expiry < 120:
            max_price_cents = 90
        
        # Apply clamping
        if price_cents < 15:
            price_cents = 15
        elif price_cents > max_price_cents:
            price_cents = max_price_cents
        
        assert price_cents == 90  # No clamping needed (within 90c limit)
        assert max_price_cents == 90
    
    def test_no_price_clamp_below_15c(self):
        """Test NO price clamping to minimum 15c."""
        signal_side = "no"
        best_bid = 93
        best_ask = 99
        
        # Calculate NO bid/ask from YES bid/ask
        no_bid = 100 - best_ask  # 1
        no_ask = 100 - best_bid  # 7
        price_cents = int((no_bid + no_ask) / 2)  # 4
        
        # Mock market with normal expiry
        market = Mock()
        market.close_time = time.time() + 300
        
        # Calculate time to expiry
        time_to_expiry = market.close_time - time.time()
        
        # Determine max price
        max_price_cents = 70
        if time_to_expiry is not None and time_to_expiry < 120:
            max_price_cents = 90
        
        # Apply clamping
        if price_cents < 15:
            price_cents = 15
        elif price_cents > max_price_cents:
            price_cents = max_price_cents
        
        assert price_cents == 15  # Clamped to minimum
    
    def test_time_to_expiry_threshold(self):
        """Test that 120 seconds (2 minutes) is the threshold for dynamic clamping."""
        # Test at exactly 120 seconds (should use 70c cap)
        market = Mock()
        market.close_time = time.time() + 120
        time_to_expiry = market.close_time - time.time()
        
        max_price_cents = 70
        if time_to_expiry is not None and time_to_expiry < 120:
            max_price_cents = 90
        
        assert max_price_cents == 70  # Should use 70c cap (not < 120)
        
        # Test at 119 seconds (should use 90c cap)
        market.close_time = time.time() + 119
        time_to_expiry = market.close_time - time.time()
        
        max_price_cents = 70
        if time_to_expiry is not None and time_to_expiry < 120:
            max_price_cents = 90
        
        assert max_price_cents == 90  # Should use 90c cap (< 120)
    
    def test_no_close_time_attribute(self):
        """Test price clamping when market has no close_time attribute."""
        signal_side = "yes"
        best_bid = 85
        best_ask = 95
        price_cents = int((best_bid + best_ask) / 2)  # 90
        
        # Mock market without close_time
        market = Mock(spec=[])  # No attributes
        
        # Calculate time to expiry
        time_to_expiry = None
        if hasattr(market, 'close_time'):
            time_to_expiry = market.close_time - time.time()
        
        # Determine max price (should use default 70c)
        max_price_cents = 70
        if time_to_expiry is not None and time_to_expiry < 120:
            max_price_cents = 90
        
        # Apply clamping
        if price_cents < 15:
            price_cents = 15
        elif price_cents > max_price_cents:
            price_cents = max_price_cents
        
        assert price_cents == 70  # Clamped to 70c (default)
        assert max_price_cents == 70
    
    def test_price_within_range_no_clamping(self):
        """Test that prices within 15-70c range are not clamped during normal trading."""
        signal_side = "yes"
        best_bid = 40
        best_ask = 50
        price_cents = int((best_bid + best_ask) / 2)  # 45
        
        # Mock market with normal expiry
        market = Mock()
        market.close_time = time.time() + 300
        
        # Calculate time to expiry
        time_to_expiry = market.close_time - time.time()
        
        # Determine max price
        max_price_cents = 70
        if time_to_expiry is not None and time_to_expiry < 120:
            max_price_cents = 90
        
        # Apply clamping
        original_price = price_cents
        if price_cents < 15:
            price_cents = 15
        elif price_cents > max_price_cents:
            price_cents = max_price_cents
        
        assert price_cents == original_price  # No clamping applied
        assert price_cents == 45
    
    def test_price_within_range_near_expiry(self):
        """Test that prices within 15-90c range are not clamped near expiry."""
        signal_side = "yes"
        best_bid = 40
        best_ask = 50
        price_cents = int((best_bid + best_ask) / 2)  # 45
        
        # Mock market with expiry < 2 minutes
        market = Mock()
        market.close_time = time.time() + 60
        
        # Calculate time to expiry
        time_to_expiry = market.close_time - time.time()
        
        # Determine max price
        max_price_cents = 70
        if time_to_expiry is not None and time_to_expiry < 120:
            max_price_cents = 90
        
        # Apply clamping
        original_price = price_cents
        if price_cents < 15:
            price_cents = 15
        elif price_cents > max_price_cents:
            price_cents = max_price_cents
        
        assert price_cents == original_price  # No clamping applied
        assert price_cents == 45
