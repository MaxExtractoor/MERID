"""Regression tests for the 2026-10-28 WS critical-event protection fixes.

Root causes covered:
  * ``ws.py::_check_sequence`` tracked Kalshi ``seq`` in one connection-global
    bucket while Kalshi scopes ``seq`` per subscription (``sid``).  The
    high-volume orderbook sid pushed the connection max into the hundreds of
    thousands, so every fill / order_group / ticker / trade frame on other
    sids was silently dropped as an out-of-order duplicate — the operator-
    visible "mkt and bal get dropped" symptom.
  * ``ws.py`` had a single FIFO message queue; fills and order events sat
    behind tens of thousands of orderbook deltas (~2s pq_wait observed).
  * ``ws_bridge.py`` drop paths only spared ``type=="fill"``; order_group /
    position / balance events were shed, and the literal-oldest pop could
    evict a queued fill to admit a delta.
  * The dedup key dropped seq-less same-type events for a ticker as
    "duplicates".
  * ``_apply_orderbook_on_drain`` paid the full apply cost for deltas already
    past the upstream freshness bound, keeping the drain thread saturated.
"""

import asyncio
import queue as _queue
import time as _time
from unittest.mock import MagicMock, patch

import pytest

from merid.event_venues.kalshi.ws import KalshiWebSocket
from merid.event_venues.kalshi import ws_bridge as ws_bridge_mod
from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge


# ── helpers ──────────────────────────────────────────────────────────────


def _make_ws() -> KalshiWebSocket:
    cfg = MagicMock()
    return KalshiWebSocket(cfg)


@pytest.fixture
def bridge():
    """Real bridge with mocked ws/config; resets the singleton guard."""
    KalshiWebSocketBridge._instance_created = False
    b = KalshiWebSocketBridge(ws=MagicMock(), config=MagicMock())
    yield b
    KalshiWebSocketBridge._instance_created = False


def _ob_event(ticker="KXBTC15M-T1", sid=1, seq=1):
    return {
        "type": "orderbook_delta",
        "sid": sid,
        "seq": seq,
        "msg": {"market_ticker": ticker, "clock": seq, "price_dollars": "0.90", "delta": "1"},
    }


def _fill_event(ticker="KXBTC15M-T1", sid=7, seq=1, fill_id="f1"):
    return {
        "type": "fill",
        "sid": sid,
        "seq": seq,
        "fill_id": fill_id,
        "msg": {"market_ticker": ticker},
    }


def _book_q(bridge, ticker="KXBTC15M-T1"):
    """2026-11-04 shard routing: orderbook events land on the per-ticker
    hash-sharded ``_book_queues`` queue, not ``_thread_queue``."""
    return bridge._book_queues[hash(ticker) % ws_bridge_mod._BOOK_DRAIN_SHARDS]


# ── 1. per-sid sequence tracking ─────────────────────────────────────────


class TestPerSidSequenceTracking:
    """Kalshi seq is scoped per subscription; buckets must be per-sid."""

    async def test_low_volume_sid_not_dropped_behind_orderbook_sid(self):
        ws = _make_ws()
        # Orderbook sid floods with high seqs
        assert ws._check_sequence({"sid": 1, "seq": 250_000, "type": "orderbook_delta"}) is True
        assert ws._check_sequence({"sid": 1, "seq": 250_001, "type": "orderbook_delta"}) is True
        # A fill on a different sid with a tiny seq must NOT be seen as a dup.
        assert ws._check_sequence({"sid": 2, "seq": 5, "type": "fill"}) is True
        # And a fresh subscription (new sid, seq starts at 1) must flow too.
        assert ws._check_sequence({"sid": 9, "seq": 1, "type": "orderbook_snapshot"}) is True

    async def test_duplicate_within_same_sid_still_dropped(self):
        ws = _make_ws()
        assert ws._check_sequence({"sid": 2, "seq": 5, "type": "fill"}) is True
        assert ws._check_sequence({"sid": 2, "seq": 5, "type": "fill"}) is False
        assert ws._check_sequence({"sid": 2, "seq": 4, "type": "fill"}) is False
        assert ws._check_sequence({"sid": 2, "seq": 6, "type": "fill"}) is True

    async def test_gap_on_one_sid_does_not_poison_other_sids(self):
        ws = _make_ws()
        ws._spawn_tracked = MagicMock()  # no real recovery task in tests
        assert ws._check_sequence({"sid": 1, "seq": 10, "type": "orderbook_delta"}) is True
        # Gap on sid1: 10 -> 20 (returns True but counts the 9 skipped seqs)
        assert ws._check_sequence({"sid": 1, "seq": 20, "type": "orderbook_delta"}) is True
        assert ws._seq_gaps == 9
        # sid2 untouched by sid1's gap
        assert ws._check_sequence({"sid": 2, "seq": 3, "type": "fill"}) is True

    def test_seq_less_messages_pass(self):
        ws = _make_ws()
        assert ws._check_sequence({"sid": 1, "type": "subscribed"}) is True


# ── 1b. dual-queue processing order ──────────────────────────────────────


class TestProcessQueuePriorityLane:
    """Critical events must dispatch before queued market data."""

    async def test_critical_dispatched_before_backlogged_deltas(self):
        ws = _make_ws()
        ws._running = True
        dispatched = []

        async def cb(data):
            dispatched.append(data.get("type"))

        try:
            main_q = ws._ensure_msg_queue()
            prio_q = ws._ensure_priority_msg_queue()
            # Backlog of deltas already waiting, then a fill arrives
            for i in range(50):
                main_q.put_nowait((4, {"type": "orderbook_delta", "seq": i}))
            prio_q.put_nowait((1, {"type": "fill", "seq": 1}))

            task = asyncio.ensure_future(ws._process_queue(cb))
            await asyncio.sleep(0.5)
            ws._running = False
            await asyncio.wait_for(task, timeout=5.0)
        finally:
            ws._running = False

        assert dispatched[0] == "fill"
        assert dispatched.count("fill") == 1
        assert dispatched.count("orderbook_delta") == 50


# ── 2. ws.py priority classification ─────────────────────────────────────


class TestPriorityClassification:
    def test_critical_types_classified_at_or_below_critical_max(self):
        ws = _make_ws()
        for t in (
            "fill", "order_group_update", "order_group_updates",
            "order_update", "market_positions", "balance", "portfolio",
        ):
            prio = ws._classify_message_priority({"type": t})
            assert prio <= ws._CRITICAL_PRIORITY_MAX, f"{t} not critical (prio={prio})"

    def test_market_data_types_are_not_critical(self):
        ws = _make_ws()
        for t in ("orderbook_snapshot", "orderbook_delta", "trade", "ticker"):
            prio = ws._classify_message_priority({"type": t})
            assert prio > ws._CRITICAL_PRIORITY_MAX, f"{t} wrongly critical"


# ── 3. bridge critical-event protection ──────────────────────────────────


class TestCriticalEventProtection:
    def test_is_critical_event(self):
        assert KalshiWebSocketBridge._is_critical_event({"type": "fill"})
        assert KalshiWebSocketBridge._is_critical_event({"type": "order_group_updates"})
        assert KalshiWebSocketBridge._is_critical_event({"type": "market_positions"})
        assert not KalshiWebSocketBridge._is_critical_event({"type": "orderbook_delta"})
        assert not KalshiWebSocketBridge._is_critical_event({"type": "ticker"})
        assert not KalshiWebSocketBridge._is_critical_event("not-a-dict")

    def test_drop_oldest_droppable_skips_criticals(self, bridge):
        # Queue: fill first (literal oldest), then deltas.
        bridge._thread_queue.put_nowait(_fill_event())
        bridge._thread_queue.put_nowait(_ob_event(seq=1))
        bridge._thread_queue.put_nowait(_ob_event(seq=2))

        dropped = bridge._drop_oldest_droppable_event()
        assert dropped is not None
        assert dropped["type"] == "orderbook_delta"
        assert dropped["seq"] == 1
        # Fill still at head of queue
        assert bridge._thread_queue.queue[0]["type"] == "fill"

    def test_drop_oldest_droppable_returns_none_when_all_critical(self, bridge):
        bridge._thread_queue.put_nowait(_fill_event(fill_id="a"))
        bridge._thread_queue.put_nowait(_fill_event(fill_id="b"))
        assert bridge._drop_oldest_droppable_event() is None
        assert bridge._thread_queue.qsize() == 2

    async def test_pressure_stop_sheds_incoming_book_delta(self, bridge):
        """>=90% on a book shard sheds the incoming delta; queued frames survive.

        2026-11-04 sharding: orderbook events live on ``_book_queues`` where
        the >=90% path sheds the incoming frame instead of evicting — queued
        orderbook data is never the drop victim.  Fills route to
        ``_thread_queue`` and are untouched by book-shard pressure entirely.
        """
        bq = _book_q(bridge)
        cap = bq.maxsize
        stop = int(cap * 0.9)
        for i in range(stop):
            bq.put_nowait(_ob_event(seq=i + 1))
        assert bq.qsize() >= stop

        await bridge._enqueue_event(_ob_event(seq=9999, sid=9001))

        assert bridge._events_dropped == 1
        assert bq.qsize() == stop  # nothing evicted; the incoming was shed

    async def test_over_95pct_sheds_noncritical_but_not_critical(self, bridge):
        bq = _book_q(bridge)
        cap = bq.maxsize
        # Fill the book shard to just over 95% with deltas
        target = int(cap * 0.95) + 1
        for i in range(target):
            bq.put_nowait(_ob_event(seq=i + 1))
        assert bq.qsize() / cap > 0.95

        # Non-critical incoming event on the pressurized shard: the >=90%
        # path sheds the incoming delta — one drop, queued frames untouched.
        await bridge._enqueue_event(_ob_event(seq=500000, sid=9002))
        assert bridge._events_dropped == 1
        assert bq.qsize() == target

        # Critical incoming events route to _thread_queue and are unaffected
        # by book-shard pressure — they enqueue with no further drops.
        await bridge._enqueue_event(_fill_event(fill_id="crit", seq=900, sid=9003))
        tail_types = [e.get("type") for e in list(bridge._thread_queue.queue)]
        assert "fill" in tail_types
        assert bridge._events_dropped == 1

    async def test_full_queue_frees_droppable_slot(self, bridge):
        cap = bridge._thread_queue.maxsize
        for i in range(cap):
            bridge._thread_queue.put_nowait(_ob_event(seq=i + 1))
        assert bridge._thread_queue.full()

        ev = _fill_event(fill_id="must-land", seq=777)
        await bridge._enqueue_event(ev)
        # A droppable delta was evicted; the fill landed.
        assert bridge._events_dropped >= 1
        assert any(
            e.get("fill_id") == "must-land"
            for e in list(bridge._thread_queue.queue)
            if isinstance(e, dict)
        )

    async def test_full_queue_of_criticals_dead_letters_fill(self, bridge):
        cap = bridge._thread_queue.maxsize
        for i in range(cap):
            bridge._thread_queue.put_nowait(_fill_event(fill_id=f"q{i}", seq=i + 1))
        assert bridge._thread_queue.full()

        await bridge._enqueue_event(_fill_event(fill_id="overflow-fill", seq=cap + 1))
        # Nothing enqueued; fill went to the dead-letter queue instead.
        assert bridge._thread_queue.qsize() == cap
        assert any(
            f.get("fill_id") == "overflow-fill" for f in bridge._fill_dead_letter_queue
        )
        assert bridge._fills_dropped == 1


# ── 4. dedup correctness ─────────────────────────────────────────────────


class TestDedupCorrectness:
    async def test_seq_less_events_are_not_deduped(self, bridge):
        """Two same-ticker same-type events without seq must both pass."""
        ev1 = {"type": "ticker", "ticker": "KXBTC15M-T1"}
        ev2 = {"type": "ticker", "ticker": "KXBTC15M-T1"}
        await bridge._enqueue_event(ev1)
        await bridge._enqueue_event(ev2)
        assert bridge._thread_queue.qsize() == 2
        assert bridge._events_dropped == 0

    async def test_identical_seq_dedupes(self, bridge):
        ev1 = _ob_event(seq=42, sid=9101)
        ev2 = _ob_event(seq=42, sid=9101)
        await bridge._enqueue_event(ev1)
        await bridge._enqueue_event(ev2)
        # second is a replay → dropped (sid-seq check runs at enqueue)
        assert _book_q(bridge).qsize() == 1
        assert bridge._events_dropped == 1

    async def test_same_seq_on_different_sids_not_deduped(self, bridge):
        """sid is part of the dedup identity — seq spaces are per-sub."""
        ev1 = _ob_event(seq=43, sid=9102)
        ev2 = _ob_event(seq=43, sid=9103)
        await bridge._enqueue_event(ev1)
        await bridge._enqueue_event(ev2)
        assert _book_q(bridge).qsize() == 2


# ── 5. drain-side early stale-drop ───────────────────────────────────────


class TestDrainEarlyStaleDrop:
    def _stale_delta(self):
        ev = _ob_event()
        ev["_t_bridge_recv_ns"] = _time.monotonic_ns() - int(5000 * 1e6)  # 5s ago
        return ev

    def test_stale_delta_still_applies(self, bridge):
        """2026-11-03: the drain-side BOOK_UPSTREAM_LAG fast-path is gone.

        A lagged but seq-contiguous delta is honest book data — it flows
        through ``apply_orderbook_message`` and market_state stale-marks it
        there (entries stay vetoed on data-age, sustained staleness feeds
        the halt ladder).  The bridge no longer skips or invalidates.
        """
        store = MagicMock()
        with patch(
            "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
            return_value=store,
        ):
            bridge._apply_orderbook_on_drain(self._stale_delta())
        store.apply_orderbook_message.assert_called_once()
        store.mark_book_untrusted_for_bridge.assert_not_called()

    def test_fresh_delta_still_applies(self, bridge):
        store = MagicMock()
        ev = _ob_event()
        ev["_t_bridge_recv_ns"] = _time.monotonic_ns()  # fresh
        with patch(
            "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
            return_value=store,
        ):
            bridge._apply_orderbook_on_drain(ev)
        store.apply_orderbook_message.assert_called_once_with(ev, "bridge_queue")
        store.mark_book_untrusted_for_bridge.assert_not_called()

    def test_snapshot_exempt_from_early_drop(self, bridge):
        """Stale snapshots still reach the store — they carry book state."""
        store = MagicMock()
        ev = _ob_event()
        ev["type"] = "orderbook_snapshot"
        ev["_t_bridge_recv_ns"] = _time.monotonic_ns() - int(5000 * 1e6)
        with patch(
            "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
            return_value=store,
        ):
            bridge._apply_orderbook_on_drain(ev)
        store.apply_orderbook_message.assert_called_once()
