"""Stress paths: feed gaps, late ticks, spikes — buffer + ingest invariants."""
from __future__ import annotations

import pytest

from merid.data.settlement_offline import build_view_or_none, replay_ticks
from merid.data.settlement_rti_buffer import SettlementRTIBuffer


def test_late_ticks_after_expiry_are_rejected():
    exp = 2_000_000_000
    buf = SettlementRTIBuffer("KXBTC15M-ABUSE", "BTC", exp)
    for i in range(60):
        assert buf.ingest(exp - 59 + i, 50_000.0 + i)
    assert buf.is_settlement_grade()
    assert not buf.ingest(exp + 1, 99_999.0)
    assert not buf.ingest(exp + 100, 99_999.0)
    assert buf.filled_count == 60
    view = build_view_or_none(buf)
    assert view is not None
    assert view.avg_received == pytest.approx(sum(50_000.0 + i for i in range(60)) / 60.0)


def test_massive_spike_does_not_corrupt_slot_count():
    exp = 2_000_000_100
    buf = SettlementRTIBuffer("KXETH15M-ABUSE", "ETH", exp)
    for i in range(60):
        px = 3_000.0 if i != 45 else 3_000_000.0
        buf.ingest(exp - 59 + i, px)
    assert buf.is_settlement_grade()
    slots = buf.slot_values()
    assert slots[45] == pytest.approx(3_000_000.0)


def test_feed_gap_preserves_missing_seconds_and_partial_avg():
    exp = 2_000_000_200
    buf = SettlementRTIBuffer("KXBTC15M-GAP", "BTC", exp)
    # Simulate outage: only even seconds in window
    for i in range(0, 60, 2):
        buf.ingest(exp - 59 + i, 100.0)
    assert buf.filled_count == 30
    assert len(buf.missing_seconds) == 30
    assert not buf.is_settlement_grade()
    assert build_view_or_none(buf) is None


def test_replay_out_of_order_sorts_and_matches_sequential():
    exp = 2_000_000_300
    buf = SettlementRTIBuffer("KXBTC15M-SORT", "BTC", exp)
    ticks = [(float(exp - 59 + i), float(10 + i)) for i in range(60)]
    import random

    random.seed(0)
    shuffled = ticks[:]
    random.shuffle(shuffled)
    n = replay_ticks(buf, shuffled, sort_by_ts=True)
    assert n == 60
    assert buf.is_settlement_grade()
    assert buf.avg_received == pytest.approx(sum(10 + i for i in range(60)) / 60.0)
