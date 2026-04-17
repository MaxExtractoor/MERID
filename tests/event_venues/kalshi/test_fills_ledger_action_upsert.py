"""Fills ledger: buy/sell action resolution, HTTP upsert over WS, position roll-up."""

from __future__ import annotations

import threading

import pytest

from merid.event_venues.kalshi.fills_ledger import (
    KalshiFillsLedger,
    OrderIntent,
    get_fills_ledger,
)
from merid.event_venues.kalshi.kalshi_ledger_metrics import reset_for_testing, snapshot


@pytest.fixture
async def ledger():
    reset_for_testing()
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
    reset_for_testing()


@pytest.mark.asyncio
async def test_ws_then_http_upsert_upgrades_action_and_keeps_single_row(ledger):
    ws_raw = {
        "fill_id": "f1",
        "trade_id": "f1",
        "order_id": "o1",
        "market_ticker": "KXTEST-1",
        "side": "yes",
        "action": "",
        "count": 10,
        "price": 0.55,
        "fee": 0.01,
        "created_at": "2025-01-01T12:00:00+00:00",
    }
    assert await ledger.ingest_ws_fill(ws_raw) is True

    http_raw = {
        "fill_id": "f1",
        "trade_id": "f1",
        "order_id": "o1",
        "ticker": "KXTEST-1",
        "side": "yes",
        "action": "buy",
        "count": 10,
        "yes_price": 0.55,
        "fee": 0.01,
        "created_time": "2025-01-01T12:00:00+00:00",
    }
    n, _ = await ledger.ingest_http_fills([http_raw])
    assert n == 0
    assert len(ledger._fills) == 1
    f = ledger._fills["f1"]
    assert f.action == "buy"

    comp = ledger.compute_position_from_fills("KXTEST-1")
    assert comp is not None
    assert comp["contracts"] == 10
    assert comp["side"] == "yes"

    m = snapshot()
    assert m["fills_http_upserts_total"] >= 1
    # WS row had no explicit buy/sell on wire before HTTP enriched.
    assert m["fills_with_missing_action_total"] >= 1


@pytest.mark.asyncio
async def test_taker_action_does_not_increment_missing_action_metric(ledger):
    raw = {
        "fill_id": "tk1",
        "ticker": "KX-TK",
        "side": "yes",
        "taker_action": "buy",
        "count": 1,
        "yes_price": 0.5,
        "fee": 0.0,
        "created_time": "2025-01-01T12:00:00+00:00",
    }
    await ledger.ingest_http_fills([raw])
    assert snapshot()["fills_with_missing_action_total"] == 0


@pytest.mark.asyncio
async def test_ws_duplicate_identical_does_not_increment_ws_merge_counter(ledger):
    ws_raw = {
        "fill_id": "dup",
        "trade_id": "dup",
        "order_id": "od",
        "market_ticker": "KX-DUP",
        "side": "yes",
        "action": "buy",
        "count": 1,
        "price": 0.55,
        "fee": 0.01,
        "created_at": "2025-01-01T12:00:00+00:00",
    }
    assert await ledger.ingest_ws_fill(ws_raw) is True
    assert await ledger.ingest_ws_fill(dict(ws_raw)) is False
    assert snapshot()["fills_ws_merge_upgrades_total"] == 0


@pytest.mark.asyncio
async def test_summary_includes_ledger_metric_keys(ledger):
    await ledger.ingest_http_fills(
        [
            {
                "fill_id": "sk",
                "ticker": "KX-SK",
                "side": "yes",
                "action": "buy",
                "count": 1,
                "yes_price": 0.5,
                "fee": 0.0,
                "created_time": "2025-01-01T12:00:00+00:00",
            }
        ]
    )
    s = ledger.summary()
    assert "fills_with_missing_action_total" in s
    assert "fills_http_upserts_total" in s
    assert "fills_ws_merge_upgrades_total" in s


@pytest.mark.asyncio
async def test_buy_sell_sequence_net_position(ledger):
    for i, act in enumerate(["buy", "sell"]):
        raw = {
            "fill_id": f"fx{i}",
            "ticker": "KXTEST-2",
            "side": "yes",
            "action": act,
            "count": 3,
            "yes_price": 0.6,
            "fee": 0.0,
            "created_time": "2025-01-01T12:00:00+00:00",
        }
        await ledger.ingest_http_fills([raw])
    comp = ledger.compute_position_from_fills("KXTEST-2")
    assert comp is None  # flat


@pytest.mark.asyncio
async def test_intent_resolves_action(ledger):
    ledger.record_intent(
        OrderIntent(
            intent_id="coid-1",
            market_ticker="KXTEST-3",
            side="yes",
            action="buy",
            count=5,
            price_cents=40,
        )
    )
    raw = {
        "fill_id": "fi",
        "ticker": "KXTEST-3",
        "side": "yes",
        "client_order_id": "coid-1",
        "count": 5,
        "yes_price": 0.4,
        "fee": 0.0,
        "created_time": "2025-01-01T12:00:00+00:00",
    }
    await ledger.ingest_http_fills([raw])
    assert ledger._fills["fi"].action == "buy"


def test_no_persisted_invalid_action_when_count_positive(ledger):
    """Invariant: parser always assigns buy/sell for count_fp > 0."""
    raw = {
        "fill_id": "inv",
        "ticker": "KX-Z",
        "side": "yes",
        "count": 2,
        "yes_price": 0.7,
        "fee": 0.0,
        "created_time": "2025-01-01T12:00:00+00:00",
    }
    f = ledger._parse_fill(raw, "http_poller")
    assert f.count_fp > 0
    assert f.action in ("buy", "sell")
