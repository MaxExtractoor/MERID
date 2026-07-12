#!/usr/bin/env python3
"""
Test for catalog normalization minutes_to_expiry fix.

This test verifies that MinimalMarket objects have the minutes_to_expiry
field populated correctly, preventing the warning about missing normalized
field during signal generation.
"""

import time
from typing import Optional

# Import MinimalMarket from agent_grid_15m
from merid.prediction.agent_grid_15m import MinimalMarket


def test_minimal_market_has_minutes_to_expiry():
    """Test that MinimalMarket has minutes_to_expiry field."""
    print("\n=== TEST: MinimalMarket Has minutes_to_expiry Field ===\n")
    
    # Create a MinimalMarket with minutes_to_expiry
    market = MinimalMarket(
        market_id="KXBTC15M-26JUL111345-45",
        close_time=time.time() + 900,  # 15 minutes from now
        asset="BTC",
        minutes_to_expiry=15.0
    )
    
    # Verify the field exists and has the correct value
    if hasattr(market, 'minutes_to_expiry'):
        print("✅ PASS: MinimalMarket has minutes_to_expiry field")
    else:
        print("❌ FAIL: MinimalMarket missing minutes_to_expiry field")
        return False
    
    if market.minutes_to_expiry == 15.0:
        print(f"✅ PASS: minutes_to_expiry = {market.minutes_to_expiry:.1f} (expected 15.0)")
    else:
        print(f"❌ FAIL: minutes_to_expiry = {market.minutes_to_expiry:.1f} (expected 15.0)")
        return False
    
    # Verify other fields
    if market.market_id == "KXBTC15M-26JUL111345-45":
        print(f"✅ PASS: market_id = {market.market_id}")
    else:
        print(f"❌ FAIL: market_id = {market.market_id}")
        return False
    
    if market.asset == "BTC":
        print(f"✅ PASS: asset = {market.asset}")
    else:
        print(f"❌ FAIL: asset = {market.asset}")
        return False
    
    return True


def test_minimal_market_minutes_to_expiry_optional():
    """Test that minutes_to_expiry is optional (can be None)."""
    print("\n=== TEST: MinimalMarket minutes_to_expiry Optional ===\n")
    
    # Create a MinimalMarket without minutes_to_expiry (should default to None)
    market = MinimalMarket(
        market_id="KXETH15M-26JUL111345-45",
        close_time=time.time() + 900,
        asset="ETH"
    )
    
    # Verify the field exists and defaults to None
    if hasattr(market, 'minutes_to_expiry'):
        print("✅ PASS: MinimalMarket has minutes_to_expiry field")
    else:
        print("❌ FAIL: MinimalMarket missing minutes_to_expiry field")
        return False
    
    if market.minutes_to_expiry is None:
        print(f"✅ PASS: minutes_to_expiry = None (default)")
    else:
        print(f"❌ FAIL: minutes_to_expiry = {market.minutes_to_expiry:.1f} (expected None)")
        return False
    
    return True


def test_minimal_market_self_reference():
    """Test that MinimalMarket.market property returns self."""
    print("\n=== TEST: MinimalMarket Self Reference ===\n")
    
    market = MinimalMarket(
        market_id="KXSOL15M-26JUL111345-45",
        close_time=time.time() + 900,
        asset="SOL",
        minutes_to_expiry=15.0
    )
    
    # Verify market.market returns self
    if market.market is market:
        print("✅ PASS: market.market returns self")
    else:
        print("❌ FAIL: market.market does not return self")
        return False
    
    # Verify minutes_to_expiry is accessible through market.market
    if market.market.minutes_to_expiry == 15.0:
        print(f"✅ PASS: market.market.minutes_to_expiry = {market.market.minutes_to_expiry:.1f}")
    else:
        print(f"❌ FAIL: market.market.minutes_to_expiry = {market.market.minutes_to_expiry:.1f}")
        return False
    
    return True


if __name__ == "__main__":
    test1 = test_minimal_market_has_minutes_to_expiry()
    test2 = test_minimal_market_minutes_to_expiry_optional()
    test3 = test_minimal_market_self_reference()
    
    print("\n=== TEST SUMMARY ===")
    print(f"Test 1 (Has minutes_to_expiry): {'PASS' if test1 else 'FAIL'}")
    print(f"Test 2 (Optional minutes_to_expiry): {'PASS' if test2 else 'FAIL'}")
    print(f"Test 3 (Self Reference): {'PASS' if test3 else 'FAIL'}")
    
    if test1 and test2 and test3:
        print("\n=== ALL TESTS PASSED ===")
        exit(0)
    else:
        print("\n=== SOME TESTS FAILED ===")
        exit(1)
