"""Tests for KalshiWebSocketBridge event-bus wiring and subscriptions."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from merid.event_venues.base import QuoteEvent
from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge


@pytest.fixture
def bridge() -> KalshiWebSocketBridge:
    ws = MagicMock()
    ws.connect = AsyncMock()
    ws.subscribe_quotes = AsyncMock()
    ws.subscribe_trades = AsyncMock()
    ws.subscribe_orderbook = AsyncMock()
    ws.listen = AsyncMock()
    ws.close = AsyncMock()
    ws.stats = MagicMock(return_value={})
    return KalshiWebSocketBridge(ws=ws)


@pytest.mark.asyncio
async def test_subscribe_adds_orderbook_channels(bridge: KalshiWebSocketBridge) -> None:
    await bridge.subscribe(["KXBTC", "KXETH"])

    bridge._ws.subscribe_quotes.assert_awaited_once_with(["KXBTC", "KXETH"])
    bridge._ws.subscribe_trades.assert_awaited_once_with(["KXBTC", "KXETH"])
    assert bridge._ws.subscribe_orderbook.await_count == 2
    subscribed = [call.args[0] for call in bridge._ws.subscribe_orderbook.await_args_list]
    assert subscribed == ["KXBTC", "KXETH"]


@pytest.mark.asyncio
async def test_publish_quote_uses_event_type_and_payload(monkeypatch, bridge: KalshiWebSocketBridge) -> None:
    publish = AsyncMock()
    monkeypatch.setattr("core.event_bus.event_stream.publish", publish)

    quote = QuoteEvent(
        market_id="KXBTC",
        outcome_id=None,
        bid_price=Decimal("0.54"),
        ask_price=Decimal("0.56"),
        last_price=Decimal("0.55"),
        volume=Decimal("1234"),
        timestamp=datetime.now(timezone.utc),
        venue="kalshi",
    )

    await bridge._publish_event(quote)

    publish.assert_awaited_once()
    event_type, payload = publish.await_args.args
    assert event_type == "kalshi:price_update"
    assert payload["market_id"] == "KXBTC"
    assert payload["bid"] == 0.54
    assert payload["ask"] == 0.56


@pytest.mark.asyncio
async def test_publish_orderbook_event_uses_two_arg_contract(monkeypatch, bridge: KalshiWebSocketBridge) -> None:
    publish = AsyncMock()
    monkeypatch.setattr("core.event_bus.event_stream.publish", publish)

    event = {
        "type": "orderbook_delta",
        "ticker": "KXBTC",
        "seq": 42,
        "yes": [[55, 10]],
        "no": [[45, 12]],
    }

    await bridge._publish_event(event)

    publish.assert_awaited_once()
    event_type, payload = publish.await_args.args
    assert event_type == "kalshi:orderbook_delta"
    assert payload["ticker"] == "KXBTC"
    assert payload["seq"] == 42
