"""Tests for KalshiWebSocketBridge event-bus wiring and subscriptions."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from merid.event_venues.base import QuoteEvent, VenueTrade
from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge


@pytest.fixture
def bridge() -> KalshiWebSocketBridge:
    ws = MagicMock()
    ws.connect = AsyncMock()
    ws.subscribe_quotes = AsyncMock()
    ws.subscribe_trades = AsyncMock()
    ws.subscribe_fills = AsyncMock()
    ws.subscribe_orderbook = AsyncMock()
    ws.subscribe_orderbooks_batch = AsyncMock()
    ws.listen = AsyncMock()
    ws.close = AsyncMock()
    ws.stats = MagicMock(return_value={})
    return KalshiWebSocketBridge(ws=ws)


@pytest.mark.asyncio
async def test_subscribe_adds_orderbook_channels(bridge: KalshiWebSocketBridge) -> None:
    await bridge.subscribe(["KXBTC", "KXETH"])

    bridge._ws.subscribe_quotes.assert_awaited_once_with(["KXBTC", "KXETH"])
    bridge._ws.subscribe_trades.assert_awaited_once_with(["KXBTC", "KXETH"])
    bridge._ws.subscribe_fills.assert_awaited_once_with(["KXBTC", "KXETH"])
    bridge._ws.subscribe_orderbooks_batch.assert_awaited_once_with(["KXBTC", "KXETH"])


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


@pytest.mark.asyncio
async def test_public_venue_trade_emits_tape_only_not_order_filled(monkeypatch, bridge: KalshiWebSocketBridge) -> None:
    """Public ``trade`` channel prints must not emit portfolio ``order_filled`` or touch the fills ledger."""
    publish = AsyncMock()
    monkeypatch.setattr("core.event_bus.event_stream.publish", publish)

    vt = VenueTrade(
        trade_id="t1",
        market_id="KXBTC-TEST",
        order_id="o1",
        side="yes",
        size=Decimal("5"),
        price=Decimal("0.5"),
        fee=Decimal("0.01"),
        timestamp=datetime.now(timezone.utc),
        venue="kalshi",
    )
    await bridge._publish_event(vt)

    types = [c.args[0] for c in publish.await_args_list]
    assert "kalshi:trade" in types
    assert "kalshi:order_filled" not in types
