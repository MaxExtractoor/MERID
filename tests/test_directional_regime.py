"""Tests for merid.prediction.directional_regime — post-drawdown controls."""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.prediction import directional_regime as dr


@pytest.fixture(autouse=True)
def _conviction_gate_on(monkeypatch):
    # conftest pins the gate off for legacy decision tests; this module owns it.
    monkeypatch.setenv("MERID_CONVICTION_GATE_ENABLED", "1")


class _Slice:
    def __init__(self, r60=None, eligible=True, yes_imb=None, no_imb=None):
        self.rti_returns = {"rti_return_60s": r60} if r60 is not None else {}
        self.rti_execution_eligible = eligible
        self.book_imbalance_yes = yes_imb
        self.book_imbalance_no = no_imb


class _Snap:
    def __init__(self, slices):
        self.by_asset = slices


def _snap_all(r60):
    return _Snap({a: _Slice(r60) for a in dr._REGIME_ASSETS})


def _snap_map(**kw):
    return _Snap({a: _Slice(kw.get(a)) for a in dr._REGIME_ASSETS})


# ---------------------------------------------------------------- regime ----

def test_rally_confirmed_when_breadth_and_btc_positive():
    snap = _snap_map(BTC=0.001, ETH=0.002, SOL=0.001, XRP=0.0005, DOGE=-0.001)
    reg = dr.compute_directional_regime(snap)
    assert reg.label == "RALLY_CONFIRMED"
    assert reg.breadth60_pos == 4 and reg.breadth60_total == 5


def test_selloff_confirmed_when_breadth_and_btc_negative():
    snap = _snap_map(BTC=-0.001, ETH=-0.002, SOL=-0.001, XRP=-0.0005, DOGE=0.001)
    reg = dr.compute_directional_regime(snap)
    assert reg.label == "SELL_OFF_CONFIRMED"


def test_neutral_when_breadth_mixed():
    snap = _snap_map(BTC=0.001, ETH=0.002, SOL=-0.001, XRP=0.0005, DOGE=-0.001)
    assert dr.compute_directional_regime(snap).label == "NEUTRAL"


def test_neutral_when_insufficient_breadth():
    snap = _snap_map(BTC=0.01, ETH=None, SOL=None, XRP=None, DOGE=None)
    reg = dr.compute_directional_regime(snap)
    assert reg.label == "NEUTRAL"
    assert reg.reason == "insufficient_rti_breadth"


def test_rally_requires_btc_positive():
    snap = _snap_map(BTC=-0.0001, ETH=0.002, SOL=0.001, XRP=0.0005, DOGE=0.001)
    assert dr.compute_directional_regime(snap).label == "NEUTRAL"


def test_ineligible_rti_excluded_from_breadth():
    snap = _Snap({a: _Slice(0.001, eligible=(a != "DOGE")) for a in dr._REGIME_ASSETS})
    reg = dr.compute_directional_regime(snap)
    assert reg.breadth60_total == 4
    assert reg.label == "RALLY_CONFIRMED"


# ------------------------------------------------------------- entry gate ----

def test_no_blocked_in_rally_unless_deep_itm():
    reg = dr.compute_directional_regime(
        _snap_map(BTC=0.001, ETH=0.002, SOL=0.001, XRP=0.0005, DOGE=-0.001)
    )
    assert dr.regime_entry_block(reg, "no", zscore=-0.1) == "countertrend_no_rally_regime"
    assert dr.regime_entry_block(reg, "no", zscore=-0.9) is None
    assert dr.regime_entry_block(reg, "yes", zscore=0.1) is None


def test_yes_blocked_in_selloff_unless_deep_itm():
    reg = dr.compute_directional_regime(
        _snap_map(BTC=-0.001, ETH=-0.002, SOL=-0.001, XRP=-0.0005, DOGE=0.001)
    )
    assert dr.regime_entry_block(reg, "yes", zscore=0.2) == "countertrend_yes_selloff_regime"
    assert dr.regime_entry_block(reg, "yes", zscore=0.9) is None
    assert dr.regime_entry_block(reg, "no", zscore=-0.2) is None


def test_neutral_regime_blocks_nothing():
    reg = dr.compute_directional_regime(_snap_all(0.0))
    for side in ("yes", "no"):
        assert dr.regime_entry_block(reg, side, zscore=0.0) is None


def test_none_regime_blocks_nothing():
    assert dr.regime_entry_block(None, "no", zscore=0.0) is None


# ------------------------------------------------------------ conviction ----

def test_conviction_defaults():
    assert dr.conviction_min_distance("BTC") == pytest.approx(0.06)
    assert dr.conviction_min_distance("ETH") == pytest.approx(0.06)
    assert dr.conviction_min_distance("SOL") == pytest.approx(0.07)
    assert dr.conviction_min_distance("XRP") == pytest.approx(0.07)
    assert dr.conviction_min_distance("DOGE") == pytest.approx(0.08)


def test_coin_flip_blocked_both_sides():
    # BTC NO at p=0.501 — the canonical loss-episode violation.
    assert dr.conviction_block_reason("BTC", 0.501) == "low_conviction"
    assert dr.conviction_block_reason("BTC", 0.499) == "low_conviction"
    assert dr.conviction_block_reason("BTC", 0.561) is None
    assert dr.conviction_block_reason("BTC", 0.439) is None


def test_conviction_none_passes():
    assert dr.conviction_block_reason("BTC", None) is None


def test_conviction_env_override(monkeypatch):
    monkeypatch.setenv("MERID_CONVICTION_MIN_DIST_BTC", "0.10")
    assert dr.conviction_min_distance("BTC") == pytest.approx(0.10)
    assert dr.conviction_block_reason("BTC", 0.58) == "low_conviction"


def test_conviction_gate_disable(monkeypatch):
    monkeypatch.setenv("MERID_CONVICTION_GATE_ENABLED", "0")
    assert dr.conviction_block_reason("BTC", 0.501) is None


# ------------------------------------------------------------- bookflow ----

def test_bookflow_blocks_no_under_yes_pressure():
    snap = _Snap({"XRP": _Slice(0.001, yes_imb=0.35)})
    assert dr.bookflow_block_reason(snap, "XRP", "no") == "bookflow_yes_pressure"
    assert dr.bookflow_block_reason(snap, "XRP", "yes") is None


def test_bookflow_blocks_yes_under_no_pressure():
    snap = _Snap({"XRP": _Slice(-0.001, no_imb=0.35)})
    assert dr.bookflow_block_reason(snap, "XRP", "yes") == "bookflow_no_pressure"


def test_bookflow_missing_slice_no_block():
    assert dr.bookflow_block_reason(None, "XRP", "no") is None
    assert dr.bookflow_block_reason(_Snap({}), "XRP", "no") is None


# --------------------------------------------------------- side throttle ----

@pytest.fixture
def throttle_path(tmp_path, monkeypatch):
    p = tmp_path / "throttle.json"
    monkeypatch.setenv("MERID_DIRECTIONAL_THROTTLE_PATH", str(p))
    dr._throttle_cache = (0.0, {})
    yield str(p)
    dr._throttle_cache = (0.0, {})


def test_two_losses_60m_suspend_side(throttle_path):
    now = 1_000_000.0
    dr.record_side_settlement("no", -50.0, ts=now - 100, decision_id="d1")
    dr.record_side_settlement("no", -30.0, ts=now, decision_id="d2")
    blk = dr.side_throttle_block("no", now=now + 1)
    assert blk and "side_suspended" in blk
    assert "2_consecutive_losses" in blk


def test_win_breaks_streak(throttle_path):
    now = 1_000_000.0
    dr.record_side_settlement("no", -50.0, ts=now - 200, decision_id="d1")
    dr.record_side_settlement("no", +40.0, ts=now - 100, decision_id="d2")
    dr.record_side_settlement("no", -30.0, ts=now, decision_id="d3")
    assert dr.side_throttle_block("no", now=now + 1) is None


def test_other_side_settlement_ignored_for_streak(throttle_path):
    now = 1_000_000.0
    dr.record_side_settlement("no", -50.0, ts=now - 100, decision_id="d1")
    dr.record_side_settlement("yes", -70.0, ts=now - 50, decision_id="d2")
    dr.record_side_settlement("no", -30.0, ts=now, decision_id="d3")
    blk = dr.side_throttle_block("no", now=now + 1)
    assert blk and "2_consecutive_losses" in blk
    # yes side has 1 loss -> not suspended
    assert dr.side_throttle_block("yes", now=now + 1) is None


def test_three_epoch_losses_manual_review(throttle_path):
    # Third consecutive loss is >60m after the first — windowed rule can't
    # fire, but the epoch-wide review tier still must.
    now = 1_000_000.0
    dr.record_side_settlement("no", -10.0, ts=now - 7200, decision_id="d1")
    dr.record_side_settlement("no", -20.0, ts=now - 3700, decision_id="d2")
    dr.record_side_settlement("no", -30.0, ts=now, decision_id="d3")
    blk = dr.side_throttle_block("no", now=now + 1)
    assert blk and "manual_review" in blk


def test_suspension_expires_after_window(throttle_path):
    now = 1_000_000.0
    dr.record_side_settlement("no", -50.0, ts=now - 100, decision_id="d1")
    dr.record_side_settlement("no", -30.0, ts=now, decision_id="d2")
    # 60m suspension from `now` — active at +30m, cleared at +61m.
    assert dr.side_throttle_block("no", now=now + 1800) is not None
    assert dr.side_throttle_block("no", now=now + 3661) is None


def test_epoch_reset_clears_state(throttle_path, monkeypatch):
    dr.record_side_settlement("no", -50.0, ts=1_000_000.0, decision_id="d1")
    dr.record_side_settlement("no", -50.0, ts=1_000_001.0, decision_id="d2")
    monkeypatch.setattr(dr, "POLICY_EPOCH", "next_epoch_test")
    monkeypatch.setenv("MERID_POLICY_EPOCH", "next_epoch_test")
    dr._throttle_cache = (0.0, {})
    assert dr.side_throttle_block("no", now=1_000_002.0) is None


def test_strip_concentration_blocks_open_same_side(throttle_path):
    now = 1_700_000_000.0
    dr.record_strip_entry("no", 5.0, ts=now, decision_id="a")
    blk = dr.strip_concentration_block("no", 9.0, ts=now + 60)
    assert blk == "strip_same_side_open:no"
    # opposite side unaffected
    assert dr.strip_concentration_block("yes", 1.0, ts=now + 60) is None


def test_strip_second_entry_needs_ev_margin(throttle_path):
    now = 1_700_000_000.0
    dr.record_strip_entry("no", 5.0, ts=now, decision_id="a")
    dr.record_side_settlement("no", +20.0, ts=now + 30, decision_id="a")  # closes 'a'
    assert dr.strip_concentration_block("no", 7.0, ts=now + 60) == "strip_same_side_ev:no"
    assert dr.strip_concentration_block("no", 9.0, ts=now + 60) is None


def test_strip_window_rolls_over(throttle_path):
    now = 1_700_000_000.0
    dr.record_strip_entry("no", 5.0, ts=now, decision_id="a")
    assert dr.strip_concentration_block("no", 1.0, ts=now + 901) is None


def test_throttle_disabled_no_blocks(throttle_path, monkeypatch):
    monkeypatch.setenv("MERID_SIDE_THROTTLE_ENABLED", "0")
    dr.record_side_settlement("no", -50.0, ts=1_000_000.0, decision_id="d1")
    dr.record_side_settlement("no", -50.0, ts=1_000_001.0, decision_id="d2")
    assert dr.side_throttle_block("no", now=1_000_002.0) is None


# ------------------------------------------------------- countertrend lane ----

def test_countertrend_lane_cold_start(monkeypatch, throttle_path):
    reg = dr.compute_directional_regime(
        _snap_map(BTC=0.001, ETH=0.002, SOL=0.001, XRP=0.0005, DOGE=-0.001)
    )
    blk = dr.countertrend_lane_block("XRP", "no", reg)
    assert blk and blk.startswith("countertrend_lane_cold_start")


def test_countertrend_lane_neutral_no_block(throttle_path):
    reg = dr.compute_directional_regime(_snap_all(0.0))
    assert dr.countertrend_lane_block("XRP", "no", reg) is None
