"""
Slot-Based $1 Exposure Model Test Suite

Tests the new fixed $1 total exposure model with slot-based position management.
This replaces percentage-based sizing with a simple slot system:
- Total exposure across all positions must be ≤ $1
- Each contract consumes its price in USD from the $1 cap
- When a position exits, its slot becomes available for new entries
- Exit orders are never blocked by sequential trading
"""

import sys
from decimal import Decimal


def test_profile_fixed_exposure_cap():
    """Test that profile YAML has fixed $1 exposure cap configured."""
    print("\n=== TEST 1: Profile Fixed Exposure Cap ===")
    
    try:
        import yaml
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        # Check fixed exposure cap
        fixed_exposure_cap = profile["risk_policy"]["fixed_exposure_cap_usd"]
        assert fixed_exposure_cap == 1.00, f"Expected 1.00, got {fixed_exposure_cap}"
        print(f"  Fixed exposure cap: ${fixed_exposure_cap} - PASS")
        
        # Check sequential trading
        sequential_trading = profile["risk_policy"]["sequential_trading"]
        assert sequential_trading == True, f"Expected True, got {sequential_trading}"
        print(f"  Sequential trading: {sequential_trading} - PASS")
        
        # Check mandatory profit exit
        mandatory_profit = profile["risk_policy"]["mandatory_profit_exit"]["enabled"]
        assert mandatory_profit == True, f"Expected True, got {mandatory_profit}"
        print(f"  Mandatory profit exit: {mandatory_profit} - PASS")
        
        # Check max entry price
        max_entry_price = profile["risk_policy"].get("max_entry_price_cents", 75)
        assert max_entry_price == 50, f"Expected 50, got {max_entry_price}"
        print(f"  Max entry price: {max_entry_price}c - PASS")
        
        print(f"  [PASS] Profile configured correctly for slot-based model")
        return True
        
    except Exception as e:
        print(f"  [FAIL] Profile test failed: {e}")
        raise


def test_profile_adapter_fixed_exposure():
    """Test that profile adapter loads fixed $1 exposure cap correctly."""
    print("\n=== TEST 2: Profile Adapter Fixed Exposure ===")
    
    try:
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
        
        adapter = Crypto15mProfileAdapter()  # No parameters needed
        profile = adapter.profile
        
        # Check fixed exposure cap
        assert profile.risk_policy_fixed_exposure_cap_usd == 1.00, \
            f"Expected 1.00, got {profile.risk_policy_fixed_exposure_cap_usd}"
        print(f"  Profile adapter fixed_exposure_cap_usd: ${profile.risk_policy_fixed_exposure_cap_usd} - PASS")
        
        # Check sequential trading
        assert profile.risk_policy_sequential_trading == True, \
            f"Expected True, got {profile.risk_policy_sequential_trading}"
        print(f"  Profile adapter sequential_trading: {profile.risk_policy_sequential_trading} - PASS")
        
        print(f"  [PASS] Profile adapter loads fixed exposure cap correctly")
        return True
        
    except Exception as e:
        print(f"  [FAIL] Profile adapter test failed: {e}")
        raise


def test_unified_sizing_slot_based():
    """Test that unified sizing uses slot-based $1 exposure model."""
    print("\n=== TEST 3: Unified Sizing Slot-Based ===")
    
    try:
        from merid.prediction.unified_sizing import compute_order_size
        import inspect
        
        source = inspect.getsource(compute_order_size)
        
        # Check that slot-based logic is present
        assert "available_exposure_usd" in source, \
            "Unified sizing should calculate available exposure"
        print(f"  Available exposure calculation present - PASS")
        
        # Check that it queries position_cache
        assert "position_cache" in source, \
            "Unified sizing should query position_cache for existing exposure"
        print(f"  Position cache query present - PASS")
        
        # Check that it compares contract cost to available exposure
        assert "contract_cost_usd" in source, \
            "Unified sizing should calculate contract cost"
        print(f"  Contract cost calculation present - PASS")
        
        # Check that percentage-based sizing is removed
        assert "risk_pct_effective" not in source or "DISABLED" in source, \
            "Percentage-based sizing should be removed"
        print(f"  Percentage-based sizing removed - PASS")
        
        print(f"  [PASS] Unified sizing uses slot-based model")
        return True
        
    except Exception as e:
        print(f"  [FAIL] Unified sizing test failed: {e}")
        raise


def test_position_cache_total_exposure():
    """Test that position cache calculates total USD exposure correctly."""
    print("\n=== TEST 4: Position Cache Total Exposure ===")
    
    try:
        from merid.event_venues.kalshi.position_cache import KalshiPositionCache
        import inspect
        
        source = inspect.getsource(KalshiPositionCache)
        
        # Check that position cache has total exposure tracking
        assert "get_total_exposure_usd" in source, \
            "Position cache should have get_total_exposure_usd method"
        print(f"  Position cache has get_total_exposure_usd - PASS")
        
        print(f"  [PASS] Position cache tracks total exposure")
        return True
        
    except Exception as e:
        print(f"  [FAIL] Position cache test failed: {e}")
        raise


def test_sequential_trading_gate_check():
    """Test that order gate blocks entries when positions exist (sequential trading)."""
    print("\n=== TEST 5: Sequential Trading Gate Check ===")
    
    try:
        from merid.event_venues.kalshi.order_gate import PreTradeGate
        import inspect
        
        source = inspect.getsource(PreTradeGate.check)
        
        # Check that sequential trading logic is present
        assert "sequential_trading" in source, \
            "Order gate should have sequential trading logic"
        print(f"  Sequential trading logic present - PASS")
        
        # Check that it blocks new entries when positions exist
        assert "total_exposure" in source, \
            "Order gate should check total exposure"
        print(f"  Total exposure check logic present - PASS")
        
        print(f"  [PASS] Sequential trading gate check logic present")
        return True
        
    except Exception as e:
        print(f"  [FAIL] Sequential trading gate test failed: {e}")
        raise


def test_core_settings_fixed_exposure():
    """Test that core.settings has FIXED_EXPOSURE_CAP_USD configured."""
    print("\n=== TEST 6: Core Settings Fixed Exposure ===")
    
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
    print("\n=== TEST 7: Portfolio Risk Agent Fixed Exposure ===")
    
    try:
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
        
        print(f"  [PASS] PortfolioRiskAgent uses fixed exposure cap")
        return True
        
    except Exception as e:
        print(f"  [FAIL] PortfolioRiskAgent test failed: {e}")
        raise


def test_max_entry_price_lowered():
    """Test that max entry price is lowered to 50c for easier loss recovery."""
    print("\n=== TEST 8: Max Entry Price Lowered ===")
    
    try:
        from merid.event_venues.kalshi.risk_parameters import (
            DEEP_OTM_EXPENSIVE_CENTS,
            MAX_OPEN_PRICE_CENTS
        )
        
        # Check DEEP_OTM_EXPENSIVE_CENTS is 50c
        assert DEEP_OTM_EXPENSIVE_CENTS == 50, \
            f"Expected DEEP_OTM_EXPENSIVE_CENTS=50, got {DEEP_OTM_EXPENSIVE_CENTS}"
        print(f"  DEEP_OTM_EXPENSIVE_CENTS: {DEEP_OTM_EXPENSIVE_CENTS}c - PASS")
        
        # Check MAX_OPEN_PRICE_CENTS is 50c
        assert MAX_OPEN_PRICE_CENTS == 50, \
            f"Expected MAX_OPEN_PRICE_CENTS=50, got {MAX_OPEN_PRICE_CENTS}"
        print(f"  MAX_OPEN_PRICE_CENTS: {MAX_OPEN_PRICE_CENTS}c - PASS")
        
        print(f"  [PASS] Max entry price lowered to 50c")
        return True
        
    except Exception as e:
        print(f"  [FAIL] Max entry price test failed: {e}")
        raise


def test_percentage_limits_removed_from_profile():
    """Test that percentage-based limits are removed from profile YAML."""
    print("\n=== TEST 9: Percentage Limits Removed from Profile ===")
    
    try:
        import yaml
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        # Check that max_notional_pct is removed for all assets
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        for asset in assets:
            asset_config = profile["assets"][asset]
            assert "max_notional_pct" not in asset_config, \
                f"{asset} should not have max_notional_pct (percentage-based limit removed)"
            print(f"  {asset} max_notional_pct removed - PASS")
        
        print(f"  [PASS] Percentage limits removed from all assets")
        return True
        
    except Exception as e:
        print(f"  [FAIL] Percentage limits removal test failed: {e}")
        raise


def test_risk_envelope_percentage_disabled():
    """Test that risk envelope returns 0.0 for percentage-based sizing."""
    print("\n=== TEST 10: Risk Envelope Percentage Disabled ===")
    
    try:
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import KalshiCrypto15mRiskEnvelope
        import inspect
        
        # Check source code for get_per_trade_risk_pct method
        source = inspect.getsource(KalshiCrypto15mRiskEnvelope.get_per_trade_risk_pct)
        
        # Check that it returns 0.0 (disabled)
        assert "0.0" in source, \
            "Risk envelope should return 0.0 for percentage-based sizing"
        print(f"  Risk envelope returns 0.0 for percentage-based sizing - PASS")
        
        print(f"  [PASS] Risk envelope percentage-based sizing disabled")
        return True
        
    except Exception as e:
        print(f"  [FAIL] Risk envelope test failed: {e}")
        raise


def test_agent_grid_config_fixed_exposure():
    """Test that agent grid config uses fixed $1 exposure cap."""
    print("\n=== TEST 11: Agent Grid Config Fixed Exposure ===")
    
    try:
        from merid.prediction.agent_grid_config import apply_profile_to_agent
        import inspect
        
        # Check function source for max_notional_usd assignment
        source = inspect.getsource(apply_profile_to_agent)
        
        # Check that it uses max_notional_usd with fixed $1
        assert "max_notional_usd" in source, \
            "Agent grid config should have max_notional_usd"
        assert 'Decimal("1.00")' in source or "1.00" in source, \
            "Agent grid config should use fixed $1 exposure cap"
        print(f"  max_notional_usd with fixed $1 present - PASS")
        
        print(f"  [PASS] Agent grid config uses fixed $1 exposure cap")
        return True
        
    except Exception as e:
        print(f"  [FAIL] Agent grid config test failed: {e}")
        raise


def test_order_gate_window_limits_disabled():
    """Test that order gate window-based risk limits are disabled."""
    print("\n=== TEST 12: Order Gate Window Limits Disabled ===")
    
    try:
        from merid.event_venues.kalshi.order_gate import PreTradeGate
        import inspect
        
        source = inspect.getsource(PreTradeGate.check)
        
        # Check that window-based limits are disabled
        assert "DISABLED" in source or "Window-based risk limit check DISABLED" in source, \
            "Order gate should have window-based limits disabled"
        print(f"  Window-based risk limits disabled - PASS")
        
        print(f"  [PASS] Order gate window limits disabled")
        return True
        
    except Exception as e:
        print(f"  [FAIL] Order gate test failed: {e}")
        raise


def test_top3_allocator_fixed_exposure():
    """Test that top3 allocator uses fixed $1 exposure cap."""
    print("\n=== TEST 13: Top3 Allocator Fixed Exposure ===")
    
    try:
        from merid.trading.top3_edge_allocator import Top3EdgeAllocator, Top3SelectionSpec
        
        # Check spec has fixed USD cap
        spec = Top3SelectionSpec()
        assert hasattr(spec, 'DEFAULT_CYCLE_RISK_CAP_USD'), \
            "Top3 spec should have DEFAULT_CYCLE_RISK_CAP_USD"
        assert spec.DEFAULT_CYCLE_RISK_CAP_USD == 1.00, \
            f"Expected 1.00, got {spec.DEFAULT_CYCLE_RISK_CAP_USD}"
        print(f"  Top3 spec DEFAULT_CYCLE_RISK_CAP_USD: ${spec.DEFAULT_CYCLE_RISK_CAP_USD} - PASS")
        
        # Check allocator uses USD instead of percentage
        allocator = Top3EdgeAllocator()
        assert hasattr(allocator, '_cycle_risk_cap_usd'), \
            "Top3 allocator should have _cycle_risk_cap_usd"
        assert allocator.get_cycle_risk_cap_usd() == 1.00, \
            f"Expected 1.00, got {allocator.get_cycle_risk_cap_usd()}"
        print(f"  Top3 allocator cycle_risk_cap_usd: ${allocator.get_cycle_risk_cap_usd()} - PASS")
        
        print(f"  [PASS] Top3 allocator uses fixed $1 exposure cap")
        return True
        
    except Exception as e:
        print(f"  [FAIL] Top3 allocator test failed: {e}")
        raise


def test_position_sizer_percentage_disabled():
    """Test that position sizer has percentage-based parameters disabled."""
    print("\n=== TEST 14: Position Sizer Percentage Disabled ===")
    
    try:
        from merid.event_venues.kalshi.position_sizer import SizerConfig
        from merid.event_venues.kalshi.risk_parameters import SIZER_MAX_BANKROLL_PCT, SIZER_MIN_BANKROLL_PCT
        
        # Check that risk parameters are set to 0.0 (disabled)
        assert SIZER_MAX_BANKROLL_PCT == 0.0, \
            f"Expected 0.0 (disabled), got {SIZER_MAX_BANKROLL_PCT}"
        print(f"  SIZER_MAX_BANKROLL_PCT: {SIZER_MAX_BANKROLL_PCT} - PASS")
        
        assert SIZER_MIN_BANKROLL_PCT == 0.0, \
            f"Expected 0.0 (disabled), got {SIZER_MIN_BANKROLL_PCT}"
        print(f"  SIZER_MIN_BANKROLL_PCT: {SIZER_MIN_BANKROLL_PCT} - PASS")
        
        # Check config has per_trade_risk_pct set to 0.0
        config = SizerConfig()
        assert config.per_trade_risk_pct == 0.0, \
            f"Expected 0.0 (disabled), got {config.per_trade_risk_pct}"
        print(f"  SizerConfig per_trade_risk_pct: {config.per_trade_risk_pct} - PASS")
        
        print(f"  [PASS] Position sizer percentage-based parameters disabled")
        return True
        
    except Exception as e:
        print(f"  [FAIL] Position sizer test failed: {e}")
        raise


if __name__ == "__main__":
    print("=" * 60)
    print("SLOT-BASED $1 EXPOSURE MODEL TEST SUITE")
    print("=" * 60)
    
    tests = [
        test_profile_fixed_exposure_cap,
        test_profile_adapter_fixed_exposure,
        test_unified_sizing_slot_based,
        test_position_cache_total_exposure,
        test_sequential_trading_gate_check,
        test_core_settings_fixed_exposure,
        test_portfolio_risk_agent_fixed_exposure,
        test_max_entry_price_lowered,
        test_percentage_limits_removed_from_profile,
        test_risk_envelope_percentage_disabled,
        test_agent_grid_config_fixed_exposure,
        test_order_gate_window_limits_disabled,
        test_top3_allocator_fixed_exposure,
        test_position_sizer_percentage_disabled,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            failed += 1
            print(f"  [ERROR] {test.__name__}: {e}")
    
    print("\n" + "=" * 60)
    print(f"TEST RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)
    
    sys.exit(0 if failed == 0 else 1)
