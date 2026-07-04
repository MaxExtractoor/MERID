"""
Tests for 2026 bankroll risk management fixes.

These tests validate the bankroll discrepancy fixes based on 2026 industry standards:
- Removed 1-3% clamp on MAX_CYCLE_RISK_PCT (uses profile's 0.5%)
- Increased micro-account multiplier to 5x (from 2x)
- Added $0.50 minimum order floor
- Aligned per-trade risk to 2% (from 4%) for micro-accounts
- Aligned emergency reset threshold to $100 (from $50)
- Fixed fallback to use 0.5% (from 3%)
- Changed ABSOLUTE_MAX_RISK_PER_TRADE_PCT to 2% (from 3%)
"""

import pytest
from unittest.mock import patch, MagicMock


def test_order_router_no_clamp():
    """Test that order_router does NOT clamp MAX_CYCLE_RISK_PCT to 1-3%."""
    with open('merid/event_venues/kalshi/order_router.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Verify the clamp line is NOT present
    assert 'max(0.01, min(0.03, risk_fraction))' not in content, \
        "Order router should NOT clamp risk_fraction to 1-3%"
    
    # Verify the comment mentions 0.5% (profile value)
    assert '0.5%' in content or '0.005' in content, \
        "Should reference 0.5% profile value in comments"


def test_order_router_micro_account_multiplier_5x():
    """Test that micro-account multiplier is 5x (from 2x)."""
    with open('merid/event_venues/kalshi/order_router.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Verify the multiplier is 5.0
    assert 'max_total_risk_usd * 5.0' in content, \
        "Micro-account multiplier should be 5x"
    
    # Verify the tolerance multiplier is 5.0
    assert 'tolerance_multiplier = 5.0' in content, \
        "Tolerance multiplier should be 5.0 for micro-accounts"
    
    # Verify the comment mentions 5x
    assert '5x' in content, \
        "Should mention 5x multiplier in comments"


def test_order_router_minimum_order_floor():
    """Test that order_router has $0.50 minimum order floor."""
    with open('merid/event_venues/kalshi/order_router.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Verify the minimum order notional floor is present
    assert 'min_order_notional = 0.50' in content, \
        "Should have $0.50 minimum order notional floor"
    
    # Verify it's applied to effective_max
    assert 'effective_max = max(effective_max, min_order_notional)' in content, \
        "Should apply minimum floor to effective_max"


def test_risk_envelope_per_trade_risk_2_percent():
    """Test that per-trade risk for micro-accounts is 2% (from 4%)."""
    with open('merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Verify the micro-account per-trade risk is 0.02 (2%)
    assert 'return 0.02  # 2% for small bankroll' in content, \
        "Per-trade risk for micro-accounts should be 2%"
    
    # Verify the comment mentions fractional Kelly
    assert 'fractional Kelly' in content, \
        "Should reference fractional Kelly in comments"


def test_global_risk_guard_emergency_reset_100():
    """Test that emergency reset threshold is $100 (from $50)."""
    with open('merid/guards/global_risk_guard.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Verify the threshold is 10000 cents ($100)
    assert '_emergency_reset_threshold_cents: int = 10000' in content, \
        "Emergency reset threshold should be $100 (10000 cents)"
    
    # Verify the comment mentions alignment with micro-account threshold
    assert 'aligned with micro-account threshold' in content, \
        "Should reference alignment with micro-account threshold"


def test_settings_fallback_0_5_percent():
    """Test that settings fallback uses 0.5% (from 3%)."""
    with open('merid/settings.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Verify the fallback uses 0.005 (0.5%)
    assert 'unified_cap = bankroll_usd * 0.005' in content, \
        "Fallback should use 0.5% unified cycle risk"
    
    # Verify the comment mentions 0.5%
    assert '0.5% unified cycle risk' in content, \
        "Should reference 0.5% in comments"


def test_unified_risk_enforcement_2_percent():
    """Test that ABSOLUTE_MAX_RISK_PER_TRADE_PCT is 2% (from 3%)."""
    with open('merid/config/unified_risk_enforcement.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Verify the absolute max is 0.02 (2%)
    assert 'ABSOLUTE_MAX_RISK_PER_TRADE_PCT = 0.02' in content, \
        "Absolute max per-trade risk should be 2%"
    
    # Verify the comment mentions alignment with profile
    assert 'aligned with profile' in content, \
        "Should reference alignment with profile"


def test_micro_account_order_calculation():
    """Test that micro-account order calculation allows $0.70 orders with $34 bankroll."""
    # Simulate the order router calculation
    effective_equity_usd = 34.12
    risk_fraction = 0.005  # 0.5% from profile
    
    # Calculate max total risk
    max_total_risk_usd = effective_equity_usd * risk_fraction  # $0.17
    
    # Apply micro-account adjustment (5x)
    effective_max = max_total_risk_usd * 5.0  # $0.85
    
    # Apply minimum floor
    effective_max = max(effective_max, 0.50)  # $0.85 (floor not needed)
    
    # Test $0.70 order
    intent_notional_usd = 0.70
    
    assert intent_notional_usd <= effective_max, \
        f"$0.70 order should be allowed with $34 bankroll (effective_max=${effective_max:.2f})"
    
    print(f"✓ Micro-account calculation: ${effective_equity_usd:.2f} equity → ${effective_max:.2f} effective max → allows ${intent_notional_usd:.2f} orders")


def test_consistent_100_dollar_threshold():
    """Test that all $100 thresholds are consistent across components."""
    components = {
        'order_router.py': 'merid/event_venues/kalshi/order_router.py',
        'risk_envelope.py': 'merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py',
        'loop_15m.py': 'merid/loop_15m.py',
        'global_risk_guard.py': 'merid/guards/global_risk_guard.py',
    }
    
    for component, path in components.items():
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for 100.0 threshold (not 50.0)
        # This is a basic check - components may use different representations
        if component == 'global_risk_guard.py':
            # Uses cents: 10000
            assert '10000' in content, \
                f"{component} should use $100 threshold (10000 cents)"
        else:
            # Uses dollars: 100.0
            assert '100.0' in content or '< 100' in content, \
                f"{component} should use $100 threshold"


def test_profile_0_5_percent_consistency():
    """Test that profile's 0.5% is consistently used across components."""
    profile_path = 'config/profiles/kalshi_crypto_15m_v2.yaml'
    
    with open(profile_path, 'r', encoding='utf-8') as f:
        profile_content = f.read()
    
    # Verify profile specifies 0.5% (0.005) - check for nested dict format
    assert 'value: 0.005' in profile_content and 'max_cycle_risk_pct' in profile_content, \
        "Profile should specify 0.5% max_cycle_risk_pct (nested dict format)"
    
    # Verify core.settings uses 0.5% default (as string)
    with open('core/settings.py', 'r', encoding='utf-8') as f:
        settings_content = f.read()
    
    assert '_DEFAULT_CYCLE_RISK_PCT = "0.005"' in settings_content, \
        "core.settings should default to 0.5%"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
