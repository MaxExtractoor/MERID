#!/usr/bin/env python3
"""
Test to verify live order authorization works correctly.

This test runs as an authorized module (tests.* prefix) to verify
the order router accepts orders from authorized callers.
"""

import asyncio
import time
import pytest


async def test_authorized_caller_can_route():
    """Verify authorized caller can route orders."""
    from merid.event_venues.kalshi.order_router import (
        route_order_async, 
        OrderIntent,
        _is_authorized_caller,
        _get_caller_module,
    )
    from merid.prediction.venue_gate import get_venue_gate
    
    # Verify we're running as an authorized module
    caller = _get_caller_module()
    authorized = _is_authorized_caller(caller)
    
    print(f"\n=== AUTHORIZATION TEST ===")
    print(f"Caller module: {caller}")
    print(f"Is authorized: {authorized}")
    
    # Verify venue gate is in live mode
    gate = get_venue_gate()
    print(f"VenueGate mode: {gate.mode}")
    print(f"VenueGate live_enabled: {gate.live_enabled}")
    print(f"Should simulate: {gate.should_simulate_fill()}")
    
    assert authorized, f"Test module should be authorized: {caller}"
    
    # Create a test order intent (this will be rejected at Kalshi API level
    # due to invalid ticker, but should NOT be rejected for caller authorization)
    intent = OrderIntent(
        ticker='KXBTC15M-TEST-0000',  # Invalid ticker for safety
        side='yes',
        action='buy',
        price_cents=50,
        count=1,
        source='authorization_test',
        agent_id='test_agent',
        snapshot_ts=time.time(),
        decision_trace_id='auth_test_001',
    )
    
    # Try to route - this should NOT fail with unauthorized_caller
    result = await route_order_async(intent)
    
    print(f"\nResult status: {result.status}")
    print(f"Result reason: {result.reason}")
    
    # Should NOT be rejected for caller authorization
    assert "unauthorized_caller" not in result.reason, \
        f"Should not be rejected for caller auth, got: {result.reason}"
    
    # Expected results:
    # - If it gets to Kalshi API: rejected for invalid ticker or auth
    # - If blocked earlier: stale_snapshot, kill_switch, etc.
    # 
    # The key point: it should NOT be "unauthorized_caller"
    
    print("\n=== TEST PASSED ===")
    print("Authorization is working correctly - test module was authorized")
    
    return True


def test_trading_agent_is_authorized():
    """Verify trading_agent module is in authorized list."""
    from merid.event_venues.kalshi.order_router import (
        _is_authorized_caller,
        _ALLOWED_CALLER_PREFIXES,
    )
    
    # Check trading_agent is in the list
    agent_module = "merid.prediction.trading_agent"
    is_auth = _is_authorized_caller(agent_module)
    
    print(f"\n=== TRADING AGENT AUTHORIZATION ===")
    print(f"Module: {agent_module}")
    print(f"Is authorized: {is_auth}")
    print(f"Allowed prefixes: {_ALLOWED_CALLER_PREFIXES}")
    
    assert is_auth, "trading_agent must be authorized"
    assert "merid.prediction.trading_agent" in _ALLOWED_CALLER_PREFIXES, \
        "trading_agent must be in _ALLOWED_CALLER_PREFIXES"
    
    print("=== TEST PASSED ===")
    return True


if __name__ == "__main__":
    # Run sync test
    test_trading_agent_is_authorized()
    
    # Run async test
    asyncio.run(test_authorized_caller_can_route())
