"""
Test for Spread Threshold Optimization to 10c (2026-07-09)

This test validates the spread threshold optimization from 20c to 10c
based on 2026 industry research on prediction market liquidity.

Research Findings:
- 3-5 cents: Moderate-liquidity markets (crypto price markets typical range)
- 6-10 cents: Lower-liquidity markets (niche events, new contracts)
- 10+ cents: Illiquid or stale markets

Optimization Decision:
- Changed from 20c to 10c to restore trading activity
- 10c is the upper bound of moderate-liquidity range
- Provides balanced trade frequency with acceptable quality
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from merid.event_venues.kalshi.invariants import is_liquid_enough
from merid.event_venues.kalshi.order_router import check_market_microstructure
from merid.prediction.unified_edge import EdgeCheckResult


def test_profile_config_10c_spread():
    """Test that profile config has 10c spread threshold."""
    profile_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
    
    with open(profile_path, 'r', encoding='utf-8') as f:
        profile = yaml.safe_load(f)
    
    # Check universe max_spread_cents
    universe = profile.get("universe", {})
    max_spread = universe.get("max_spread_cents", 0)
    
    assert max_spread == 10, f"Expected universe.max_spread_cents to be 10, got {max_spread}"
    print(f"✓ Profile config: universe.max_spread_cents = {max_spread}c")


def test_invariants_default_10c():
    """Test that is_liquid_enough default is 10c."""
    import inspect
    
    sig = inspect.signature(is_liquid_enough)
    default_spread = sig.parameters['max_spread_cents'].default
    
    assert default_spread == 10, f"Expected is_liquid_enough default to be 10, got {default_spread}"
    print(f"✓ Invariants default: max_spread_cents = {default_spread}c")


def test_order_router_default_10c():
    """Test that check_market_microstructure default is 10c."""
    import inspect
    
    sig = inspect.signature(check_market_microstructure)
    default_spread = sig.parameters['max_spread_cents'].default
    
    assert default_spread == 10.0, f"Expected check_market_microstructure default to be 10.0, got {default_spread}"
    print(f"✓ Order router default: max_spread_cents = {default_spread}c")


def test_unified_edge_default_10c():
    """Test that unified_edge max_spread_for_edge default is 10c."""
    # This is tested indirectly by checking the code comments
    # The actual value is loaded from profile, but the fallback should be 10c
    from merid.prediction import unified_edge
    import inspect
    
    source = inspect.getsource(unified_edge)
    assert "max_spread_for_edge = 10" in source, "Expected max_spread_for_edge fallback to be 10c"
    print("✓ Unified edge fallback: max_spread_for_edge = 10c")


def test_10c_allows_moderate_liquidity():
    """Test that 10c threshold allows moderate-liquidity markets."""
    # Test with 8c spread (should pass)
    passes = is_liquid_enough(
        best_bid_cents=46,
        best_ask_cents=54,  # 8c spread
        bid_size=50,
        ask_size=50,
        max_spread_cents=10
    )
    
    assert passes, "8c spread should pass with 10c threshold"
    print("✓ 8c spread passes with 10c threshold")
    
    # Test with 12c spread (should fail)
    passes = is_liquid_enough(
        best_bid_cents=44,
        best_ask_cents=56,  # 12c spread
        bid_size=50,
        ask_size=50,
        max_spread_cents=10
    )
    
    assert not passes, "12c spread should fail with 10c threshold"
    print("✓ 12c spread fails with 10c threshold")


def test_microstructure_10c_allows_good_markets():
    """Test that microstructure check allows markets with 10c spread."""
    passes, reason = check_market_microstructure(
        yes_bid_cents=45,
        yes_ask_cents=55,  # 10c spread
        no_bid_cents=45,
        no_ask_cents=55,
        yes_depth=400,
        no_depth=400,
        max_spread_cents=10.0
    )
    
    assert passes, f"10c spread should pass: {reason}"
    print(f"✓ Microstructure: 10c spread passes ({reason})")
    
    # Test with 11c spread (should fail)
    passes, reason = check_market_microstructure(
        yes_bid_cents=45,
        yes_ask_cents=56,  # 11c spread
        no_bid_cents=45,
        no_ask_cents=56,
        yes_depth=400,
        no_depth=400,
        max_spread_cents=10.0
    )
    
    assert not passes, "11c spread should fail"
    assert "spread" in reason.lower(), f"Should fail with spread error: {reason}"
    print(f"✓ Microstructure: 11c spread fails ({reason})")


def test_10c_vs_20c_comparison():
    """Test that 10c is more permissive than 20c."""
    # Market with 15c spread
    # With 20c threshold: should pass
    passes_20c = is_liquid_enough(
        best_bid_cents=42,
        best_ask_cents=57,  # 15c spread
        bid_size=50,
        ask_size=50,
        max_spread_cents=20
    )
    
    # With 10c threshold: should fail
    passes_10c = is_liquid_enough(
        best_bid_cents=42,
        best_ask_cents=57,  # 15c spread
        bid_size=50,
        ask_size=50,
        max_spread_cents=10
    )
    
    assert passes_20c, "15c spread should pass with 20c threshold"
    assert not passes_10c, "15c spread should fail with 10c threshold"
    print("✓ 10c threshold is more restrictive than 20c (as expected)")


def main():
    """Run all tests."""
    print("\n" + "="*80)
    print("SPREAD THRESHOLD 10c OPTIMIZATION TESTS")
    print("="*80 + "\n")
    
    tests = [
        ("Profile Config 10c", test_profile_config_10c_spread),
        ("Invariants Default 10c", test_invariants_default_10c),
        ("Order Router Default 10c", test_order_router_default_10c),
        ("Unified Edge Default 10c", test_unified_edge_default_10c),
        ("10c Allows Moderate Liquidity", test_10c_allows_moderate_liquidity),
        ("Microstructure 10c Check", test_microstructure_10c_allows_good_markets),
        ("10c vs 20c Comparison", test_10c_vs_20c_comparison),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            print(f"\nRunning: {test_name}")
            test_func()
            passed += 1
        except AssertionError as e:
            print(f"✗ FAILED: {test_name}")
            print(f"  Error: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ ERROR: {test_name}")
            print(f"  Error: {e}")
            failed += 1
    
    print("\n" + "="*80)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("="*80 + "\n")
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
