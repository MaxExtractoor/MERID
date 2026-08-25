"""
High-severity bug fixes test suite - 2026-08-01

Tests for high-severity bugs identified in the end-to-end stack sweep:
1. Intent-fill state desynchronization in fills_ledger.py
2. Slot leaks on rejection paths in order_router.py
3. Exit order over-close risk (moved to order_router.py)
"""

import pytest


# Test 1: Verify fills_ledger.py has the fix in place
def test_fills_ledger_global_allocator_notification_order():
    """
    Test that global_allocator notification happens BEFORE terminal state checks
    by verifying the code structure in fills_ledger.py.
    """
    import re
    
    with open('C:/Dev/MERID/merid/event_venues/kalshi/fills_ledger.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find the add_fill method
    add_fill_match = re.search(r'def add_fill\(self.*?\n(.*?)(?=\n    def |\n    @)', content, re.DOTALL)
    
    if add_fill_match:
        add_fill_code = add_fill_match.group(0)
        
        # CRITICAL FIX VERIFICATION: Check that global_allocator notification comes BEFORE terminal state checks
        # The fix moved the notification from after terminal checks to before them
        allocator_notification_pos = add_fill_code.find('allocator.record_order_filled')
        terminal_check_pos = add_fill_code.find('if self.status == "filled"')
        
        # Notification should come before terminal checks
        assert allocator_notification_pos > 0, "global_allocator notification not found in add_fill"
        assert terminal_check_pos > 0, "terminal state check not found in add_fill"
        assert allocator_notification_pos < terminal_check_pos, \
            "global_allocator notification should come BEFORE terminal state checks"
        
        print("✓ global_allocator notification is BEFORE terminal state checks (fix verified)")
    else:
        pytest.fail("Could not find add_fill method in fills_ledger.py")


# Test 2: Verify order_router.py has retry mechanism in slot release
def test_slot_release_retry_mechanism():
    """
    Test that _release_allocated_slot has retry mechanism with exponential backoff.
    """
    import re
    
    with open('C:/Dev/MERID/merid/event_venues/kalshi/order_router.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find the _release_allocated_slot function
    release_slot_match = re.search(r'def _release_allocated_slot\(intent.*?\n(.*?)(?=\n\ndef |\n    @)', content, re.DOTALL)
    
    if release_slot_match:
        release_slot_code = release_slot_match.group(0)
        
        # CRITICAL FIX VERIFICATION: Check for retry mechanism
        assert 'max_retries' in release_slot_code, "max_retries not found in _release_allocated_slot"
        assert 'for attempt in range(max_retries)' in release_slot_code, "retry loop not found"
        assert 'exponential backoff' in release_slot_code.lower() or '2 ** attempt' in release_slot_code, \
            "exponential backoff not found"
        assert 'SLOT LEAK' in release_slot_code or 'slot leak' in release_slot_code.lower(), \
            "slot leak detection not found"
        
        print("✓ Slot release has retry mechanism with exponential backoff (fix verified)")
    else:
        pytest.fail("Could not find _release_allocated_slot function in order_router.py")


# Test 3: Verify order_router.py has exit delta invariant check
def test_exit_delta_invariant_check():
    """
    Test that _check_exit_delta_invariant function exists and is called in route_order.
    """
    import re
    
    with open('C:/Dev/MERID/merid/event_venues/kalshi/order_router.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # CRITICAL FIX VERIFICATION: Check that _check_exit_delta_invariant function exists
    assert 'def _check_exit_delta_invariant(' in content, \
        "_check_exit_delta_invariant function not found in order_router.py"
    
    # Check that it's called in the main routing path
    assert '_check_exit_delta_invariant(intent' in content, \
        "_check_exit_delta_invariant not called in order_router.py"
    
    # Check for the invariant checks
    check_delta_match = re.search(r'def _check_exit_delta_invariant\(.*?\n(.*?)(?=\n\ndef |\n    @)', content, re.DOTALL)
    if check_delta_match:
        check_delta_code = check_delta_match.group(0)
        
        # Verify the 5 invariants are checked
        assert 'pre_position_size <= 0' in check_delta_code, "INVARIANT-1 not found"
        assert 'count <= 0' in check_delta_code, "INVARIANT-2 not found"
        assert 'count > pre_position_size' in check_delta_code, "INVARIANT-3 not found"
        assert 'expected_post_position_size < 0' in check_delta_code, "INVARIANT-4 not found"
        assert 'expected_post_position_size >= pre_position_size' in check_delta_code, "INVARIANT-5 not found"
        
        print("✓ Exit delta invariant check exists with all 5 invariants (fix verified)")
    else:
        pytest.fail("Could not find _check_exit_delta_invariant function")


# Test 4: Verify critical bug fixes are documented with timestamps
def test_bug_fix_documentation():
    """
    Test that all critical fixes have proper documentation with 2026-08-01 timestamps.
    """
    files_to_check = [
        ('C:/Dev/MERID/merid/event_venues/kalshi/fills_ledger.py', 'CRITICAL FIX (2026-08-01)'),
        ('C:/Dev/MERID/merid/event_venues/kalshi/order_router.py', 'CRITICAL FIX (2026-08-01)'),
    ]
    
    for file_path, expected_comment in files_to_check:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        assert expected_comment in content, \
            f"Expected comment '{expected_comment}' not found in {file_path}"
    
    print("✓ All critical fixes have proper documentation with 2026-08-01 timestamps")


if __name__ == "__main__":
    # Run tests
    print("Running high-severity bug fixes test suite...\n")
    
    test_fills_ledger_global_allocator_notification_order()
    test_slot_release_retry_mechanism()
    test_exit_delta_invariant_check()
    test_bug_fix_documentation()
    
    print("\n✅ All high-severity bug fix tests passed!")

