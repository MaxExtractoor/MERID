"""Documented Kalshi snapshots must reach the sequenced local orderbook."""

from unittest.mock import MagicMock
from types import SimpleNamespace
import asyncio
import time

import pytest

from merid.event_venues.kalshi.market_state import KalshiMarketStateStore
from merid.event_venues.kalshi.ws import KalshiWebSocket


TICKER = "KXBTC15M-26NOV021145-45"


def _snapshot(seq, yes, no):
    return {
        "type": "orderbook_snapshot",
        "sid": 4,
        "seq": seq,
        "msg": {
            "market_ticker": TICKER,
            "yes_dollars_fp": yes,
            "no_dollars_fp": no,
        },
    }


@pytest.fixture
def pipeline():
    ws = KalshiWebSocket(config=SimpleNamespace(api_key="test-key"))
    store = KalshiMarketStateStore()
    store._batch_worker_running = True
    store._enqueue_delta = MagicMock(return_value=True)
    return ws, store


def test_documented_snapshot_and_following_delta(pipeline):
    ws, store = pipeline
    raw = _snapshot(42, [["0.3200", "7.00"]], [["0.6700", "11.00"]])
    event = ws._parse_message(raw)
    assert event is not None
    store.apply_orderbook_message(event, "bridge_queue")

    book = store._ob.get_book(TICKER)
    assert book.yes_levels == {32: 7}
    assert book.no_levels == {67: 11}
    assert book.last_seq == 42
    assert store._ticker_sid[TICKER] == 4
    assert store._sid_last_seq[4] == 42

    delta = {
        "type": "orderbook_delta",
        "sid": 4,
        "seq": 43,
        "msg": {"market_ticker": TICKER, "price_dollars": "0.3200", "delta_fp": "2.00", "side": "yes"},
    }
    store.apply_orderbook_message(ws._parse_message(delta), "bridge_queue")
    assert store._sid_last_seq[4] == 43
    assert store._enqueue_delta.call_count == 1


def test_empty_ws_snapshot_replaces_existing_book(pipeline):
    ws, store = pipeline
    store.apply_orderbook_message(
        ws._parse_message(_snapshot(1, [["0.3200", "7.00"]], [["0.6700", "11.00"]])),
        "bridge_queue",
    )
    state = store.get(TICKER)
    state.last_rest_bid_cents = 32
    state.last_rest_ask_cents = 33
    state.last_rest_yes_bids = [(32, 7)]
    state.last_rest_no_bids = [(67, 11)]
    state.last_rest_quote_update_ts = time.monotonic()
    store.apply_orderbook_message(ws._parse_message(_snapshot(2, [], [])), "bridge_queue")
    book = store._ob.get_book(TICKER)
    assert book.initialized
    assert not book.yes_levels and not book.no_levels
    assert book.last_seq == 2
    assert state.best_bid_cents is None and state.best_ask_cents is None
    assert not state.executable


def test_replayed_snapshot_does_not_rewind_subscription_or_book(pipeline):
    ws, store = pipeline
    store.apply_orderbook_message(
        ws._parse_message(_snapshot(10, [["0.3200", "7.00"]], [["0.6700", "11.00"]])),
        "bridge_queue",
    )
    store._check_sid_delta_sequence(4, 11, "KXETH15M-26NOV021145-45")
    store.apply_orderbook_message(
        ws._parse_message(_snapshot(9, [["0.3000", "1.00"]], [["0.6700", "11.00"]])),
        "bridge_queue",
    )
    assert store._sid_last_seq[4] == 11
    assert store._ob.get_book(TICKER).yes_levels == {32: 7}


def test_gap_before_snapshot_invalidates_other_subscription_books(pipeline):
    ws, store = pipeline
    store.apply_orderbook_message(
        ws._parse_message(_snapshot(10, [["0.3200", "7.00"]], [["0.6700", "11.00"]])),
        "bridge_queue",
    )
    sibling = "KXETH15M-26NOV021145-45"
    store._check_sid_delta_sequence(4, 11, sibling)
    store._mark_book_untrusted_and_resync = MagicMock()
    store.apply_orderbook_message(
        ws._parse_message(_snapshot(14, [["0.3300", "7.00"]], [["0.6600", "11.00"]])),
        "bridge_queue",
    )
    assert {call.args[0] for call in store._mark_book_untrusted_and_resync.call_args_list} == {
        TICKER, sibling
    }
    assert store._ob.get_book(TICKER).yes_levels == {33: 7}
    assert store._sid_last_seq[4] == 14


@pytest.mark.parametrize("bad_yes", [
    [["not-a-price", "7.00"]],
    [["0.3200", "NaN"]],
    [["0.3200"]],
    "not-a-list",
])
def test_malformed_snapshot_invalidates_without_replacing_book(pipeline, bad_yes):
    ws, store = pipeline
    store.apply_orderbook_message(
        ws._parse_message(_snapshot(1, [["0.3200", "7.00"]], [["0.6700", "11.00"]])),
        "bridge_queue",
    )
    event = ws._parse_message(_snapshot(2, bad_yes, [["0.6700", "11.00"]]))
    assert event is not None
    store.apply_orderbook_message(event, "bridge_queue")
    book = store._ob.get_book(TICKER)
    assert book.yes_levels == {32: 7}
    assert book.last_seq == 1
    assert not store.get(TICKER).snapshot_complete


@pytest.mark.parametrize("price,size", [("0.3210", "2.00"), ("0.3200", "0.50")])
def test_unsupported_snapshot_precision_invalidates_book(pipeline, price, size):
    ws, store = pipeline
    store.apply_orderbook_message(
        ws._parse_message(_snapshot(1, [["0.3200", "7.00"]], [["0.6700", "11.00"]])),
        "bridge_queue",
    )
    store.apply_orderbook_message(
        ws._parse_message(_snapshot(2, [[price, size]], [["0.6700", "11.00"]])),
        "bridge_queue",
    )
    assert not store.get(TICKER).snapshot_complete
    assert store._ob.get_book(TICKER).last_seq == 1


@pytest.mark.parametrize("price,size", [("0.3210", "2.00"), ("0.3200", "0.50")])
def test_unsupported_delta_precision_invalidates_book(pipeline, price, size):
    ws, store = pipeline
    store.apply_orderbook_message(
        ws._parse_message(_snapshot(1, [["0.3200", "7.00"]], [["0.6700", "11.00"]])),
        "bridge_queue",
    )
    event = {
        "type": "orderbook_delta", "sid": 4, "seq": 2,
        "msg": {"market_ticker": TICKER, "price_dollars": price, "delta_fp": size, "side": "yes"},
    }
    store.apply_orderbook_message(ws._parse_message(event), "bridge_queue")
    assert not store.get(TICKER).snapshot_complete
    store._enqueue_delta.assert_not_called()


def test_rest_degraded_book_may_enter_while_ws_snapshot_pending(pipeline):
    ws, store = pipeline
    store.apply_orderbook_message(
        ws._parse_message(_snapshot(1, [["0.3200", "7.00"]], [["0.6700", "11.00"]])),
        "bridge_queue",
    )
    state = store.get(TICKER)
    state.quote_owner = "REST_VERIFIED_DEGRADED"
    state.data_quality = "GOOD"
    state.executable = True
    state.floor_strike = 77000.0
    state.last_rest_quote_update_ts = time.monotonic()
    event = {
        "type": "orderbook_delta", "sid": 4, "seq": 2,
        "msg": {"market_ticker": TICKER, "price_dollars": "0.3200", "delta_fp": "0.50", "side": "yes"},
    }
    store.apply_orderbook_message(ws._parse_message(event), "bridge_queue")
    # The WS leg still needs a snapshot, but a REST-owned GOOD executable
    # book with a fresh attested REST quote is the designed degraded-entry
    # path — the snapshot latch must not veto it.
    ready, _reason = store.is_market_entry_ready(TICKER)
    assert ready is True

    store.apply_orderbook_message(
        ws._parse_message(_snapshot(3, [["0.3200", "7.00"]], [["0.6700", "11.00"]])),
        "bridge_queue",
    )
    assert TICKER not in store._ws_book_requires_snapshot


def test_ws_snapshot_latch_blocks_without_rest_evidence(pipeline):
    ws, store = pipeline
    store.apply_orderbook_message(
        ws._parse_message(_snapshot(1, [["0.3200", "7.00"]], [["0.6700", "11.00"]])),
        "bridge_queue",
    )
    state = store.get(TICKER)
    # WS-owned untrusted state: no REST owner, no attested recovery source.
    state.quote_owner = "WS_FRESH_VERIFIED"
    state.data_quality = "GOOD"
    state.executable = True
    state.floor_strike = 77000.0
    store._ws_book_requires_snapshot.add(TICKER)
    state.live_sequence_confirmed = False
    state.recovery_source = None
    assert store.is_market_entry_ready(TICKER) == (False, "WS-BOOK-REQUIRES-VALID-SNAPSHOT")


def test_snapshot_without_subscription_sequence_cannot_recover_book(pipeline):
    ws, store = pipeline
    store.apply_orderbook_message(
        ws._parse_message(_snapshot(1, [["0.3200", "7.00"]], [["0.6700", "11.00"]])),
        "bridge_queue",
    )
    raw = _snapshot(2, [["0.3300", "7.00"]], [["0.6600", "11.00"]])
    raw.pop("sid")
    store.apply_orderbook_message(ws._parse_message(raw), "bridge_queue")
    assert store._ob.get_book(TICKER).yes_levels == {32: 7}
    ready, _reason = store.is_market_entry_ready(TICKER)
    assert ready is False


def test_sequenced_control_flows_in_order_through_bridge(pipeline, monkeypatch):
    from merid.event_venues.kalshi import market_state
    from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge

    ws, store = pipeline
    ws._subscription_ids["orderbook_delta"] = 4
    monkeypatch.setattr(market_state, "get_kalshi_market_state_store", lambda: store)
    monkeypatch.setattr(KalshiWebSocketBridge, "_instance_created", False)
    bridge = KalshiWebSocketBridge(ws=MagicMock(), config=SimpleNamespace(api_key="test-key"))
    events = [
        ws._parse_message(_snapshot(1, [["0.3200", "7.00"]], [["0.6700", "11.00"]])),
        ws._parse_message({"type": "ok", "sid": 4, "seq": 2, "msg": {"market_tickers": [TICKER]}}),
        ws._parse_message({
            "type": "orderbook_delta", "sid": 4, "seq": 3,
            "msg": {"market_ticker": TICKER, "price_dollars": "0.3200", "delta_fp": "2.00", "side": "yes"},
        }),
    ]
    assert all(event is not None for event in events)
    for event in events:
        asyncio.run(bridge._enqueue_event(event))
    for event in events:
        bridge._apply_orderbook_on_drain(bridge._thread_queue.get_nowait())
    assert bridge._sequence_gaps == 0
    assert store._sid_last_seq[4] == 3
    assert store._enqueue_delta.call_count == 1
    assert store.get(TICKER).snapshot_complete


def test_control_with_gap_invalidates_all_known_sid_books(pipeline):
    _, store = pipeline
    sibling = "KXETH15M-26NOV021145-45"
    store._check_sid_delta_sequence(4, 1, TICKER)
    store._check_sid_delta_sequence(4, 2, sibling)
    store._mark_book_untrusted_and_resync = MagicMock()
    store.apply_orderbook_sequence_control({"sid": 4, "seq": 5})
    assert store._sid_last_seq[4] == 5
    assert {call.args[0] for call in store._mark_book_untrusted_and_resync.call_args_list} == {
        TICKER, sibling
    }
    assert "" not in store._ticker_sid


def test_other_subscription_ack_is_not_orderbook_control(pipeline):
    ws, _ = pipeline
    ws._subscription_ids["orderbook_delta"] = 4
    assert ws._parse_message({"type": "ok", "sid": 9, "seq": 2, "msg": {}}) is None


def test_unattributed_large_control_gap_does_not_expand_missing_range(pipeline, monkeypatch):
    from merid.event_venues.kalshi import market_state

    _, store = pipeline
    store._check_sid_delta_sequence(4, 1, TICKER)
    store._mark_book_untrusted_and_resync = MagicMock()
    monkeypatch.setattr(
        market_state, "range", MagicMock(side_effect=AssertionError("expanded missing range")),
        raising=False,
    )
    store.apply_orderbook_sequence_control({"sid": 4, "seq": 1_000_000_001})
    store._mark_book_untrusted_and_resync.assert_called_once()


def test_replayed_control_does_not_rewind_sid(pipeline):
    _, store = pipeline
    store._check_sid_delta_sequence(4, 10, TICKER)
    store._mark_book_untrusted_and_resync = MagicMock()
    store.apply_orderbook_sequence_control({"sid": 4, "seq": 9})
    assert store._sid_last_seq[4] == 10
    store._mark_book_untrusted_and_resync.assert_not_called()


def test_old_connection_frame_cannot_restore_book(pipeline, monkeypatch):
    from merid.event_venues.kalshi import market_state
    from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge

    ws, store = pipeline
    ws._connection_generation = 2
    monkeypatch.setattr(market_state, "get_kalshi_market_state_store", lambda: store)
    monkeypatch.setattr(KalshiWebSocketBridge, "_instance_created", False)
    bridge = KalshiWebSocketBridge(ws=ws, config=SimpleNamespace(api_key="test-key"))
    event = ws._parse_message(_snapshot(1, [["0.3200", "7.00"]], [["0.6700", "11.00"]]))
    event["_ws_connection_generation"] = 1
    bridge._apply_orderbook_on_drain(event)
    assert store.get(TICKER) is None
    event["_ws_connection_generation"] = 2
    bridge._apply_orderbook_on_drain(event)
    assert store._ob.get_book(TICKER).yes_levels == {32: 7}
