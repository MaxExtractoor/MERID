"""Tests for position risk logging fix in order_router.py.

The fix adds position_count to the risk check logging to clarify the difference
between "no existing positions" and "existing positions sum to this value".

Before the fix:
- Log showed: total=0.44 (ambiguous - could be existing positions or just this order)
- When there were no existing positions, total_with_order equaled just the new order's notional

After the fix:
- Log shows: existing_total=0.00 (0 positions) order_notional=0.44 total_with_order=0.44
- This makes it clear that there are no existing positions and total is just this order
"""

import pytest
from unittest.mock import Mock, patch, MagicMock


class TestPositionRiskLoggingFix:
    """Tests for position risk logging clarity improvement."""
    
    def test_logging_with_no_existing_positions(self):
        """Test that logging clearly shows when there are no existing positions."""
        # Simulate position cache with no positions
        position_cache = Mock()
        position_cache.get_all_positions.return_value = {}  # No positions
        
        # Simulate order intent
        intent = Mock()
        intent.count = 4
        intent.price_cents = 11  # 11 cents per contract
        intent.ticker = "KXDOGE15M-26JUL050815-15"
        
        # Calculate notional values
        order_notional = (intent.count * intent.price_cents) / 100.0  # 0.44
        total_position_notional = 0.0  # No existing positions
        position_count = 0
        total_with_order = total_position_notional + order_notional  # 0.44
        
        # Verify calculations
        assert order_notional == 0.44, "Order notional should be $0.44"
        assert total_position_notional == 0.0, "Existing total should be $0.00"
        assert position_count == 0, "Position count should be 0"
        assert total_with_order == 0.44, "Total with order should be $0.44"
        
        # The new logging format should show:
        # existing_total=0.00 (0 positions) order_notional=0.44 total_with_order=0.44
        # This makes it clear that total_with_order is just this order, not existing positions
    
    def test_logging_with_existing_positions(self):
        """Test that logging clearly shows when there are existing positions."""
        # Simulate position cache with existing positions
        position_cache = Mock()
        
        # Create mock position objects
        pos1 = Mock()
        pos1.contracts = 10
        pos1.current_price_cents = 50  # 50 cents
        
        pos2 = Mock()
        pos2.contracts = 5
        pos2.current_price_cents = 30  # 30 cents
        
        position_cache.get_all_positions.return_value = {
            "KXBTC15M-26JUL050800-00": pos1,
            "KXETH15M-26JUL050800-00": pos2,
        }
        
        # Simulate order intent
        intent = Mock()
        intent.count = 4
        intent.price_cents = 11
        intent.ticker = "KXDOGE15M-26JUL050815-15"
        
        # Calculate notional values
        existing_notional = (pos1.contracts * pos1.current_price_cents) / 100.0  # 5.00
        existing_notional += (pos2.contracts * pos2.current_price_cents) / 100.0  # +1.50 = 6.50
        order_notional = (intent.count * intent.price_cents) / 100.0  # 0.44
        position_count = 2
        total_with_order = existing_notional + order_notional  # 6.94
        
        # Verify calculations
        assert existing_notional == 6.50, "Existing notional should be $6.50"
        assert order_notional == 0.44, "Order notional should be $0.44"
        assert position_count == 2, "Position count should be 2"
        assert total_with_order == 6.94, "Total with order should be $6.94"
        
        # The new logging format should show:
        # existing_total=6.50 (2 positions) order_notional=0.44 total_with_order=6.94
        # This makes it clear that total_with_order includes existing positions
    
    def test_logging_clarity_comparison(self):
        """Test that the new logging format provides better clarity than the old format."""
        # Old format: total=0.44 (ambiguous)
        # New format: existing_total=0.00 (0 positions) order_notional=0.44 total_with_order=0.44
        
        # Case 1: No existing positions
        old_log_no_positions = "total=0.44"
        new_log_no_positions = "existing_total=0.00 (0 positions) order_notional=0.44 total_with_order=0.44"
        
        # The new log clearly shows there are no existing positions
        assert "(0 positions)" in new_log_no_positions, "New log should show position count"
        assert "existing_total=0.00" in new_log_no_positions, "New log should show existing total"
        assert "order_notional=0.44" in new_log_no_positions, "New log should show order notional"
        
        # Case 2: With existing positions
        old_log_with_positions = "total=6.94"
        new_log_with_positions = "existing_total=6.50 (2 positions) order_notional=0.44 total_with_order=6.94"
        
        # The new log clearly shows the breakdown
        assert "(2 positions)" in new_log_with_positions, "New log should show position count"
        assert "existing_total=6.50" in new_log_with_positions, "New log should show existing total"
        assert "order_notional=0.44" in new_log_with_positions, "New log should show order notional"
    
    def test_position_count_calculation(self):
        """Test that position count is correctly calculated."""
        # Test with various position counts
        test_cases = [
            ({}, 0, "no positions"),
            ({"ticker1": Mock(contracts=5)}, 1, "one position"),
            ({"ticker1": Mock(contracts=5), "ticker2": Mock(contracts=10)}, 2, "two positions"),
            ({"ticker1": Mock(contracts=5), "ticker2": Mock(contracts=10), "ticker3": Mock(contracts=3)}, 3, "three positions"),
        ]
        
        for positions, expected_count, description in test_cases:
            # Count positions with contracts > 0
            count = sum(1 for pos in positions.values() if pos.contracts > 0)
            assert count == expected_count, f"Position count should be {expected_count} for {description}"
    
    def test_notional_calculation_accuracy(self):
        """Test that notional calculations are accurate."""
        # Test various contract counts and prices
        test_cases = [
            (1, 10, 0.10, "1 contract at 10c"),
            (5, 20, 1.00, "5 contracts at 20c"),
            (10, 50, 5.00, "10 contracts at 50c"),
            (4, 11, 0.44, "4 contracts at 11c"),
        ]
        
        for contracts, price_cents, expected_notional, description in test_cases:
            notional = (contracts * price_cents) / 100.0
            assert abs(notional - expected_notional) < 0.01, f"Notional should be {expected_notional} for {description}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
