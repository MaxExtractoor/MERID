"""Tests for the flag-gated, single-writer WebSocket bridge reorder path."""

import asyncio

import pytest

from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge
from merid.utils.sequence_reorder_buffer import SequenceReorderBuffer


@pytest.fixture
def bridge():
    """Create a minimal bridge with the new reorder path enabled."""
    # Allow a fresh instance in this test process.
    KalshiWebSocketBridge._instance_created = False
    b = KalshiWebSocketBridge(ws=None, config=None)
    b._single_writer_mode = True
    b._reorder_buffer = SequenceReorderBuffer(max_buffered=1024)
    b._async_queue = asyncio.Queue(maxsize=100)
    b._events_dropped = 0
    return b


def test_bridge_reorder_releases_in_order(bridge: KalshiWebSocketBridge) -> None:
    """Out-of-order deltas after a snapshot are released in sequence order."""
    bridge._reorder_push_one({"ticker": "KXBTC", "type": "orderbook_snapshot", "sequence": 0, "p": 0})
    bridge._reorder_push_one({"ticker": "KXBTC", "type": "orderbook_delta", "sequence": 3, "p": 3})
    bridge._reorder_push_one({"ticker": "KXBTC", "type": "orderbook_delta", "sequence": 2, "p": 2})
    bridge._reorder_push_one({"ticker": "KXBTC", "type": "orderbook_delta", "sequence": 1, "p": 1})

    assert bridge._async_queue.qsize() == 4
    assert bridge._async_queue.get_nowait()["p"] == 0
    assert bridge._async_queue.get_nowait()["p"] == 1
    assert bridge._async_queue.get_nowait()["p"] == 2
    assert bridge._async_queue.get_nowait()["p"] == 3
    assert bridge._async_queue.empty()


def test_bridge_reorder_gap_fill_splices(bridge: KalshiWebSocketBridge) -> None:
    """A later gap-fill is spliced in and released deterministically."""
    bridge._reorder_push_one({"ticker": "KXETH", "type": "orderbook_snapshot", "sequence": 10, "p": 10})
    bridge._reorder_push_one({"ticker": "KXETH", "type": "orderbook_delta", "sequence": 12, "p": 12})
    assert bridge._async_queue.qsize() == 1
    assert bridge._async_queue.get_nowait()["p"] == 10
    assert bridge._async_queue.empty()

    # Missing seq 11 arrives out of order.
    bridge._reorder_push_one({"ticker": "KXETH", "type": "orderbook_delta", "sequence": 11, "p": 11})
    assert bridge._async_queue.qsize() == 2
    assert bridge._async_queue.get_nowait()["p"] == 11
    assert bridge._async_queue.get_nowait()["p"] == 12


def test_bridge_reorder_without_seq_is_monotonic(bridge: KalshiWebSocketBridge) -> None:
    """Events without explicit seq are treated as in-order per channel."""
    bridge._reorder_push_one({"ticker": "KXSOL", "type": "fill", "p": 1})
    bridge._reorder_push_one({"ticker": "KXSOL", "type": "fill", "p": 2})
    assert bridge._async_queue.qsize() == 2
    assert bridge._async_queue.get_nowait()["p"] == 1
    assert bridge._async_queue.get_nowait()["p"] == 2


def test_bridge_reorder_uses_nested_kalshi_payload(bridge: KalshiWebSocketBridge) -> None:
    """Channel and sequence come from the nested ``msg`` body, not the top-level global seq."""
    # Kalshi WS v2 wraps the per-market payload under ``msg`` and the top-level
    # ``seq`` is a global connection counter. Using it would create a fake gap.
    bridge._reorder_push_one({
        "type": "orderbook_delta",
        "seq": 1,  # global connection counter
        "p": 100,
        "msg": {"market_ticker": "KXBTC", "price_dollars": 0.5, "side": "no", "sequence": 100},
    })
    bridge._reorder_push_one({
        "type": "orderbook_delta",
        "seq": 2,  # global connection counter
        "p": 101,
        "msg": {"market_ticker": "KXBTC", "price_dollars": 0.51, "side": "no", "sequence": 101},
    })
    bridge._reorder_push_one({
        "type": "orderbook_delta",
        "seq": 5,  # global connection counter, skipped seqs 3/4 are other channels
        "p": 50,
        "msg": {"market_ticker": "KXETH", "price_dollars": 0.6, "side": "no", "sequence": 50},
    })

    assert bridge._async_queue.qsize() == 3
    # KXBTC released in per-market sequence order.
    assert bridge._async_queue.get_nowait()["p"] == 100
    assert bridge._async_queue.get_nowait()["p"] == 101
    # KXETH is a separate channel and does not see KXBTC's sequence.
    assert bridge._async_queue.get_nowait()["p"] == 50


def test_bridge_reorder_resync_fast_forward(bridge: KalshiWebSocketBridge) -> None:
    """A resync drops stale buffered events and fast-forwards to the current event."""
    bridge._reorder_buffer._max_buffered = 1  # force resync quickly
    bridge._reorder_push_one({
        "type": "orderbook_delta",
        "p": 1,
        "msg": {"market_ticker": "KXDOGE", "sequence": 1},
    })
    bridge._reorder_push_one({
        "type": "orderbook_delta",
        "p": 3,
        "msg": {"market_ticker": "KXDOGE", "sequence": 3},
    })
    # seq 2 never arrives, buffer size = 2, this third push triggers resync.
    bridge._reorder_push_one({
        "type": "orderbook_delta",
        "p": 4,
        "msg": {"market_ticker": "KXDOGE", "sequence": 4},
    })
    # After resync the previous gap is discarded and the current event (seq 4)
    # becomes the new base, so it is released. The stream can continue.
    assert bridge._async_queue.qsize() >= 1
    assert bridge._async_queue.get_nowait()["p"] == 1
    # seq 4 should have been fast-forwarded and released as the new base.
    assert bridge._async_queue.get_nowait()["p"] == 4
