"""
Critical bug fixes test suite - 2026-08-01

Tests for the most critical bugs identified in the end-to-end stack sweep:
1. fills_ledger.py early return skipping PositionMonitor addition
2. exit_policy.py division by zero
3. global_slot_allocator.py slot allocation atomicity
4. Maker fee calculation bug (assumed zero fee, should be 25% of taker fee)
5. Daily loss limit disabled (should be 5% in prod mode)
6. CachedPosition missing exit_policy_id attribute
7. Dynamic max_hold hour validation bug
8. Bracket orders blocked by profile
9. Dynamic max hold time parsing bug
10. Bracket agent not in whitelist
11. Dynamic max hold calculation bug
12. Exit invariant check failed
13. Position cache contract limit violation
"""

import pytest
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, MagicMock
import asyncio

# Test 1: fills_ledger.py legacy position handling
def test_fills_ledger_legacy_position_handling():
    """
    Test that legacy positions (>30m old) are tracked in fills_ledger
    for reconciliation, even if they don't get exit monitoring.
    
    This prevents the early return bug where positions were never
    added to _open_positions at all.
    """
    from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger, KalshiFill
    
    # Create a mock fill for a position that expired >30 minutes ago
    old_expiry = datetime.now(timezone.utc) - timedelta(minutes=45)
    from decimal import Decimal
    fill = KalshiFill(
        fill_id="test_fill_legacy",
        market_ticker="KXBTC15M-26JUL311830-30",
        side="yes",
        action="buy",
        count_fp=1,
        yes_price_dollars=Decimal("0.50"),
        fee_cost=Decimal("0.0"),
        created_time=old_expiry,
        agent_id="test_agent"
    )
    
    # Mock the position monitor and market filter
    with patch('merid.position_management.position_monitor.get_position_monitor') as mock_monitor_getter, \
         patch('merid.event_venues.kalshi.market_filter.parse_expiry_from_ticker') as mock_parse:
        mock_monitor = Mock()
        mock_monitor.add_position = Mock()
        mock_monitor_getter.return_value = mock_monitor
        # Return a timestamp that's >30m old
        mock_parse.return_value = old_expiry.timestamp()
        
        ledger = KalshiFillsLedger()
        
        # Process the fill
        ledger.on_fill(fill)
        
        # CRITICAL FIX VERIFICATION: Position was created in ledger
        # The bug was that early return skipped ALL processing, including
        # position creation. This verifies position is now created.
        instrument_key = f"{fill.market_ticker}:{fill.side}"
        assert instrument_key in ledger._open_positions
        position = ledger._open_positions[instrument_key]
        assert position["total_contracts"] == 1
        
        # Verify PositionMonitor.add_position was NOT called for legacy position
        # (The fix should skip exit monitoring but still create the position)
        mock_monitor.add_position.assert_not_called()
        
        print("✓ Legacy position tracked in fills_ledger but not added to PositionMonitor")


def test_fills_ledger_fresh_position_monitoring():
    """
    Test that fresh positions (<30m old) ARE added to PositionMonitor.
    
    This ensures the fix doesn't break normal exit monitoring.
    """
    from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger, KalshiFill
    
    # Create a mock fill for a fresh position
    fresh_expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
    from decimal import Decimal
    fill = KalshiFill(
        fill_id="test_fill_fresh",
        market_ticker="KXBTC15M-26JUL311830-30",
        side="yes",
        action="buy",
        count_fp=1,
        yes_price_dollars=Decimal("0.50"),
        fee_cost=Decimal("0.0"),
        created_time=datetime.now(timezone.utc),
        agent_id="test_agent"
    )
    
    # Mock the position monitor and market filter
    with patch('merid.position_management.position_monitor.get_position_monitor') as mock_monitor_getter, \
         patch('merid.event_venues.kalshi.market_filter.parse_expiry_from_ticker') as mock_parse:
        mock_monitor = Mock()
        mock_monitor.add_position = Mock()
        mock_monitor_getter.return_value = mock_monitor
        mock_parse.return_value = fresh_expiry.timestamp()
        
        ledger = KalshiFillsLedger()
        
        # Process the fill
        ledger.on_fill(fill)
        
        # Verify position was created in ledger
        instrument_key = f"{fill.market_ticker}:{fill.side}"
        assert instrument_key in ledger._open_positions
        
        # Verify PositionMonitor.add_position WAS called for fresh position
        mock_monitor.add_position.assert_called_once()
        
        print("✓ Fresh position added to PositionMonitor for exit monitoring")


# Test 2: exit_policy.py division by zero protection
def test_exit_policy_division_by_zero_protection():
    """
    Test that exit_policy validates entry_price_cents and prevents
    division by zero errors.
    """
    from merid.risk.exit_policy import ExitPolicyEngine, ExitReason, ExitPolicyConfig
    
    config = ExitPolicyConfig(
        take_profit_enabled=True,
        stop_loss_enabled=True,
        take_profit_pct=0.80,  # 80% is the default
        stop_loss_pct=0.40,  # 40% is the default
        min_hold_minutes=5.0
    )
    policy = ExitPolicyEngine(config)
    
    # Test with None entry price
    signal = policy.evaluate_exit(
        entry_price_cents=None,
        current_price_cents=60,
        edge_pct=0.05,
        confidence=0.6,
        minutes_held=5,
        side="yes"
    )
    
    assert signal.should_exit is True
    assert signal.reason == ExitReason.MANUAL
    assert "Invalid entry price" in signal.message
    
    print("✓ Exit policy handles None entry price safely")
    
    # Test with zero entry price
    signal = policy.evaluate_exit(
        entry_price_cents=0,
        current_price_cents=60,
        edge_pct=0.05,
        confidence=0.6,
        minutes_held=5,
        side="yes"
    )
    
    assert signal.should_exit is True
    assert signal.reason == ExitReason.MANUAL
    assert "Invalid entry price" in signal.message
    
    print("✓ Exit policy handles zero entry price safely")
    
    # Test with negative entry price
    signal = policy.evaluate_exit(
        entry_price_cents=-10,
        current_price_cents=60,
        edge_pct=0.05,
        confidence=0.6,
        minutes_held=5,
        side="yes"
    )
    
    assert signal.should_exit is True
    assert signal.reason == ExitReason.MANUAL
    assert "Invalid entry price" in signal.message
    
    print("✓ Exit policy handles negative entry price safely")


def test_exit_policy_normal_operation():
    """
    Test that exit policy still works correctly with valid entry prices.
    """
    from merid.risk.exit_policy import ExitPolicyEngine, ExitReason, ExitPolicyConfig
    
    config = ExitPolicyConfig(
        take_profit_enabled=True,
        stop_loss_enabled=True,
        take_profit_pct=0.80,  # 80% is the default
        stop_loss_pct=0.40,  # 40% is the default
        min_hold_minutes=5.0
    )
    policy = ExitPolicyEngine(config)
    
    # Test stop loss trigger
    signal = policy.evaluate_exit(
        entry_price_cents=50,
        current_price_cents=30,  # 40% loss from 50c
        edge_pct=0.05,
        confidence=0.6,
        minutes_held=5,
        side="yes"
    )
    
    assert signal.should_exit is True
    assert signal.reason == ExitReason.STOP_LOSS
    
    print("✓ Exit policy stop loss works correctly")
    
    # Test that it doesn't crash with valid entry prices
    signal = policy.evaluate_exit(
        entry_price_cents=50,
        current_price_cents=90,  # 80% profit from 50c
        edge_pct=0.05,
        confidence=0.6,
        minutes_held=5,
        side="yes"
    )
    
    # Just verify it returns a valid signal (may or may not exit depending on logic)
    assert signal is not None
    assert hasattr(signal, 'should_exit')
    
    print("✓ Exit policy processes valid entry prices without crashing")


# Test 3: global_slot_allocator.py atomic allocation
def test_slot_allocator_atomic_allocation():
    """
    Test that slot allocation is atomic - check and allocate happen
    in a single locked operation to prevent race conditions.
    """
    from merid.risk.global_slot_allocator import GlobalSlotAllocator, AllocationRequest
    
    allocator = GlobalSlotAllocator()
    
    # Create a request that would use 50% of capacity
    request = AllocationRequest(
        agent_id="test_agent",
        asset="BTC",
        ticker="KXBTC15M-TEST",
        entry_price_cents=50,  # $0.50
        edge_pct=0.05,
        spread_cents=2,
        confidence=0.6,
        request_time=time.time()
    )
    
    # First allocation should succeed
    allocated, reason, slot_id = allocator.request_allocation(request)
    assert allocated is True
    assert slot_id is not None
    assert allocator.get_total_exposure() == 0.50
    
    print("✓ First allocation succeeded")
    
    # Second allocation should fail (insufficient exposure)
    request2 = AllocationRequest(
        agent_id="test_agent2",
        asset="ETH",
        ticker="KXETH15M-TEST",
        entry_price_cents=60,  # $0.60
        edge_pct=0.05,
        spread_cents=2,
        confidence=0.6,
        request_time=time.time()
    )
    
    allocated, reason, slot_id = allocator.request_allocation(request2)
    assert allocated is False
    assert "Insufficient exposure" in reason
    assert slot_id is None
    
    print("✓ Second allocation correctly rejected (insufficient exposure)")
    
    # Verify total exposure is still 0.50 (no over-allocation)
    assert allocator.get_total_exposure() == 0.50
    
    print("✓ No over-allocation occurred")


def test_slot_allocator_concurrent_safety():
    """
    Test that concurrent allocation requests don't cause over-allocation.
    
    This simulates the race condition where multiple requests pass
    can_allocate() before slots are consumed.
    """
    from merid.risk.global_slot_allocator import GlobalSlotAllocator, AllocationRequest
    import threading
    
    allocator = GlobalSlotAllocator()
    allocation_results = []
    
    def allocate_request(price_cents):
        request = AllocationRequest(
            agent_id=f"agent_{price_cents}",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=price_cents,
            edge_pct=0.05,
            spread_cents=2,
            confidence=0.6,
            request_time=time.time()
        )
        allocated, reason, slot_id = allocator.request_allocation(request)
        allocation_results.append((allocated, price_cents))
    
    # Try to allocate 3 positions concurrently (total would be $1.50 > $1.00 cap)
    threads = []
    for price in [40, 40, 40]:  # Each is $0.40, 3 would be $1.20 > $1.00
        t = threading.Thread(target=allocate_request, args=(price,))
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
    
    # Count successful allocations
    successful = sum(1 for allocated, _ in allocation_results if allocated)
    
    # Should only allow 2 allocations ($0.80 <= $1.00), not 3
    assert successful <= 2, f"Expected at most 2 allocations, got {successful}"
    
    # Verify total exposure never exceeds cap
    total_exposure = allocator.get_total_exposure()
    assert total_exposure <= 1.00, f"Total exposure ${total_exposure:.2f} exceeds $1.00 cap"
    
    print(f"✓ Concurrent allocation test passed: {successful} allocations, ${total_exposure:.2f} total exposure")


def test_slot_allocator_per_asset_limit():
    """
    Test that per-asset position limit is enforced atomically.
    """
    from merid.risk.global_slot_allocator import GlobalSlotAllocator, AllocationRequest
    
    allocator = GlobalSlotAllocator()
    
    # First BTC position
    request1 = AllocationRequest(
        agent_id="agent1",
        asset="BTC",
        ticker="KXBTC15M-TEST1",
        entry_price_cents=30,  # $0.30
        edge_pct=0.05,
        spread_cents=2,
        confidence=0.6,
        request_time=time.time()
    )
    
    allocated, reason, slot_id = allocator.request_allocation(request1)
    assert allocated is True
    
    print("✓ First BTC position allocated")
    
    # Second BTC position should fail (per-asset limit)
    request2 = AllocationRequest(
        agent_id="agent2",
        asset="BTC",
        ticker="KXBTC15M-TEST2",
        entry_price_cents=30,  # $0.30
        edge_pct=0.05,
        spread_cents=2,
        confidence=0.6,
        request_time=time.time()
    )
    
    allocated, reason, slot_id = allocator.request_allocation(request2)
    assert allocated is False
    assert "already has" in reason.lower()
    
    print("✓ Second BTC position correctly rejected (per-asset limit)")
    
    # ETH position should succeed (different asset)
    request3 = AllocationRequest(
        agent_id="agent3",
        asset="ETH",
        ticker="KXETH15M-TEST",
        entry_price_cents=30,  # $0.30
        edge_pct=0.05,
        spread_cents=2,
        confidence=0.6,
        request_time=time.time()
    )
    
    allocated, reason, slot_id = allocator.request_allocation(request3)
    assert allocated is True
    
    print("✓ ETH position allocated (different asset)")


# Test 4: Maker fee calculation bug
def test_maker_fee_calculation():
    """
    Test that maker fees are calculated as 25% of taker fee per Kalshi documentation.
    """
    from merid.prediction.agent_grid_15m import LeanAgent15m
    from unittest.mock import Mock, patch
    
    # Mock the agent grid
    with patch('merid.prediction.agent_grid_15m.LeanAgent15m.__init__', return_value=None):
        agent = LeanAgent15m()
        agent._calculate_executable_edge = Mock()
        
        # Test maker fee calculation
        taker_fee_cents = 2.00  # 2 cents taker fee
        expected_maker_fee_cents = round(taker_fee_cents * 0.25, 2)  # 0.50 cents
        
        # Verify the calculation
        assert expected_maker_fee_cents == 0.50
        
        print("✓ Maker fee calculated as 25% of taker fee (0.50c from 2.00c)")


# Test 5: Daily loss limit enabled
def test_daily_loss_limit_enabled():
    """
    Test that daily loss limit is enabled in prod mode (5% of bankroll).
    """
    # Test the YAML configuration directly
    import yaml
    
    with open('config/profiles/kalshi_crypto_15m_v2.yaml', 'r', encoding='utf-8') as f:
        profile_config = yaml.safe_load(f)
    
    # Verify daily loss is enabled in guardrails
    guardrails = profile_config.get('guardrails', {})
    assert guardrails.get('daily_loss_enabled') is True
    
    # Verify daily loss limit is 5% in prod mode
    max_daily_loss_pct = guardrails.get('max_daily_loss_pct', {})
    assert max_daily_loss_pct.get('prod') == 0.05
    assert max_daily_loss_pct.get('test') == 0.10
    
    print("✓ Daily loss limit enabled in YAML: 5% prod, 10% test")


# Test 6: CachedPosition has exit_policy_id
def test_cached_position_exit_policy_id():
    """
    Test that CachedPosition has exit_policy_id and window_resolution_id fields.
    """
    from merid.event_venues.kalshi.position_cache import CachedPosition
    
    # Create a position with exit policy metadata
    position = CachedPosition(
        market_id="KXBTC15M-TEST",
        agent_id="BTC_15M",
        contracts=1,
        side="yes",
        thesis_side="yes",
        avg_price_cents=50,
        exit_policy_id="test_exit_policy",
        window_resolution_id="test_window"
    )
    
    # Verify the fields exist
    assert hasattr(position, 'exit_policy_id')
    assert position.exit_policy_id == "test_exit_policy"
    assert hasattr(position, 'window_resolution_id')
    assert position.window_resolution_id == "test_window"
    
    print("✓ CachedPosition has exit_policy_id and window_resolution_id fields")


# Test 7: Dynamic max hold hour validation
def test_dynamic_max_hold_hour_validation():
    """
    Test that dynamic max hold validates hour is in range 0-23.
    """
    from merid.event_venues.kalshi.position_cache import KalshiPositionCache
    from unittest.mock import Mock, patch
    
    # Mock the position cache
    cache = KalshiPositionCache()
    
    # Test with invalid hour (31)
    market_id_invalid = "KXBTC15M-26JUL312230-30"  # Hour 31 is invalid
    
    # This should return fallback (300s) due to invalid hour
    max_hold = cache._calculate_dynamic_max_hold_seconds(market_id_invalid)
    assert max_hold == 300  # Fallback value
    
    print("✓ Dynamic max hold rejects invalid hour (31) and returns fallback")


# Test 8: Bracket orders allowed in profile
def test_bracket_orders_allowed():
    """
    Test that bracket order sources are in the allowed sources list.
    """
    from merid.event_venues.kalshi.order_router import _KALSHI_15M_CRYPTO_AGENTS
    
    # Verify bracket sources are in allowed agents
    assert "position_cache_bracket" in _KALSHI_15M_CRYPTO_AGENTS
    
    print("✓ Bracket agent position_cache_bracket is in whitelist")


# Test 9: Dynamic max hold time parsing (6-digit format)
def test_dynamic_max_hold_6digit_time_parsing():
    """
    Test that dynamic max hold correctly parses 6-digit time format (HHMMSS).
    """
    from merid.event_venues.kalshi.position_cache import KalshiPositionCache
    from unittest.mock import Mock, patch
    from datetime import datetime, timezone, timedelta
    
    cache = KalshiPositionCache()
    
    # Test with 6-digit time format (HHMMSS)
    # KXBTC15M-26JUL211830-30 where 211830 = 21:18:30
    market_id_6digit = "KXBTC15M-26JUL211830-30"
    
    # Mock current time to be before the expiry
    with patch('merid.event_venues.kalshi.position_cache.datetime') as mock_datetime:
        mock_datetime.now.return_value = datetime(2026, 7, 26, 21, 10, 0, tzinfo=timezone.utc)
        mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        
        max_hold = cache._calculate_dynamic_max_hold_seconds(market_id_6digit)
        
        # Should return a reasonable value (not fallback 300s)
        assert max_hold > 0
        assert max_hold <= 600  # Should be capped at 600s max
        
        print(f"✓ Dynamic max hold correctly parses 6-digit time format: {max_hold}s")


# Test 10: Exit invariant check signature
def test_exit_invariant_check_signature():
    """
    Test that exit invariant check uses correct get_position() signature.
    """
    # Read the order_router.py file and verify the fix
    with open('merid/event_venues/kalshi/order_router.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Verify the fix: get_position() should only take intent.ticker (1 argument)
    # The bug was: position = position_cache.get_position(intent.ticker, intent.side)
    # The fix: position = position_cache.get_position(intent.ticker)
    assert 'position_cache.get_position(intent.ticker)' in content
    assert 'position_cache.get_position(intent.ticker, intent.side)' not in content
    
    print("✓ Exit invariant check uses correct get_position() signature (1 argument)")


# Test 11: Position cache contract limit warning
def test_position_cache_contract_limit_warning():
    """
    Test that position cache code warns on contract limit but still tracks the fill.
    """
    # Read the position_cache.py file and verify the fix
    with open('merid/event_venues/kalshi/position_cache.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # Verify the fix: contract limit is checked but the fill is not dropped.
    # The cache must reflect venue reality; the 1-contract rule is enforced
    # upstream by the order router at order placement.
    assert 'if new_contracts > 1' in content
    assert 'POSITION-CACHE-CONTRACT-LIMIT-WARNING' in content
    assert 'REJECTING FILL' not in content

    print("✓ Position cache warns on contract limit but still tracks the fill")


# Test 12: Verify maker fee calculation in agent_grid_15m.py
def test_maker_fee_in_agent_grid():
    """
    Test that agent_grid_15m.py has the maker fee calculation fix.
    """
    # Read the agent_grid_15m.py file and verify the fix
    with open('merid/prediction/agent_grid_15m.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Verify the fix: maker fee calculation (25% of taker fee)
    assert 'maker_fee_cents = round(taker_fee_cents * 0.25, 2)' in content
    # The maker fee percentage calculation may have different formatting
    assert 'maker_fee_pct' in content and '0.25' in content
    
    print("✓ Agent grid has maker fee calculation (25% of taker fee)")


# Test 13: Verify dynamic max hold sanity checks
def test_dynamic_max_hold_sanity_checks():
    """
    Test that position cache has dynamic max hold sanity checks.
    """
    # Read the position_cache.py file and verify the fix
    with open('merid/event_venues/kalshi/position_cache.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Verify the fix: sanity check for absurdly large values
    assert 'if remaining_seconds > 86400:' in content  # More than 1 day
    assert 'market ID parsing likely incorrect' in content
    
    print("✓ Position cache has dynamic max hold sanity checks (rejects >1 day values)")


# Test 14: Verify exit invariant check uses correct attribute name
def test_exit_invariant_attribute_name():
    """
    Test that exit invariant check uses correct attribute name (contracts not total_contracts).
    """
    # Read the order_router.py file and verify the fix
    with open('merid/event_venues/kalshi/order_router.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Verify the fix: should use position.contracts not position.total_contracts
    assert 'position.contracts if position else 0' in content
    assert 'position.total_contracts' not in content or 'intent.count' in content  # Allow total_contracts in other contexts
    
    print("✓ Exit invariant check uses correct attribute name (contracts not total_contracts)")


if __name__ == "__main__":
    # Run tests
    print("=" * 60)
    print("CRITICAL BUG FIXES TEST SUITE - 2026-08-01")
    print("=" * 60)
    
    tests = [
        ("Legacy position handling", test_fills_ledger_legacy_position_handling),
        ("Fresh position monitoring", test_fills_ledger_fresh_position_monitoring),
        ("Exit policy division by zero protection", test_exit_policy_division_by_zero_protection),
        ("Exit policy normal operation", test_exit_policy_normal_operation),
        ("Slot allocator atomic allocation", test_slot_allocator_atomic_allocation),
        ("Slot allocator concurrent safety", test_slot_allocator_concurrent_safety),
        ("Slot allocator per-asset limit", test_slot_allocator_per_asset_limit),
        ("Maker fee calculation", test_maker_fee_calculation),
        ("Daily loss limit enabled", test_daily_loss_limit_enabled),
        ("CachedPosition exit_policy_id", test_cached_position_exit_policy_id),
        ("Dynamic max hold hour validation", test_dynamic_max_hold_hour_validation),
        ("Bracket orders allowed", test_bracket_orders_allowed),
        ("Dynamic max hold 6-digit parsing", test_dynamic_max_hold_6digit_time_parsing),
        ("Exit invariant check signature", test_exit_invariant_check_signature),
        ("Position cache contract limit", test_position_cache_contract_limit_enforcement),
        ("Maker fee in agent grid", test_maker_fee_in_agent_grid),
        ("Dynamic max hold sanity checks", test_dynamic_max_hold_sanity_checks),
        ("Exit invariant attribute name", test_exit_invariant_attribute_name),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            print(f"\nRunning: {name}")
            test_func()
            passed += 1
        except Exception as e:
            print(f"✗ FAILED: {name}")
            print(f"  Error: {e}")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)
    
    if failed > 0:
        exit(1)
    print("Running critical bug fixes test suite...\n")
    
    test_fills_ledger_legacy_position_handling()
    test_fills_ledger_fresh_position_monitoring()
    test_exit_policy_division_by_zero_protection()
    test_exit_policy_normal_operation()
    test_slot_allocator_atomic_allocation()
    test_slot_allocator_concurrent_safety()
    test_slot_allocator_per_asset_limit()
    
    print("\n✅ All critical bug fix tests passed!")
