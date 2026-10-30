"""Tests for per-subscription (sid) orderbook sequence tracking (2026-10-30).

Kalshi's WS ``seq`` counts messages on one *subscription* — every ticker
multiplexed on an orderbook_delta subscription shares the counter.  A
per-ticker ``last_seq + 1`` check manufactures false INVALID_SEQUENCE_GAP
invalidations whenever sibling tickers interleave on the stream, so
contiguity is enforced at enqueue time per sid and the dequeue-side
validator only checks monotonicity.
"""

from unittest.mock import MagicMock

import pytest

from merid.event_venues.kalshi.market_state import KalshiMarketStateStore
from merid.event_venues.kalshi.ws import _orderbook_update_interval_ms


@pytest.fixture
def store():
    return KalshiMarketStateStore()


class _FakeBook:
    def __init__(self, last_seq=None):
        self.initialized = True
        self.last_seq = last_seq


class TestSidSequenceTracking:
    def test_interleaved_sibling_deltas_are_contiguous(self, store):
        """Deltas for two tickers sharing one sid consume one seq space."""
        assert store._check_sid_delta_sequence(4, 100, "KXBTC15M-A") == 0
        # seq 101 belongs to another ticker on the same sid — still contiguous
        assert store._check_sid_delta_sequence(4, 101, "KXETH15M-A") == 0
        assert store._check_sid_delta_sequence(4, 102, "KXBTC15M-A") == 0
        assert store._sid_tickers[4] == {"KXBTC15M-A", "KXETH15M-A"}

    def test_real_gap_reports_dropped_count(self, store):
        assert store._check_sid_delta_sequence(4, 100, "KXBTC15M-A") == 0
        assert store._check_sid_delta_sequence(4, 105, "KXBTC15M-A") == 4
        # cursor advances past the gap so subsequent frames track cleanly
        assert store._check_sid_delta_sequence(4, 106, "KXBTC15M-A") == 0

    def test_replay_is_dropped_not_a_gap(self, store):
        assert store._check_sid_delta_sequence(4, 100, "KXBTC15M-A") == 0
        assert store._check_sid_delta_sequence(4, 100, "KXBTC15M-A") == -1
        assert store._check_sid_delta_sequence(4, 99, "KXBTC15M-A") == -1
        assert store._check_sid_delta_sequence(4, 101, "KXBTC15M-A") == 0

    def test_missing_sid_or_seq_is_permissive(self, store):
        assert store._check_sid_delta_sequence(None, 100, "KXBTC15M-A") == 0
        assert store._check_sid_delta_sequence(4, None, "KXBTC15M-A") == 0

    def test_independent_sids_track_independently(self, store):
        assert store._check_sid_delta_sequence(1, 50, "KXBTC15M-A") == 0
        assert store._check_sid_delta_sequence(7, 900, "KXETH15M-A") == 0
        assert store._check_sid_delta_sequence(1, 51, "KXBTC15M-A") == 0
        assert store._check_sid_delta_sequence(7, 901, "KXETH15M-A") == 0

    def test_gap_invalidates_all_tickers_on_sid(self, store):
        store._check_sid_delta_sequence(4, 100, "KXBTC15M-A")
        store._check_sid_delta_sequence(4, 101, "KXETH15M-A")
        store._mark_book_untrusted_and_resync = MagicMock()
        gap = store._check_sid_delta_sequence(4, 110, "KXBTC15M-A")
        assert gap == 8
        store._handle_sid_sequence_gap(4, 110, gap, "KXBTC15M-A")
        invalidated = {
            c.args[0] for c in store._mark_book_untrusted_and_resync.call_args_list
        }
        assert invalidated == {"KXBTC15M-A", "KXETH15M-A"}

    def test_invalidate_all_resets_sid_cursors(self, store):
        store._check_sid_delta_sequence(4, 500, "KXBTC15M-A")
        store.invalidate_all_live_sequence()
        # sid values are small ints that Kalshi may reuse on a fresh
        # subscription — a stale high cursor must not drop the new stream
        assert store._check_sid_delta_sequence(4, 1, "KXBTC15M-A") == 0


class TestDequeueValidator:
    def test_newer_seq_on_sid_applies(self, store):
        ob = _FakeBook(last_seq=100)
        ok, expected, got = store._validate_delta_sequence(
            "KXBTC15M-A", {"_sid": 4, "seq": 105}, ob
        )
        assert ok is True and expected == 101 and got == 105

    def test_interleaved_gap_is_not_false_invalid(self, store):
        """The bug being fixed: sid seqs jump per ticker; must not invalidate."""
        ob = _FakeBook(last_seq=100)
        ok, _, _ = store._validate_delta_sequence(
            "KXBTC15M-A", {"_sid": 4, "seq": 150}, ob
        )
        assert ok is True

    def test_replayed_seq_is_stale_not_invalid(self, store):
        ob = _FakeBook(last_seq=100)
        ok, expected, got = store._validate_delta_sequence(
            "KXBTC15M-A", {"_sid": 4, "seq": 100}, ob
        )
        assert ok == "stale"
        assert got == 100

    def test_no_sid_keeps_strict_per_ticker_check(self, store):
        ob = _FakeBook(last_seq=100)
        ok, expected, got = store._validate_delta_sequence(
            "KXBTC15M-A", {"seq": 102}, ob
        )
        assert ok is False
        ok2, _, _ = store._validate_delta_sequence(
            "KXBTC15M-A", {"seq": 101}, ob
        )
        assert ok2 is True

    def test_no_seq_or_uninitialized_is_permissive(self, store):
        assert store._validate_delta_sequence(
            "KXBTC15M-A", {"_sid": 4}, _FakeBook(last_seq=100)
        ) == (True, None, None)
        assert store._validate_delta_sequence(
            "KXBTC15M-A", {"_sid": 4, "seq": 5}, _FakeBook(last_seq=None)
        ) == (True, None, None)


class TestUpdateIntervalMs:
    def test_default_realtime(self, monkeypatch):
        monkeypatch.delenv("MERID_KALSHI_OB_UPDATE_INTERVAL_MS", raising=False)
        assert _orderbook_update_interval_ms() == 0

    def test_supported_values(self, monkeypatch):
        monkeypatch.setenv("MERID_KALSHI_OB_UPDATE_INTERVAL_MS", "100")
        assert _orderbook_update_interval_ms() == 100
        monkeypatch.setenv("MERID_KALSHI_OB_UPDATE_INTERVAL_MS", "1000")
        assert _orderbook_update_interval_ms() == 1000

    def test_clamps_to_supported(self, monkeypatch):
        monkeypatch.setenv("MERID_KALSHI_OB_UPDATE_INTERVAL_MS", "50")
        assert _orderbook_update_interval_ms() == 100
        monkeypatch.setenv("MERID_KALSHI_OB_UPDATE_INTERVAL_MS", "500")
        assert _orderbook_update_interval_ms() == 100
        monkeypatch.setenv("MERID_KALSHI_OB_UPDATE_INTERVAL_MS", "5000")
        assert _orderbook_update_interval_ms() == 1000

    def test_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv("MERID_KALSHI_OB_UPDATE_INTERVAL_MS", "abc")
        assert _orderbook_update_interval_ms() == 0
