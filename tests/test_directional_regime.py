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
    def __init__(self, r60=None, eligible=True, yes_imb=None, no_imb=None, r30=None, r120=None):
        self.rti_returns = {}
        if r60 is not None:
            self.rti_returns["rti_return_60s"] = r60
        if r30 is not None:
            self.rti_returns["rti_return_30s"] = r30
        if r120 is not None:
            self.rti_returns["rti_return_120s"] = r120
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


@pytest.fixture
def regime_state(tmp_path, monkeypatch):
    """Isolated regime-EMA state file per test + clean module cache."""
    p = tmp_path / "regime_state.json"
    monkeypatch.setenv("MERID_DIRECTIONAL_REGIME_STATE_PATH", str(p))
    dr._regime_cache = (0.0, {})
    yield str(p)
    dr._regime_cache = (0.0, {})


def _drive(snap, ticks=3, start=1_000_000.0, gap=5.0):
    """Feed ``snap`` for ``ticks`` consecutive observations (EMA/hysteresis)."""
    reg = None
    for i in range(ticks):
        reg = dr.compute_directional_regime(snap, now=start + i * gap)
    return reg


# ---------------------------------------------------------------- regime ----

def test_rally_confirmed_when_breadth_and_btc_positive(regime_state):
    snap = _snap_map(BTC=0.001, ETH=0.002, SOL=0.001, XRP=0.0005, DOGE=-0.001)
    # First aligned observation is only a vote — hysteresis requires the
    # confirm ticks before the label flips.
    assert dr.compute_directional_regime(snap, now=1_000_000.0).label == "NEUTRAL"
    reg = _drive(snap, ticks=1, start=1_000_005.0)
    assert reg.label == "RALLY_CONFIRMED"
    assert reg.breadth60_pos == 4 and reg.breadth60_total == 5
    assert reg.score > dr._regime_confirm_score()
    assert reg.up_ticks == 2


def test_selloff_confirmed_when_breadth_and_btc_negative(regime_state):
    snap = _snap_map(BTC=-0.001, ETH=-0.002, SOL=-0.001, XRP=-0.0005, DOGE=0.001)
    reg = _drive(snap)
    assert reg.label == "SELL_OFF_CONFIRMED"
    assert reg.score < -dr._regime_confirm_score()


def test_neutral_when_breadth_mixed(regime_state):
    snap = _snap_map(BTC=0.001, ETH=0.002, SOL=-0.001, XRP=0.0005, DOGE=-0.001)
    assert _drive(snap).label == "NEUTRAL"


def test_neutral_when_insufficient_breadth(regime_state):
    snap = _snap_map(BTC=0.01, ETH=None, SOL=None, XRP=None, DOGE=None)
    reg = _drive(snap, ticks=2)
    assert reg.label == "NEUTRAL"
    assert reg.reason.startswith("insufficient_rti_breadth")


def test_rally_requires_btc_positive(regime_state):
    snap = _snap_map(BTC=-0.0001, ETH=0.002, SOL=0.001, XRP=0.0005, DOGE=0.001)
    assert _drive(snap).label == "NEUTRAL"


def test_ineligible_rti_excluded_from_breadth(regime_state):
    snap = _Snap({a: _Slice(0.001, eligible=(a != "DOGE")) for a in dr._REGIME_ASSETS})
    reg = _drive(snap)
    assert reg.breadth60_total == 4
    assert reg.label == "RALLY_CONFIRMED"


def test_regime_weakens_before_neutral(regime_state):
    """Confirmed rally decays through WEAKENING rather than snapping off."""
    rally = _snap_map(BTC=0.001, ETH=0.002, SOL=0.001, XRP=0.0005, DOGE=-0.001)
    t = 1_000_000.0
    assert _drive(rally, ticks=3, start=t).label == "RALLY_CONFIRMED"
    # Mixed tape: vote 0 — EMA decays but the label stays directional
    # while score >= weaken threshold.
    mixed = _snap_map(BTC=0.0001, ETH=0.0, SOL=-0.0, XRP=0.0, DOGE=0.0)
    t += 3 * 5.0
    reg1 = dr.compute_directional_regime(mixed, now=t)
    assert reg1.label in ("RALLY_CONFIRMED", "RALLY_WEAKENING")
    # Enough neutral ticks eventually lands NEUTRAL.
    reg = _drive(mixed, ticks=6, start=t + 5.0)
    assert reg.label == "NEUTRAL"


def test_regime_no_whipsaw_on_single_tick(regime_state):
    """One selloff vote after a confirmed rally must not flip the label."""
    rally = _snap_map(BTC=0.001, ETH=0.002, SOL=0.001, XRP=0.0005, DOGE=-0.001)
    t = 1_000_000.0
    assert _drive(rally, ticks=3, start=t).label == "RALLY_CONFIRMED"
    dump = _snap_map(BTC=-0.001, ETH=-0.002, SOL=-0.001, XRP=-0.0005, DOGE=0.001)
    reg = dr.compute_directional_regime(dump, now=t + 5.0)
    assert reg.label != "SELL_OFF_CONFIRMED"


# ------------------------------------------------------------- entry gate ----

def test_no_blocked_in_rally_unless_deep_itm(regime_state):
    reg = _drive(_snap_map(BTC=0.001, ETH=0.002, SOL=0.001, XRP=0.0005, DOGE=-0.001))
    assert dr.regime_entry_block(reg, "no", zscore=-0.1) == "countertrend_no_rally_regime"
    assert dr.regime_entry_block(reg, "no", zscore=-0.9) is None
    assert dr.regime_entry_block(reg, "yes", zscore=0.1) is None


def test_yes_blocked_in_selloff_unless_deep_itm(regime_state):
    reg = _drive(_snap_map(BTC=-0.001, ETH=-0.002, SOL=-0.001, XRP=-0.0005, DOGE=0.001))
    assert dr.regime_entry_block(reg, "yes", zscore=0.2) == "countertrend_yes_selloff_regime"
    assert dr.regime_entry_block(reg, "yes", zscore=0.9) is None
    assert dr.regime_entry_block(reg, "no", zscore=-0.2) is None


def test_neutral_regime_blocks_nothing(regime_state):
    reg = _drive(_snap_all(0.0))
    for side in ("yes", "no"):
        assert dr.regime_entry_block(reg, side, zscore=0.0) is None


def test_weakening_regime_releases_countertrend_block(regime_state):
    """WEAKENING is not a blocking state — only *_CONFIRMED gates the
    countertrend side."""
    rally = _snap_map(BTC=0.001, ETH=0.002, SOL=0.001, XRP=0.0005, DOGE=-0.001)
    t = 1_000_000.0
    _drive(rally, ticks=3, start=t)
    mixed = _snap_map(BTC=0.0001, ETH=0.0, SOL=0.0, XRP=0.0, DOGE=0.0)
    reg = dr.compute_directional_regime(mixed, now=t + 15.0)
    assert reg.label == "RALLY_WEAKENING"
    assert dr.regime_entry_block(reg, "no", zscore=-0.1) is None


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
    # Pin lane-config knobs: production .env may relax them (2026-10-03
    # throughput audit); these tests assert the code defaults regardless
    # of operator configuration.
    monkeypatch.delenv("MERID_STRIP_CONC_MAX_OPEN_SAME_SIDE", raising=False)
    monkeypatch.delenv("MERID_SIDE_CATASTROPHE_SCOPE", raising=False)
    monkeypatch.delenv("MERID_SIDE_CATASTROPHE_TTL_S", raising=False)
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

def test_countertrend_lane_cold_start(regime_state, throttle_path, monkeypatch):
    # Pin the floor explicitly: production .env may set
    # MERID_ASR_COUNTERTREND_MIN_MARKOUTS=0 (cold-start deadlock fix), and this
    # test asserts the positive-floor path regardless of operator config.
    monkeypatch.setenv("MERID_ASR_COUNTERTREND_MIN_MARKOUTS", "20")
    reg = _drive(_snap_map(BTC=0.001, ETH=0.002, SOL=0.001, XRP=0.0005, DOGE=-0.001))
    blk = dr.countertrend_lane_block("XRP", "no", reg)
    assert blk and blk.startswith("countertrend_lane_cold_start")


def test_countertrend_lane_neutral_no_block(regime_state, throttle_path):
    reg = _drive(_snap_all(0.0))
    assert dr.countertrend_lane_block("XRP", "no", reg) is None


def test_countertrend_lane_min_markouts_zero_opens(regime_state, throttle_path, monkeypatch):
    """MIN_MARKOUTS=0 opens the cold-start lane even with n=0 samples.

    Markouts only accrue from orders the lane admits, so a positive floor
    can never be satisfied during the regime it gates.  Zero is the
    deadlock-breaking configuration; every other gate still applies.
    """
    monkeypatch.setenv("MERID_ASR_COUNTERTREND_MIN_MARKOUTS", "0")
    reg = _drive(_snap_map(BTC=0.001, ETH=0.002, SOL=0.001, XRP=0.0005, DOGE=-0.001))
    assert reg is not None and reg.label == "RALLY_CONFIRMED"
    assert dr.countertrend_lane_block("XRP", "no", reg) is None

    # A positive floor still gates the symmetric countertrend lane: fresh
    # selloff state -> countertrend YES with zero samples stays cold-start
    # blocked when the env floor is restored.
    monkeypatch.setenv("MERID_ASR_COUNTERTREND_MIN_MARKOUTS", "20")
    if os.path.exists(regime_state):
        os.remove(regime_state)
    dr._regime_cache = (0.0, {})
    reg_sell = _drive(_snap_map(BTC=-0.001, ETH=-0.002, SOL=-0.001, XRP=-0.0005, DOGE=0.001))
    assert reg_sell is not None and reg_sell.label == "SELL_OFF_CONFIRMED"
    blk = dr.countertrend_lane_block("XRP", "yes", reg_sell)
    assert blk and blk.startswith("countertrend_lane_cold_start")


# ------------------------------------------------- graded lane machine ----

def test_first_loss_caution_not_suspension(throttle_path):
    """One post-release loss -> CAUTION (edge margin), not a block."""
    dr.record_side_settlement("no", -50.0, ts=1_000_000.0, decision_id="d1")
    assert dr.side_throttle_block("no", now=1_000_001.0) is None
    assert dr.side_caution_margin_cents("no", now=1_000_001.0) == pytest.approx(2.0)
    assert dr.side_lane_state("no", now=1_000_001.0) == "CAUTION"
    assert dr.side_caution_margin_cents("yes", now=1_000_001.0) == 0.0


def test_caution_expires_and_win_clears(throttle_path):
    dr.record_side_settlement("no", -50.0, ts=1_000_000.0, decision_id="d1")
    assert dr.side_caution_margin_cents("no", now=1_000_000.0 + 3700.0) == 0.0
    dr.record_side_settlement("no", +10.0, ts=1_000_100.0, decision_id="d2")
    assert dr.side_caution_margin_cents("no", now=1_000_101.0) == 0.0
    assert dr.side_lane_state("no", now=1_000_101.0) == "OPEN"


def test_release_watermark_restarts_streak(throttle_path):
    """Operator release: pre-release losses no longer count toward tiers."""
    now = 1_000_000.0
    dr.record_side_settlement("no", -50.0, ts=now - 300, decision_id="d1")
    dr.record_side_settlement("no", -40.0, ts=now - 200, decision_id="d2")
    dr.record_side_settlement("no", -30.0, ts=now - 100, decision_id="d3")
    assert "manual_review" in (dr.side_throttle_block("no", now=now) or "")
    dr.release_side("no", ts=now)
    assert dr.side_throttle_block("no", now=now + 1) is None
    # The very next loss is tier-1 CAUTION, not an instant relock.
    dr.record_side_settlement("no", -25.0, ts=now + 10, decision_id="d4")
    assert dr.side_throttle_block("no", now=now + 11) is None
    assert dr.side_caution_margin_cents("no", now=now + 11) > 0.0


def test_record_side_catastrophe_manual_review(throttle_path):
    dr.record_side_catastrophe("yes", "cbp_eth_yes_50_60:post_only_order_became_taker", ts=1_000_000.0)
    blk = dr.side_throttle_block("yes", now=1_000_001.0)
    assert blk and "manual_review" in blk and "catastrophic" in blk
    assert dr.side_lane_state("yes", now=1_000_001.0) == "MANUAL_REVIEW"


# --------------------------------------------------- trend-yes-hi lane ----

def test_trend_yes_hi_disabled_by_default(regime_state, monkeypatch):
    monkeypatch.delenv("MERID_TREND_YES_HI_ENABLED", raising=False)
    reg = _drive(_snap_map(BTC=0.001, ETH=0.002, SOL=0.001, XRP=0.0005, DOGE=-0.001))
    assert dr.trend_yes_hi_enabled() is False
    assert dr.trend_yes_hi_reachable(92.0, 200.0) is False
    assert dr.trend_yes_hi_band_match(92.0) is True
    assert dr.trend_yes_hi_band_match(90.0) is False  # 90c is skewed_high, not the lane
    assert dr.trend_yes_hi_band_match(95.0) is False
    blk = dr.trend_yes_hi_block(
        "BTC", 92.0, 0.96, 4.0, 200.0, reg,
        _Snap({a: _Slice(r60=0.001, r30=0.001, r120=0.001) for a in dr._REGIME_ASSETS}),
    )
    assert blk is None  # inert when disabled


def test_trend_yes_hi_strict_gate(regime_state, throttle_path, monkeypatch):
    monkeypatch.setenv("MERID_TREND_YES_HI_ENABLED", "1")
    rally = _snap_map(BTC=0.001, ETH=0.002, SOL=0.001, XRP=0.0005, DOGE=-0.001)
    reg = _drive(rally, ticks=3)
    assert reg.label == "RALLY_CONFIRMED"
    snap = _Snap({a: _Slice(r60=0.001, r30=0.001, r120=0.001) for a in dr._REGIME_ASSETS})
    # Clean pass.
    assert dr.trend_yes_hi_block("BTC", 92.0, 0.95, 3.5, 200.0, reg, snap) is None
    # Each strict condition must veto.
    assert dr.trend_yes_hi_block("BTC", 92.0, 0.93, 3.5, 200.0, reg, snap) == "trend_yes_hi_low_conviction"
    assert dr.trend_yes_hi_block("BTC", 92.0, 0.95, 2.5, 200.0, reg, snap) == "trend_yes_hi_low_ev"
    assert dr.trend_yes_hi_block("BTC", 92.0, 0.95, 3.5, 400.0, reg, snap) == "trend_yes_hi_tte"
    # Missing BTC r120 fails closed.
    snap_no120 = _Snap({a: _Slice(r60=0.001, r30=0.001) for a in dr._REGIME_ASSETS})
    assert dr.trend_yes_hi_block("BTC", 92.0, 0.95, 3.5, 200.0, reg, snap_no120) == "trend_yes_hi_btc_r120"
    # Countertrend regime never admits the lane.
    neutral = _drive(_snap_all(0.0), start=2_000_000.0)
    assert dr.trend_yes_hi_block("BTC", 92.0, 0.95, 3.5, 200.0, neutral, snap) == "trend_yes_hi_regime_not_confirmed"
    # Out-of-window prices fail closed when armed (95-99c never admitted).
    assert dr.trend_yes_hi_block("BTC", 95.0, 0.97, 5.0, 200.0, reg, snap) == "trend_yes_hi_band"
    assert dr.trend_yes_hi_block("BTC", 89.0, 0.97, 5.0, 200.0, reg, snap) == "trend_yes_hi_band"
