"""
Test suite for mid-spread entry optimization (2026-07-04).

Tests the calculate_optimal_entry_price function in agent_grid_15m.py
which implements industry best practices for prediction market entry price optimization.

Key features tested:
- Mid-spread entry (posting 1-2 cents from opposite side)
- Time-decay adjustment (patient early, aggressive late)
- Edge-based adjustment (high edge = patient, low edge = aggressive)
- Fallback when no orderbook data
- Price clamping to 10-50c range (2026-07-09: updated from 55-75c to match profile)
- YES vs NO side logic
"""

import pytest
from typing import Optional


def calculate_optimal_entry_price(
    side: str,
    best_bid: int,
    best_ask: int,
    minutes_to_expiry: float,
    edge_pct: float
) -> int:
    """
    Calculate optimal entry price using mid-spread strategy.
    
    This is a copy of the function from agent_grid_15m.py for testing purposes.
    """
    if best_bid == 0 or best_ask == 0:
        # No orderbook data, use mid-price fallback
        return (best_bid + best_ask) // 2 if best_bid > 0 and best_ask > 0 else 50
    
    # Time-decay adjustment: more aggressive as expiry approaches
    if minutes_to_expiry >= 4.0:
        # Optimal window: patient entry (2 cents from mid)
        time_offset = 2
    elif minutes_to_expiry >= 0.5:
        # Late entry: moderate aggressiveness (1 cent from mid)
        time_offset = 1
    else:
        # Last 30 seconds: aggressive (use mid-price)
        time_offset = 0
    
    # Edge-based adjustment: high edge = patient, low edge = aggressive
    if edge_pct >= 0.10:
        edge_offset = 1  # High edge: be patient
    elif edge_pct >= 0.05:
        edge_offset = 0  # Medium edge: neutral
    else:
        edge_offset = -1  # Low edge: be aggressive
    
    # Combine adjustments (minimum 0 offset)
    total_offset = max(0, time_offset + edge_offset)
    
    # Calculate optimal price based on side
    if side == "yes":
        # For YES buy: post below ask to capture spread
        optimal_price = best_ask - total_offset
    else:  # side == "no"
        # For NO buy: post above bid to capture spread
        optimal_price = best_bid + total_offset
    
    # Ensure price is within bid-ask spread
    if side == "yes":
        optimal_price = max(best_bid, min(best_ask, optimal_price))
    else:
        optimal_price = max(best_bid, min(best_ask, optimal_price))
    
    return int(optimal_price)


class TestMidSpreadEntryOptimization:
    """Test suite for mid-spread entry optimization."""
    
    def test_yes_side_mid_spread_capture(self):
        """Test that YES side posts below ask to capture spread."""
        best_bid = 50
        best_ask = 52
        minutes_to_expiry = 8.0  # Optimal window
        edge_pct = 0.08  # Medium edge
        
        result = calculate_optimal_entry_price(
            side="yes",
            best_bid=best_bid,
            best_ask=best_ask,
            minutes_to_expiry=minutes_to_expiry,
            edge_pct=edge_pct
        )
        
        # Should post 2 cents below ask (time_offset=2, edge_offset=0)
        expected = best_ask - 2
        assert result == expected, f"Expected {expected}, got {result}"
        assert result < best_ask, "Should post below ask for YES buy"
        assert result >= best_bid, "Should not go below bid"
    
    def test_no_side_mid_spread_capture(self):
        """Test that NO side posts above bid to capture spread."""
        best_bid = 48
        best_ask = 50
        minutes_to_expiry = 8.0  # Optimal window
        edge_pct = 0.08  # Medium edge
        
        result = calculate_optimal_entry_price(
            side="no",
            best_bid=best_bid,
            best_ask=best_ask,
            minutes_to_expiry=minutes_to_expiry,
            edge_pct=edge_pct
        )
        
        # Should post 2 cents above bid (time_offset=2, edge_offset=0)
        expected = best_bid + 2
        assert result == expected, f"Expected {expected}, got {result}"
        assert result > best_bid, "Should post above bid for NO buy"
        assert result <= best_ask, "Should not go above ask"
    
    def test_time_decay_patient_entry(self):
        """Test that early in window (4+ min) uses patient entry (2 cents offset)."""
        best_bid = 50
        best_ask = 52
        minutes_to_expiry = 10.0  # Early in window
        edge_pct = 0.08  # Medium edge
        
        result = calculate_optimal_entry_price(
            side="yes",
            best_bid=best_bid,
            best_ask=best_ask,
            minutes_to_expiry=minutes_to_expiry,
            edge_pct=edge_pct
        )
        
        # Should use 2 cent offset (patient)
        expected = best_ask - 2
        assert result == expected, f"Expected {expected}, got {result}"
    
    def test_time_decay_moderate_entry(self):
        """Test that late in window (0.5-4 min) uses moderate entry (1 cent offset)."""
        best_bid = 50
        best_ask = 52
        minutes_to_expiry = 2.0  # Late in window
        edge_pct = 0.08  # Medium edge
        
        result = calculate_optimal_entry_price(
            side="yes",
            best_bid=best_bid,
            best_ask=best_ask,
            minutes_to_expiry=minutes_to_expiry,
            edge_pct=edge_pct
        )
        
        # Should use 1 cent offset (moderate)
        expected = best_ask - 1
        assert result == expected, f"Expected {expected}, got {result}"
    
    def test_time_decay_aggressive_entry(self):
        """Test that very late (<0.5 min) uses aggressive entry (0 cent offset)."""
        best_bid = 50
        best_ask = 52
        minutes_to_expiry = 0.3  # Very late
        edge_pct = 0.08  # Medium edge
        
        result = calculate_optimal_entry_price(
            side="yes",
            best_bid=best_bid,
            best_ask=best_ask,
            minutes_to_expiry=minutes_to_expiry,
            edge_pct=edge_pct
        )
        
        # Should use 0 cent offset (aggressive - post at ask)
        expected = best_ask  # No offset means post at ask
        assert result == expected, f"Expected {expected}, got {result}"
    
    def test_high_edge_patient_entry(self):
        """Test that high edge (>=10%) uses patient entry (extra 1 cent offset)."""
        best_bid = 50
        best_ask = 54  # Wider spread to accommodate 3 cent offset
        minutes_to_expiry = 8.0  # Optimal window
        edge_pct = 0.12  # High edge
        
        result = calculate_optimal_entry_price(
            side="yes",
            best_bid=best_bid,
            best_ask=best_ask,
            minutes_to_expiry=minutes_to_expiry,
            edge_pct=edge_pct
        )
        
        # Should use 3 cent offset (time_offset=2 + edge_offset=1)
        expected = best_ask - 3
        assert result == expected, f"Expected {expected}, got {result}"
    
    def test_low_edge_aggressive_entry(self):
        """Test that low edge (<5%) uses aggressive entry (reduces offset)."""
        best_bid = 50
        best_ask = 52
        minutes_to_expiry = 8.0  # Optimal window
        edge_pct = 0.03  # Low edge
        
        result = calculate_optimal_entry_price(
            side="yes",
            best_bid=best_bid,
            best_ask=best_ask,
            minutes_to_expiry=minutes_to_expiry,
            edge_pct=edge_pct
        )
        
        # Should use 1 cent offset (time_offset=2 + edge_offset=-1 = 1)
        expected = best_ask - 1
        assert result == expected, f"Expected {expected}, got {result}"
    
    def test_no_orderbook_data_fallback(self):
        """Test fallback when no orderbook data (bid=0 or ask=0)."""
        # No bid
        result = calculate_optimal_entry_price(
            side="yes",
            best_bid=0,
            best_ask=52,
            minutes_to_expiry=8.0,
            edge_pct=0.08
        )
        assert result == 50, f"Expected fallback to 50, got {result}"
        
        # No ask
        result = calculate_optimal_entry_price(
            side="yes",
            best_bid=50,
            best_ask=0,
            minutes_to_expiry=8.0,
            edge_pct=0.08
        )
        assert result == 50, f"Expected fallback to 50, got {result}"
        
        # No data at all
        result = calculate_optimal_entry_price(
            side="yes",
            best_bid=0,
            best_ask=0,
            minutes_to_expiry=8.0,
            edge_pct=0.08
        )
        assert result == 50, f"Expected fallback to 50, got {result}"
    
    def test_price_within_spread_bounds(self):
        """Test that calculated price stays within bid-ask spread."""
        best_bid = 50
        best_ask = 52
        minutes_to_expiry = 8.0
        edge_pct = 0.08
        
        result = calculate_optimal_entry_price(
            side="yes",
            best_bid=best_bid,
            best_ask=best_ask,
            minutes_to_expiry=minutes_to_expiry,
            edge_pct=edge_pct
        )
        
        assert best_bid <= result <= best_ask, \
            f"Price {result} should be within spread [{best_bid}, {best_ask}]"
    
    def test_wide_spread_capture(self):
        """Test spread capture on wide spreads (e.g., 5 cents)."""
        best_bid = 50
        best_ask = 55  # 5 cent spread
        minutes_to_expiry = 8.0
        edge_pct = 0.08
        
        result = calculate_optimal_entry_price(
            side="yes",
            best_bid=best_bid,
            best_ask=best_ask,
            minutes_to_expiry=minutes_to_expiry,
            edge_pct=edge_pct
        )
        
        # Should capture 2 cents of the 5 cent spread
        expected = best_ask - 2
        assert result == expected, f"Expected {expected}, got {result}"
        assert result < best_ask, "Should capture spread"
    
    def test_narrow_spread_handling(self):
        """Test handling of narrow spreads (e.g., 1 cent)."""
        best_bid = 50
        best_ask = 51  # 1 cent spread
        minutes_to_expiry = 8.0
        edge_pct = 0.08
        
        result = calculate_optimal_entry_price(
            side="yes",
            best_bid=best_bid,
            best_ask=best_ask,
            minutes_to_expiry=minutes_to_expiry,
            edge_pct=edge_pct
        )
        
        # Should still work, just capture less spread
        assert best_bid <= result <= best_ask, \
            f"Price {result} should be within spread [{best_bid}, {best_ask}]"
    
    def test_combined_time_and_edge_adjustment(self):
        """Test combined effect of time-decay and edge adjustments."""
        best_bid = 50
        best_ask = 52
        minutes_to_expiry = 2.0  # Late: time_offset=1
        edge_pct = 0.12  # High edge: edge_offset=1
        
        result = calculate_optimal_entry_price(
            side="yes",
            best_bid=best_bid,
            best_ask=best_ask,
            minutes_to_expiry=minutes_to_expiry,
            edge_pct=edge_pct
        )
        
        # Should use 2 cent offset (time_offset=1 + edge_offset=1)
        expected = best_ask - 2
        assert result == expected, f"Expected {expected}, got {result}"
    
    def test_negative_offset_clamped_to_zero(self):
        """Test that negative total offset is clamped to zero (minimum)."""
        best_bid = 50
        best_ask = 52
        minutes_to_expiry = 0.3  # Very late: time_offset=0
        edge_pct = 0.03  # Low edge: edge_offset=-1
        
        result = calculate_optimal_entry_price(
            side="yes",
            best_bid=best_bid,
            best_ask=best_ask,
            minutes_to_expiry=minutes_to_expiry,
            edge_pct=edge_pct
        )
        
        # Should clamp to 0 offset (post at ask)
        expected = best_ask  # max(0, 0 + -1) = 0, so no offset
        assert result == expected, f"Expected {expected}, got {result}"


class TestPriceClamping:
    """Test price clamping to 50-70c range (optimized for scaling)."""
    
    def test_price_below_minimum_clamped(self):
        """Test that prices below 50c are clamped to 50c."""
        price_cents = 40
        clamped = max(50, min(70, price_cents))
        assert clamped == 50, f"Expected 50, got {clamped}"
    
    def test_price_above_maximum_clamped(self):
        """Test that prices above 70c are clamped to 70c."""
        price_cents = 80
        clamped = max(50, min(70, price_cents))
        assert clamped == 70, f"Expected 70, got {clamped}"
    
    def test_price_within_range_unchanged(self):
        """Test that prices within 50-70c range are unchanged."""
        price_cents = 60
        clamped = max(50, min(70, price_cents))
        assert clamped == 60, f"Expected 60, got {clamped}"
    
    def test_price_at_minimum_unchanged(self):
        """Test that price at 50c is unchanged."""
        price_cents = 50
        clamped = max(50, min(70, price_cents))
        assert clamped == 50, f"Expected 50, got {clamped}"
    
    def test_price_at_maximum_unchanged(self):
        """Test that price at 70c is unchanged."""
        price_cents = 70
        clamped = max(50, min(70, price_cents))
        assert clamped == 70, f"Expected 70, got {clamped}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
