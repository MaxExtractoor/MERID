"""Ledger invariants: incomplete WS rejection, HTTP merge without zeroing, API helpers."""

from __future__ import annotations

import asyncio
import threading

import pytest

from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger, get_fills_ledger, OrderIntent


@pytest.fixture
async def ledger(monkeypatch):
    from merid.event_venues.kalshi import fills_ledger as _fl
    _fl._ledgers.clear()
    KalshiFillsLedger._instance = None
    KalshiFillsLedger._lock = threading.Lock()
    lg = get_fills_ledger()
    lg._fills.clear()
    lg._fills_by_order.clear()
    lg._fills_by_market.clear()
    lg._intents.clear()
    lg._processed_fill_ids.clear()
    lg._loaded_count = 1  # skip DB reload so tests use a clean ledger
    yield lg
    # Clean up: shutdown writer task properly
    await lg.shutdown()
    _fl._ledgers.clear()
    KalshiFillsLedger._instance = None


@pytest.mark.asyncio
async def test_ws_fill_rejected_when_incomplete_zero_price(ledger: KalshiFillsLedger) -> None:
    raw = {
        "fill_id": "inc-ws-1",
        "market_ticker": "KXBTCD-26JAN-T50000",
        "side": "yes",
        "action": "",
        "count": 5,
        "price": 0,
        "fee": 0,
        "created_at": "2025-01-01T12:00:00+00:00",
    }
    ok = await ledger.ingest_ws_fill(raw)
    assert ok is False
    assert "inc-ws-1" not in ledger._fills


@pytest.mark.asyncio
async def test_http_then_http_merge_does_not_zero_price(ledger: KalshiFillsLedger) -> None:
    first = {
        "fill_id": "m1",
        "ticker": "KXETH-TEST",
        "side": "yes",
        "action": "buy",
        "count": 10,
        "yes_price": 0.5,
        "fee": 0.01,
        "created_time": "2025-01-01T12:00:00+00:00",
    }
    n1, ids1 = await ledger.ingest_http_fills([first])
    assert n1 == 1
    assert ledger._fills["m1"].yes_price_dollars is not None

    second = {
        **first,
        "yes_price": 0,
        "count": 10,
    }
    n2, ids2 = await ledger.ingest_http_fills([second])
    assert n2 == 0
    assert ids2 == []
    assert float(ledger._fills["m1"].yes_price_dollars or 0) > 0


@pytest.mark.asyncio
async def test_kalshi_fill_resolved_asset(ledger: KalshiFillsLedger) -> None:
    raw = {
        "fill_id": "a1",
        "market_ticker": "KXETH-26MAR2914-T3000",
        "side": "yes",
        "action": "buy",
        "count": 1,
        "price": 0.4,
        "fee": 0.01,
        "created_at": "2025-01-01T12:00:00+00:00",
    }
    await ledger.ingest_ws_fill(raw)
    f = ledger._fills["a1"]
    assert f.resolved_asset() == "ETH"


@pytest.mark.asyncio
async def test_ws_fill_reclassified_when_http_provides_order_id(ledger: KalshiFillsLedger) -> None:
    """A WS fill lacking an order_id is unmatched; an HTTP upsert with the order_id
    reclassifies it when the order_id maps to a known intent."""
    intent = OrderIntent(
        intent_id="intent-1",
        ticker="KXBTC15M-TEST",
        side="yes",
        action="buy",
        count=1,
        price_cents=50,
        client_order_id="client-1",
    )
    ledger._intents["client-1"] = intent
    ledger._intents_by_client_order_id["client-1"] = "client-1"

    # First: a WebSocket fill with no correlation IDs is unmatched.
    ws_raw = {
        "fill_id": "ws-only",
        "market_ticker": "KXBTC15M-TEST",
        "side": "yes",
        "action": "buy",
        "count": 1,
        "price": 0.5,
        "fee": 0.01,
        "created_at": "2025-01-01T12:00:00+00:00",
    }
    await ledger.ingest_ws_fill(ws_raw)
    f = ledger._fills["ws-only"]
    assert f.unmatched is True

    # Then: HTTP upsert provides the client_order_id and reclassifies the fill.
    http_raw = {
        **ws_raw,
        "client_order_id": "client-1",
        "order_id": "order-1",
    }
    n, _ = await ledger.ingest_http_fills([http_raw])
    assert n == 0  # duplicate
    assert f.unmatched is False
    assert f.intent_id == "client-1"


@pytest.mark.asyncio
async def test_get_fill_resolution_state_reclassifies_unmatched_fill(ledger: KalshiFillsLedger) -> None:
    """get_fill_resolution_state resolves an unmatched fill via durable intent indices."""
    intent = OrderIntent(
        intent_id="intent-1",
        ticker="KXBTC15M-TEST",
        side="yes",
        action="buy",
        count=1,
        price_cents=50,
        client_order_id="client-1",
    )
    ledger._intents["client-1"] = intent
    ledger._intents_by_client_order_id["client-1"] = "client-1"

    ws_raw = {
        "fill_id": "ws-only",
        "market_ticker": "KXBTC15M-TEST",
        "side": "yes",
        "action": "buy",
        "count": 1,
        "price": 0.5,
        "fee": 0.01,
        "created_at": "2025-01-01T12:00:00+00:00",
    }
    await ledger.ingest_ws_fill(ws_raw)
    f = ledger._fills["ws-only"]
    f.client_order_id = "client-1"
    assert f.unmatched is True

    state = await ledger.get_fill_resolution_state("ws-only")
    assert state is not None
    assert state["found"] is True
    assert state["resolved"] is True
    assert state["unmatched"] is False
    assert f.unmatched is False


@pytest.mark.asyncio
async def test_get_fill_resolution_state_returns_unresolved_for_unknown_fill(ledger: KalshiFillsLedger) -> None:
    state = await ledger.get_fill_resolution_state("does-not-exist")
    assert state is None


@pytest.mark.asyncio
async def test_count_unmatched_fills_respects_since(ledger: KalshiFillsLedger) -> None:
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    f1 = ledger._fills["old"] = ledger._parse_fill({
        "fill_id": "old",
        "market_ticker": "KXBTC15M-TEST",
        "side": "yes",
        "action": "buy",
        "count": 1,
        "price": 0.5,
        "created_time": (now - timedelta(hours=1)).isoformat(),
    }, source="http_poller")
    f1.unmatched = True

    f2 = ledger._fills["recent"] = ledger._parse_fill({
        "fill_id": "recent",
        "market_ticker": "KXBTC15M-TEST",
        "side": "yes",
        "action": "buy",
        "count": 1,
        "price": 0.5,
        "created_time": now.isoformat(),
    }, source="http_poller")
    f2.unmatched = True

    assert ledger.count_unmatched_fills(since=now - timedelta(minutes=30)) == 1
    assert ledger.count_unmatched_fills() == 2
