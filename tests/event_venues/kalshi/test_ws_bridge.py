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
