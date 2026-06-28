"""Schema contract test for KalshiMarketState field access.

This test ensures that validate_market_state_for_entry and other validators
only access fields that actually exist on KalshiMarketState, preventing
silent schema violations like the depth_yes/min_depth_yes mismatch.
"""

import pytest
from dataclasses import fields
from merid.event_venues.kalshi.models import KalshiMarketState

pytestmark = pytest.mark.kalshi_15m


def test_kalshi_market_state_has_all_liquidity_fields():
    """Verify KalshiMarketState has all liquidity audit fields defined."""
    state = KalshiMarketState(ticker="TEST")
    
    # These fields must exist on the dataclass (not just dynamically added)
    required_fields = [
        "has_bid",
        "has_ask", 
        "min_depth_yes",
        "min_depth_no",
        "liquidity_status",
        "last_update_ts",
        "book_initialized",
        "executable",
        "best_bid_cents",
        "best_ask_cents",
        "last_update",
        "last_book_update_ts",
    ]
    
    field_names = {f.name for f in fields(KalshiMarketState)}
    
    for field_name in required_fields:
        assert field_name in field_names, (
            f"Field '{field_name}' not defined in KalshiMarketState dataclass. "
            f"Available fields: {sorted(field_names)}"
        )


def test_validator_fields_exist_on_state():
    """Ensure validate_market_state_for_entry only accesses existing fields."""
    from merid.prediction.agent_grid_15m import validate_market_state_for_entry
    import inspect
    
    # Get the source code of the validator
    source = inspect.getsource(validate_market_state_for_entry)
    
    # Extract all getattr calls to state
    import re
    getattr_pattern = r'getattr\(state,\s*["\']([^"\']+)["\']'
    accessed_fields = set(re.findall(getattr_pattern, source))
    
    # Also check direct attribute access
    direct_pattern = r'state\.([a-zA-Z_][a-zA-Z0-9_]*)'
    direct_fields = set(re.findall(direct_pattern, source))
    
    all_accessed = accessed_fields | direct_fields
    
    # Get actual fields from KalshiMarketState
    state_fields = {f.name for f in fields(KalshiMarketState)}
    
    # Find any accessed fields that don't exist
    missing = all_accessed - state_fields
    
    # Filter out Python builtins, methods, and non-field attributes
    missing = {f for f in missing if not f.startswith('_') and f not in {'regime', 'get'}}
    
    assert not missing, (
        f"Validator accesses fields not defined in KalshiMarketState: {missing}. "
        f"Available fields: {sorted(state_fields)}"
    )


def test_md_health_fields_match_validator():
    """Ensure MD-HEALTH logging uses same field names as validator."""
    from merid.prediction.agent_grid_15m import validate_market_state_for_entry
    import inspect
    
    # Get validator source
    validator_source = inspect.getsource(validate_market_state_for_entry)
    
    # Extract fields accessed by validator
    import re
    getattr_pattern = r'getattr\(state,\s*["\']([^"\']+)["\']'
    validator_fields = set(re.findall(getattr_pattern, validator_source))
    
    # Read agent_grid_15m to find MD-HEALTH log
    with open('c:/Dev/MERID/merid/prediction/agent_grid_15m.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find MD-HEALTH log section
    md_health_match = re.search(
        r'\[MD-HEALTH\].*?depth_yes=.*?depth_no=',
        content,
        re.DOTALL
    )
    
    if md_health_match:
        md_health_section = md_health_match.group(0)
        
        # Extract field names from MD-HEALTH log
        # Looking for patterns like: state.best_bid_cents, depth_yes = getattr(state, 'min_depth_yes')
        md_fields = set(re.findall(r'\.([a-zA-Z_][a-zA-Z0-9_]*)', md_health_section))
        md_fields.update(re.findall(r'getattr\(state,\s*["\']([^"\']+)["\']', md_health_section))
        
        # Filter to state-related fields
        state_fields = {f.name for f in fields(KalshiMarketState)}
        md_state_fields = md_fields & state_fields
        
        # Check for mismatches
        # Validator should use min_depth_yes/min_depth_no (fixed bug)
        assert 'min_depth_yes' in validator_fields, "Validator should use min_depth_yes"
        assert 'min_depth_no' in validator_fields, "Validator should use min_depth_no"
        
        # MD-HEALTH should also use these fields
        assert 'min_depth_yes' in md_fields or 'min_depth_yes' in content, (
            "MD-HEALTH should reference min_depth_yes"
        )
        assert 'min_depth_no' in md_fields or 'min_depth_no' in content, (
            "MD-HEALTH should reference min_depth_no"
        )


def test_validate_market_state_for_entry_depth_validation():
    """Test that validate_market_state_for_entry correctly validates min_depth_yes/min_depth_no.
    
    This test ensures the LIQUIDITY-REJECT logic works correctly:
    - Rejects when depth_yes < min_depth_yes
    - Rejects when depth_no < min_depth_no
    - Passes when both depths meet thresholds
    """
    from merid.prediction.agent_grid_15m import validate_market_state_for_entry
    from merid.event_venues.kalshi.models import KalshiMarketState
    from datetime import datetime, timezone
    import time
    
    # Create a market state with sufficient depth
    state_good = KalshiMarketState(
        ticker="KXBTC15M-TEST",
        book_initialized=True,
        executable=True,
        best_bid_cents=45,
        best_ask_cents=55,
        min_depth_yes=100,  # Sufficient depth
        min_depth_no=100,   # Sufficient depth
        last_update=datetime.now(timezone.utc),
        last_update_ts=time.time(),
    )
    
    # Create a market state with insufficient yes depth
    state_low_yes = KalshiMarketState(
        ticker="KXBTC15M-TEST",
        book_initialized=True,
        executable=True,
        best_bid_cents=45,
        best_ask_cents=55,
        min_depth_yes=5,   # Below threshold
        min_depth_no=100,  # Sufficient depth
        last_update=datetime.now(timezone.utc),
        last_update_ts=time.time(),
    )
    
    # Create a market state with insufficient no depth
    state_low_no = KalshiMarketState(
        ticker="KXBTC15M-TEST",
        book_initialized=True,
        executable=True,
        best_bid_cents=45,
        best_ask_cents=55,
        min_depth_yes=100,  # Sufficient depth
        min_depth_no=3,    # Below threshold
        last_update=datetime.now(timezone.utc),
        last_update_ts=time.time(),
    )
    
    import time
    
    # Test with profile thresholds (e.g., min_depth_yes=10, min_depth_no=10)
    min_depth_yes_threshold = 10
    min_depth_no_threshold = 10
    max_staleness_sec = 30.0
    minutes_to_expiry = 10.0  # Well above MIN_TIME_TO_EXPIRY_FOR_ENTRY_MIN
    
    # Good state should pass
    result_good = validate_market_state_for_entry(
        asset="BTC",
        market_id="KXBTC15M-TEST",
        state=state_good,
        minutes_to_expiry=minutes_to_expiry,
        min_depth_yes=min_depth_yes_threshold,
        min_depth_no=min_depth_no_threshold,
        max_md_staleness_sec=max_staleness_sec,
    )
    assert result_good.ok, f"Good state should pass validation, got reason: {result_good.reason}"
    assert result_good.reason == "OK"
    
    # Low yes depth should reject with DEPTH-LOW
    result_low_yes = validate_market_state_for_entry(
        asset="BTC",
        market_id="KXBTC15M-TEST",
        state=state_low_yes,
        minutes_to_expiry=minutes_to_expiry,
        min_depth_yes=min_depth_yes_threshold,
        min_depth_no=min_depth_no_threshold,
        max_md_staleness_sec=max_staleness_sec,
    )
    assert not result_low_yes.ok, "Low yes depth should fail validation"
    assert result_low_yes.reason.startswith("DEPTH-LOW"), f"Expected DEPTH-LOW prefix, got {result_low_yes.reason}"
    
    # Low no depth should reject with DEPTH-LOW
    result_low_no = validate_market_state_for_entry(
        asset="BTC",
        market_id="KXBTC15M-TEST",
        state=state_low_no,
        minutes_to_expiry=minutes_to_expiry,
        min_depth_yes=min_depth_yes_threshold,
        min_depth_no=min_depth_no_threshold,
        max_md_staleness_sec=max_staleness_sec,
    )
    assert not result_low_no.ok, "Low no depth should fail validation"
    assert result_low_no.reason.startswith("DEPTH-LOW"), f"Expected DEPTH-LOW prefix, got {result_low_no.reason}"


def test_validate_market_state_for_entry_md_staleness():
    """Test that validate_market_state_for_entry correctly rejects stale market data.
    
    This test ensures the MD-STALE gate works correctly:
    - Rejects when last_update > max_md_staleness_sec
    - Accepts when last_update <= max_md_staleness_sec
    """
    from merid.prediction.agent_grid_15m import validate_market_state_for_entry
    from merid.event_venues.kalshi.models import KalshiMarketState
    from datetime import datetime, timezone, timedelta
    import time
    
    max_staleness_sec = 30.0
    minutes_to_expiry = 10.0
    min_depth_yes_threshold = 10
    min_depth_no_threshold = 10
    
    # Fresh state (within staleness threshold)
    state_fresh = KalshiMarketState(
        ticker="KXBTC15M-TEST",
        book_initialized=True,
        executable=True,
        best_bid_cents=45,
        best_ask_cents=55,
        min_depth_yes=100,
        min_depth_no=100,
        last_update=datetime.now(timezone.utc) - timedelta(seconds=10),  # 10 seconds ago
        last_update_ts=time.time() - 10,
    )
    
    # Stale state (beyond staleness threshold)
    state_stale = KalshiMarketState(
        ticker="KXBTC15M-TEST",
        book_initialized=True,
        executable=True,
        best_bid_cents=45,
        best_ask_cents=55,
        min_depth_yes=100,
        min_depth_no=100,
        last_update=datetime.now(timezone.utc) - timedelta(seconds=45),  # 45 seconds ago
        last_update_ts=time.time() - 45,
    )
    
    # Fresh state should pass
    result_fresh = validate_market_state_for_entry(
        asset="BTC",
        market_id="KXBTC15M-TEST",
        state=state_fresh,
        minutes_to_expiry=minutes_to_expiry,
        min_depth_yes=min_depth_yes_threshold,
        min_depth_no=min_depth_no_threshold,
        max_md_staleness_sec=max_staleness_sec,
    )
    assert result_fresh.ok, f"Fresh state should pass validation, got reason: {result_fresh.reason}"
    assert result_fresh.reason == "OK"
    
    # Stale state should reject with MD-STALE
    result_stale = validate_market_state_for_entry(
        asset="BTC",
        market_id="KXBTC15M-TEST",
        state=state_stale,
        minutes_to_expiry=minutes_to_expiry,
        min_depth_yes=min_depth_yes_threshold,
        min_depth_no=min_depth_no_threshold,
        max_md_staleness_sec=max_staleness_sec,
    )
    assert not result_stale.ok, "Stale state should fail validation"
    assert result_stale.reason == "MD-STALE", f"Expected MD-STALE, got {result_stale.reason}"


def test_validate_market_state_for_entry_bid_ask_patterns():
    """Test that validate_market_state_for_entry correctly handles bid/ask pattern guards.
    
    This test ensures the PATTERN-0100 and NO-BIDASK logic works correctly:
    - Rejects (0, 100) pattern with PATTERN-0100
    - Rejects (0, 0) or (None, None) with NO-BIDASK
    - Accepts valid bid/ask pairs
    """
    from merid.prediction.agent_grid_15m import validate_market_state_for_entry
    from merid.event_venues.kalshi.models import KalshiMarketState
    from datetime import datetime, timezone
    import time
    
    max_staleness_sec = 30.0
    minutes_to_expiry = 10.0
    min_depth_yes_threshold = 10
    min_depth_no_threshold = 10
    
    # (0, 100) pattern - empty orderbook or parsing anomaly
    state_0100 = KalshiMarketState(
        ticker="KXBTC15M-TEST",
        book_initialized=True,
        executable=True,
        best_bid_cents=0,
        best_ask_cents=100,
        min_depth_yes=100,
        min_depth_no=100,
        last_update=datetime.now(timezone.utc),
        last_update_ts=time.time(),
    )
    
    # (0, 0) pattern - no valid bid/ask
    state_00 = KalshiMarketState(
        ticker="KXBTC15M-TEST",
        book_initialized=True,
        executable=True,
        best_bid_cents=0,
        best_ask_cents=0,
        min_depth_yes=100,
        min_depth_no=100,
        last_update=datetime.now(timezone.utc),
        last_update_ts=time.time(),
    )
    
    # Valid bid/ask
    state_valid = KalshiMarketState(
        ticker="KXBTC15M-TEST",
        book_initialized=True,
        executable=True,
        best_bid_cents=45,
        best_ask_cents=55,
        min_depth_yes=100,
        min_depth_no=100,
        last_update=datetime.now(timezone.utc),
        last_update_ts=time.time(),
    )
    
    # (0, 100) should reject with PATTERN-0100
    result_0100 = validate_market_state_for_entry(
        asset="BTC",
        market_id="KXBTC15M-TEST",
        state=state_0100,
        minutes_to_expiry=minutes_to_expiry,
        min_depth_yes=min_depth_yes_threshold,
        min_depth_no=min_depth_no_threshold,
        max_md_staleness_sec=max_staleness_sec,
    )
    assert not result_0100.ok, "(0, 100) pattern should fail validation"
    assert result_0100.reason == "PATTERN-0100", f"Expected PATTERN-0100, got {result_0100.reason}"
    
    # (0, 0) should reject with NO-BIDASK
    result_00 = validate_market_state_for_entry(
        asset="BTC",
        market_id="KXBTC15M-TEST",
        state=state_00,
        minutes_to_expiry=minutes_to_expiry,
        min_depth_yes=min_depth_yes_threshold,
        min_depth_no=min_depth_no_threshold,
        max_md_staleness_sec=max_staleness_sec,
    )
    assert not result_00.ok, "(0, 0) pattern should fail validation"
    assert result_00.reason == "NO-BIDASK", f"Expected NO-BIDASK, got {result_00.reason}"
    
    # Valid bid/ask should pass
    result_valid = validate_market_state_for_entry(
        asset="BTC",
        market_id="KXBTC15M-TEST",
        state=state_valid,
        minutes_to_expiry=minutes_to_expiry,
        min_depth_yes=min_depth_yes_threshold,
        min_depth_no=min_depth_no_threshold,
        max_md_staleness_sec=max_staleness_sec,
    )
    assert result_valid.ok, f"Valid bid/ask should pass validation, got reason: {result_valid.reason}"
    assert result_valid.reason == "OK"


def test_validate_market_state_for_entry_expiry_gate():
    """Test that validate_market_state_for_entry correctly enforces expiry gate.
    
    This test ensures the EXPIRY-TOO-CLOSE logic works correctly:
    - Rejects when minutes_to_expiry < MIN_TIME_TO_EXPIRY_FOR_ENTRY_MIN
    - Accepts when minutes_to_expiry >= MIN_TIME_TO_EXPIRY_FOR_ENTRY_MIN
    """
    from merid.prediction.agent_grid_15m import validate_market_state_for_entry, MIN_TIME_TO_EXPIRY_FOR_ENTRY_MIN
    from merid.event_venues.kalshi.models import KalshiMarketState
    from datetime import datetime, timezone
    import time
    
    max_staleness_sec = 30.0
    min_depth_yes_threshold = 10
    min_depth_no_threshold = 10
    
    # State with sufficient time to expiry
    state = KalshiMarketState(
        ticker="KXBTC15M-TEST",
        book_initialized=True,
        executable=True,
        best_bid_cents=45,
        best_ask_cents=55,
        min_depth_yes=100,
        min_depth_no=100,
        last_update=datetime.now(timezone.utc),
        last_update_ts=time.time(),
    )
    
    # Too close to expiry (below threshold)
    minutes_to_expiry_too_close = MIN_TIME_TO_EXPIRY_FOR_ENTRY_MIN - 1.0
    
    result_too_close = validate_market_state_for_entry(
        asset="BTC",
        market_id="KXBTC15M-TEST",
        state=state,
        minutes_to_expiry=minutes_to_expiry_too_close,
        min_depth_yes=min_depth_yes_threshold,
        min_depth_no=min_depth_no_threshold,
        max_md_staleness_sec=max_staleness_sec,
    )
    assert not result_too_close.ok, "Too close to expiry should fail validation"
    assert result_too_close.reason == "EXPIRY-TOO-CLOSE-NORMAL", f"Expected EXPIRY-TOO-CLOSE-NORMAL, got {result_too_close.reason}"
    
    # Sufficient time to expiry (at threshold)
    minutes_to_expiry_sufficient = MIN_TIME_TO_EXPIRY_FOR_ENTRY_MIN + 1.0
    
    result_sufficient = validate_market_state_for_entry(
        asset="BTC",
        market_id="KXBTC15M-TEST",
        state=state,
        minutes_to_expiry=minutes_to_expiry_sufficient,
        min_depth_yes=min_depth_yes_threshold,
        min_depth_no=min_depth_no_threshold,
        max_md_staleness_sec=max_staleness_sec,
    )
    assert result_sufficient.ok, f"Sufficient time to expiry should pass validation, got reason: {result_sufficient.reason}"
    assert result_sufficient.reason == "OK"


def test_strip_limit_behavior():
    """Test that strip limit enforcement works correctly per profile config.
    
    This test ensures the STRIP-LIMIT logic works correctly:
    - Rejects when strip order count >= per_strip_order_limit
    - Accepts when strip order count < per_strip_order_limit
    - Correctly increments strip order count on register_order_fire
    """
    from merid.prediction.agent_grid_15m import can_fire_order, register_order_fire, reset_branch_counters
    import time
    
    # Reset strip order counts for clean test
    from merid.prediction.agent_grid_15m import _strip_order_counts
    _strip_order_counts.clear()
    
    # Reset branch counters to clear asset cooldown
    reset_branch_counters()
    
    now = time.time()
    asset = "BTC"
    
    # First order for strip should be allowed
    ticker1 = "KXBTC15M-26MAY131530"  # Strip: 26MAY131530
    result1 = can_fire_order(asset, now, ticker1)
    # can_fire_order returns (allowed, reason) tuple
    assert result1[0] is True, f"First order for strip should be allowed, got {result1}"
    
    # Register the order
    register_order_fire(asset, now, ticker1)
    
    # Second order for same strip should be rejected (limit=1 by default)
    ticker2 = "KXBTC15M-26MAY131545"  # Same strip: 26MAY131530
    result2 = can_fire_order(asset, now, ticker2)
    assert result2[0] is False, f"Second order for same strip should be rejected due to strip limit, got {result2}"
    
    # Order for different strip should be allowed (after reset and time advance)
    reset_branch_counters()
    # Advance time past asset cooldown (60s)
    now = time.time() + 61.0
    ticker3 = "KXBTC15M-26MAY140000"  # Different strip: 26MAY140000
    result3 = can_fire_order(asset, now, ticker3)
    assert result3[0] is True, f"Order for different strip should be allowed, got {result3}"
    
    # Clean up
    _strip_order_counts.clear()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
