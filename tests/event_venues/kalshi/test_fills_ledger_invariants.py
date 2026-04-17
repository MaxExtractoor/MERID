"""Ledger invariants: incomplete WS rejection, HTTP merge without zeroing, API helpers."""

from __future__ import annotations

import asyncio
import threading

import pytest

from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger, get_fills_ledger


@pytest.fixture
async def ledger(monkeypatch):
    KalshiFillsLedger._instance = None
    KalshiFillsLedger._lock = threading.Lock()
    lg = get_fills_ledger()
    lg._fills.clear()
    lg._fills_by_order.clear()
    lg._fills_by_market.clear()
    lg._intents.clear()
    yield lg
    # Clean up: shutdown writer task properly
    await lg.shutdown()
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
