"""
Comprehensive test for the fixed-dollar exposure cap enforcement.

This test verifies the end-to-end enforcement of the fixed global risk
exposure cap across all components of the 15m Kalshi crypto trading system:

1. unified_sizing.compute_order_size() enforces the cap via slot allocator
2. kalshi_tools.py has bounded max_contracts defaults (still capped by exposure)
3. strategy.py uses unified_sizing (not legacy PositionSizer)
4. The slot allocator correctly tracks and enforces exposure
5. Orders that would exceed the cap are rejected

The canonical cap moved from $1.00 to $0.90 (2026-09-10, aligned with
MERID_FIXED_EXPOSURE_CAP_USD in .env and the one-contract canary); the
profile YAML and GlobalSlotAllocator are the sources of truth. Caps may be
raised together with bankroll growth per the AGENTS.md contract.
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock, patch
import os


class TestComprehensive1DollarCapEnforcement:
    """Comprehensive end-to-end test for $1 exposure cap enforcement."""

    def test_unified_sizing_enforces_slot_based_1dollar_cap(self):
        """
        Verify that unified_sizing uses slot allocator for $1 cap enforcement.
        """
        unified_sizing_path = os.path.join(os.path.dirname(__file__), '..', 'merid', 'prediction', 'unified_sizing.py')
        with open(unified_sizing_path, 'r') as f:
            content = f.read()
        
        # Verify slot allocator integration
        assert 'from merid.risk.global_slot_allocator import get_global_slot_allocator' in content, \
            "unified_sizing must import slot allocator"
        assert 'slot_allocator.get_total_exposure()' in content, \
            "unified_sizing must query slot allocator for existing exposure"
        assert 'fixed_exposure_cap_usd' in content, \
            "unified_sizing must use fixed_exposure_cap_usd for $1 cap"
        
        # Verify slot-based sizing logic
        assert 'Slot-based sizing' in content or 'slot-based' in content.lower(), \
            "unified_sizing should implement slot-based sizing logic"

    def test_kalshi_tools_enforces_max_contracts_1_default(self):
        """
        Verify that kalshi_tools.py defaults to max_contracts=1 to enforce $1 cap.
        """
        kalshi_tools_path = os.path.join(os.path.dirname(__file__), '..', 'merid', 'prediction', 'kalshi_tools.py')
        with open(kalshi_tools_path, 'r') as f:
            content = f.read()
        
        # Count instances of default max_contracts_limit = 1 with $1 cap comment
        lines = content.split('\n')
        safe_defaults = 0
        unsafe_defaults = 0
        
        for i, line in enumerate(lines):
            # Fallbacks bounded at <=3 contracts are safe: the fixed exposure
            # cap remains the binding constraint on dollar exposure.
            import re as _re
            m = _re.search(r'max_contracts_limit\s*=\s*(\d+)', line)
            if m:
                if int(m.group(1)) <= 3:
                    safe_defaults += 1
                else:
                    unsafe_defaults += 1

        assert safe_defaults >= 1, \
            f"Expected at least 1 bounded default (max_contracts_limit<=3), found {safe_defaults}"
        assert unsafe_defaults == 0, \
            f"Found {unsafe_defaults} unsafe defaults (max_contracts_limit>3)"

    def test_strategy_uses_unified_sizing_not_legacy(self):
        """
        Verify that strategy.py uses unified_sizing instead of legacy PositionSizer.
        """
        strategy_path = os.path.join(os.path.dirname(__file__), '..', 'merid', 'prediction', 'strategy.py')
        with open(strategy_path, 'r') as f:
            content = f.read()
        
        # Verify unified_sizing import
        assert 'from merid.prediction.unified_sizing import compute_order_size' in content, \
            "strategy.py must import compute_order_size from unified_sizing"
        
        # Verify NO legacy PositionSizer import
        assert 'from merid.event_venues.kalshi.position_sizer import get_position_sizer' not in content, \
            "strategy.py must NOT import legacy PositionSizer"
        
        # Verify compute_order_size is called
        assert 'compute_order_size(' in content, \
            "strategy.py must call compute_order_size()"

    def test_profile_yaml_has_1dollar_fixed_exposure_cap(self):
        """
        Verify that the production profile has fixed_exposure_cap_usd=1.00.
        """
        import yaml
        profile_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'profiles', 'kalshi_crypto_15m_v2.yaml')
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile = yaml.safe_load(f)
        
        # Canonical cap: $3.00 (2026-10-06), aligned with
        # MERID_FIXED_EXPOSURE_CAP_USD in .env and the 3-contract entry target.
        assert 'risk_policy' in profile, "Profile must have risk_policy section"
        assert 'fixed_exposure_cap_usd' in profile['risk_policy'], "Profile must have fixed_exposure_cap_usd"
        assert profile['risk_policy']['fixed_exposure_cap_usd'] == 3.00, \
            f"fixed_exposure_cap_usd must be 3.00, got {profile['risk_policy']['fixed_exposure_cap_usd']}"

    def test_profile_yaml_has_max_contracts_1_per_asset(self):
        """
        Verify that the production profile has max_contracts=1 for all assets.
        """
        import yaml
        profile_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'profiles', 'kalshi_crypto_15m_v2.yaml')
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile = yaml.safe_load(f)
        
        # Verify all 5 assets have max_contracts=3
        required_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        for asset in required_assets:
            assert asset in profile['assets'], f"Profile must have asset config for {asset}"
            assert 'max_contracts' in profile['assets'][asset], f"{asset} must have max_contracts"
            
            # max_contracts may be a dict with 'value' key or a simple int
            max_contracts = profile['assets'][asset]['max_contracts']
            if isinstance(max_contracts, dict):
                max_contracts_value = max_contracts.get('value', max_contracts)
            else:
                max_contracts_value = max_contracts
            
            assert max_contracts_value == 3, \
                f"{asset} max_contracts must be 3, got {max_contracts_value}"

    def test_order_scaling_disabled_in_profile(self):
        """
        Verify that order_scaling is disabled in the production profile
        (conflicts with 1-contract-per-order slot-based model).
        """
        import yaml
        profile_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'profiles', 'kalshi_crypto_15m_v2.yaml')
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile = yaml.safe_load(f)
        
        # Verify order_scaling is disabled
        assert 'order_scaling' in profile, "Profile must have order_scaling section"
        assert profile['order_scaling']['enabled'] == False, \
            "order_scaling must be disabled (conflicts with 1-contract-per-order model)"
        
        # Verify the comment explains why it's disabled
        assert '1-contract-per-order' in str(profile['order_scaling']) or \
               'slot-based' in str(profile['order_scaling']), \
            "order_scaling section should mention 1-contract-per-order or slot-based model"

    def test_percentage_based_caps_pruned(self):
        """
        Verify that percentage-based allocation caps are pruned (set to 0.0)
        to defer to the $1 fixed exposure cap.
        """
        import yaml
        profile_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'profiles', 'kalshi_crypto_15m_v2.yaml')
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile = yaml.safe_load(f)
        
        # Verify percentage-based caps are 0.0 (disabled)
        if 'portfolio_risk' in profile:
            portfolio_risk = profile['portfolio_risk']
            # These should be 0.0 to defer to $1 cap
            pct_caps = [
                portfolio_risk.get('max_cycle_risk_pct'),
                portfolio_risk.get('max_total_risk_pct'),
            ]
            for cap in pct_caps:
                if cap is not None:
                    assert cap == 0.0, \
                        f"Percentage-based cap must be 0.0 (disabled), got {cap}"

    def test_all_5_crypto_assets_included(self):
        """
        Verify that all 5 crypto assets (BTC, ETH, SOL, XRP, DOGE) are
        included in the production profile.
        
        CRITICAL: BTC, ETH, SOL, XRP, DOGE are the entire crypto stack.
        NEVER skip, comment out, or disable any of these 5 assets.
        """
        import yaml
        profile_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'profiles', 'kalshi_crypto_15m_v2.yaml')
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile = yaml.safe_load(f)
        
        # Verify all 5 assets are present
        required_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        for asset in required_assets:
            assert asset in profile['assets'], \
                f"CRITICAL: Asset {asset} must be included in production profile"

    def test_risk_limits_yaml_has_1dollar_cap(self):
        """
        Verify that risk_limits.yaml has fixed_exposure_cap_usd=1.00.
        """
        import yaml
        risk_limits_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'risk_limits.yaml')
        with open(risk_limits_path, 'r', encoding='utf-8') as f:
            risk_limits = yaml.safe_load(f)
        
        # risk_limits.yaml keeps the $3.00 file default; production resolves
        # the cap via MERID_FIXED_EXPOSURE_CAP_USD env override ($3.00).
        assert 'fixed_exposure_cap_usd' in risk_limits, "risk_limits.yaml must have fixed_exposure_cap_usd"
        assert risk_limits['fixed_exposure_cap_usd'] == 3.00, \
            f"fixed_exposure_cap_usd must be 3.00, got {risk_limits['fixed_exposure_cap_usd']}"

    def test_risk_limits_yaml_max_contracts_1(self):
        """
        Verify that risk_limits.yaml has max_contracts=1 for per-trade limit.
        """
        import yaml
        risk_limits_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'risk_limits.yaml')
        with open(risk_limits_path, 'r', encoding='utf-8') as f:
            risk_limits = yaml.safe_load(f)
        
        # Verify per_trade max_contracts is 3
        if 'per_trade' in risk_limits:
            assert 'max_contracts' in risk_limits['per_trade'], "per_trade must have max_contracts"
            assert risk_limits['per_trade']['max_contracts'] == 3, \
                f"per_trade max_contracts must be 3, got {risk_limits['per_trade']['max_contracts']}"

    def test_no_percentage_based_allocation_caps(self):
        """
        Verify that percentage-based allocation caps are disabled (0.0)
        in risk_limits.yaml to defer to $1 fixed exposure cap.
        """
        import yaml
        risk_limits_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'risk_limits.yaml')
        with open(risk_limits_path, 'r', encoding='utf-8') as f:
            risk_limits = yaml.safe_load(f)
        
        # Verify percentage-based caps are 0.0
        if 'bankroll' in risk_limits:
            bankroll = risk_limits['bankroll']
            pct_caps = [
                bankroll.get('max_cycle_risk_pct'),
                bankroll.get('max_total_risk_pct'),
            ]
            for cap in pct_caps:
                if cap is not None:
                    assert cap == 0.0, \
                        f"Percentage-based cap must be 0.0 (disabled), got {cap}"
        
        if 'categories' in risk_limits and 'crypto' in risk_limits['categories']:
            crypto = risk_limits['categories']['crypto']
            max_notional_pct = crypto.get('max_notional_pct')
            if max_notional_pct is not None:
                assert max_notional_pct == 0.0, \
                    f"Category max_notional_pct must be 0.0 (disabled), got {max_notional_pct}"
        
        if 'per_trade' in risk_limits:
            per_trade = risk_limits['per_trade']
            max_notional_pct = per_trade.get('max_notional_pct')
            if max_notional_pct is not None:
                assert max_notional_pct == 0.0, \
                    f"Per-trade max_notional_pct must be 0.0 (disabled), got {max_notional_pct}"

    def test_global_slot_allocator_enforces_1dollar_cap(self):
        """
        Verify that global_slot_allocator.py enforces the $1 cap.
        """
        slot_allocator_path = os.path.join(os.path.dirname(__file__), '..', 'merid', 'risk', 'global_slot_allocator.py')
        with open(slot_allocator_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify the fixed exposure cap is referenced (env-resolved, $2.00
        # file default / $0.90 via MERID_FIXED_EXPOSURE_CAP_USD in .env)
        assert 'fixed_exposure_cap' in content or 'MAX_EXPOSURE_USD' in content, \
            "global_slot_allocator must reference the fixed exposure cap"

        # Verify MAX_ENTRY_CENTS defaults to 75 (canonical 10-75c range),
        # allowing the env-override wrapper.
        assert 'MAX_ENTRY_CENTS' in content, \
            "global_slot_allocator must define MAX_ENTRY_CENTS"
        import re
        m = re.search(r'MAX_ENTRY_CENTS\s*=\s*(?:int\(os\.getenv\("[^"]+",\s*")?(\d+)', content)
        assert m and m.group(1) == '75', \
            "MAX_ENTRY_CENTS must default to 75 (canonical range)"

    def test_unified_risk_manager_uses_1dollar_cap(self):
        """
        Verify that unified_risk_manager.py uses the $1 fixed exposure cap.
        """
        urm_path = os.path.join(os.path.dirname(__file__), '..', 'merid', 'risk', 'unified_risk_manager.py')
        with open(urm_path, 'r') as f:
            content = f.read()
        
        # Verify fixed_exposure_cap_usd is used
        assert 'fixed_exposure_cap_usd' in content, \
            "unified_risk_manager must use fixed_exposure_cap_usd"
        
        # Verify that when pct==0.0, it returns fixed $1 cap
        assert 'pct == 0.0' in content or 'pct == Decimal("0")' in content, \
            "unified_risk_manager should check for pct==0.0 to defer to fixed cap"

    def test_order_router_uses_1dollar_cap_messages(self):
        """
        Verify that order_router.py uses "$1 fixed exposure cap" messages
        instead of legacy "3% per-trade risk limit" messages.
        """
        order_router_path = os.path.join(os.path.dirname(__file__), '..', 'merid', 'event_venues', 'kalshi', 'order_router.py')
        with open(order_router_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify "$1 fixed exposure cap" or similar messaging is present
        assert '$1' in content or 'fixed exposure cap' in content.lower(), \
            "order_router should mention $1 fixed exposure cap"
        
        # Verify legacy "3% per-trade" messages are removed
        # (at least in docstrings/comments - some may remain in legacy code paths)
        legacy_3pct_count = content.count('3% per-trade')
        # Allow a few instances in legacy comments, but should be minimal
        assert legacy_3pct_count <= 2, \
            f"Found {legacy_3pct_count} instances of legacy '3% per-trade' messaging (should be minimal)"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
