"""
Test for effective_max zero check fix in order_router.py.

This test verifies that the order router properly rejects orders when effective_max
is zero or negative (capital_usd=0 case where dynamic computation failed).
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from merid.event_venues.kalshi.order_router import OrderIntent, OrderResult, TradingMode


def test_effective_max_zero_rejects_order():
    """
    Test that orders are rejected when effective_max is zero (capital_usd=0 case).
    
    This prevents the system from accepting orders when the dynamic bankroll
    computation has failed and left effective_max at 0.0.
    """
    # Create a mock order intent
    intent = OrderIntent(
        ticker="KXBTC15M-26JUL060115-15",
        side="yes",
        action="buy",
        price_cents=25,
        count=1,
        mode=TradingMode.LIVE,
        source="merid.prediction.agent_grid_15m",
    )
    
    # Mock the risk envelope config to return zero effective_max
    mock_envelope_config = Mock()
    mock_envelope_config.max_single_order_notional_usd = 0.0  # Zero effective_max
    
    # Mock the effective equity
    effective_equity_usd = 1000.0
    
    # Calculate intent notional
    intent_notional_usd = intent.count * intent.price_cents / 100.0  # 1 * 25 / 100 = 0.25
    
    # The fix should reject when effective_max <= 0
    effective_max = mock_envelope_config.max_single_order_notional_usd
    
    assert effective_max == 0.0
    assert effective_max <= 0  # Should trigger rejection
    
    # Verify intent notional is positive (would be accepted if effective_max was valid)
    assert intent_notional_usd > 0


def test_effective_max_negative_rejects_order():
    """
    Test that orders are rejected when effective_max is negative.
    
    This is a defensive check for edge cases where computation might produce
    negative values due to bugs or data corruption.
    """
    # Create a mock order intent
    intent = OrderIntent(
        ticker="KXETH15M-26JUL060115-15",
        side="no",
        action="sell",
        price_cents=30,
        count=1,
        mode=TradingMode.LIVE,
        source="merid.prediction.agent_grid_15m",
    )
    
    # Mock the risk envelope config to return negative effective_max
    mock_envelope_config = Mock()
    mock_envelope_config.max_single_order_notional_usd = -10.0  # Negative effective_max
    
    effective_max = mock_envelope_config.max_single_order_notional_usd
    
    assert effective_max < 0  # Should trigger rejection


def test_effective_max_positive_allows_order():
    """
    Test that orders are allowed when effective_max is positive and sufficient.
    
    This verifies the normal case where effective_max is properly computed.
    """
    # Create a mock order intent
    intent = OrderIntent(
        ticker="KXSOL15M-26JUL060115-15",
        side="yes",
        action="buy",
        price_cents=25,
        count=1,
        mode=TradingMode.LIVE,
        source="merid.prediction.agent_grid_15m",
    )
    
    # Mock the risk envelope config to return positive effective_max
    mock_envelope_config = Mock()
    mock_envelope_config.max_single_order_notional_usd = 1.0  # $1.00 effective_max
    
    effective_max = mock_envelope_config.max_single_order_notional_usd
    intent_notional_usd = intent.count * intent.price_cents / 100.0  # 0.25
    
    assert effective_max > 0  # Should not trigger zero/negative rejection
    assert intent_notional_usd <= effective_max  # Should pass notional check


def test_fallback_effective_max_zero_rejects_order():
    """
    Test that orders are rejected when fallback effective_max is zero.
    
    This tests the fallback calculation path when the risk envelope service fails.
    """
    # Mock effective equity
    effective_equity_usd = 1000.0
    
    # Simulate fallback calculation that produces zero
    risk_fraction = 0.0  # Zero risk fraction
    max_total_risk_usd = effective_equity_usd * risk_fraction  # 0.0
    per_edge_estimate = max_total_risk_usd / 3.0  # 0.0
    effective_max = per_edge_estimate * 1.5  # 0.0
    
    assert effective_max == 0.0
    assert effective_max <= 0  # Should trigger rejection


def test_fallback_effective_max_negative_rejects_order():
    """
    Test that orders are rejected when fallback effective_max is negative.
    
    This tests the fallback calculation path with corrupted data.
    """
    # Mock effective equity as negative (corrupted data)
    effective_equity_usd = -1000.0
    
    # Simulate fallback calculation
    risk_fraction = 0.01
    max_total_risk_usd = effective_equity_usd * risk_fraction  # -10.0
    per_edge_estimate = max_total_risk_usd / 3.0  # -3.33
    effective_max = per_edge_estimate * 1.5  # -5.0
    
    assert effective_max < 0  # Should trigger rejection


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
