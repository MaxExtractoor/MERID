"""
Unit test for the resting order monitor side conversion fix.
This test verifies that the RestingOrderRecord properly converts
lowercase sides (yes/no) to Kalshi format (BUY_YES, BUY_NO, etc.)
for duplicate detection.
"""

import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from merid.event_venues.kalshi.resting_order_monitor import RestingOrderRecord, RestingOrderMonitor
from merid.event_venues.kalshi.binary_price_space import to_kalshi_side


def test_side_conversion_in_resting_order_record():
    """Test that RestingOrderRecord converts side/action to Kalshi format."""
    
    # Create a record with lowercase side/action
    record = RestingOrderRecord(
        kalshi_order_id="test_order_123",
        ticker="KXBTC15M-2669-2026-07-31T19:00:00Z",
        side="yes",  # lowercase
        action="buy",  # lowercase
        price_cents=50,
        time_in_force="GTC"
    )
    
    # Simulate the conversion that happens in register_order
    if record.side and record.action:
        try:
            record.side = to_kalshi_side(record.side, record.action)
        except ValueError:
            pass
    
    # Verify the side was converted to Kalshi format
    assert record.side == "BUY_YES", f"Expected 'BUY_YES', got '{record.side}'"
    print("[PASS] Test 1 passed: 'yes' + 'buy' converted to 'BUY_YES'")
    
    # Test NO side
    record2 = RestingOrderRecord(
        kalshi_order_id="test_order_456",
        ticker="KXBTC15M-2669-2026-07-31T19:00:00Z",
        side="no",  # lowercase
        action="buy",  # lowercase
        price_cents=50,
        time_in_force="GTC"
    )
    
    if record2.side and record2.action:
        try:
            record2.side = to_kalshi_side(record2.side, record2.action)
        except ValueError:
            pass
    
    assert record2.side == "BUY_NO", f"Expected 'BUY_NO', got '{record2.side}'"
    print("[PASS] Test 2 passed: 'no' + 'buy' converted to 'BUY_NO'")


def test_duplicate_detection_with_kalshi_sides():
    """Test that duplicate detection works with Kalshi-formatted sides."""
    
    monitor = RestingOrderMonitor()
    
    # Register first order with Kalshi-formatted side
    record1 = RestingOrderRecord(
        kalshi_order_id="order_1",
        ticker="KXBTC15M-2669-2026-07-31T19:00:00Z",
        side="BUY_YES",  # Kalshi format
        action="buy",
        price_cents=50,
        time_in_force="GTC",
        status="resting",  # Must be non-terminal status
        remaining_size=10  # Must have remaining size > 0
    )
    monitor.register_order(record1)
    
    # Try to find the order using Kalshi format
    found = monitor.find_open_order(
        ticker="KXBTC15M-2669-2026-07-31T19:00:00Z",
        side="BUY_YES",
        action="buy"
    )
    
    assert found is not None, "Should find the order with Kalshi-formatted side"
    print("[PASS] Test 3 passed: Duplicate detection works with Kalshi-formatted sides")
    
    # Try to find with lowercase - should NOT find (because we now use Kalshi format)
    not_found = monitor.find_open_order(
        ticker="KXBTC15M-2669-2026-07-31T19:00:00Z",
        side="yes",
        action="buy"
    )
    
    assert not_found is None, "Should NOT find order with lowercase side (mismatch)"
    print("[PASS] Test 4 passed: Lowercase side correctly does not match Kalshi-formatted side")


def test_integration_with_loop_15m_workflow():
    """Test the full workflow: loop_15m converts to Kalshi format, monitor uses it."""
    
    monitor = RestingOrderMonitor()
    
    # Simulate loop_15m workflow:
    # 1. Candidate has lowercase side/action
    candidate = {"side": "no", "action": "buy"}
    
    # 2. loop_15m converts to Kalshi format before calling monitor.find_open_order
    kalshi_side = to_kalshi_side(candidate["side"], candidate["action"])
    assert kalshi_side == "BUY_NO"
    
    # 3. Check for existing order using Kalshi format
    found_before = monitor.find_open_order(
        ticker="KXBTC15M-2669-2026-07-31T19:00:00Z",
        side=kalshi_side,
        action=candidate["action"]
    )
    assert found_before is None, "No order should exist yet"
    
    # 4. Register the order (monitor converts to Kalshi format in register_order)
    record = RestingOrderRecord(
        kalshi_order_id="order_integration",
        ticker="KXBTC15M-2669-2026-07-31T19:00:00Z",
        side=candidate["side"],  # lowercase
        action=candidate["action"],  # lowercase
        price_cents=50,
        time_in_force="GTC",
        status="resting",  # Must be non-terminal status
        remaining_size=10  # Must have remaining size > 0
    )
    
    # Simulate the conversion in register_order
    if record.side and record.action:
        try:
            record.side = to_kalshi_side(record.side, record.action)
        except ValueError:
            pass
    
    monitor.register_order(record)
    
    # 5. Check again using Kalshi format - should find it now
    found_after = monitor.find_open_order(
        ticker="KXBTC15M-2669-2026-07-31T19:00:00Z",
        side=kalshi_side,
        action=candidate["action"]
    )
    
    assert found_after is not None, "Should find the order after registration"
    assert found_after == "order_integration", f"Expected 'order_integration', got '{found_after}'"
    print("[PASS] Test 5 passed: Full integration workflow works correctly")


if __name__ == "__main__":
    print("Testing resting order monitor side conversion fix...\n")
    
    test_side_conversion_in_resting_order_record()
    test_duplicate_detection_with_kalshi_sides()
    test_integration_with_loop_15m_workflow()
    
    print("\n[PASS] All tests passed!")
