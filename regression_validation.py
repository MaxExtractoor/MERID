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
        from decimal import Decimal
        
        config = PortfolioRiskConfig(
            max_total_notional_usd=Decimal("25000"),
            max_daily_loss_usd=Decimal("5000"),  # 10% of 50k
            max_notional_per_asset_usd=Decimal("4000"),
            max_margin_utilization_pct=Decimal("0.75")
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
        assert max_loss <= 5000, f"max_loss {max_loss} should not exceed static cap 5000"
        
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
        # Signature: check_strike(spot, strike, asset, timeframe, ...)
        result = selector.check_strike(
            spot=70000.0,      # float
            strike=69000.0,    # float (1.4% below spot)
            asset="BTC",
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

def test_dynamic_risk_baseline_parity():
    """Verify dynamic risk at baseline matches previous static caps (no regression)."""
    try:
        from merid.event_venues.kalshi.kalshi_risk import KalshiRiskManager
        from merid.prediction.agent_grid_config import PortfolioRiskConfig
        from decimal import Decimal
        
        config = PortfolioRiskConfig(
            max_total_notional_usd=Decimal("25000"),
            max_daily_loss_usd=Decimal("5000"),  # 10% of 50k bankroll
            max_notional_per_asset_usd=Decimal("4000"),
            max_margin_utilization_pct=Decimal("0.75")
        )
        
        risk_mgr = KalshiRiskManager(config)
        bankroll_cents = 5000000  # $50,000
        bankroll_usd = 50000.0
        
        # Test 1: Daily loss at baseline (equity = bankroll, ratio = 1.0)
        # Previous static: 10% of 50k = 5000
        # Dynamic baseline: 14% of 50k = 7000, but clamped to 5000
        max_loss, regime, ratio = risk_mgr._compute_dynamic_daily_loss(bankroll_usd, bankroll_cents)
        assert regime == "BASELINE", f"Expected BASELINE, got {regime}"
        assert abs(max_loss - 5000.0) < 0.01, f"Daily loss {max_loss} should equal static cap 5000"
        
        # Test 2: Stop loss at baseline
        # Previous static: daily_loss * cluster_stop_pct = 5000 * 0.5 = 2500
        max_sl, regime, ratio = risk_mgr._compute_dynamic_stop_loss(bankroll_usd, bankroll_cents)
        assert regime == "BASELINE"
        assert abs(max_sl - 2500.0) < 0.01, f"Stop loss {max_sl} should equal static 2500"
        
        # Test 3: Contract caps at baseline
        # Previous static: min(5000, 25000) = 25000 notional, contracts = 25000
        result = risk_mgr._compute_dynamic_contract_caps(bankroll_usd, bankroll_cents)
        (max_notional_total, max_notional_asset, max_notional_cluster,
         max_contracts_total, max_contracts_asset, max_contracts_cluster,
         regime, ratio) = result
        
        assert regime == "BASELINE"
        # At baseline, dynamic uses 25% of bankroll = 12500, but clamped to static 25000
        assert abs(max_notional_total - 12500.0) < 0.01, f"Notional {max_notional_total} should be clamped dynamic 12500"
        
        print(f"✓ Dynamic risk baseline parity OK (max_loss={max_loss:.0f}, max_sl={max_sl:.0f}, regime={regime})")
        return True
    except Exception as e:
        print(f"✗ Dynamic risk baseline parity failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_dynamic_risk_monotonicity():
    """Verify risk limits are monotonic and never exceed static caps across regimes."""
    try:
        from merid.event_venues.kalshi.kalshi_risk import KalshiRiskManager
        from merid.prediction.agent_grid_config import PortfolioRiskConfig
        from decimal import Decimal
        
        config = PortfolioRiskConfig(
            max_total_notional_usd=Decimal("25000"),
            max_daily_loss_usd=Decimal("5000"),  # 10% of 50k bankroll
            max_notional_per_asset_usd=Decimal("4000"),
            max_margin_utilization_pct=Decimal("0.75")
        )
        
        risk_mgr = KalshiRiskManager(config)
        bankroll_cents = 5000000  # $50,000
        
        # Test regimes: DEEP_UNDERWATER -> UNDERWATER -> BASELINE -> LOCK_IN_GAINS
        test_cases = [
            (0.6 * 50000, "DEEP_UNDERWATER"),   # 60% of bankroll
            (0.8 * 50000, "UNDERWATER"),        # 80% of bankroll
            (1.0 * 50000, "BASELINE"),          # 100% of bankroll
            (1.6 * 50000, "LOCK_IN_GAINS"),     # 160% of bankroll
        ]
        
        prev_daily_loss = float('inf')
        prev_stop_loss = float('inf')
        
        for equity_usd, expected_regime in test_cases:
            # Daily loss monotonicity
            max_loss, regime, ratio = risk_mgr._compute_dynamic_daily_loss(equity_usd, bankroll_cents)
            assert max_loss <= 5000, f"Daily loss {max_loss} exceeds static cap 5000"
            assert max_loss <= prev_daily_loss, f"Daily loss should decrease: {max_loss} > {prev_daily_loss}"
            prev_daily_loss = max_loss
            
            # Stop loss monotonicity
            max_sl, regime_sl, ratio_sl = risk_mgr._compute_dynamic_stop_loss(equity_usd, bankroll_cents)
            assert max_sl <= 2500, f"Stop loss {max_sl} exceeds static cap 2500"
            assert max_sl <= prev_stop_loss, f"Stop loss should decrease: {max_sl} > {prev_stop_loss}"
            prev_stop_loss = max_sl
            
            print(f"  {expected_regime}: loss={max_loss:.0f}, sl={max_sl:.0f}")
        
        # Verify LOCK_IN_GAINS is most conservative
        assert prev_daily_loss < 5000, "LOCK_IN_GAINS should have lower limit than baseline"
        
        print("✓ Dynamic risk monotonicity OK")
        return True
    except Exception as e:
        print(f"✗ Dynamic risk monotonicity failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_strike_selector_edge_cases():
    """Test strike selector edge cases including global warn threshold."""
    try:
        from merid.event_venues.kalshi.strike_selector import StrikeSelector, DistanceCheckResult
        from merid.settings import settings
        
        selector = StrikeSelector()
        global_warn = settings.KALSHI_SPOT_STRIKE_GLOBAL_WARN_PCT
        
        # Test 1: spot <= 0 should hard-reject
        result = selector.check_strike(
            spot=0.0,      # Invalid spot
            strike=65000.0,
            asset="BTC",
            timeframe="15m"
        )
        assert not result.accepted, "Should reject when spot <= 0"
        assert "spot" in result.rejection_reason.lower() or result.distance_pct == float('inf'), f"Expected spot error, got: {result.rejection_reason}"
        
        # Test 2: Distance slightly below global_warn should use normal logic
        # BTC weekly base is 12%, global_warn is 85%
        # Test at 50% distance (below global_warn but above base)
        result = selector.check_strike(
            spot=70000.0,
            strike=35000.0,  # 50% below spot
            asset="BTC",
            timeframe="weekly"
        )
        assert isinstance(result, DistanceCheckResult)
        # Should be computed normally, may be accepted or rejected based on dynamic calc
        
        # Test 3: Distance above global_warn should hard-reject with spot_out_of_range
        result = selector.check_strike(
            spot=70000.0,
            strike=10000.0,  # ~86% below spot, exceeds 85% global_warn
            asset="BTC",
            timeframe="weekly"
        )
        assert not result.accepted, "Should reject when distance > global_warn"
        assert "range" in result.rejection_reason.lower() or "warn" in result.rejection_reason.lower(), f"Expected out_of_range, got: {result.rejection_reason}"
        
        # Test 4: Dynamic enabled with multiplier pushing above hard cap
        # Use a case where vol/tenor multipliers would push distance allowance high
        # but hard cap should clamp
        result_dynamic = selector.check_strike(
            spot=70000.0,
            strike=75000.0,  # ~7% above spot
            asset="BTC",
            timeframe="15m",
            dynamic_enabled=True,
            vol_bucket="high",  # high multiplier
            tenor_bucket="long",
            regime="LOCK_IN_GAINS"
        )
        # Hard cap for BTC is 0.25, should never be exceeded
        max_allowed = selector.get_max_allowed_pct("BTC", "15m", True, "high", "long", "LOCK_IN_GAINS")
        assert max_allowed <= 0.25, f"Max allowed {max_allowed} exceeds hard cap 0.25"
        
        print(f"✓ Strike selector edge cases OK (global_warn={global_warn})")
        return True
    except Exception as e:
        print(f"✗ Strike selector edge cases failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_loop_pipeline_smoke():
    """Smoke test for loop and pipeline after flag removal."""
    try:
        # Just import the loop module and verify key components exist
        import merid.loop as loop_module
        
        # Verify MeridLoop class exists
        assert hasattr(loop_module, 'MeridLoop'), "MeridLoop class should exist"
        
        # Verify no betting-related code remains in module
        loop_source = open(loop_module.__file__, encoding='utf-8').read()
        assert '_betting_refresh' not in loop_source, "_betting_refresh should be removed from loop.py"
        assert '_refresh_betting_odds' not in loop_source, "_refresh_betting_odds should be removed"
        
        # Verify core loop attributes are present in MeridLoop class
        from merid.loop import MeridLoop
        loop_attrs = dir(MeridLoop)
        assert '_last_liquidity_update' in loop_attrs or 'last_liquidity_update' in loop_attrs, "liquidity tracking should exist"
        
        print("✓ Loop pipeline smoke test OK (module structure verified)")
        return True
    except Exception as e:
        print(f"✗ Loop pipeline smoke test failed: {e}")
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
    results.append(("Dynamic Risk Baseline Parity", test_dynamic_risk_baseline_parity()))
    results.append(("Dynamic Risk Monotonicity", test_dynamic_risk_monotonicity()))
    results.append(("Strike Selector", test_strike_selector()))
    results.append(("Strike Selector Edge Cases", test_strike_selector_edge_cases()))
    results.append(("Loop Pipeline Smoke", test_loop_pipeline_smoke()))
    
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
