"""Test fractional contract support for micro-bankroll trading.

This test verifies that the position sizing logic correctly calculates
fractional contracts for small bankrolls ($40-$100 range) using Kalshi's
fractional contract support (CFTC Rule 13.1, Jan 2026).
"""

import pytest
from decimal import Decimal
from merid.formulas import quarter_kelly_size, PositionSizingInputs


def test_fractional_contracts_micro_bankroll():
    """Test that fractional contracts are calculated correctly for micro-bankrolls.
    
    Scenario: $40.15 bankroll, 2% edge, $0.91/contract, 2% Kelly fraction
    Expected: ~0.20 contracts (fractional, not truncated to 0)
    
    Calculation:
    - implied_prob = 91/100 = 0.91
    - win_prob = 0.91 + 0.02 = 0.93
    - win_odds = (1-0.91)/0.91 = 0.0989
    - kelly = (0.93*0.0989 - 0.07)/0.0989 = 0.221
    - fractional_kelly = 0.221 * 0.02 = 0.00442
    - position_cents = 4015 * 0.00442 = 17.74
    - contracts = 17.74 / 91 = 0.195
    """
    # $40.15 bankroll = 4015 cents
    bankroll_cents = 4015
    # 2% edge
    edge = 0.02
    # $0.91/contract = 91 cents
    price_cents = 91
    # 2% Kelly fraction (aligned with unified risk limit)
    fractional_kelly = 0.02
    
    inputs = PositionSizingInputs(
        bankroll_cents=bankroll_cents,
        edge=edge,
        price_cents=price_cents,
        fractional_kelly=fractional_kelly
    )
    
    contracts, kelly_used, warning = quarter_kelly_size(inputs)
    
    # Expected: ~0.20 contracts (calculated above)
    expected_contracts = 0.20
    
    assert contracts > 0, "Fractional contracts should be > 0 for micro-bankroll"
    assert abs(contracts - expected_contracts) < 0.01, f"Expected {expected_contracts}, got {contracts}"
    assert warning is None, f"Should not have warning: {warning}"
    
    print(f"✓ Micro-bankroll fractional contracts: {contracts:.3f} (expected {expected_contracts:.2f})")


def test_fractional_contracts_larger_bankroll():
    """Test that fractional contracts work for larger bankrolls too.
    
    Scenario: $1000 bankroll, 2% edge, $0.50/contract, 2% Kelly fraction
    Expected: ~4.4 contracts (fractional calculation)
    
    Calculation:
    - implied_prob = 50/100 = 0.50
    - win_prob = 0.50 + 0.02 = 0.52
    - win_odds = (1-0.50)/0.50 = 1.0
    - kelly = (0.52*1.0 - 0.48)/1.0 = 0.04
    - fractional_kelly = 0.04 * 0.02 = 0.0008
    - position_cents = 100000 * 0.0008 = 80
    - contracts = 80 / 50 = 1.6
    """
    bankroll_cents = 100000  # $1000
    edge = 0.02
    price_cents = 50  # $0.50
    fractional_kelly = 0.02
    
    inputs = PositionSizingInputs(
        bankroll_cents=bankroll_cents,
        edge=edge,
        price_cents=price_cents,
        fractional_kelly=fractional_kelly
    )
    
    contracts, kelly_used, warning = quarter_kelly_size(inputs)
    
    # Expected: ~1.6 contracts (calculated above)
    expected_contracts = 1.6
    
    assert contracts > 0, "Contracts should be > 0"
    assert abs(contracts - expected_contracts) < 0.1, f"Expected {expected_contracts}, got {contracts}"
    assert warning is None, f"Should not have warning: {warning}"
    
    print(f"✓ Larger bankroll contracts: {contracts:.2f} (expected {expected_contracts:.2f})")


def test_fractional_contracts_zero_edge():
    """Test that zero edge returns zero contracts."""
    bankroll_cents = 4015
    edge = 0.0  # No edge
    price_cents = 91
    fractional_kelly = 0.02
    
    inputs = PositionSizingInputs(
        bankroll_cents=bankroll_cents,
        edge=edge,
        price_cents=price_cents,
        fractional_kelly=fractional_kelly
    )
    
    contracts, kelly_used, warning = quarter_kelly_size(inputs)
    
    assert contracts == 0.0, "Zero edge should return zero contracts"
    assert warning is not None, "Should have warning for zero edge"
    assert "NO_EDGE" in warning, f"Warning should mention NO_EDGE: {warning}"
    
    print(f"✓ Zero edge correctly returns zero contracts")


def test_fractional_contracts_negative_edge():
    """Test that negative edge returns zero contracts."""
    bankroll_cents = 4015
    edge = -0.01  # Negative edge
    price_cents = 91
    fractional_kelly = 0.02
    
    inputs = PositionSizingInputs(
        bankroll_cents=bankroll_cents,
        edge=edge,
        price_cents=price_cents,
        fractional_kelly=fractional_kelly
    )
    
    contracts, kelly_used, warning = quarter_kelly_size(inputs)
    
    assert contracts == 0.0, "Negative edge should return zero contracts"
    assert warning is not None, "Should have warning for negative edge"
    
    print(f"✓ Negative edge correctly returns zero contracts")


def test_fractional_contracts_very_small_bankroll():
    """Test extreme micro-bankroll scenario.
    
    Scenario: $10 bankroll, 2% edge, $0.91/contract, 2% Kelly fraction
    Expected: ~0.05 contracts (fractional, enables trading with $10)
    
    Calculation:
    - implied_prob = 91/100 = 0.91
    - win_prob = 0.91 + 0.02 = 0.93
    - win_odds = (1-0.91)/0.91 = 0.0989
    - kelly = (0.93*0.0989 - 0.07)/0.0989 = 0.221
    - fractional_kelly = 0.221 * 0.02 = 0.00442
    - position_cents = 1000 * 0.00442 = 4.42
    - contracts = 4.42 / 91 = 0.0486
    """
    bankroll_cents = 1000  # $10
    edge = 0.02
    price_cents = 91
    fractional_kelly = 0.02
    
    inputs = PositionSizingInputs(
        bankroll_cents=bankroll_cents,
        edge=edge,
        price_cents=price_cents,
        fractional_kelly=fractional_kelly
    )
    
    contracts, kelly_used, warning = quarter_kelly_size(inputs)
    
    # Expected: ~0.05 contracts (calculated above)
    expected_contracts = 0.05
    
    assert contracts > 0, "Even $10 bankroll should produce > 0 contracts with fractional support"
    assert abs(contracts - expected_contracts) < 0.01, f"Expected {expected_contracts}, got {contracts}"
    
    print(f"✓ Extreme micro-bankroll ($10): {contracts:.3f} contracts (enables trading)")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
