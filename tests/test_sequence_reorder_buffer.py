"""Tests for SequenceReorderBuffer."""

import pytest

from merid.utils.sequence_reorder_buffer import ResyncRequired, SequenceReorderBuffer


def test_reorder_releases_in_sequence_order() -> None:
    rb = SequenceReorderBuffer()
    rb.reset("kalshi", 0)
    assert rb.push("kalshi", 3, "e3") == []
    assert rb.push("kalshi", 2, "e2") == []
    assert rb.push("kalshi", 1, "e1") == ["e1", "e2", "e3"]
    assert rb.push("kalshi", 4, "e4") == ["e4"]
    assert rb.push("kalshi", 3, "dup") == []  # stale after watermark
    assert rb.has_gap("kalshi") is False


def test_gap_fill_splices_by_sequence() -> None:
    rb = SequenceReorderBuffer()
    rb.reset("kalshi", 10)
    assert rb.push("kalshi", 12, "e12") == []             # gap at 11
    assert rb.missing_seqs("kalshi") == [11]
    assert rb.push("kalshi", 11, "e11") == ["e11", "e12"] # gap filled, contiguous
    assert rb.has_gap("kalshi") is False


def test_per_channel_isolation() -> None:
    rb = SequenceReorderBuffer()
    rb.reset("kalshi", 0)
    rb.reset("rti", 99)
    assert rb.push("kalshi", 1, "k1") == ["k1"]
    assert rb.push("kalshi", 2, "k2") == ["k2"]
    assert rb.push("rti", 100, "r100") == ["r100"]
    assert rb.push("kalshi", 4, "k4") == []
    assert rb.push("kalshi", 3, "k3") == ["k3", "k4"]


def test_resync_required_bounds_memory() -> None:
    rb = SequenceReorderBuffer(max_buffered=2)
    rb.reset("kalshi", 0)
    rb.push("kalshi", 3, "e3")
    rb.push("kalshi", 4, "e4")
    with pytest.raises(ResyncRequired):
        rb.push("kalshi", 5, "e5")
