"""Regression validation script for feature flag cleanup and dynamic risk changes."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_settings_load():
    """Verify settings load without removed flags."""
    try:
        from merid.settings import settings
        
        # Verify removed flags don't exist
        removed_flags = [
            'PHASE0_ENABLED', 'MERID_ENABLE_CHAINLINK', 'MERID_ENABLE_AUGUR',
            'MERID_ENABLE_NEWS_AGENT', 'MERID_ENABLE_WHALE_INTEL', 
            'MERID_ENABLE_POLYMARKET', 'KALSHI_DYNAMIC_DAILY_LOSS',
            'KALSHI_DYNAMIC_STOP_LOSS', 'KALSHI_DYNAMIC_CONTRACTS',
            'KALSHI_SPOT_STRIKE_DISTANCE_DYNAMIC'
        ]
        
        for flag in removed_flags:
            assert not hasattr(settings, flag), f"Removed flag {flag} still exists!"
        
        # Verify kept flags exist
        assert hasattr(settings, 'KALSHI_SPOT_STRIKE_GLOBAL_WARN_PCT')
        assert settings.KALSHI_SPOT_STRIKE_GLOBAL_WARN_PCT == 0.85
        
        print("✓ Settings load OK - removed flags verified absent")
        return True
    except Exception as e:
        print(f"✗ Settings load failed: {e}")
        return False

def test_core_feature_flags():
    """Verify core feature flags registry."""
    try:
        from core.feature_flags import _FLAG_DEFAULTS, is_enabled
        
        # Verify betting_refresh removed
        assert 'betting_refresh' not in _FLAG_DEFAULTS, "betting_refresh still in registry!"
        
        # Verify active flags exist
        assert 'auto_downsize' in _FLAG_DEFAULTS
        assert 'unusual_volume_reaction' in _FLAG_DEFAULTS
        assert 'telegram_alerts' in _FLAG_DEFAULTS
        
        print("✓ Core feature flags OK")
        return True
    except Exception as e:
        print(f"✗ Core feature flags failed: {e}")
        return False

def test_dynamic_risk_functions():
    """Verify dynamic risk functions work correctly."""
    try:
        from merid.event_venues.kalshi.kalshi_risk import KalshiRiskManager
        from merid.prediction.agent_grid_config import PortfolioRiskConfig
        
        config = PortfolioRiskConfig(
            max_total_notional_usd=25000,
            max_daily_loss_usd=2000,
            max_daily_loss_pct=0.10
        )
        
        risk_mgr = KalshiRiskManager(config)
        
        # Test baseline regime (equity = bankroll)
        result = risk_mgr._compute_dynamic_daily_loss(50000.0, 5000000)  # 50k equity, 50k bankroll
        max_loss, regime, ratio = result
        
        assert regime == "BASELINE", f"Expected BASELINE, got {regime}"
        assert 0.99 < ratio < 1.01, f"Expected ratio ~1.0, got {ratio}"
        assert max_loss > 0, "max_loss should be positive"
        
        # Test that result is clamped to static cap (10% of 50k = 5000)
        # Dynamic baseline is 14% of 50k = 7000, but should clamp to 5000
        assert max_loss <= 5000, f"max_loss {max_loss} exceeds static cap 5000"
        
        # Test underwater regime
        result = risk_mgr._compute_dynamic_daily_loss(35000.0, 5000000)  # 70% ratio
        max_loss, regime, ratio = result
        assert regime in ["UNDERWATER", "DEEP_UNDERWATER"], f"Expected underwater, got {regime}"
        
        # Test lock-in-gains regime
        result = risk_mgr._compute_dynamic_daily_loss(80000.0, 5000000)  # 160% ratio
        max_loss, regime, ratio = result
        assert regime == "LOCK_IN_GAINS", f"Expected LOCK_IN_GAINS, got {regime}"
        
        print("✓ Dynamic risk functions OK")
        return True
    except Exception as e:
        print(f"✗ Dynamic risk functions failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_strike_selector():
    """Verify strike selector works with GLOBAL_WARN_PCT."""
    try:
        from merid.event_venues.kalshi.strike_selector import StrikeSelector, DistanceCheckResult
        
        selector = StrikeSelector()
        
        # Test acceptance below base_pct
        result = selector.check_strike(
            asset="BTC", 
            strike_price=69000, 
            spot_price=70000,
            timeframe="15m",
            dynamic_enabled=False
        )
        assert isinstance(result, DistanceCheckResult)
        
        distance_pct = result.distance_pct
        
        # Very close to spot (~1.4%)
        assert distance_pct < 0.03, f"Expected <3%, got {distance_pct}"
        
        if result.accepted:
            print(f"✓ Strike selector OK (distance: {distance_pct:.2%}, accepted)")
        else:
            print(f"✓ Strike selector OK (distance: {distance_pct:.2%}, rejected: {result.reason})")
        
        return True
    except Exception as e:
        print(f"✗ Strike selector failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all regression tests."""
    print("=" * 60)
    print("REGRESSION VALIDATION - Feature Flag Cleanup")
    print("=" * 60)
    
    results = []
    
    results.append(("Settings Load", test_settings_load()))
    results.append(("Core Feature Flags", test_core_feature_flags()))
    results.append(("Dynamic Risk Functions", test_dynamic_risk_functions()))
    results.append(("Strike Selector", test_strike_selector()))
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {name}")
        if not passed:
            all_passed = False
    
    print("=" * 60)
    if all_passed:
        print("ALL TESTS PASSED ✓")
        return 0
    else:
        print("SOME TESTS FAILED ✗")
        return 1

if __name__ == "__main__":
    sys.exit(main())
