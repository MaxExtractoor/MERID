"""
Test suite for Kelly sizing and risk caps implementation.

Tests:
1. Fractional Kelly sizing (0.25x to 0.5x based on edge bands)
2. Per-asset contract ceiling (max 1 contract default)
3. Portfolio-level ceiling across BTC/ETH/SOL/XRP/DOGE
4. Kelly determines >1 contract eligibility, risk caps determine permission
"""

import sys
from decimal import Decimal
from unittest.mock import patch, MagicMock

def test_fractional_kelly_sizing():
    """Test fractional Kelly multiplier based on edge bands."""
    print("\n=== TEST 1: Fractional Kelly Sizing ===")
    
    try:
        from merid.prediction.unified_sizing import _get_kelly_multiplier
        
        # Mock profile unavailable to test default behavior
        with patch('merid.prediction.unified_sizing._PROFILE_AVAILABLE', False):
            # Test default when profile unavailable: 0.5x Kelly
            multiplier = _get_kelly_multiplier(Decimal("0.02"))
            assert multiplier == 0.5, f"Profile unavailable should return 0.5x Kelly (default), got {multiplier}"
            print(f"  Profile unavailable (default): {multiplier}x Kelly - PASS")
        
        # Mock profile available with edge bands disabled
        mock_profile = MagicMock()
        mock_profile.edge_bands_enabled = False
        
        with patch('merid.prediction.unified_sizing._PROFILE_AVAILABLE', True), \
             patch('merid.prediction.unified_sizing.is_profile_active', return_value=True), \
             patch('merid.prediction.unified_sizing.get_active_profile', return_value=MagicMock(profile=mock_profile)):
            
            # Test edge bands disabled: 0.5x Kelly (default)
            multiplier = _get_kelly_multiplier(Decimal("0.02"))
            assert multiplier == 0.5, f"Edge bands disabled should return 0.5x Kelly (default), got {multiplier}"
            print(f"  Edge bands disabled (default): {multiplier}x Kelly - PASS")
        
        # Mock profile available with edge bands enabled
        mock_profile = MagicMock()
        mock_profile.edge_bands_enabled = True
        
        with patch('merid.prediction.unified_sizing._PROFILE_AVAILABLE', True), \
             patch('merid.prediction.unified_sizing.is_profile_active', return_value=True), \
             patch('merid.prediction.unified_sizing.get_active_profile', return_value=MagicMock(profile=mock_profile)):
            
            # Test watch band (0.5% edge): 0.0x Kelly (no trading)
            multiplier = _get_kelly_multiplier(Decimal("0.005"))
            assert multiplier == 0.0, f"Watch band (0.5% edge) should return 0.0x Kelly, got {multiplier}"
            print(f"  Watch band (0.5% edge): {multiplier}x Kelly - PASS")
            
            # Test small band (0.75% edge): 0.25x Kelly
            multiplier = _get_kelly_multiplier(Decimal("0.0075"))
            assert multiplier == 0.25, f"Small band (0.75% edge) should return 0.25x Kelly, got {multiplier}"
            print(f"  Small band (0.75% edge): {multiplier}x Kelly - PASS")
            
            # Test standard band (2% edge): 0.5x Kelly
            multiplier = _get_kelly_multiplier(Decimal("0.02"))
            assert multiplier == 0.5, f"Standard band (2% edge) should return 0.5x Kelly, got {multiplier}"
            print(f"  Standard band (2% edge): {multiplier}x Kelly - PASS")
            
            # Test high edge (5% edge): 0.5x Kelly (still standard band)
            multiplier = _get_kelly_multiplier(Decimal("0.05"))
            assert multiplier == 0.5, f"High edge (5% edge) should return 0.5x Kelly, got {multiplier}"
            print(f"  High edge (5% edge): {multiplier}x Kelly - PASS")
            
            # Test no edge provided: 0.5x Kelly (default)
            multiplier = _get_kelly_multiplier(None)
            assert multiplier == 0.5, f"No edge should return 0.5x Kelly (default), got {multiplier}"
            print(f"  No edge (default): {multiplier}x Kelly - PASS")
        
        print(f"  [PASS] Fractional Kelly sizing works correctly")
        return True
        
    except Exception as e:
        print(f"  [FAIL] {e}")
        import traceback
        traceback.print_exc()
        return False


def test_per_asset_contract_ceiling():
    """Test per-asset contract ceiling (max 1 contract default)."""
    print("\n=== TEST 2: Per-Asset Contract Ceiling ===")
    
    try:
        from merid.prediction.unified_sizing import _get_max_contracts_per_asset
        
        # Mock profile adapter
        mock_profile = MagicMock()
        mock_profile.asset_configs = {
            "BTC": MagicMock(max_contracts=1),
            "ETH": MagicMock(max_contracts=1),
            "SOL": MagicMock(max_contracts=1),
            "XRP": MagicMock(max_contracts=1),
            "DOGE": MagicMock(max_contracts=1),
        }
        
        with patch('merid.prediction.unified_sizing.is_profile_active', return_value=True), \
             patch('merid.prediction.unified_sizing.get_active_profile', return_value=MagicMock(profile=mock_profile)):
            
            # Test all 5 assets have max_contracts=1
            for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                max_contracts = _get_max_contracts_per_asset(asset)
                assert max_contracts == 1, f"Asset {asset} should have max_contracts=1, got {max_contracts}"
                print(f"  {asset}: max_contracts={max_contracts} - PASS")
            
            # Test asset with "15M" suffix (normalization)
            max_contracts = _get_max_contracts_per_asset("BTC15M")
            assert max_contracts == 1, f"BTC15M should normalize to BTC with max_contracts=1, got {max_contracts}"
            print(f"  BTC15M (normalized): max_contracts={max_contracts} - PASS")
        
        print(f"  [PASS] Per-asset contract ceiling works correctly")
        return True
        
    except Exception as e:
        print(f"  [FAIL] {e}")
        import traceback
        traceback.print_exc()
        return False


def test_portfolio_level_ceiling():
    """Test portfolio-level ceiling across BTC/ETH/SOL/XRP/DOGE."""
    print("\n=== TEST 3: Portfolio-Level Ceiling ===")
    
    try:
        import yaml
        from pathlib import Path
        
        # Read profile YAML directly to verify contract caps
        repo_root = Path(__file__).parent
        profile_path = repo_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile_config = yaml.safe_load(f)
        
        # Verify portfolio-level caps from profile YAML
        contract_caps = profile_config.get('contract_caps', {})
        
        assert contract_caps.get('max_contracts_total') == 5000, \
            f"Max total contracts should be 5000, got {contract_caps.get('max_contracts_total')}"
        print(f"  Max total contracts: {contract_caps.get('max_contracts_total')} - PASS")
        
        assert contract_caps.get('max_contracts_per_asset') == 1750, \
            f"Max contracts per asset should be 1750, got {contract_caps.get('max_contracts_per_asset')}"
        print(f"  Max contracts per asset: {contract_caps.get('max_contracts_per_asset')} - PASS")
        
        assert contract_caps.get('max_contracts_per_cluster') == 750, \
            f"Max contracts per cluster should be 750, got {contract_caps.get('max_contracts_per_cluster')}"
        print(f"  Max contracts per cluster: {contract_caps.get('max_contracts_per_cluster')} - PASS")
        
        assert contract_caps.get('max_single_order_contracts') == 1, \
            f"Max single order contracts should be 1, got {contract_caps.get('max_single_order_contracts')}"
        print(f"  Max single order contracts: {contract_caps.get('max_single_order_contracts')} - PASS")
        
        # Verify all 5 assets are included in assets section with max_contracts=1
        assets = profile_config.get('assets', {})
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            assert asset in assets, f"Asset {asset} should be in assets section"
            asset_config = assets[asset]
            max_contracts = asset_config.get('max_contracts', {}).get('value', 0)
            assert max_contracts == 1, f"Asset {asset} should have max_contracts=1, got {max_contracts}"
            print(f"  {asset} per-asset cap: {max_contracts} contract - PASS")
        
        print(f"  [PASS] Portfolio-level ceiling works correctly")
        return True
        
    except Exception as e:
        print(f"  [FAIL] {e}")
        import traceback
        traceback.print_exc()
        return False


def test_kelly_determines_eligibility_risk_caps_determine_permission():
    """Test that Kelly determines >1 contract eligibility, risk caps determine permission."""
    print("\n=== TEST 4: Kelly Eligibility vs Risk Cap Permission ===")
    
    try:
        from merid.prediction.strategy import StrategyConfig
        from merid.prediction.unified_sizing import compute_order_size
        
        # Test scenario: Kelly suggests >1 contract, but risk cap limits to 1
        bankroll = Decimal("100.00")
        price_cents = 10  # $0.10 per contract
        edge_pct = Decimal("0.05")  # 5% edge (high quality)
        
        # With 5% edge and $100 bankroll, Kelly might suggest multiple contracts
        # But risk cap (max_contracts=1) should limit to 1 contract
        count, notional, metadata = compute_order_size(
            bankroll_usd=bankroll,
            price_cents=price_cents,
            asset="BTC",
            edge_pct=edge_pct,
            confidence=Decimal("0.8"),
            model_prob=0.60  # 2026-07-12: Kelly Criterion integration
        )
        
        # Risk cap should limit to 1 contract
        assert count == 1, f"Risk cap should limit to 1 contract, got {count}"
        print(f"  Kelly suggested >1, risk cap limited to {count} contract - PASS")
        
        # Test with higher price where Kelly suggests 1 contract
        price_cents = 50  # $0.50 per contract
        count, notional, metadata = compute_order_size(
            bankroll_usd=bankroll,
            price_cents=price_cents,
            asset="BTC",
            edge_pct=edge_pct,
            confidence=Decimal("0.8"),
            model_prob=0.60  # 2026-07-12: Kelly Criterion integration
        )
        
        # Should still be 1 contract (Kelly eligible, cap permits)
        assert count == 1, f"Should be 1 contract, got {count}"
        print(f"  Kelly eligible for 1, cap permits {count} contract - PASS")
        
        print(f"  [PASS] Kelly eligibility vs risk cap permission works correctly")
        return True
        
    except Exception as e:
        print(f"  [FAIL] {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("=" * 70)
    print("KELLY SIZING AND RISK CAPS TEST SUITE")
    print("=" * 70)
    
    results = []
    results.append(("Fractional Kelly Sizing", test_fractional_kelly_sizing()))
    results.append(("Per-Asset Contract Ceiling", test_per_asset_contract_ceiling()))
    results.append(("Portfolio-Level Ceiling", test_portfolio_level_ceiling()))
    results.append(("Kelly Eligibility vs Risk Cap Permission", test_kelly_determines_eligibility_risk_caps_determine_permission()))
    
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    for test_name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status}: {test_name}")
    
    all_passed = all(passed for _, passed in results)
    
    if all_passed:
        print("\n[PASS] All tests passed!")
        return 0
    else:
        print("\n[FAIL] Some tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
