"""Sentiment-tagged fill aggregation."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from merid.event_venues.kalshi.fills_ledger import KalshiFill
from merid.sentiment.sentiment_pnl_attribution import aggregate_sentiment_pnl


def test_aggregate_splits_tagged_vs_untagged() -> None:
    fills = [
        KalshiFill(
            fill_id="a",
            market_ticker="KXBTC15M-X",
            side="yes",
            action="buy",
            count_fp=1,
            yes_price_dollars=Decimal("0.55"),
            decision_trace_id="t1",
            created_time=datetime.now(timezone.utc),
        ),
        KalshiFill(
            fill_id="b",
            market_ticker="KXETH15M-Y",
            side="yes",
            action="buy",
            count_fp=2,
            yes_price_dollars=Decimal("0.50"),
            created_time=datetime.now(timezone.utc),
        ),
    ]
    r = aggregate_sentiment_pnl(fills=fills)
    assert r["sentiment_tagged_fills"] == 1
    assert r["untagged_fills"] == 1
    assert "BTC" in r["by_asset"] or "UNKNOWN" in r["by_asset"]
