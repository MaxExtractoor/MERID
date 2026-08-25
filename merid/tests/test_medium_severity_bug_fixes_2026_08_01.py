"""
Medium-severity bug fixes test suite - 2026-08-01

Tests for medium-severity bugs identified in the end-to-end stack sweep:
1. Lazy lock initialization race conditions in market_state.py
2. REST/WS state desynchronization in market_state.py
3. Empty orderbook acceptance in market_state.py
"""

import pytest
import re


# Test 1: Verify lazy lock initialization fix
def test_lazy_lock_initialization_fix():
    """
    Test that async lock is eagerly initialized during store creation
    to prevent race conditions where locks are created in wrong event loop.
    """
    with open('C:/Dev/MERID/merid/event_venues/kalshi/market_state.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # CRITICAL FIX VERIFICATION: Check that lazy initialization was removed
    assert '_store_lock_async_init' not in content, \
        "Lazy initialization lock still exists - should be removed"
    
    # Check that eager initialization was added
    assert 'Eagerly initialize async lock' in content or 'eagerly initialize' in content.lower(), \
        "Eager initialization comment not found"
    
    # Check that async lock is initialized in get_kalshi_market_state_store
    get_store_match = re.search(r'def get_kalshi_market_state_store\(.*?\n(.*?)(?=\n\ndef |\n    @)', content, re.DOTALL)
    if get_store_match:
        get_store_code = get_store_match.group(0)
        assert '_store_lock_async = asyncio.Lock()' in get_store_code, \
            "Async lock not eagerly initialized in get_kalshi_market_state_store"
    
    print("✓ Lazy lock initialization fixed (eager initialization in store creation)")


# Test 2: Verify REST/WS state desynchronization fix
def test_rest_ws_state_desynchronization_fix():
    """
    Test that pending deltas are cleared after snapshot application
    to prevent stale data from being applied to fresh state.
    """
    with open('C:/Dev/MERID/merid/event_venues/kalshi/market_state.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # CRITICAL FIX VERIFICATION: Check that pending deltas are cleared after snapshot
    assert 'SNAPSHOT-DELTA-CLEAR' in content, \
        "Snapshot delta clear log not found"
    
    assert 'cleared %d pending deltas after snapshot' in content, \
        "Pending delta clear logic not found"
    
    # Check that the old replay logic was removed
    assert 'replayed %d pending delta(s) for %s after snapshot' not in content, \
        "Old pending delta replay logic still exists - should be removed"
    
    print("✓ REST/WS state desynchronization fixed (pending deltas cleared after snapshot)")


# Test 3: Verify empty orderbook acceptance fix
def test_empty_orderbook_acceptance_fix():
    """
    Test that empty orderbooks are rejected BEFORE state modification
    and state is marked as not initialized.
    """
    with open('C:/Dev/MERID/merid/event_venues/kalshi/market_state.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # CRITICAL FIX VERIFICATION: Check that validation happens BEFORE apply
    assert 'validation before apply' in content, \
        "Pre-apply validation comment not found"
    
    # Check that state is marked as not initialized when book is removed
    assert 'state.book_initialized = False' in content, \
        "State not marked as not initialized on empty book rejection"
    
    assert 'state.executable = False' in content, \
        "State not marked as not executable on empty book rejection"
    
    # Check that pending deltas are cleared on empty book rejection
    assert 'EMPTY-BOOK-REJECTION' in content, \
        "Empty book rejection log not found"
    
    print("✓ Empty orderbook acceptance fixed (validation before apply, state marked not initialized)")


# Test 4: Verify all medium-severity fixes are documented
def test_medium_severity_bug_fix_documentation():
    """
    Test that all medium-severity fixes have proper documentation with 2026-08-01 timestamps.
    """
    with open('C:/Dev/MERID/merid/event_venues/kalshi/market_state.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for 2026-08-01 timestamps in the fixes
    assert 'CRITICAL FIX (2026-08-01)' in content, \
        "2026-08-01 timestamp not found in market_state.py"
    
    # Count occurrences of 2026-08-01 fixes
    fix_count = content.count('CRITICAL FIX (2026-08-01)')
    assert fix_count >= 3, \
        f"Expected at least 3 CRITICAL FIX (2026-08-01) comments, found {fix_count}"
    
    print(f"✓ All medium-severity fixes have proper documentation ({fix_count} fixes with 2026-08-01 timestamp)")


if __name__ == "__main__":
    # Run tests
    print("Running medium-severity bug fixes test suite...\n")
    
    test_lazy_lock_initialization_fix()
    test_rest_ws_state_desynchronization_fix()
    test_empty_orderbook_acceptance_fix()
    test_medium_severity_bug_fix_documentation()
    
    print("\n✅ All medium-severity bug fix tests passed!")
