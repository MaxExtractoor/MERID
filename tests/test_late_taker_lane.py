"""Regression coverage for the late_taker_ioc lane (2026-11-13).

The lane is a bounded taker/ask-priced rescue for the single
counterfactual-positive cell in the late_taker_shadow cohort: ETH NO ask
50-59c at TTE 120-240s (+4.57c settle mean, +4.69c markout).  These tests
pin the domain boundaries, the ask-basis requirement, scope lists, EV
floor, per-ticker/daily budgets, and fail-closed semantics — and confirm
the lane never applies to bid-priced evaluations.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.prediction import drift_lane as dl


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("MERID_LATE_TAKER_LANE_ENABLED", "1")
    monkeypatch.setenv("MERID_DRIFT_LANE_STATE_PATH", str(tmp_path / "dl.json"))
    for key, value in {
        "MERID_LATE_TAKER_ASSETS": "ETH",
        "MERID_LATE_TAKER_SIDES": "no",
        "MERID_LATE_TAKER_PRICE_LO": "50",
        "MERID_LATE_TAKER_PRICE_HI": "59.99",
        "MERID_LATE_TAKER_TTE_MIN_S": "120",
        "MERID_LATE_TAKER_TTE_MAX_S": "240",
        "MERID_LATE_TAKER_MIN_NET_EV_CENTS": "1.0",
        "MERID_LATE_TAKER_MAX_PER_TICKER": "1",
        "MERID_LATE_TAKER_DAILY_MAX": "24",
    }.items():
        monkeypatch.setenv(key, value)
    yield


def _ok(**kw):
    args = dict(
        side="no",
        side_price_cents=55.0,
        net_ev_cents=2.0,
        tte_seconds=180.0,
        asset="ETH",
        entry_price_basis="ask",
        ticker="KXETH15M-TEST",
    )
    args.update(kw)
    return dl.late_taker_block(**args)


def test_admits_measured_cell():
    assert _ok() is None


def test_rejects_bid_basis():
    # The measured cohort is the executable-ask distribution; a bid-priced
    # pass must never inherit the lane floor.
    assert _ok(entry_price_basis="bid") == "late_taker_basis_not_ask"


def test_rejects_wrong_side():
    assert _ok(side="yes") == "late_taker_side"


def test_rejects_wrong_asset():
    assert _ok(asset="BTC") == "late_taker_asset"


def test_rejects_out_of_band_price():
    assert _ok(side_price_cents=45.0) == "late_taker_band"
    assert _ok(side_price_cents=61.0) == "late_taker_band"


def test_rejects_tte_outside_window():
    assert _ok(tte_seconds=100.0) == "late_taker_tte"
    assert _ok(tte_seconds=300.0) == "late_taker_tte"
    assert _ok(tte_seconds=None) == "late_taker_tte"


def test_rejects_low_ev():
    assert _ok(net_ev_cents=0.5) == "late_taker_low_ev"
    assert _ok(net_ev_cents=None) == "late_taker_low_ev"


def test_disabled_lane_inert():
    os.environ["MERID_LATE_TAKER_LANE_ENABLED"] = "0"
    try:
        assert _ok() == "late_taker_disabled"
    finally:
        os.environ["MERID_LATE_TAKER_LANE_ENABLED"] = "1"


def test_per_ticker_budget_exhausts():
    t = "KXETH15M-BUDGET"
    assert dl.late_taker_block(
        side="no", side_price_cents=55.0, net_ev_cents=2.0,
        tte_seconds=180.0, asset="ETH", entry_price_basis="ask",
        ticker=t,
    ) is None
    dl.record_lane_attempt(dl.LATE_TAKER_LANE_ID, t)
    assert dl.late_taker_block(
        side="no", side_price_cents=55.0, net_ev_cents=2.0,
        tte_seconds=180.0, asset="ETH", entry_price_basis="ask",
        ticker=t,
    ) == "late_taker_attempts_exhausted"


def test_band_match_boundaries():
    assert dl.late_taker_band_match(50.0)
    assert dl.late_taker_band_match(59.99)
    assert not dl.late_taker_band_match(49.99)
    assert not dl.late_taker_band_match(60.0)
    assert not dl.late_taker_band_match(None)


def test_scope_widening_via_env(monkeypatch):
    monkeypatch.setenv("MERID_LATE_TAKER_ASSETS", "ETH,BTC")
    monkeypatch.setenv("MERID_LATE_TAKER_SIDES", "no,yes")
    assert _ok(asset="BTC", side="yes") is None
