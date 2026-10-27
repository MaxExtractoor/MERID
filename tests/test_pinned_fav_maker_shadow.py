"""Unit tests for the pinned-fav maker-band shadow counterfactual.

The tracker must observe the 85-91c shadow window, evaluate the lane's own
gates read-only, and write JSONL records — while never emitting outside
the window, never raising, and never mutating lane state (daily cap is
inspected, not consumed).
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.prediction import pinned_fav_maker_shadow as pfs


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "MERID_PINNED_FAV_STATE_PATH", str(tmp_path / "pinned_fav.json")
    )
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_MODE", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_LO", "90")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_HI", "98")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_MIN_TTE_S", "90")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_MAX_TTE_S", "840")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_MIN_P", "0.85")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_MIN_EV_CENTS", "-12.0")
    # Route the jsonl to tmp and reset the dedup cache per test.
    monkeypatch.setattr(
        pfs, "_DEFAULT_PATH", str(tmp_path / "pf_shadow.jsonl")
    )
    pfs._emitted.clear()
    yield


def _eval(**over):
    kwargs = dict(
        run_id="pf_test",
        decision_id="cand_x",
        asset="ETH",
        ticker="KXETH15M-TEST",
        yes_bid_cents=87.0,
        yes_ask_cents=92.0,
        no_bid_cents=8.0,
        no_ask_cents=13.0,
        tte_seconds=400.0,
        p_yes=0.93,
        spot_price=101.0,
        strike_price=100.0,
    )
    kwargs.update(over)
    pfs.evaluate(**kwargs)


def _records(path):
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        return [json.loads(l) for l in fh if l.strip()]


def test_emits_record_inside_shadow_band():
    _eval()
    recs = _records(pfs._DEFAULT_PATH)
    assert len(recs) == 1
    r = recs[0]
    assert r["type"] == "pinned_fav_maker_shadow"
    assert r["side"] == "yes"
    assert r["entry_price_cents"] == 87.0
    assert r["entry_basis"] == "own_side_bid_post_only"
    assert r["in_live_band"] is False
    assert r["shadow_band_lo"] == 85.0 and r["shadow_band_hi"] == 91.0
    assert r["maker_fee_est_cents"] is not None
    # p=0.93, bid 87c, tiny maker fee -> strongly positive EV estimate
    assert r["maker_ev_est_cents"] > 5.0
    assert r["gate_tte_pass"] is True
    assert r["gate_min_p_pass"] is True
    assert r["gate_min_ev_pass"] is True
    assert r["would_qualify"] is True


def test_no_emission_outside_shadow_band():
    _eval(yes_bid_cents=84.0)
    _eval(yes_bid_cents=92.0)
    assert _records(pfs._DEFAULT_PATH) == []


def test_live_edge_flagged_as_control():
    _eval(yes_bid_cents=90.0)
    recs = _records(pfs._DEFAULT_PATH)
    assert len(recs) == 1
    assert recs[0]["in_live_band"] is True


def test_no_side_uses_inverted_price_and_prob():
    # NO bid = 100 - yes_ask = 86c -> NO-side shadow candidate
    _eval(
        yes_bid_cents=70.0,
        yes_ask_cents=14.0,  # no_bid = 100 - 14 = 86
        no_bid_cents=86.0,
        no_ask_cents=30.0,
        p_yes=0.07,          # p_no = 0.93 >= 0.85 pin
    )
    recs = _records(pfs._DEFAULT_PATH)
    assert len(recs) == 1
    r = recs[0]
    assert r["side"] == "no"
    assert r["entry_price_cents"] == 86.0
    assert abs(r["p_selected"] - 0.93) < 1e-9
    assert r["gate_min_p_pass"] is True


def test_min_p_gate_fails_below_pin():
    _eval(p_yes=0.80)  # below the 0.85 maker pin
    r = _records(pfs._DEFAULT_PATH)[0]
    assert r["gate_min_p_pass"] is False
    assert r["would_qualify"] is False


def test_missing_p_fails_closed_like_lane():
    _eval(p_yes=None)
    r = _records(pfs._DEFAULT_PATH)[0]
    assert r["gate_min_p_pass"] is False
    assert r["min_p_block"] == "no_p"
    assert r["maker_ev_est_cents"] is None
    assert r["would_qualify"] is False


def test_min_ev_gate_fails_below_lane_floor(monkeypatch):
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_MIN_EV_CENTS", "7.0")
    _eval(p_yes=0.93)  # ev ~+6c at 87c < raised 7c floor
    r = _records(pfs._DEFAULT_PATH)[0]
    assert r["gate_min_ev_pass"] is False
    assert r["would_qualify"] is False


def test_tte_gate_fails_outside_window():
    _eval(tte_seconds=50.0)  # below maker 90s floor
    r = _records(pfs._DEFAULT_PATH)[0]
    assert r["gate_tte_pass"] is False
    assert r["would_qualify"] is False


def test_moneyness_cap_blocks_but_does_not_hide_record(monkeypatch):
    monkeypatch.setenv(
        "MERID_MONEYNESS_MAX_ENTRY_PRICE_CENTS_YES_XRP", "89"
    )
    _eval(asset="XRP", ticker="KXXRP15M-TEST", yes_bid_cents=90.0)
    r = _records(pfs._DEFAULT_PATH)[0]
    assert r["moneyness_cap_cents"] == 89.0
    assert r["gate_moneyness_pass"] is False
    assert r["would_qualify"] is False


def test_dedup_one_record_per_minute_per_price():
    _eval()                       # emit
    _eval()                       # same key -> suppressed
    _eval(tte_seconds=399.0)      # same minute -> suppressed
    _eval(tte_seconds=350.0)      # new minute bucket -> emit
    _eval(yes_bid_cents=88.0)     # new price -> emit
    assert len(_records(pfs._DEFAULT_PATH)) == 3


def test_disabled_flag_emits_nothing(monkeypatch):
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_SHADOW_ENABLED", "0")
    _eval()
    assert _records(pfs._DEFAULT_PATH) == []


def test_shadow_band_env_overrides(monkeypatch):
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_SHADOW_LO", "80")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_SHADOW_HI", "84")
    _eval(yes_bid_cents=82.0)
    _eval(yes_bid_cents=86.0)
    recs = _records(pfs._DEFAULT_PATH)
    assert len(recs) == 1 and recs[0]["entry_price_cents"] == 82.0


def test_never_raises_on_garbage():
    _eval(yes_bid_cents="bad", p_yes="worse", tte_seconds=object())
    # garbage bid cannot satisfy the band -> no records, no exception
    assert isinstance(_records(pfs._DEFAULT_PATH), list)
