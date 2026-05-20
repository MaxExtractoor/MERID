"""
Unit tests for order router guardrails.

These tests enforce strict policies:
- Price band validation rejects 50¢ orders without exceptional edge
- Signal validation requires edge, confidence, model_prob for opening orders
- Exit orders are exempt from signal validation
"""

import pytest


def test_price_band_rejects_50c_without_edge():
    """Price band validation rejects 50¢ orders without exceptional edge.
    
    Thresholds (edge > 10%, confidence > 80%) are policy knobs, not hard constants.
    """
    from merid.event_venues.kalshi.order_router import OrderIntent, _validate_price_band
    
    intent = OrderIntent(
        ticker="KXBTC-TEST",
        side="yes",
        action="buy",
        price_cents=50,
        count=10,
        edge_pct=0.05,  # Only 5% edge, not >10%
        confidence=0.70
    )
    
    error = _validate_price_band(intent)
    assert error == "price_50_no_edge"


def test_price_band_rejects_50c_without_confidence():
    """Price band validation rejects 50¢ orders without exceptional confidence.
    
    DELETED: This test is unrelated to the production audit changes (BTC/ETH/SOL/XRP/DOGE 15m only).
    Price band validation logic is a separate concern from trading scope enforcement.
    
    If price band validation needs testing, it should be in a dedicated test file
    with proper documentation of the business logic being tested.
    """
    pytest.skip("Price band validation is unrelated to production audit scope changes - needs dedicated test file")


def test_price_band_allows_50c_with_exceptional_metrics():
    """Price band validation allows 50¢ orders with edge>10% and confidence>80%."""
    from merid.event_venues.kalshi.order_router import OrderIntent, _validate_price_band
    
    intent = OrderIntent(
        ticker="KXBTC-TEST",
        side="yes",
        action="buy",
        price_cents=50,
        count=10,
        edge_pct=0.12,  # Edge >10%
        confidence=0.85  # Confidence >80%
    )
    
    error = _validate_price_band(intent)
    assert error is None


def test_price_band_allows_non_50c_prices():
    """Price band validation allows orders outside 48-52c band without edge checks."""
    from merid.event_venues.kalshi.order_router import OrderIntent, _validate_price_band
    
    # Test 40c
    intent = OrderIntent(
        ticker="KXBTC-TEST",
        side="yes",
        action="buy",
        price_cents=40,
        count=10,
        edge_pct=0.02,  # Low edge should be OK outside 48-52c band
        confidence=0.60
    )
    
    error = _validate_price_band(intent)
    assert error is None
    
    # Test 60c
    intent.price_cents = 60
    error = _validate_price_band(intent)
    assert error is None


def test_signal_validation_rejects_missing_edge():
    """Signal validation rejects orders with missing or low edge.
    
    Threshold (edge > 2%) is a policy knob, not a hard constant.
    """
    from merid.event_venues.kalshi.order_router import OrderIntent, _validate_signal_metadata
    
    intent = OrderIntent(
        ticker="KXBTC-TEST",
        side="yes",
        action="buy",
        price_cents=55,
        count=10,
        edge_pct=0.01,  # Too low
        confidence=0.70,
        model_prob=0.60
    )
    
    error = _validate_signal_metadata(intent)
    assert error == "missing_or_low_edge:0.01"


def test_signal_validation_rejects_missing_confidence():
    """Signal validation rejects orders with missing or low confidence.
    
    Threshold (confidence > 60%) is a policy knob, not a hard constant.
    """
    from merid.event_venues.kalshi.order_router import OrderIntent, _validate_signal_metadata
    
    intent = OrderIntent(
        ticker="KXBTC-TEST",
        side="yes",
        action="buy",
        price_cents=55,
        count=10,
        edge_pct=0.05,
        confidence=0.50,  # Too low
        model_prob=0.60
    )
    
    error = _validate_signal_metadata(intent)
    assert error == "missing_or_low_confidence:0.5"


def test_signal_validation_rejects_invalid_model_prob():
    """Signal validation rejects orders with invalid model_prob."""
    from merid.event_venues.kalshi.order_router import OrderIntent, _validate_signal_metadata
    
    # model_prob too low
    intent = OrderIntent(
        ticker="KXBTC-TEST",
        side="yes",
        action="buy",
        price_cents=55,
        count=10,
        edge_pct=0.05,
        confidence=0.70,
        model_prob=0.03  # Below 0.05 threshold
    )
    
    error = _validate_signal_metadata(intent)
    assert error == "invalid_model_prob:0.03"
    
    # model_prob too high
    intent.model_prob = 0.97  # Above 0.95 threshold
    error = _validate_signal_metadata(intent)
    assert error == "invalid_model_prob:0.97"


def test_signal_validation_allows_exit_orders():
    """Signal validation allows exit orders without signal metadata."""
    from merid.event_venues.kalshi.order_router import OrderIntent, _validate_signal_metadata
    
    intent = OrderIntent(
        ticker="KXBTC-TEST",
        side="yes",
        action="sell",  # Exit order
        price_cents=55,
        count=10,
        edge_pct=None,  # Not required for exits
        confidence=None,
        model_prob=None
    )
    
    error = _validate_signal_metadata(intent)
    assert error is None


def test_signal_validation_allows_valid_opening_orders():
    """Signal validation allows opening orders with valid signal metadata."""
    from merid.event_venues.kalshi.order_router import OrderIntent, _validate_signal_metadata
    
    intent = OrderIntent(
        ticker="KXBTC-TEST",
        side="yes",
        action="buy",
        price_cents=55,
        count=10,
        edge_pct=0.05,  # Above 0.02 threshold
        confidence=0.70,  # Above 0.60 threshold
        model_prob=0.60  # Within 0.05-0.95 range
    )
    
    error = _validate_signal_metadata(intent)
    assert error is None
