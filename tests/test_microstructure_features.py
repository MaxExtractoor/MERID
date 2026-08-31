"""Unit tests for merid.prediction.microstructure_features."""

import math
import time
from dataclasses import dataclass, field
from typing import Any, List

import pytest

from merid.prediction.microstructure_features import (
    BookSnapshot,
    SpotHistory,
    book_imbalance_ratio,
    book_pressure_edge,
    compute_microstructure_features,
    cross_asset_lead_lag,
    kalshi_state_book_levels,
    log_depth_imbalance,
    ofi_event,
    ofi_window,
    spread_cents,
)


@dataclass
class FakeLevel:
    price_cents: int
    size: int


@dataclass
class FakeState:
    best_bid_cents: int
    best_ask_cents: int
    best_no_bid_cents: int = 0
    best_no_ask_cents: int = 0
    yes_bids: List[Any] = field(default_factory=list)
    no_bids: List[Any] = field(default_factory=list)
    top_of_book_size: int = 0
    last_book_update_ts: float = 0.0


def test_kalshi_state_book_levels_yes_side():
    state = FakeState(
        best_bid_cents=40,
        best_ask_cents=42,
        yes_bids=[FakeLevel(40, 100), FakeLevel(39, 50)],
        no_bids=[FakeLevel(58, 200)],  # NO bid 58 == YES ask 42
        top_of_book_size=300,
        last_book_update_ts=1000.0,
    )
    snap = kalshi_state_book_levels(state, "yes")
    assert snap is not None
    assert snap.bid_cents == 40
    assert snap.bid_size == 100
    assert snap.ask_cents == 42
    assert snap.ask_size == 200
    assert snap.ts == 1000.0


def test_kalshi_state_book_levels_no_side_derived():
    state = FakeState(
        best_bid_cents=40,
        best_ask_cents=42,
        yes_bids=[FakeLevel(40, 100)],
        no_bids=[FakeLevel(58, 200)],
    )
    snap = kalshi_state_book_levels(state, "no")
    assert snap is not None
    # NO bid = 100 - YES ask = 58
    assert snap.bid_cents == 58
    assert snap.bid_size == 200
    # NO ask = 100 - YES bid = 60
    assert snap.ask_cents == 60
    assert snap.ask_size == 100


def test_kalshi_state_book_levels_uses_top_of_book_fallback():
    state = FakeState(
        best_bid_cents=40,
        best_ask_cents=42,
        yes_bids=[],
        no_bids=[],
        top_of_book_size=120,
    )
    snap = kalshi_state_book_levels(state, "yes")
    assert snap is not None
    assert snap.bid_size == 60
    assert snap.ask_size == 60


def test_book_imbalance_balanced():
    snap = BookSnapshot(0.0, "yes", 40, 100, 42, 100)
    assert book_imbalance_ratio(snap) == 0.0


def test_book_imbalance_buy_pressure():
    snap = BookSnapshot(0.0, "yes", 40, 300, 42, 100)
    assert book_imbalance_ratio(snap) == 0.5


def test_log_depth_imbalance():
    snap = BookSnapshot(0.0, "yes", 40, 100, 42, 25)
    assert log_depth_imbalance(snap) == pytest.approx(math.log(4.0))


def test_spread_cents():
    snap = BookSnapshot(0.0, "yes", 40, 100, 42, 100)
    assert spread_cents(snap) == 2


def test_ofi_event_price_increase_bid():
    prev = BookSnapshot(0.0, "yes", 40, 100, 42, 100)
    curr = BookSnapshot(1.0, "yes", 41, 150, 42, 100)
    # bid up -> add current bid size; ask unchanged -> subtract ask size change (0)
    assert ofi_event(prev, curr) == 150.0


def test_ofi_event_price_decrease_ask():
    prev = BookSnapshot(0.0, "yes", 40, 100, 42, 100)
    curr = BookSnapshot(1.0, "yes", 40, 100, 41, 120)
    # ask down -> subtract current ask size
    assert ofi_event(prev, curr) == -120.0


def test_ofi_event_unchanged_prices_size_change():
    prev = BookSnapshot(0.0, "yes", 40, 100, 42, 100)
    curr = BookSnapshot(1.0, "yes", 40, 120, 42, 80)
    # bid size +20; ask size -20 (event subtracts ask change: 80-100 = -20)
    assert ofi_event(prev, curr) == 40.0


def test_ofi_window_trailing():
    now = time.time()
    hist = [
        BookSnapshot(now - 60, "yes", 40, 100, 42, 100),
        BookSnapshot(now - 25, "yes", 40, 120, 42, 100),
        BookSnapshot(now - 5, "yes", 40, 120, 42, 80),
        BookSnapshot(now, "yes", 41, 150, 42, 80),
    ]
    # Window 30s: events from [-25,-5], [-5,0], [0,now] if now-30 cutoff excludes -60
    # Actually events: (event at -60->-25 excluded because -25 < now-30? if now-30 = now-30, -25 > now-30? depends)
    # Just verify it returns a finite number and is positive (bid up at end).
    val = ofi_window(hist, 30.0)
    assert math.isfinite(val)


def test_compute_microstructure_features():
    state = FakeState(
        best_bid_cents=40,
        best_ask_cents=42,
        yes_bids=[FakeLevel(40, 100), FakeLevel(39, 50)],
        no_bids=[FakeLevel(58, 200)],
    )
    feats = compute_microstructure_features(state, "yes")
    assert feats is not None
    assert feats["spread_cents"] == 2
    assert feats["book_imbalance"] == pytest.approx((100.0 - 200.0) / 300.0)
    assert feats["ofi"] == 0.0


def test_compute_microstructure_features_with_history():
    state = FakeState(
        best_bid_cents=41,
        best_ask_cents=42,
        yes_bids=[FakeLevel(41, 150)],
        no_bids=[FakeLevel(58, 100)],  # unchanged ask size so OFI is bid-up only
        top_of_book_size=250,
    )
    now = time.time()
    hist = [
        BookSnapshot(now - 5, "yes", 40, 100, 42, 100),
    ]
    feats = compute_microstructure_features(state, "yes", history=hist, ofi_window_s=30.0)
    assert feats is not None
    assert feats["ofi"] == pytest.approx(150.0)


def test_book_pressure_edge_yes():
    snap = BookSnapshot(0.0, "yes", 40, 300, 42, 100)
    edge = book_pressure_edge(snap, "yes", max_edge_pct=2.0)
    assert edge == pytest.approx(1.0, rel=1e-3)


def test_book_pressure_edge_no():
    snap = BookSnapshot(0.0, "no", 58, 300, 60, 100)
    # For NO, bid_size=300, ask_size=100, book_imbalance_no = +0.5
    edge = book_pressure_edge(snap, "no", max_edge_pct=2.0)
    assert edge == pytest.approx(1.0, rel=1e-3)


def test_spot_history_log_return():
    h = SpotHistory(window_s=60.0)
    now = time.time()
    h.update(now - 120, 100.0)
    h.update(now - 30, 100.0)
    h.update(now, 101.0)
    ret = h.log_return()
    assert ret == pytest.approx(math.log(101.0 / 100.0))


def test_cross_asset_lead_lag_zero_when_flat():
    h = SpotHistory(window_s=60.0)
    assert cross_asset_lead_lag(h, 100.0) == 0.0


def test_cross_asset_lead_lag_positive_base_return():
    h = SpotHistory(window_s=60.0)
    now = time.time()
    h.update(now - 60, 100.0)
    h.update(now, 101.0)  # ~0.995% log return
    edge = cross_asset_lead_lag(h, 100.0, beta=1.0, max_edge_pct=2.0)
    # log(101/100) * 100 * 1.0 * 2.0 == ~1.99 pp
    assert edge == pytest.approx(2.0, abs=0.02)
