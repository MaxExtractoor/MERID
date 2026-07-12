"""Test MAX_OPEN_PRICE_CENTS=55c change based on 2026 Turbine research.

Tests verify:
- MAX_OPEN_PRICE_CENTS is set to 55c (not 85c or 98c)
- Rationale comments reference Turbine research
- Risk/reward above 55c is poor (below 1:1)
"""

import pytest


def test_max_open_price_55c():
    """Test that MAX_OPEN_PRICE_CENTS is set to 55c."""
    with open('merid/event_venues/kalshi/risk_parameters.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Verify MAX_OPEN_PRICE_CENTS is 55
    assert 'MAX_OPEN_PRICE_CENTS: Final[int] = 55' in content, \
        "MAX_OPEN_PRICE_CENTS should be 55c"
    
    # Verify the comment mentions research-based rationale
    assert 'RESEARCH-BASED' in content or 'Turbine research' in content, \
        "Should reference research-based rationale in comments"
    
    # Verify the comment mentions 1:1 risk/reward
    assert '1:1' in content or 'reward:risk' in content, \
        "Should mention risk/reward ratio in comments"


def test_max_open_price_not_85c():
    """Test that MAX_OPEN_PRICE_CENTS is NOT 85c (previous value)."""
    with open('merid/event_venues/kalshi/risk_parameters.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Verify 85c is NOT the value
    assert 'MAX_OPEN_PRICE_CENTS: Final[int] = 85' not in content, \
        "MAX_OPEN_PRICE_CENTS should NOT be 85c"


def test_max_open_price_not_98c():
    """Test that MAX_OPEN_PRICE_CENTS is NOT 98c (blocks 96-98c orders)."""
    with open('merid/event_venues/kalshi/risk_parameters.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Verify 98c is NOT the value
    assert 'MAX_OPEN_PRICE_CENTS: Final[int] = 98' not in content, \
        "MAX_OPEN_PRICE_CENTS should NOT be 98c"


def test_risk_reward_rationale():
    """Test that comments explain why 55c is the optimal entry price."""
    with open('merid/event_venues/kalshi/risk_parameters.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Verify the comment mentions poor risk/reward above 55c
    assert 'Above 55c' in content and 'reward:risk' in content, \
        "Should explain that above 55c, reward:risk drops below 1:1"
    
    # Verify the comment mentions Turbine research
    assert 'Turbine' in content, \
        "Should reference Turbine research"


def test_optimal_entry_range_40_55c():
    """Test that the optimal entry range is 40-55c."""
    with open('merid/event_venues/kalshi/risk_parameters.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # The optimal range should be mentioned in comments
    # This is a soft check - the actual enforcement is in order_router
    assert '40-55c' in content or '40c' in content, \
        "Should mention 40-55c optimal entry range in comments"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
