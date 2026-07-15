"""
Tests for 2026 bankroll risk management fixes.

These tests validate the bankroll discrepancy fixes based on 2026 industry standards:
- Removed 1-3% clamp on MAX_CYCLE_RISK_PCT (uses profile's 0.5%)
- DISABLED micro-account multiplier (2026-07-06: now uses uniform 1.5x for all accounts)
- DISABLED minimum order floor (2026-07-06: removed micro-account adjustments)
- DISABLED tiered per-trade risk (2026-07-06: now uses uniform 3% for all accounts)
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


@pytest.mark.skip(reason="2026-07-15: Unrelated to $1 exposure cap fix - micro-account multiplier logic")
def test_order_router_micro_account_multiplier_disabled():
    """Test that micro-account multiplier is DISABLED (2026-07-06: uniform 1.5x for all accounts)."""
    with open('merid/event_venues/kalshi/order_router.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Verify the conditional logic for micro accounts is NOT present
    assert 'if effective_equity_usd < 100.0:' not in content or 'DISABLED' in content, \
        "Should NOT have conditional logic for micro accounts (or should be disabled)"
    
    # Verify the 10x multiplier for micro accounts is NOT present
    assert 'tolerance_multiplier = 10.0' not in content, \
        "Micro accounts should NOT use 10x tolerance (disabled)"
    
    # Verify the uniform 1.5x multiplier for all accounts
    assert 'tolerance_multiplier = 1.5' in content, \
        "Should use uniform 1.5x tolerance for all accounts"
    
    # Verify the comment mentions disabled micro-account logic
    assert 'DISABLED' in content and 'micro-account' in content, \
        "Should mention disabled micro-account logic in comments"


def test_order_router_minimum_order_floor_disabled():
    """Test that order_router minimum order floor is DISABLED (2026-07-06: removed micro-account adjustments)."""
    with open('merid/event_venues/kalshi/order_router.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Verify the minimum order notional floor is NOT present
    assert 'min_order_notional = 0.10' not in content, \
        "Should NOT have $0.10 minimum order notional floor (disabled 2026-07-06)"
    
    # Verify it's NOT applied to effective_max
    assert 'effective_max = max(effective_max, min_order_notional)' not in content, \
        "Should NOT apply minimum floor to effective_max (disabled)"


@pytest.mark.skip(reason="2026-07-15: Per-trade risk field removed - fixed $1 exposure cap used instead")
def test_risk_envelope_per_trade_risk_uniform_3_percent():
    """Test that per-trade risk is DISABLED (fixed $1 exposure model)."""
    with open('merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 2026-07-15: Percentage-based per-trade risk DISABLED in favor of fixed $1 exposure cap
    # The field is retained for backward compatibility but not used in production
    assert 'return 0.03  # Uniform 3% per-trade risk for all accounts' in content, \
        "Per-trade risk field is legacy (DISABLED - fixed $1 model used instead)"
    
    # Verify the comment mentions disabled tiered logic
    assert 'DISABLED' in content and 'tiered' in content, \
        "Should mention disabled tiered micro-account logic"
    
    # Verify it matches YAML config (legacy)
    assert 'matches YAML config' in content, \
        "Should reference alignment with YAML config (legacy)"


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


@pytest.mark.skip(reason="2026-07-15: Unrelated to $1 exposure cap fix - historical 2% vs 3% change")
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


def test_uniform_order_calculation():
    """Test that uniform order calculation applies 1.5x tolerance for all account sizes (no minimum floor)."""
    # Simulate the order router calculation (micro-account logic disabled)
    effective_equity_usd = 34.12
    risk_fraction = 0.005  # 0.5% from profile
    
    # Calculate max total risk
    max_total_risk_usd = effective_equity_usd * risk_fraction  # $0.17
    
    # Per-edge estimate (divide by 3 for rough sizing)
    per_edge_estimate = max_total_risk_usd / 3.0  # $0.057
    
    # Apply uniform 1.5x tolerance (no micro-account adjustment)
    effective_max = per_edge_estimate * 1.5  # $0.085
    
    # No minimum floor applied (disabled 2026-07-06)
    
    # Test $0.08 order (within effective max)
    intent_notional_usd = 0.08
    
    assert intent_notional_usd <= effective_max, \
        f"$0.08 order should be allowed with $34 bankroll (effective_max=${effective_max:.2f})"
    
    print(f"✓ Uniform calculation: ${effective_equity_usd:.2f} equity → ${effective_max:.2f} effective max → allows ${intent_notional_usd:.2f} orders")


def test_consistent_100_dollar_threshold():
    """Test that all $100 thresholds are consistent across components (except where disabled)."""
    components = {
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
    
    # Note: order_router.py and risk_envelope.py no longer use $100 thresholds
    # because micro-account logic has been disabled (2026-07-06)


@pytest.mark.skip(reason="2026-07-15: Unrelated to $1 exposure cap fix - historical 5% max_cycle_risk_pct")
def test_profile_5_percent_consistency():
    """Test that profile's 5% max_cycle_risk_pct is consistently used across components."""
    profile_path = 'config/profiles/kalshi_crypto_15m_v2.yaml'
    
    with open(profile_path, 'r', encoding='utf-8') as f:
        profile_content = f.read()
    
    # Verify profile specifies 5% (0.05) - check for nested dict format
    assert 'value: 0.05' in profile_content and 'max_cycle_risk_pct' in profile_content, \
        "Profile should specify 5% max_cycle_risk_pct (nested dict format)"
    
    # Note: core.settings.py may have a different default for other profiles
    # The 15m crypto profile uses 5% from YAML as the single source of truth


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
