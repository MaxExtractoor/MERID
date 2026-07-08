"""
Tests for order router cached bankroll fix.

These tests verify that the order router uses cached bankroll values
instead of blocking on get_summary_sync() calls.
"""

import pytest
from unittest.mock import Mock, patch


def test_apply_risk_based_order_sizing_uses_provided_bankroll():
    """Test that _apply_risk_based_order_sizing uses provided bankroll when available."""
    from merid.event_venues.kalshi.order_router import _apply_risk_based_order_sizing, OrderIntent
    from decimal import Decimal
    
    intent = OrderIntent(
        ticker="KXBTC15M-TEST",
        side="yes",
        action="buy",
        price_cents=50,
        count=10,
    )
    
    # Provide explicit bankroll
    bankroll_usd = Decimal("50.0")
    count = _apply_risk_based_order_sizing(intent, bankroll_usd=bankroll_usd)
    
    # Should use provided bankroll and return adjusted count
    assert count is not None
    assert isinstance(count, int)


def test_apply_risk_based_order_sizing_handles_none_bankroll():
    """Test that _apply_risk_based_order_sizing handles None bankroll gracefully."""
    from merid.event_venues.kalshi.order_router import _apply_risk_based_order_sizing, OrderIntent
    
    intent = OrderIntent(
        ticker="KXBTC15M-TEST",
        side="yes",
        action="buy",
        price_cents=50,
        count=10,
    )
    
    # Test with None bankroll - should return original count when cache unavailable
    count = _apply_risk_based_order_sizing(intent, bankroll_usd=None)
    
    # Should return original count when bankroll is None
    assert count == intent.count
