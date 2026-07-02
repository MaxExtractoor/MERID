#!/usr/bin/env python3
"""
End-to-end test script for unified edge system.

This script performs a comprehensive end-to-end test of the unified edge
system without requiring actual market data or trading.

Usage:
    python scripts/test_unified_edge_e2e.py
"""

import sys
from datetime import datetime, timezone

# Add merid to path
sys.path.insert(0, 'c:\\Dev\\MERID')


def test_imports():
    """Test that all modules can be imported without errors."""
    print("=" * 80)
    print("TEST 1: IMPORTS")
    print("=" * 80)
    
    try:
        from merid.prediction.unified_edge import (
            UnifiedEdgeComputer,
            SpotReference,
            ContractState,
            OrderBookSnapshot,
            EdgeResult,
            PerAssetCalibration,
            CalibrationManager,
        )
        print("✅ unified_edge imports successful")
    except Exception as e:
        print(f"❌ unified_edge import failed: {e}")
        return False
    
    try:
        from merid.prediction.dynamic_risk_routing import (
            DynamicRiskRouter,
            Opportunity,
            RiskAllocation,
        )
        print("✅ dynamic_risk_routing imports successful")
    except Exception as e:
        print(f"❌ dynamic_risk_routing import failed: {e}")
        return False
    
    try:
        from merid.prediction.alignment_degraded_mode import (
            AlignmentDegradedMode,
            get_alignment_degraded_mode,
        )
        print("✅ alignment_degraded_mode imports successful")
    except Exception as e:
        print(f"❌ alignment_degraded_mode import failed: {e}")
        return False
    
    try:
        from merid.event_venues.kalshi.cfb_spot_proxy import (
            CFBSpotProxy,
            get_cfb_spot_proxy,
        )
        print("✅ cfb_spot_proxy imports successful")
    except Exception as e:
        print(f"❌ cfb_spot_proxy import failed: {e}")
        return False
    
    try:
        from merid.startup_validations import validate_unified_edge_configuration
        print("✅ startup_validations imports successful")
    except Exception as e:
        print(f"❌ startup_validations import failed: {e}")
        return False
    
    print("\n✅ All imports successful\n")
    return True


def test_unified_edge_computer():
    """Test UnifiedEdgeComputer basic functionality."""
    print("=" * 80)
    print("TEST 2: UNIFIED EDGE COMPUTER")
    print("=" * 80)
    
    try:
        from merid.prediction.unified_edge import (
            UnifiedEdgeComputer,
            SpotReference,
            ContractState,
        )
        
        computer = UnifiedEdgeComputer()
        print("✅ UnifiedEdgeComputer initialized")
        
        spot_ref = SpotReference(
            asset="BTC",
            price_usd=70000.0,
            timestamp=datetime.now(timezone.utc),
            source="CFB",
            is_rti_proxy=True,
        )
        print("✅ SpotReference created")
        
        contract = ContractState(
            market_id="KXBTC15M-26APR141315-30",
            asset="BTC",
            side="yes",
            strike_price=70000.0,
            mid_price_cents=5000,
            time_to_expiry_seconds=600,
            orderbook=None,
        )
        print("✅ ContractState created")
        
        edge_result = computer.compute_edge("BTC", spot_ref, contract, order_size=1)
        print(f"✅ Edge computed: edge={edge_result.edge:.4f}, edge_r={edge_result.edge_risk_adjusted:.4f}")
        
        is_aligned, gap_cents = computer.check_alignment("BTC", spot_ref, contract)
        print(f"✅ Alignment check: is_aligned={is_aligned}, gap_cents={gap_cents:.2f}")
        
        print("\n✅ UnifiedEdgeComputer test passed\n")
        return True
        
    except Exception as e:
        print(f"❌ UnifiedEdgeComputer test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_dynamic_risk_router():
    """Test DynamicRiskRouter basic functionality."""
    print("=" * 80)
    print("TEST 3: DYNAMIC RISK ROUTER")
    print("=" * 80)
    
    try:
        from merid.prediction.dynamic_risk_routing import (
            DynamicRiskRouter,
            Opportunity,
        )
        
        router = DynamicRiskRouter(total_risk_budget_usd=300.0)
        print("✅ DynamicRiskRouter initialized")
        
        opportunities = [
            Opportunity("BTC", "market1", 1.5, 10.0),
            Opportunity("ETH", "market2", 2.0, 10.0),
            Opportunity("SOL", "market3", 1.0, 10.0),
        ]
        print("✅ Opportunities created")
        
        ranked = router.rank_opportunities(opportunities)
        print(f"✅ Opportunities ranked: {len(ranked)}")
        print(f"   Highest: {ranked[0].asset} (edge_R={ranked[0].edge_r})")
        
        current_exposures = {"BTC": 0.0, "ETH": 0.0, "SOL": 0.0}
        group_utilizations = {"crypto": 0.0}
        remaining_budget = 300.0
        
        allocations = router.allocate_risk(
            opportunities, current_exposures, group_utilizations, remaining_budget
        )
        print(f"✅ Risk allocated: {len(allocations)} allocations")
        total_allocated = sum(a.risk_usd for a in allocations)
        print(f"   Total risk: ${total_allocated:.2f}")
        
        print("\n✅ DynamicRiskRouter test passed\n")
        return True
        
    except Exception as e:
        print(f"❌ DynamicRiskRouter test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_alignment_degraded_mode():
    """Test AlignmentDegradedMode basic functionality."""
    print("=" * 80)
    print("TEST 4: ALIGNMENT DEGRADED MODE")
    print("=" * 80)
    
    try:
        from merid.prediction.alignment_degraded_mode import (
            AlignmentDegradedMode,
            get_alignment_degraded_mode,
        )
        
        mode = AlignmentDegradedMode(
            gap_threshold_cents=50,
            consecutive_failures_threshold=3
        )
        print("✅ AlignmentDegradedMode initialized")
        
        # Test aligned
        is_aligned = mode.check_alignment("BTC", 30.0)
        print(f"✅ Aligned check: is_aligned={is_aligned}")
        
        # Test degraded mode entry
        for i in range(3):
            is_aligned = mode.check_alignment("BTC", 60.0)
            print(f"   Failure {i+1}: is_aligned={is_aligned}, failures={mode.consecutive_failures['BTC']}")
        
        print(f"✅ Degraded mode: is_degraded={mode.is_degraded('BTC')}")
        print(f"✅ Can enter new position: {mode.can_enter_new_position('BTC')}")
        
        # Test restoration
        is_aligned = mode.check_alignment("BTC", 30.0)
        print(f"✅ Restored: is_aligned={is_aligned}, is_degraded={mode.is_degraded('BTC')}")
        
        print("\n✅ AlignmentDegradedMode test passed\n")
        return True
        
    except Exception as e:
        print(f"❌ AlignmentDegradedMode test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_cfb_spot_proxy():
    """Test CFBSpotProxy basic functionality."""
    print("=" * 80)
    print("TEST 5: CFB SPOT PROXY")
    print("=" * 80)
    
    try:
        from merid.event_venues.kalshi.cfb_spot_proxy import (
            CFBSpotProxy,
            get_cfb_spot_proxy,
        )
        
        proxy = get_cfb_spot_proxy()
        print("✅ CFBSpotProxy initialized")
        
        spot = proxy.get_spot_price("BTC")
        print(f"✅ CFB spot (placeholder): {spot}")
        
        proxy.update_composite_price("BTC", 70000.0)
        composite = proxy.get_composite_price("BTC")
        print(f"✅ Composite spot: {composite}")
        
        available = proxy.is_rti_proxy_available()
        print(f"✅ CFB proxy available: {available}")
        
        print("\n✅ CFBSpotProxy test passed\n")
        return True
        
    except Exception as e:
        print(f"❌ CFBSpotProxy test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_startup_validation():
    """Test startup validation."""
    print("=" * 80)
    print("TEST 6: STARTUP VALIDATION")
    print("=" * 80)
    
    try:
        from merid.startup_validations import validate_unified_edge_configuration
        import os
        
        # Test with unified edge disabled
        os.environ['MERID_UNIFIED_EDGE_ENABLED'] = 'false'
        os.environ['MERID_CALIBRATION_VERSION'] = 'placeholder'
        
        validate_unified_edge_configuration()
        print("✅ Validation passed (unified edge disabled)")
        
        # Test with unified edge enabled but placeholder (should fail)
        os.environ['MERID_UNIFIED_EDGE_ENABLED'] = 'true'
        try:
            validate_unified_edge_configuration()
            print("❌ Should have failed with placeholder calibration")
            return False
        except Exception as e:
            print(f"✅ Validation correctly failed with placeholder: {e}")
        
        # Test with unified edge enabled and valid version
        os.environ['MERID_CALIBRATION_VERSION'] = 'v1'
        validate_unified_edge_configuration()
        print("✅ Validation passed (unified edge enabled with valid version)")
        
        print("\n✅ Startup validation test passed\n")
        return True
        
    except Exception as e:
        print(f"❌ Startup validation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all end-to-end tests."""
    print("\n" + "=" * 80)
    print("UNIFIED EDGE END-TO-END TEST")
    print("=" * 80)
    print(f"Started at: {datetime.now(timezone.utc).isoformat()}\n")
    
    tests = [
        ("Imports", test_imports),
        ("Unified Edge Computer", test_unified_edge_computer),
        ("Dynamic Risk Router", test_dynamic_risk_router),
        ("Alignment Degraded Mode", test_alignment_degraded_mode),
        ("CFB Spot Proxy", test_cfb_spot_proxy),
        ("Startup Validation", test_startup_validation),
    ]
    
    results = []
    for name, test_fn in tests:
        try:
            result = test_fn()
            results.append((name, result))
        except Exception as e:
            print(f"❌ Test '{name}' crashed: {e}")
            results.append((name, False))
    
    # Summary
    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
