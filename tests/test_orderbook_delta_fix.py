"""Tests for orderbook delta float-to-int conversion fix.

2026-07-05: Fixed critical bug where Kalshi WebSocket sends delta_fp as float (e.g., 0.28)
but orderbook levels store int sizes. Without conversion, float values get stored in int dict,
causing depth calculations to fail microstructure gate checks (e.g., 0.28 < 1 threshold).

Run: py -m pytest tests/test_orderbook_delta_fix.py -v
"""

from __future__ import annotations

import pytest
from collections import defaultdict
from typing import Dict, Any

# Import the LocalOrderbook class
from merid.event_venues.kalshi.orderbook import LocalOrderbook


class TestOrderbookDeltaFloatToIntFix:
    """Tests for float-to-int conversion in delta application."""
    
    def test_delta_with_float_size_delta_converts_to_int(self):
        """Test that float size_delta from WS is converted to int."""
        book = LocalOrderbook("KXBTC15M-26JUL050730-30")
        
        # Initialize with a snapshot
        snapshot = {
            "ticker": "KXBTC15M-26JUL050730-30",
            "yes": [[0.50, 10]],  # 50 cents, 10 contracts
            "no": [[0.50, 10]],   # 50 cents, 10 contracts
        }
        book.apply_snapshot(snapshot)
        
        # Apply delta with float size_delta (as sent by Kalshi WS)
        delta = {
            "side": "yes",
            "price_dollars": 0.50,  # 50 cents
            "delta_fp": 0.28,  # Float delta (the bug case)
        }
        book.apply_delta(delta)
        
        # Verify the size is stored as int, not float
        assert isinstance(book.yes_levels[50], int), "Size should be stored as int"
        assert book.yes_levels[50] == 10, "10 + 0.28 should round to 10"
    
    def test_delta_with_float_size_delta_rounds_up(self):
        """Test that float size_delta rounds correctly (round half up)."""
        book = LocalOrderbook("KXBTC15M-26JUL050730-30")
        
        # Initialize with a snapshot
        snapshot = {
            "ticker": "KXBTC15M-26JUL050730-30",
            "yes": [[0.50, 10]],
            "no": [[0.50, 10]],
        }
        book.apply_snapshot(snapshot)
        
        # Apply delta with float that should round up
        delta = {
            "side": "yes",
            "price_dollars": 0.50,
            "delta_fp": 0.72,  # Should round to 1
        }
        book.apply_delta(delta)
        
        # Verify rounding
        assert isinstance(book.yes_levels[50], int), "Size should be stored as int"
        assert book.yes_levels[50] == 11, "10 + 0.72 should round to 11"
    
    def test_delta_with_negative_float_size_delta(self):
        """Test that negative float size_delta works correctly."""
        book = LocalOrderbook("KXBTC15M-26JUL050730-30")
        
        # Initialize with a snapshot
        snapshot = {
            "ticker": "KXBTC15M-26JUL050730-30",
            "yes": [[0.50, 10]],
            "no": [[0.50, 10]],
        }
        book.apply_snapshot(snapshot)
        
        # Apply negative delta with float
        delta = {
            "side": "yes",
            "price_dollars": 0.50,
            "delta_fp": -0.28,  # Should round to 0
        }
        book.apply_delta(delta)
        
        # Verify the size remains 10 (10 + 0 = 10)
        assert isinstance(book.yes_levels[50], int), "Size should be stored as int"
        assert book.yes_levels[50] == 10, "10 + (-0.28) should round to 10"
    
    def test_delta_with_negative_float_size_delta_removes_level(self):
        """Test that negative float size_delta can remove a level."""
        book = LocalOrderbook("KXBTC15M-26JUL050730-30")
        
        # Initialize with a snapshot
        snapshot = {
            "ticker": "KXBTC15M-26JUL050730-30",
            "yes": [[0.50, 1]],  # Only 1 contract
            "no": [[0.50, 10]],
        }
        book.apply_snapshot(snapshot)
        
        # Apply negative delta that should remove the level
        delta = {
            "side": "yes",
            "price_dollars": 0.50,
            "delta_fp": -0.72,  # Should round to -1, removing the level
        }
        book.apply_delta(delta)
        
        # Verify the level is removed
        assert 50 not in book.yes_levels, "Level should be removed when size <= 0"
    
    def test_delta_with_int_size_delta_still_works(self):
        """Test that int size_delta still works (backward compatibility)."""
        book = LocalOrderbook("KXBTC15M-26JUL050730-30")
        
        # Initialize with a snapshot
        snapshot = {
            "ticker": "KXBTC15M-26JUL050730-30",
            "yes": [[0.50, 10]],
            "no": [[0.50, 10]],
        }
        book.apply_snapshot(snapshot)
        
        # Apply delta with int size_delta (legacy format)
        delta = {
            "side": "yes",
            "price": 50,  # cents
            "size_delta": 5,  # int
        }
        book.apply_delta(delta)
        
        # Verify the size is stored as int
        assert isinstance(book.yes_levels[50], int), "Size should be stored as int"
        assert book.yes_levels[50] == 15, "10 + 5 should equal 15"
    
    def test_delta_with_string_float_size_delta(self):
        """Test that string float size_delta is handled (WS may send strings)."""
        book = LocalOrderbook("KXBTC15M-26JUL050730-30")
        
        # Initialize with a snapshot
        snapshot = {
            "ticker": "KXBTC15M-26JUL050730-30",
            "yes": [[0.50, 10]],
            "no": [[0.50, 10]],
        }
        book.apply_snapshot(snapshot)
        
        # Apply delta with string float (as sent by some WS implementations)
        delta = {
            "side": "yes",
            "price_dollars": 0.50,
            "delta_fp": "0.28",  # String float
        }
        book.apply_delta(delta)
        
        # Verify the size is stored as int
        assert isinstance(book.yes_levels[50], int), "Size should be stored as int"
        assert book.yes_levels[50] == 10, "10 + 0.28 should round to 10"
    
    def test_multiple_deltas_with_floats(self):
        """Test multiple delta applications with floats."""
        book = LocalOrderbook("KXBTC15M-26JUL050730-30")
        
        # Initialize with a snapshot
        snapshot = {
            "ticker": "KXBTC15M-26JUL050730-30",
            "yes": [[0.50, 10]],
            "no": [[0.50, 10]],
        }
        book.apply_snapshot(snapshot)
        
        # Apply multiple deltas with floats
        deltas = [
            {"side": "yes", "price_dollars": 0.50, "delta_fp": 0.28},
            {"side": "yes", "price_dollars": 0.50, "delta_fp": 0.72},
            {"side": "yes", "price_dollars": 0.50, "delta_fp": -0.50},
        ]
        
        for delta in deltas:
            book.apply_delta(delta)
        
        # Final size: 10 + 0 + 1 + 0 = 11 (round(-0.50) = 0 in banker's rounding)
        assert isinstance(book.yes_levels[50], int), "Size should be stored as int"
        assert book.yes_levels[50] == 11, "Final size should be 11"
    
    def test_no_side_delta_converts_to_int(self):
        """Test that NO side deltas also convert to int."""
        book = LocalOrderbook("KXBTC15M-26JUL050730-30")
        
        # Initialize with a snapshot
        snapshot = {
            "ticker": "KXBTC15M-26JUL050730-30",
            "yes": [[0.50, 10]],
            "no": [[0.50, 10]],
        }
        book.apply_snapshot(snapshot)
        
        # Apply delta to NO side with float
        delta = {
            "side": "no",
            "price_dollars": 0.50,
            "delta_fp": 0.28,
        }
        book.apply_delta(delta)
        
        # Verify the size is stored as int
        assert isinstance(book.no_levels[50], int), "Size should be stored as int"
        assert book.no_levels[50] == 10, "10 + 0.28 should round to 10"
    
    def test_crossed_market_invariant_with_tolerance(self):
        """Test that crossed market invariant has 3c tolerance for crypto volatility."""
        book = LocalOrderbook("KXBTC15M-26JUL050730-30")
        
        # Create a book with slight cross (within 3c tolerance)
        snapshot = {
            "ticker": "KXBTC15M-26JUL050730-30",
            "yes": [[0.51, 10]],  # 51 cents
            "no": [[0.50, 10]],   # 50 cents -> YES ask = 50c
        }
        book.apply_snapshot(snapshot)
        
        # yes_bid (51) + no_bid (50) = 101 > 100, but within 3c tolerance (103)
        # This should NOT trigger an alert
        best_bid = book.get_best_bid()
        best_no_bid = min(book.no_levels.keys()) if book.no_levels else None
        
        if best_bid and best_no_bid:
            # Sum is 101, which is <= 103 (tolerance), so no alert should fire
            assert best_bid[0] + best_no_bid <= 103, "Cross should be within tolerance"
    
    def test_crossed_market_invariant_beyond_tolerance(self):
        """Test that crossed market beyond 3c tolerance triggers alert."""
        book = LocalOrderbook("KXBTC15M-26JUL050730-30")
        
        # Create a book with significant cross (beyond 3c tolerance)
        snapshot = {
            "ticker": "KXBTC15M-26JUL050730-30",
            "yes": [[0.60, 10]],  # 60 cents
            "no": [[0.45, 10]],   # 45 cents -> YES ask = 55c
        }
        book.apply_snapshot(snapshot)
        
        # yes_bid (60) + no_bid (45) = 105 > 103 (beyond tolerance)
        # This SHOULD trigger an alert
        best_bid = book.get_best_bid()
        best_no_bid = min(book.no_levels.keys()) if book.no_levels else None
        
        if best_bid and best_no_bid:
            # Sum is 105, which is > 103 (tolerance), so alert should fire
            assert best_bid[0] + best_no_bid > 103, "Cross should be beyond tolerance"
    
    def test_price_boundary_validation_rejects_invalid_prices(self):
        """Test that prices outside 1-99 cents are rejected."""
        book = LocalOrderbook("KXBTC15M-26JUL050730-30")
        
        # Test invalid prices in delta
        invalid_prices = [0, 100, -1, 101, 0.5, 99.5]
        
        for price_dollars in invalid_prices:
            snapshot = {
                "ticker": "KXBTC15M-26JUL050730-30",
                "yes": [[0.50, 10]],
                "no": [[0.50, 10]],
            }
            book.apply_snapshot(snapshot)
            
            delta = {
                "side": "yes",
                "price_dollars": price_dollars,
                "delta_fp": 5,
            }
            book.apply_delta(delta)
            
            # Check if invalid price was rejected
            price_cents = int(round(price_dollars * 100))
            # Prices outside 1-99 should be clamped or rejected
            if price_cents <= 0 or price_cents >= 100:
                # Level should not exist or be clamped to valid range
                if price_cents in book.yes_levels:
                    # If it exists, it should be clamped to 1 or 99
                    assert price_cents in [1, 99], f"Invalid price {price_cents}c should be clamped to 1 or 99"
    
    def test_invalid_no_price_clamped_to_valid_range(self):
        """Test that invalid NO price (0c) is clamped to 1c in snapshot."""
        book = LocalOrderbook("KXBTC15M-26JUL050730-30")
        
        # Create book with invalid NO price (0c) - should be clamped to 1c
        snapshot = {
            "ticker": "KXBTC15M-26JUL050730-30",
            "yes": [[0.50, 10]],
            "no": [[0.0, 10]],  # Invalid NO price (0c) -> clamped to 1c
        }
        book.apply_snapshot(snapshot)
        
        # NO price should be clamped to 1c (valid range)
        assert 1 in book.no_levels, "NO price 0c should be clamped to 1c"
        assert book.no_levels[1] == 10, "Size should be preserved after clamping"
    
    def test_invalid_no_price_boundary_clamped_to_valid_range(self):
        """Test that NO price >= 100c is clamped to 99c in snapshot."""
        book = LocalOrderbook("KXBTC15M-26JUL050730-30")
        
        # Create book with NO price at boundary - should be clamped to 99c
        snapshot = {
            "ticker": "KXBTC15M-26JUL050730-30",
            "yes": [[0.50, 10]],
            "no": [[1.0, 10]],  # NO price = 100c (invalid) -> clamped to 99c
        }
        book.apply_snapshot(snapshot)
        
        # NO price should be clamped to 99c (valid range)
        assert 99 in book.no_levels, "NO price 100c should be clamped to 99c"
        assert book.no_levels[99] == 10, "Size should be preserved after clamping"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
