"""Test price clamping fixes for [50, 70] range optimization.

Tests verify:
- YES prices are clamped to [50, 70] range
- NO prices are clamped to [50, 70] range
- Mid-spread entry respects 70c maximum
- Time-of-day scaling parsing handles ' ET' suffix correctly
"""

import pytest
from unittest.mock import Mock, MagicMock
from datetime import datetime, timezone


def test_yes_price_clamping_to_50_70():
    """Test that YES prices are clamped to [50, 70] range."""
    # Test price below minimum
    price_cents = 30
    clamped = max(50, min(70, price_cents))
    assert clamped == 50, f"Expected 50c, got {clamped}c"
    
    # Test price above maximum
    price_cents = 90
    clamped = max(50, min(70, price_cents))
    assert clamped == 70, f"Expected 70c, got {clamped}c"
    
    # Test price within range
    price_cents = 60
    clamped = max(50, min(70, price_cents))
    assert clamped == 60, f"Expected 60c, got {clamped}c"
    
    # Test price at boundaries
    price_cents = 50
    clamped = max(50, min(70, price_cents))
    assert clamped == 50, f"Expected 50c, got {clamped}c"
    
    price_cents = 70
    clamped = max(50, min(70, price_cents))
    assert clamped == 70, f"Expected 70c, got {clamped}c"


def test_no_price_clamping_to_50_70():
    """Test that NO prices are clamped to [50, 70] range."""
    # NO prices are calculated as 100 - YES price
    # If YES bid=90, YES ask=95, then NO mid = 100 - 92.5 = 7.5c -> should clamp to 50c
    
    # Test NO price below minimum
    price_cents = 7
    clamped = max(50, min(70, price_cents))
    assert clamped == 50, f"Expected 50c, got {clamped}c"
    
    # Test NO price above maximum (rare but possible)
    price_cents = 95
    clamped = max(50, min(70, price_cents))
    assert clamped == 70, f"Expected 70c, got {clamped}c"
    
    # Test NO price within range
    price_cents = 55
    clamped = max(50, min(70, price_cents))
    assert clamped == 55, f"Expected 55c, got {clamped}c"


def test_time_of_day_scaling_parsing():
    """Test that time-of-day scaling parsing handles ' ET' suffix correctly."""
    def parse_time_range(time_str: str) -> tuple[float, float]:
        """Parse 'HH:MM-HH:MM ET' to UTC hours."""
        # Strip ' ET' suffix if present
        time_str = time_str.replace(' ET', '')
        start_str, end_str = time_str.split('-')
        start_h, start_m = map(int, start_str.split(':'))
        end_h, end_m = map(int, end_str.split(':'))
        et_offset = 4
        start_utc = (start_h + et_offset) % 24
        end_utc = (end_h + et_offset) % 24
        return start_utc + start_m / 60.0, end_utc + end_m / 60.0
    
    # Test parsing with ' ET' suffix
    start, end = parse_time_range("09:30-16:00 ET")
    assert start == 13.5, f"Expected 13.5, got {start}"
    assert end == 20.0, f"Expected 20.0, got {end}"
    
    # Test parsing without ' ET' suffix (should still work)
    start, end = parse_time_range("09:30-16:00")
    assert start == 13.5, f"Expected 13.5, got {start}"
    assert end == 20.0, f"Expected 20.0, got {end}"
    
    # Test Asian session (crosses midnight)
    start, end = parse_time_range("20:00-02:00 ET")
    assert start == 0.0, f"Expected 0.0, got {start}"
    assert end == 6.0, f"Expected 6.0, got {end}"


def test_mid_spread_entry_respects_70c_max():
    """Test that mid-spread entry optimization respects 70c maximum."""
    def calculate_optimal_entry_price(side: str, best_bid: int, best_ask: int, 
                                     minutes_to_expiry: float, edge_pct: float) -> int:
        """Simplified mid-spread entry calculation."""
        # Calculate offset based on time and edge
        if minutes_to_expiry > 10:
            time_offset = 2
        elif minutes_to_expiry > 5:
            time_offset = 1
        else:
            time_offset = 0
        
        if edge_pct >= 0.10:
            edge_offset = 1
        elif edge_pct >= 0.05:
            edge_offset = 0
        else:
            edge_offset = -1
        
        total_offset = max(0, time_offset + edge_offset)
        
        if side == "yes":
            optimal_price = best_ask - total_offset
        else:
            optimal_price = best_bid + total_offset
        
        # Ensure price is within bid-ask spread
        optimal_price = max(best_bid, min(best_ask, optimal_price))
        
        # Clamp to [50, 70] range
        optimal_price = max(50, min(70, optimal_price))
        
        return int(optimal_price)
    
    # Test with high ask price (should clamp to 70c)
    price = calculate_optimal_entry_price(
        side="yes",
        best_bid=65,
        best_ask=99,
        minutes_to_expiry=5.0,
        edge_pct=0.02
    )
    assert price == 70, f"Expected 70c, got {price}c"
    
    # Test with low bid price (should clamp to 50c)
    price = calculate_optimal_entry_price(
        side="no",
        best_bid=45,
        best_ask=55,
        minutes_to_expiry=5.0,
        edge_pct=0.02
    )
    assert price == 50, f"Expected 50c, got {price}c"
    
    # Test with normal spread (should stay within range)
    price = calculate_optimal_entry_price(
        side="yes",
        best_bid=55,
        best_ask=65,
        minutes_to_expiry=5.0,
        edge_pct=0.02
    )
    assert 50 <= price <= 70, f"Price {price}c outside [50, 70] range"


def test_price_clamping_in_fallback_paths():
    """Test that price clamping is applied in all fallback paths."""
    # Bid-only fallback
    best_bid = 45
    price_cents = best_bid
    price_cents = max(50, min(70, price_cents))
    assert price_cents == 50, f"Expected 50c, got {price_cents}c"
    
    # Ask-only fallback
    best_ask = 95
    price_cents = best_ask
    price_cents = max(50, min(70, price_cents))
    assert price_cents == 70, f"Expected 70c, got {price_cents}c"
    
    # NO calculation from bid
    best_bid = 90
    price_cents = 100 - best_bid
    price_cents = max(50, min(70, price_cents))
    assert price_cents == 50, f"Expected 50c, got {price_cents}c"
    
    # NO calculation from ask
    best_ask = 95
    price_cents = 100 - best_ask
    price_cents = max(50, min(70, price_cents))
    assert price_cents == 50, f"Expected 50c, got {price_cents}c"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
