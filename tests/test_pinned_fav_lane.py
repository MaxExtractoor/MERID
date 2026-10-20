"""Regression coverage for the pinned-favorite lane (2026-10-17).

The extreme-band audit found the market-regime classifier hard-disabled
both sides at >=91c / <=9c before economics ran — yet the measured
counterfactual showed 92-98c favorites at TTE 300-900s realizing
+1.9..+7.3c/contract (97.5-98.8% win, all five assets, both sides).

The lane removes only the *pre-economics* vetoes for that window; normal
economics (net-EV floor, reserves, evidence, throttle, book-flow,
edge-bias correction, model-edge floor) still decide admission.  These
tests pin the lane's window, terminal codes, precedence, and the
single-charge tail-LCB semantics — and confirm non-pinned candidates keep
the generic bounds.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import merid.prediction.trade_decision as _td
from merid.prediction import directional_regime as dr
from merid.prediction.trade_decision import compute_trade_decision


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    """Isolated durable-state + evidence env per test."""
    monkeypatch.setenv(
        "MERID_EVIDENCE_ESCAPE_STATE_PATH", str(tmp_path / "escape.json")
    )
    monkeypatch.setenv(
        "MERID_DIRECTIONAL_THROTTLE_PATH", str(tmp_path / "throttle.json")
    )
    # The lane's own durable daily counter must never read production state.
    monkeypatch.setenv(
        "MERID_PINNED_FAV_STATE_PATH", str(tmp_path / "pinned_fav.json")
    )
    yield


def _decision(asset: str = "ETH", **over):
    """Decision for a strongly pinned market: YES ask 93c, spot well clear
    of strike (raw Bachelier p_yes ~0.9999 -> capped at the lane p-cap)."""
    args = dict(
        run_id="pf_test",
        decision_id=f"pf_{asset}",
        ticker=f"KX{asset}15M-TEST",
        asset=asset,
        spot_price=101.0,
        strike_price=100.0,
        seconds_to_expiry=600.0,
        yes_bid_cents=91.0,
        yes_ask_cents=93.0,
        no_bid_cents=7.0,
        no_ask_cents=9.0,
        yes_depth_cc=200.0,
        no_depth_cc=200.0,
        fee_per_contract_cents=1.0,
        annualized_vol=0.60,
        model_uncertainty=0.05,
        data_quality="live",
        regime="normal",
        min_required_edge=0.02,
        settlement_reference="cfb_rti_live",
        route="taker",
    )
    args.update(over)
    return compute_trade_decision(**args)


# ------------------------------------------------------------ gate unit ----

def test_band_match_flag_independent():
    """Band match is flag-independent: the engine uses it to disable the
    normal qualify path at 92-98c even with the lane off."""
    assert dr.pinned_fav_band_match(92.0) is True
    assert dr.pinned_fav_band_match(98.0) is True
    assert dr.pinned_fav_band_match(95.5) is True
    assert dr.pinned_fav_band_match(91.9) is False   # 91c is break-even
    assert dr.pinned_fav_band_match(99.0) is False   # no payoff headroom
    assert dr.pinned_fav_band_match(None) is False
    assert dr.pinned_fav_band_match(50.0) is False


def test_reachable_requires_armed_band_tte(monkeypatch):
    monkeypatch.delenv("MERID_PINNED_FAV_ENABLED", raising=False)
    assert dr.pinned_fav_reachable(93.0, 600.0) is False
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "1")
    assert dr.pinned_fav_reachable(93.0, 600.0) is True
    assert dr.pinned_fav_reachable(93.0, 299.0) is False   # below lane TTE
    assert dr.pinned_fav_reachable(93.0, 841.0) is False   # above live bound
    assert dr.pinned_fav_reachable(90.0, 600.0) is False   # out of band
    assert dr.pinned_fav_reachable(93.0, None) is False


def test_block_inert_when_disabled():
    blk = dr.pinned_fav_block(side_price_cents=93.0, net_ev_cents=5.0,
                              tte_seconds=600.0)
    assert blk is None


def test_block_each_failure_named(monkeypatch):
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_MIN_EV_CENTS", "2.0")
    assert dr.pinned_fav_block(91.0, 5.0, 600.0) == "pinned_fav_band"
    assert dr.pinned_fav_block(99.0, 5.0, 600.0) == "pinned_fav_band"
    assert dr.pinned_fav_block(93.0, 5.0, 200.0) == "pinned_fav_tte"
    assert dr.pinned_fav_block(93.0, 5.0, None) == "pinned_fav_tte"
    assert dr.pinned_fav_block(93.0, 1.5, 600.0) == "pinned_fav_low_ev"
    assert dr.pinned_fav_block(93.0, None, 600.0) == "pinned_fav_low_ev"
    assert dr.pinned_fav_block(93.0, 2.5, 600.0) is None


def test_block_negative_floor_probe(monkeypatch):
    """Bounded-probe semantics: a negative lane floor admits negative-net
    candidates down to the floor (the probe domain), vetoes below it."""
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_MIN_EV_CENTS", "-6.0")
    assert dr.pinned_fav_block(93.0, -4.0, 600.0) is None
    assert dr.pinned_fav_block(93.0, -6.0, 600.0) is None
    assert dr.pinned_fav_block(93.0, -6.5, 600.0) == "pinned_fav_low_ev"


def test_block_daily_cap(monkeypatch):
    """The lane's own durable daily cap: an otherwise-clean gate reports
    pinned_fav_daily_cap once the submission counter reaches the max."""
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_DAILY_MAX", "3")
    monkeypatch.setenv("MERID_PINNED_FAV_MIN_EV_CENTS", "-6.0")
    import os as _os
    _p = _os.environ["MERID_PINNED_FAV_STATE_PATH"]
    for _ in range(3):
        dr.record_pinned_fav_submission(_p)
    assert dr.pinned_fav_fills_today(_p) == 3
    assert dr.pinned_fav_cap_remaining(_p) == 0
    assert dr.pinned_fav_block(93.0, 5.0, 600.0) == "pinned_fav_daily_cap"
    # Counter resets on a new UTC day.
    import time as _t
    _tomorrow = _t.time() + 90000.0
    assert dr.pinned_fav_cap_remaining(_p, now=_tomorrow) == 3


def test_lane_in_bounded_set():
    """Bounded sizing is non-negotiable for a probe lane whose claimed edge
    can be negative — membership gives the 1-contract cap + probe
    restriction (post-only when evidence-refused or LCB<=0)."""
    assert "pinned_fav" in _td.BOUNDED_POST_ONLY_LANES


# ------------------------------------------------------- engine admission ----

def test_lane_disabled_owns_terminal_reason():
    """conftest pins the lane off — a 92-98c candidate still reports the
    lane's reserved-window label, never an ordinary-gate reason."""
    d = _decision()
    assert d.selected_outcome is None
    assert d.indicators.get("yes_block") == "pinned_fav_disabled"


def _write_live_evidence(tmp_path, cells):
    """Minimal live-evidence artifact so the evidence loop runs in tests."""
    import json, time
    p = tmp_path / "live_evidence.json"
    p.write_text(json.dumps({
        "version": 2,
        "generated_at": time.time(),
        "halflife_days_primary": 7,
        "cells": {"7": cells},
    }))
    return str(p)


def test_lane_admits_strong_pin(tmp_path, monkeypatch):
    """Armed lane + strong pin (spot >> strike): the 93c YES ask admits,
    stamps both lane fields, and survives the tail-LCB bounded-domain gate
    (single model-risk charge).  The claimed net is negative under the
    legacy reserve stack (~-4c) — the bounded negative floor is exactly
    the probe domain the lane exists to evaluate."""
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_MIN_EV_CENTS", "-6.0")
    monkeypatch.setenv(
        "MERID_LIVE_EVIDENCE_PATH", _write_live_evidence(tmp_path, {})
    )
    d = _decision()
    assert d.selected_outcome == "yes", (
        d.indicators.get("yes_block"), d.no_trade_reason,
        d.indicators.get("bounded_domain_gate"),
        d.indicators.get("yes_admission_reason"),
        d.indicators.get("evidence_yes"),
    )
    assert d.indicators.get("decision_lane") == "pinned_fav"
    assert d.indicators.get("entry_lane") == "pinned_fav"
    assert d.indicators.get("yes_pinned_fav_qualifies") is True
    bdg = d.indicators.get("bounded_domain_gate") or {}
    # Single-charge LCB: basis is net_edge, not net_edge - model_risk.
    assert bdg.get("lcb_basis") == "pinned_fav_net_edge"
    # Lane admission owner must attribute to pinned_fav, not the shared
    # escape lane.
    assert d.indicators.get("yes_admission_owner") == "pinned_fav"


def test_lane_probe_floor_still_binds(monkeypatch):
    """Floor +2c (legacy default): the same strong pin stays vetoed —
    the probe only exists because the operator set a negative floor."""
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_MIN_EV_CENTS", "2.0")
    d = _decision()
    assert d.selected_outcome is None
    assert d.indicators.get("yes_block") == "pinned_fav_low_ev"


def test_lane_rejects_short_tte(monkeypatch):
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "1")
    d = _decision(seconds_to_expiry=200.0)
    assert d.selected_outcome is None
    assert d.indicators.get("yes_block") == "pinned_fav_tte"


def test_lane_rejects_weak_ev(monkeypatch):
    """A pin where the model barely clears the ask fails the lane's own
    net-EV floor — spot barely above strike keeps p ~0.95-0.96 so the
    claimed net edge is below 2c."""
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "1")
    d = _decision(spot_price=100.05)   # p_yes ~0.5-0.6: no edge at 93c
    assert d.selected_outcome is None
    assert d.indicators.get("yes_block") in (
        "pinned_fav_low_ev", "edge_below_threshold_yes",
        "model_edge_floor", "evidence_soft_penalty_insufficient_yes",
        "evidence_challenge_insufficient_yes",
    )


def test_no_side_mirror(monkeypatch):
    """NO at 93c (yes_bid=7 -> no_price=93) uses the same lane machinery."""
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_MIN_EV_CENTS", "-6.0")
    d = _decision(
        spot_price=99.0,              # spot well below strike: p_no ~0.99
        yes_bid_cents=7.0, yes_ask_cents=9.0,
        no_bid_cents=91.0, no_ask_cents=93.0,
    )
    assert d.selected_outcome == "no", (
        d.indicators.get("no_block"), d.no_trade_reason,
    )
    assert d.indicators.get("decision_lane") == "pinned_fav"
    assert d.indicators.get("no_pinned_fav_qualifies") is True


def _refused_cells():
    """Scored-level refusal shaped like the live DOGE@92c observation:
    the matched price cell is sparse-but-winning while the cross-price
    side prior drags the pooled posterior far below the 93c breakeven —
    CELL_EVIDENCE_INSUFFICIENT, non-toxic."""
    return {
        # Scored price-matched cell: the cohort's own record is winning
        # (~95.5% like the live DOGE@92 cell) but thin.
        "ETH|yes|90-100|mid": {"w": 10.0, "l": 0.5, "n_eff": 10.5,
                               "n_raw": 60},
        # Dense cheap-side losers: drag the LOO `side` parent mean toward
        # ~0.3 so the sparse pinned cell's posterior lands far below its
        # own cost basis (the pooled-prior contamination observed live).
        "ETH|yes|40-60|mid": {"w": 20.0, "l": 40.0, "n_eff": 60.0,
                              "n_raw": 300},
        "BTC|yes|40-60|mid": {"w": 8.0, "l": 22.0, "n_eff": 30.0,
                              "n_raw": 150},
    }


def test_refused_evidence_demotes_to_probe(tmp_path, monkeypatch):
    """Inside the armed band a non-toxic evidence refusal demotes to the
    lane's bounded probe (commit 3ef44817 design): admission owner is
    pinned_fav, the refusal is recorded as an override label, and the
    decision still clears the lane gate (floor/TTE/cap)."""
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_MIN_EV_CENTS", "-8.0")
    monkeypatch.setenv("MERID_EVIDENCE_MIN_CELL_NEFF", "4")
    monkeypatch.setenv("MERID_EVIDENCE_MIN_PARENT_NEFF", "8")
    monkeypatch.setenv(
        "MERID_LIVE_EVIDENCE_PATH",
        _write_live_evidence(tmp_path, _refused_cells()),
    )
    d = _decision()
    assert d.selected_outcome == "yes", (
        d.indicators.get("yes_block"), d.no_trade_reason,
        d.indicators.get("yes_admission_reason"),
        d.indicators.get("evidence_yes"),
    )
    assert d.indicators.get("yes_admission_owner") == "pinned_fav"
    assert d.indicators.get("yes_admission_decision") == "allowed"
    assert str(
        d.indicators.get("yes_admission_reason") or ""
    ).startswith("pinned_fav_probe:")
    assert (
        d.indicators.get("yes_evidence_override")
        == "pinned_fav_refused_probe"
    )
    assert d.indicators.get("decision_lane") == "pinned_fav"
    assert d.indicators.get("entry_lane") == "pinned_fav"


def test_refused_evidence_demotion_lane_disabled(tmp_path, monkeypatch):
    """Same refused cell with the lane OFF stays a hard block owned by
    evidence_escape — the demotion is lane-scoped, not a global evidence
    bypass."""
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "0")
    monkeypatch.setenv("MERID_EVIDENCE_MIN_CELL_NEFF", "4")
    monkeypatch.setenv(
        "MERID_LIVE_EVIDENCE_PATH",
        _write_live_evidence(tmp_path, _refused_cells()),
    )
    d = _decision()
    assert d.selected_outcome is None
    assert d.indicators.get("yes_admission_owner") != "pinned_fav"
    assert "pinned_fav_probe" not in str(
        d.indicators.get("yes_admission_reason") or ""
    )


def test_refused_evidence_hard_block_not_demoted(tmp_path, monkeypatch):
    """A dense toxic cell (matching_hard_block) must NOT demote — the lane
    probes unproven cohorts, never measured losers."""
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_MIN_EV_CENTS", "-8.0")
    monkeypatch.setenv("MERID_EVIDENCE_HARD_BLOCK_MODE", "veto")
    monkeypatch.setenv("MERID_EVIDENCE_MIN_CELL_NEFF", "4")
    toxic = {
        # Dense measured loser at the candidate's own price bucket.
        "ETH|yes|90-100|mid": {"w": 15.0, "l": 45.0, "n_eff": 60.0,
                               "n_raw": 400},
    }
    monkeypatch.setenv(
        "MERID_LIVE_EVIDENCE_PATH",
        _write_live_evidence(tmp_path, toxic),
    )
    d = _decision()
    assert d.selected_outcome is None
    # The lane owns the terminal reason: the scored level's own measured
    # win rate (25% at a ~93c breakeven) is a demonstrated loss, so the
    # refusal is NOT demoted to a probe — reported as the lane's measured
    # -loss veto (or the toxic-cell veto if the hard block fired first).
    assert d.indicators.get("yes_admission_reason") in (
        "pinned_fav_measured_loss",
        "matching_toxic_cell",
    )
    assert "pinned_fav_probe" not in str(
        d.indicators.get("yes_admission_reason") or ""
    )


def test_refused_probe_still_hits_lane_floor(tmp_path, monkeypatch):
    """The demotion lifts only the evidence veto — a weak pin whose claim
    misses the lane floor is still vetoed by pinned_fav_low_ev."""
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_MIN_EV_CENTS", "-8.0")
    monkeypatch.setenv("MERID_EVIDENCE_MIN_CELL_NEFF", "4")
    monkeypatch.setenv(
        "MERID_LIVE_EVIDENCE_PATH",
        _write_live_evidence(tmp_path, _refused_cells()),
    )
    d = _decision(spot_price=100.02)  # p_yes ~ coin flip: deeply negative claim
    assert d.selected_outcome is None
    assert d.indicators.get("yes_block") == "pinned_fav_low_ev"


def test_normal_band_candidates_unaffected(monkeypatch):
    """A balanced-market candidate keeps the generic p-cap and formula
    lane — the pinned lane's machinery never touches 10-75c prices."""
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "1")
    d = _decision(
        spot_price=100.05,
        yes_bid_cents=40.0, yes_ask_cents=42.0,
        no_bid_cents=58.0, no_ask_cents=60.0,
    )
    # Whatever the economics decide, the pinned lane fields must be absent.
    assert d.indicators.get("decision_lane") != "pinned_fav"
    assert d.indicators.get("entry_lane") != "pinned_fav"
    assert d.indicators.get("yes_pinned_fav_price") is False
    assert d.indicators.get("no_pinned_fav_price") is False


def test_pcap_headroom_only_in_band(monkeypatch):
    """The lane p-cap applies only inside the band: a pinned YES admits
    p_selected > 0.95 while a normal-band decision never exceeds 0.95."""
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "1")
    d = _decision()
    yes_bd = d.yes_edge_breakdown
    assert yes_bd is not None and yes_bd.p_selected > 0.95
    d2 = _decision(
        spot_price=100.05,
        yes_bid_cents=40.0, yes_ask_cents=42.0,
        no_bid_cents=58.0, no_ask_cents=60.0,
    )
    for bd in (d2.yes_edge_breakdown, d2.no_edge_breakdown):
        if bd is not None:
            assert bd.p_selected <= 0.95 + 1e-9


# ------------------------------------------------- escape-path plumbing ----

class _Slice:
    def __init__(self, yes_imb=None, no_imb=None):
        self.rti_returns = {}
        self.book_imbalance_yes = yes_imb
        self.book_imbalance_no = no_imb


class _Snap:
    def __init__(self, slices):
        self.by_asset = slices


def test_escape_bookflow_respects_price_exemption(monkeypatch):
    """2026-10-17: the escape path omitted ``held_price_cents`` when calling
    ``bookflow_block_reason``, silently dropping the measured >=50c
    exemption the main gate applies (SOL no@92c/TTE339 vetoed
    evidence_escape_bookflow).  In-band pinned candidates must see the
    exemption; below-floor candidates keep the veto."""
    monkeypatch.setenv("MERID_BOOKFLOW_EXEMPT_MIN_PRICE_CENTS", "50")
    monkeypatch.setenv("MERID_BOOKFLOW_IMB_BLOCK", "0.45")
    snap = _Snap({"SOL": _Slice(yes_imb=0.60)})
    kw = dict(
        asset="SOL", side="no",
        net_ev_cents=-6.0, required_edge_cents=-8.0,
        seconds_to_expiry=339.0,       # outside escape late-window 120-240
        spot_price=None, strike_price=None, annualized_vol=None,
        feature_snapshot=snap, dir_regime=None,
    )
    # In the pinned band (92c >= 50c floor): exempt, no bookflow veto.
    assert _td._evidence_escape_veto_reason(price_cents=92.0, **kw) is None
    # Below the exemption floor (35c < 50c, outside the 40-60c knife band):
    # the measured-protective veto still applies.
    assert (
        _td._evidence_escape_veto_reason(price_cents=35.0, **kw)
        == "evidence_escape_bookflow"
    )


def test_pf_admission_stamps_lane_bound_pair(tmp_path, monkeypatch):
    """2026-10-17: a lane-admitted side must stamp the pair it was actually
    enforced on — (net_ev, lane floor) — into the fields the allocator's
    EDGE re-check compares.  Stamping the generic route bound + EPC-LCB
    re-vetoed the emitted cohort live (SOL no@93: cap consumed, then
    EXPECTED_VALUE_BELOW_MINIMUM with gate_ev=-1.9c vs bound=+4.0c)."""
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_MIN_EV_CENTS", "-8.0")
    monkeypatch.setenv(
        "MERID_LIVE_EVIDENCE_PATH", _write_live_evidence(tmp_path, {})
    )
    d = _decision()
    assert d.selected_outcome == "yes", (
        d.indicators.get("yes_block"), d.no_trade_reason,
    )
    assert d.indicators.get("decision_lane") == "pinned_fav"
    # Allocator-facing pair: bound is the lane floor, compared quantity is
    # the net_ev the lane's pinned_fav_block enforced — not the generic
    # route bound and not the EPC-LCB.
    assert d.indicators.get("yes_effective_required_edge_cents") == -8.0
    yes_bd = d.yes_edge_breakdown
    assert yes_bd is not None
    assert d.indicators.get("yes_gate_ev_cents") == pytest.approx(
        float(yes_bd.net_edge) * 100.0, abs=1e-6
    )
    assert d.indicators.get("yes_effective_gate_edge_cents") == -8.0
    assert d.indicators.get("yes_true_shortfall_cents") == pytest.approx(
        max(0.0, -8.0 - float(yes_bd.net_edge) * 100.0), abs=1e-6
    )


def test_non_pf_side_keeps_generic_stamps(tmp_path, monkeypatch):
    """The lane stamp substitution is lane-scoped: a normal-band decision's
    effective bound stays the generic post-caution bound."""
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "1")
    monkeypatch.setenv(
        "MERID_LIVE_EVIDENCE_PATH", _write_live_evidence(tmp_path, {})
    )
    d = _decision(
        spot_price=100.05,
        yes_bid_cents=40.0, yes_ask_cents=42.0,
        no_bid_cents=58.0, no_ask_cents=60.0,
    )
    assert d.indicators.get("decision_lane") != "pinned_fav"
    # Neither side sits in the lane band, so the lane floor must not leak
    # into the allocator-facing bound: generic bounds are non-negative.
    assert d.indicators.get("yes_pinned_fav_qualifies") is False
    assert d.indicators.get("no_pinned_fav_qualifies") is False
    for pfx in ("yes", "no"):
        bound = d.indicators.get(f"{pfx}_effective_required_edge_cents")
        if bound is not None:
            assert bound >= 0.0


def test_selected_decision_stamps_lane_floor_into_min_required_edge(
    tmp_path, monkeypatch
):
    """Router submit-time revalidation derives the permitted limit from
    intent.min_required_edge (max_price = p_held - fee - reserves -
    required_edge).  Stamping the positive formula threshold capped
    max_price at ~85c and rejected every live pinned emit
    (``limit=92 > max_price=85`` on the 2026-10-20 live XRP YES@92
    reprice).  The lane floor is the honest admission bound and must
    reach the intent."""
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_MIN_EV_CENTS", "-6.0")
    monkeypatch.setenv(
        "MERID_LIVE_EVIDENCE_PATH", _write_live_evidence(tmp_path, {})
    )
    d = _decision()
    assert d.selected_outcome == "yes", (
        d.indicators.get("yes_block"), d.no_trade_reason,
    )
    assert d.indicators.get("decision_lane") == "pinned_fav"
    # min_required_edge is a probability fraction: -6c floor -> -0.06.
    # The formula threshold is always positive, so a negative stamp
    # proves the lane floor flowed through to the intent.
    assert float(d.min_required_edge) == pytest.approx(-0.06, abs=1e-9)


def test_non_pinned_selection_keeps_positive_min_required_edge(
    tmp_path, monkeypatch
):
    """A vetoed/no-trade decision must not carry the negative lane floor:
    the stamp is selection-scoped, not lane-armed-global."""
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_MIN_EV_CENTS", "-6.0")
    monkeypatch.setenv(
        "MERID_LIVE_EVIDENCE_PATH", _write_live_evidence(tmp_path, {})
    )
    d = _decision(seconds_to_expiry=200.0)  # outside the lane TTE window
    assert d.selected_outcome is None
    assert float(d.min_required_edge) >= 0.0
