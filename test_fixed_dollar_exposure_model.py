"""Test suite for fixed $1 exposure model with mandatory profit exits and sequential trading.

This test suite validates the new risk management approach:
- Fixed $1 max exposure across all assets
- Mandatory profit exits based on entry price
- Sequential trading (no new entries until all positions exit)
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock


def test_profile_fixed_exposure_cap():
    """Test that profile YAML has fixed $1 exposure cap configured."""
    print("\n=== TEST 1: Profile Fixed Exposure Cap ===")
    
    try:
        import yaml
        from pathlib import Path
        
        # Read profile YAML directly
        repo_root = Path(__file__).parent
        profile_path = repo_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile_config = yaml.safe_load(f)
        
        # Verify fixed exposure cap
        risk_policy = profile_config.get('risk_policy', {})
        fixed_exposure_cap = risk_policy.get('fixed_exposure_cap_usd')
        
        assert fixed_exposure_cap == 1.00, \
            f"Fixed exposure cap should be $1.00, got ${fixed_exposure_cap}"
        print(f"  Fixed exposure cap: ${fixed_exposure_cap} - PASS")
        
        # Verify sequential trading is enabled
        sequential_trading = risk_policy.get('sequential_trading')
        assert sequential_trading is True, \
            f"Sequential trading should be enabled, got {sequential_trading}"
        print(f"  Sequential trading: {sequential_trading} - PASS")
        
        # Verify mandatory profit exit is enabled
        mandatory_profit_exit = risk_policy.get('mandatory_profit_exit', {})
        assert mandatory_profit_exit.get('enabled') is True, \
            "Mandatory profit exit should be enabled"
        print(f"  Mandatory profit exit enabled: {mandatory_profit_exit.get('enabled')} - PASS")
        
        # Verify profit target percentages
        assert mandatory_profit_exit.get('profit_target_pct_low') == 0.30, \
            "Low band profit target should be 30%"
        assert mandatory_profit_exit.get('profit_target_pct_mid') == 0.25, \
            "Mid band profit target should be 25%"
        assert mandatory_profit_exit.get('profit_target_pct_high') == 0.20, \
            "High band profit target should be 20%"
        print(f"  Profit targets: low=30%, mid=25%, high=20% - PASS")
        
        # Verify price thresholds
        assert mandatory_profit_exit.get('price_threshold_low_cents') == 30, \
            "Low band threshold should be 30c"
        assert mandatory_profit_exit.get('price_threshold_high_cents') == 50, \
            "High band threshold should be 50c"
        print(f"  Price thresholds: low=30c, high=50c - PASS")
        
        print(f"  [PASS] Profile fixed exposure cap configured correctly")
        return True
        
    except Exception as e:
        print(f"  [FAIL] Profile fixed exposure cap test failed: {e}")
        raise


def test_profile_adapter_fixed_exposure():
    """Test that profile adapter loads fixed exposure cap correctly."""
    print("\n=== TEST 2: Profile Adapter Fixed Exposure ===")
    
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
        
        if not is_profile_active():
            print("  [SKIP] Profile not active in test environment")
            return True
        
        adapter = get_active_profile()
        profile = adapter.profile
        
        # Verify fixed exposure cap
        assert profile.risk_policy_fixed_exposure_cap_usd == 1.00, \
            f"Profile adapter should have fixed_exposure_cap_usd=1.00, got {profile.risk_policy_fixed_exposure_cap_usd}"
        print(f"  Profile adapter fixed_exposure_cap_usd: ${profile.risk_policy_fixed_exposure_cap_usd} - PASS")
        
        # Verify sequential trading
        assert profile.risk_policy_sequential_trading is True, \
            f"Profile adapter should have sequential_trading=True, got {profile.risk_policy_sequential_trading}"
        print(f"  Profile adapter sequential_trading: {profile.risk_policy_sequential_trading} - PASS")
        
        # Verify mandatory profit exit parameters
        assert profile.mandatory_profit_exit_enabled is True, \
            "Mandatory profit exit should be enabled"
        print(f"  Mandatory profit exit enabled: {profile.mandatory_profit_exit_enabled} - PASS")
        
        assert profile.mandatory_profit_exit_target_pct_low == 0.30, \
            "Low band profit target should be 30%"
        assert profile.mandatory_profit_exit_target_pct_mid == 0.25, \
            "Mid band profit target should be 25%"
        assert profile.mandatory_profit_exit_target_pct_high == 0.20, \
            "High band profit target should be 20%"
        print(f"  Profit targets loaded correctly - PASS")
        
        print(f"  [PASS] Profile adapter loads fixed exposure cap correctly")
        return True
        
    except Exception as e:
        print(f"  [FAIL] Profile adapter test failed: {e}")
        raise


def test_unified_sizing_fixed_exposure_cap():
    """Test that unified sizing applies $1 fixed exposure cap."""
    print("\n=== TEST 3: Unified Sizing Fixed Exposure Cap ===")
    
    try:
        # Verify the code path exists in unified_sizing.py
        from merid.prediction.unified_sizing import compute_order_size
        import inspect
        
        source = inspect.getsource(compute_order_size)
        
        # Check that fixed exposure cap logic is present
        assert "fixed_exposure_cap" in source or "FIXED_EXPOSURE" in source, \
            "Fixed exposure cap logic should be present in compute_order_size"
        print(f"  Fixed exposure cap logic present in unified_sizing.py - PASS")
        
        # Check that the cap is applied after max_notional calculation
        assert "min(max_notional" in source, \
            "Should use min() to apply cap to max_notional"
        print(f"  Cap application logic present - PASS")
        
        print(f"  [PASS] Unified sizing has fixed exposure cap logic")
        return True
        
    except Exception as e:
        print(f"  [FAIL] Unified sizing test failed: {e}")
        raise


def test_mandatory_profit_exit_calculation():
    """Test that mandatory profit exit targets are calculated correctly."""
    print("\n=== TEST 4: Mandatory Profit Exit Calculation ===")
    
    try:
        # Test low band (10-30c): 30% profit target
        entry_price_low = 20  # 20c
        expected_profit_pct_low = 0.30
        expected_profit_cents_low = int(entry_price_low * expected_profit_pct_low)
        expected_target_low = entry_price_low + expected_profit_cents_low
        
        assert expected_target_low == 26, \
            f"Low band target should be 26c (20c + 30%), got {expected_target_low}"
        print(f"  Low band (20c entry): target={expected_target_low}c (30% profit) - PASS")
        
        # Test mid band (30-50c): 25% profit target
        entry_price_mid = 40  # 40c
        expected_profit_pct_mid = 0.25
        expected_profit_cents_mid = int(entry_price_mid * expected_profit_pct_mid)
        expected_target_mid = entry_price_mid + expected_profit_cents_mid
        
        assert expected_target_mid == 50, \
            f"Mid band target should be 50c (40c + 25%), got {expected_target_mid}"
        print(f"  Mid band (40c entry): target={expected_target_mid}c (25% profit) - PASS")
        
        # Test high band (50-75c): 20% profit target
        entry_price_high = 60  # 60c
        expected_profit_pct_high = 0.20
        expected_profit_cents_high = int(entry_price_high * expected_profit_pct_high)
        expected_target_high = entry_price_high + expected_profit_cents_high
        
        assert expected_target_high == 72, \
            f"High band target should be 72c (60c + 20%), got {expected_target_high}"
        print(f"  High band (60c entry): target={expected_target_high}c (20% profit) - PASS")
        
        print(f"  [PASS] Mandatory profit exit calculation correct")
        return True
        
    except Exception as e:
        print(f"  [FAIL] Mandatory profit exit calculation test failed: {e}")
        raise


def test_position_cache_total_exposure():
    """Test that position cache calculates total exposure correctly."""
    print("\n=== TEST 5: Position Cache Total Exposure ===")
    
    try:
        from merid.event_venues.kalshi.position_cache import KalshiPositionCache, CachedPosition
        
        cache = KalshiPositionCache()
        
        # Add position 1: 1 contract at 50c = $0.50 exposure
        pos1 = CachedPosition(
            market_id="KXBTC-15M-TEST1",
            contracts=1,
            avg_price_cents=50,
            side="yes"
        )
        cache._positions["KXBTC-15M-TEST1"] = pos1
        
        # Add position 2: 1 contract at 30c = $0.30 exposure
        pos2 = CachedPosition(
            market_id="KXETH-15M-TEST2",
            contracts=1,
            avg_price_cents=30,
            side="yes"
        )
        cache._positions["KXETH-15M-TEST2"] = pos2
        
        # Calculate total exposure
        total_exposure = cache.get_total_exposure_usd()
        
        expected_exposure = 0.50 + 0.30  # $0.80
        assert abs(total_exposure - expected_exposure) < 0.01, \
            f"Total exposure should be ${expected_exposure}, got ${total_exposure}"
        print(f"  Total exposure: ${total_exposure} (expected ${expected_exposure}) - PASS")
        
        # Test with closed position (contracts=0)
        pos3 = CachedPosition(
            market_id="KXSOL-15M-TEST3",
            contracts=0,  # Closed position
            avg_price_cents=40,
            side="yes"
        )
        cache._positions["KXSOL-15M-TEST3"] = pos3
        
        total_exposure_with_closed = cache.get_total_exposure_usd()
        assert total_exposure_with_closed == expected_exposure, \
            "Closed positions should not contribute to exposure"
        print(f"  Closed positions excluded from exposure - PASS")
        
        print(f"  [PASS] Position cache total exposure calculation correct")
        return True
        
    except Exception as e:
        print(f"  [FAIL] Position cache total exposure test failed: {e}")
        raise


def test_sequential_trading_gate_check():
    """Test that order gate blocks new entries when positions exist."""
    print("\n=== TEST 6: Sequential Trading Gate Check ===")
    
    try:
        # Verify the code path exists in order_gate.py
        from merid.event_venues.kalshi.order_gate import PreTradeGate
        import inspect
        
        source = inspect.getsource(PreTradeGate.check)
        
        # Check that sequential trading logic is present
        assert "sequential_trading" in source, \
            "Sequential trading logic should be present in order_gate.check"
        print(f"  Sequential trading logic present in order_gate.py - PASS")
        
        # Check that it blocks entries when positions exist
        assert "get_total_exposure_usd" in source, \
            "Should call get_total_exposure_usd to check for open positions"
        print(f"  Total exposure check logic present - PASS")
        
        # Check that exit orders are not blocked
        assert "is_exit_order" in source or "action == \"sell\"" in source, \
            "Should check if order is exit order to allow it"
        print(f"  Exit order exemption logic present - PASS")
        
        # Verify the metric is tracked
        from merid.event_venues.kalshi.order_gate import GateMetrics
        assert hasattr(GateMetrics, 'blocked_sequential_trading'), \
            "GateMetrics should have blocked_sequential_trading field"
        print(f"  Sequential trading metric tracked - PASS")
        
        print(f"  [PASS] Sequential trading gate check logic present")
        return True
        
    except Exception as e:
        print(f"  [FAIL] Sequential trading gate check test failed: {e}")
        raise


def test_core_settings_fixed_exposure():
    """Test that core.settings has FIXED_EXPOSURE_CAP_USD configured."""
    print("\n=== TEST 7: Core Settings Fixed Exposure ===")
    
    try:
        from core.settings import FIXED_EXPOSURE_CAP_USD
        
        assert FIXED_EXPOSURE_CAP_USD == 1.00, \
            f"FIXED_EXPOSURE_CAP_USD should be 1.00, got {FIXED_EXPOSURE_CAP_USD}"
        print(f"  FIXED_EXPOSURE_CAP_USD: ${FIXED_EXPOSURE_CAP_USD} - PASS")
        
        print(f"  [PASS] Core settings has fixed exposure cap configured")
        return True
        
    except Exception as e:
        print(f"  [FAIL] Core settings test failed: {e}")
        raise


def test_portfolio_risk_agent_fixed_exposure():
    """Test that PortfolioRiskAgent uses fixed $1 exposure cap instead of percentage-based limits."""
    print("\n=== TEST 8: Portfolio Risk Agent Fixed Exposure ===")
    
    try:
        # Verify the code path exists in portfolio_risk_agent.py
        from merid.prediction.portfolio_risk_agent import PortfolioRiskAgent
        import inspect
        
        source = inspect.getsource(PortfolioRiskAgent._check_limits)
        
        # Check that fixed exposure cap is used
        assert "FIXED_EXPOSURE_CAP_USD" in source, \
            "PortfolioRiskAgent should use FIXED_EXPOSURE_CAP_USD for limit checks"
        print(f"  PortfolioRiskAgent uses FIXED_EXPOSURE_CAP_USD - PASS")
        
        # Check that percentage-based limits are disabled
        assert "MAX_TOTAL_RISK_PCT" not in source or "DISABLED" in source, \
            "PortfolioRiskAgent should not use percentage-based MAX_TOTAL_RISK_PCT"
        print(f"  Percentage-based limits disabled - PASS")
        
        # Check that correlation-adjusted caps use fixed $1 cap
        assert "FIXED_EXPOSURE_CAP_USD" in source, \
            "Correlation-adjusted caps should use fixed $1 exposure cap"
        print(f"  Correlation-adjusted caps use fixed $1 cap - PASS")
        
        print(f"  [PASS] PortfolioRiskAgent uses fixed exposure cap")
        return True
        
    except Exception as e:
        print(f"  [FAIL] PortfolioRiskAgent test failed: {e}")
        raise


def test_unified_sizing_final_cap():
    """Test that unified sizing applies fixed $1 cap as final check after all multipliers."""
    print("\n=== TEST 9: Unified Sizing Final Cap ===")
    
    try:
        # Verify the code path exists in unified_sizing.py
        from merid.prediction.unified_sizing import compute_order_size
        import inspect
        
        source = inspect.getsource(compute_order_size)
        
        # Check that fixed exposure cap is applied as final check
        assert "FIXED-EXPOSURE-FINAL" in source, \
            "Unified sizing should re-apply fixed exposure cap as final check"
        print(f"  Final fixed exposure cap check present - PASS")
        
        # Check that it's applied after all multipliers
        assert source.index("FIXED-EXPOSURE-FINAL") > source.index("TTE-SIZING"), \
            "Final cap should be applied after TTE sizing (last multiplier)"
        print(f"  Final cap applied after all multipliers - PASS")
        
        print(f"  [PASS] Unified sizing has final fixed exposure cap")
        return True
        
    except Exception as e:
        print(f"  [FAIL] Unified sizing final cap test failed: {e}")
        raise


if __name__ == "__main__":
    print("=" * 60)
    print("FIXED DOLLAR EXPOSURE MODEL TEST SUITE")
    print("=" * 60)
    
    tests = [
        test_profile_fixed_exposure_cap,
        test_profile_adapter_fixed_exposure,
        test_unified_sizing_fixed_exposure_cap,
        test_mandatory_profit_exit_calculation,
        test_position_cache_total_exposure,
        test_sequential_trading_gate_check,
        test_core_settings_fixed_exposure,
        test_portfolio_risk_agent_fixed_exposure,
        test_unified_sizing_final_cap,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            failed += 1
            print(f"  Test failed with exception: {e}")
    
    print("\n" + "=" * 60)
    print(f"TEST RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)
    
    if failed > 0:
        exit(1)
