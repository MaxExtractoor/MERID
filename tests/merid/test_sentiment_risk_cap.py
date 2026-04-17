"""Sentiment per-asset notional cap."""

from __future__ import annotations

from unittest.mock import patch

from merid.event_venues.kalshi.order_router import OrderIntent
from merid.prediction.venue_gate import TradingMode
from merid.risk.sentiment_risk import sentiment_order_rejection_reason


def test_sentiment_order_rejected_when_over_cap() -> None:
    intent = OrderIntent(
        ticker="KXBTC15M-X",
        side="yes",
        action="buy",
        price_cents=50,
        count=10_000,
        mode=TradingMode.PAPER,
        sentiment_driven=True,
        sentiment_asset="BTC",
        decision_trace_id="sw-test",
    )
    with patch("merid.risk.sentiment_risk._sentiment_cap_usd_for_asset", return_value=10.0):
        with patch("merid.risk.sentiment_risk.sentiment_tagged_notional_usd", return_value=0.0):
            reason = sentiment_order_rejection_reason(intent)
    assert reason is not None
    assert "sentiment_notional_cap" in reason


def test_non_sentiment_orders_not_capped() -> None:
    intent = OrderIntent(
        ticker="KXBTC15M-X",
        side="yes",
        action="buy",
        price_cents=50,
        count=10_000,
        mode=TradingMode.PAPER,
        sentiment_driven=False,
    )
    assert sentiment_order_rejection_reason(intent) is None
