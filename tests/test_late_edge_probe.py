"""Regression coverage for the late-edge probe lane (2026-11-13).

The generic engine floor ``MERID_ENTRY_MIN_SECONDS_TO_EXPIRY`` (120s live)
and the regime classifier's ``MERID_REGIME_MIN_TTE_FLOOR_S`` (90s) veto
every ordinary candidate below the floor regardless of claimed edge —
the ``min_tte_entry_disabled`` / ``tte_entry_cutoff`` rejections audited
in MERID_TTE_ENTRY_GATES_AUDIT_2026-11-06.  Those floors were set on
pre-2026-10 taker-era data; the current stack prices maker/bid economics
with the reserve stack, per-asset caps, tail calibration, and the
settlement lane.

The probe re-opens a *bounded* slice — own-side bid inside
10-69.99c (default), TTE inside [60s, engine floor), matching side/asset
scope, bid basis — where the lane's own stricter EV floor (+3c) is an
*additional* veto on the normal path, never a rescue.  These tests pin
the lane's domain boundaries, fail-closed semantics, terminal labels,
daily budget, and the engine floor exemption — and confirm non-probe
candidates keep the generic floor untouched.
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
    # The lane's own durable daily counter must never read shared state.
    monkeypatch.setenv(
        "MERID_LATE_EDGE_PROBE_STATE_PATH", str(tmp_path / "late_probe.json")
    )
    # The probe's domain ceiling is the generic engine floor itself; the
    # suite pins that floor to 0 (conftest) so unrelated tests never see
    # min_tte_entry_disabled.  Probe tests re-arm it explicitly below.
    monkeypatch.setenv("MERID_LATE_EDGE_PROBE_ENABLED", "0")
    for key, value in {
        "MERID_MONEYNESS_EV_RELIEF_ENABLED": "0",
        "MERID_MONEYNESS_GATE_ENABLED": "0",
        "MERID_CONVICTION_GATE_ENABLED": "0",
        "MERID_EVIDENCE_CHALLENGE_MIN_RECENT_N": "3",
        "MERID_STREAM_CAL_ENABLED": "0",
        "MERID_EMPIRICAL_CAL_MODE": "off",
        "MERID_PRICE_CAP_EXCEPT_YES": "0",
        "MERID_PRICE_CAP_EXCEPT_NO": "0",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("MERID_PROVISIONAL_STATE_PATH", str(tmp_path / "provisional.json"))
    monkeypatch.setenv("MERID_LIVE_EVIDENCE_PATH", _write_live_evidence(tmp_path, {}))
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MIN_W", 0)
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MAX_W", 0)
    monkeypatch.setattr(_td, "MERID_USE_REALIZED_VOL", False)
    monkeypatch.setattr(_td, "MERID_ANCHOR_VOL_TO_MARKET", False)
    # Keep tail-only calibration scope here — the full-range cap (on in
    # .env) pins p_selected to the market-implied curve in un-evidenced
    # mid-band cells, which would make a deterministic probe admission
    # impossible to construct.  Same convention as
    # tests/test_trade_decision_release_gates.py.
    monkeypatch.setattr(_td, "MERID_CALIBRATION_CAP_FULL_RANGE", False)
    yield


@pytest.fixture
def _probe_env(monkeypatch):
    """Arm the lane with the live domain: engine floor 120s (env for the
    lane's call-time ceiling read + module constant for the engine gate),
    probe window 60-120s, band 10-69.99c, bid basis, all assets/sides."""
    monkeypatch.setenv("MERID_LATE_EDGE_PROBE_ENABLED", "1")
    monkeypatch.setenv("MERID_ENTRY_MIN_SECONDS_TO_EXPIRY", "120")
    monkeypatch.setattr(_td, "MERID_ENTRY_MIN_SECONDS_TO_EXPIRY", 120.0)
    yield


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


def _decision(asset: str = "ETH", **over):
    """Decision for a mid-band late-window market: YES bid 65c on a book
    priced near the coinflip boundary (spot ~15bp over strike at TTE 100s
    -> Bachelier p_yes ~0.93, ~+16c reserve-stacked edge), NO complement
    ~33c.  The margin is enough to clear both the ordinary bound and the
    lane's stricter +3c floor; spot overrides below exercise the edge
    boundaries."""
    args = dict(
        run_id="lep_test",
        decision_id=f"lep_{asset}",
        ticker=f"KX{asset}15M-TEST",
        asset=asset,
        spot_price=100.15,
        strike_price=100.0,
        seconds_to_expiry=100.0,
        yes_bid_cents=65.0,
        yes_ask_cents=67.0,
        no_bid_cents=33.0,
        no_ask_cents=35.0,
        yes_depth_cc=200.0,
        no_depth_cc=200.0,
        fee_per_contract_cents=1.0,
        annualized_vol=0.60,
        model_uncertainty=0.05,
        data_quality="live",
        regime="normal",
        min_required_edge=0.02,
        settlement_reference="cfb_rti_live",
        route="maker_bid",
        entry_price_basis="bid",
        adverse_selection_reserve=0.015,
    )
    args.update(over)
    return compute_trade_decision(**args)


# ------------------------------------------------------------ gate unit ----

def test_band_match_flag_independent():
    """Band match is flag-independent (same contract as pinned_fav): the
    engine uses it to apply the probe veto to in-band sides even when the
    lane flag state is ambiguous."""
    assert dr.late_edge_probe_band_match(10.0) is True
    assert dr.late_edge_probe_band_match(69.99) is True
    assert dr.late_edge_probe_band_match(50.0) is True
    assert dr.late_edge_probe_band_match(9.99) is False
    assert dr.late_edge_probe_band_match(70.0) is False
    assert dr.late_edge_probe_band_match(94.0) is False   # pf band disjoint
    assert dr.late_edge_probe_band_match(None) is False


def test_scope_match(monkeypatch):
    monkeypatch.setenv("MERID_LATE_EDGE_PROBE_SIDES", "yes")
    assert dr.late_edge_probe_scope_match("yes", "BTC") is True
    assert dr.late_edge_probe_scope_match("no", "BTC") is False
    assert dr.late_edge_probe_scope_match(None, "BTC") is False
    monkeypatch.setenv("MERID_LATE_EDGE_PROBE_SIDES", "yes,no")
    monkeypatch.setenv("MERID_LATE_EDGE_PROBE_ASSETS", "BTC,ETH")
    assert dr.late_edge_probe_scope_match("yes", "BTC") is True
    assert dr.late_edge_probe_scope_match("yes", "SOL") is False
    assert dr.late_edge_probe_scope_match("yes", None) is False
    # An empty scope list scopes to nothing — fail closed.
    monkeypatch.setenv("MERID_LATE_EDGE_PROBE_ASSETS", "")
    assert dr.late_edge_probe_scope_match("yes", "BTC") is False


def test_reachable_requires_armed_band_tte_scope(_probe_env):
    assert dr.late_edge_probe_reachable(50.0, 100.0, side="yes", asset="BTC") is True
    # TTE boundaries: [60, 120] inclusive — the domain tops out at the
    # generic engine floor itself.
    assert dr.late_edge_probe_reachable(50.0, 60.0, side="yes", asset="BTC") is True
    assert dr.late_edge_probe_reachable(50.0, 120.0, side="yes", asset="BTC") is True
    assert dr.late_edge_probe_reachable(50.0, 59.9, side="yes", asset="BTC") is False
    assert dr.late_edge_probe_reachable(50.0, 120.1, side="yes", asset="BTC") is False
    assert dr.late_edge_probe_reachable(50.0, None, side="yes", asset="BTC") is False
    # Price boundaries.
    assert dr.late_edge_probe_reachable(9.99, 100.0, side="yes", asset="BTC") is False
    assert dr.late_edge_probe_reachable(70.0, 100.0, side="yes", asset="BTC") is False
    # Scope: default sides yes,no / assets all five.
    assert dr.late_edge_probe_reachable(50.0, 100.0, side="no", asset="SOL") is True
    assert dr.late_edge_probe_reachable(50.0, 100.0, side="yes", asset="BNB") is False


def test_reachable_disabled(monkeypatch):
    monkeypatch.setenv("MERID_LATE_EDGE_PROBE_ENABLED", "0")
    monkeypatch.setenv("MERID_ENTRY_MIN_SECONDS_TO_EXPIRY", "120")
    assert dr.late_edge_probe_reachable(50.0, 100.0, side="yes", asset="BTC") is False


def test_tte_exempt_requires_bid_basis(_probe_env):
    """The floor exemption is maker-only: the late window's measured edge
    is a resting edge, so ask-basis evaluations keep the generic floor."""
    kw = dict(
        yes_bid_cents=65.0, no_bid_cents=33.0,
        seconds_to_expiry=100.0, exit_only_cutoff=30.0,
        asset="ETH",
    )
    assert dr.late_edge_probe_tte_exempt(
        entry_price_basis="bid", **kw
    ) is True
    assert dr.late_edge_probe_tte_exempt(
        entry_price_basis="ask", **kw
    ) is False
    assert dr.late_edge_probe_tte_exempt(
        entry_price_basis=None, **kw
    ) is False


def test_tte_exempt_domain_boundaries(_probe_env):
    kw = dict(
        yes_bid_cents=65.0, no_bid_cents=33.0,
        exit_only_cutoff=30.0, entry_price_basis="bid", asset="ETH",
    )
    # Inside the window.
    assert dr.late_edge_probe_tte_exempt(seconds_to_expiry=60.0, **kw) is True
    assert dr.late_edge_probe_tte_exempt(seconds_to_expiry=120.0, **kw) is True
    # Below probe min (settlement lane's domain) and above the floor.
    assert dr.late_edge_probe_tte_exempt(seconds_to_expiry=59.9, **kw) is False
    assert dr.late_edge_probe_tte_exempt(seconds_to_expiry=120.1, **kw) is False
    assert dr.late_edge_probe_tte_exempt(seconds_to_expiry=None, **kw) is False
    # At/below the exit-only cutoff the final-minute gate owns the reject.
    assert dr.late_edge_probe_tte_exempt(seconds_to_expiry=30.0, **kw) is False
    assert dr.late_edge_probe_tte_exempt(seconds_to_expiry=29.9, **kw) is False


def test_tte_exempt_requires_in_band_scoped_bid(_probe_env):
    kw = dict(
        seconds_to_expiry=100.0, exit_only_cutoff=30.0,
        entry_price_basis="bid", asset="ETH",
    )
    # YES bid in band -> exempt.
    assert dr.late_edge_probe_tte_exempt(
        yes_bid_cents=65.0, no_bid_cents=80.0, **kw
    ) is True
    # NO bid in band -> exempt (side scope yes,no default).
    assert dr.late_edge_probe_tte_exempt(
        yes_bid_cents=80.0, no_bid_cents=35.0, **kw
    ) is True
    # Neither bid in band -> no exemption.
    assert dr.late_edge_probe_tte_exempt(
        yes_bid_cents=80.0, no_bid_cents=75.0, **kw
    ) is False
    # Out-of-scope asset -> no exemption.
    _kw_bnb = dict(kw, asset="BNB")
    assert dr.late_edge_probe_tte_exempt(
        yes_bid_cents=65.0, no_bid_cents=33.0, **_kw_bnb
    ) is False
    # Missing bids -> fail closed.
    assert dr.late_edge_probe_tte_exempt(
        yes_bid_cents=None, no_bid_cents=None, **kw
    ) is False


def test_block_inert_outside_domain(_probe_env):
    """CRITICAL: the probe shares its price band with the ordinary path —
    outside its TTE window it must be fully inert (None), never a veto,
    or every in-band side above the floor would be blocked by a lane
    that does not own them."""
    # Above the floor: inert even though price is in band.
    assert dr.late_edge_probe_block(
        50.0, 10.0, 150.0, side="yes", asset="ETH",
        entry_price_basis="bid",
    ) is None
    # Below probe min: inert (settlement lane's domain).
    assert dr.late_edge_probe_block(
        50.0, 10.0, 45.0, side="yes", asset="ETH",
        entry_price_basis="bid",
    ) is None
    # Lane armed (fixture) — sanity.
    assert dr.late_edge_probe_enabled() is True
    # Out-of-band price: inert.
    assert dr.late_edge_probe_block(
        80.0, 10.0, 100.0, side="yes", asset="ETH",
        entry_price_basis="bid",
    ) is None
    # Wrong basis: inert.
    assert dr.late_edge_probe_block(
        50.0, 10.0, 100.0, side="yes", asset="ETH",
        entry_price_basis="ask",
    ) is None
    # Out-of-scope asset: inert.
    assert dr.late_edge_probe_block(
        50.0, 10.0, 100.0, side="yes", asset="BNB",
        entry_price_basis="bid",
    ) is None
    # Missing TTE: inert (cannot establish domain).
    assert dr.late_edge_probe_block(
        50.0, 10.0, None, side="yes", asset="ETH",
        entry_price_basis="bid",
    ) is None


def test_block_disabled_inert(monkeypatch):
    monkeypatch.setenv("MERID_LATE_EDGE_PROBE_ENABLED", "0")
    monkeypatch.setenv("MERID_ENTRY_MIN_SECONDS_TO_EXPIRY", "120")
    assert dr.late_edge_probe_block(
        50.0, -50.0, 100.0, side="yes", asset="ETH",
        entry_price_basis="bid",
    ) is None


def test_block_each_failure_named(_probe_env, monkeypatch):
    monkeypatch.setenv("MERID_LATE_EDGE_PROBE_MIN_EV_CENTS", "3.0")
    # EV below the probe floor -> lane's own reason.
    assert dr.late_edge_probe_block(
        50.0, 2.9, 100.0, side="yes", asset="ETH",
        entry_price_basis="bid",
    ) == "late_edge_probe_low_ev"
    assert dr.late_edge_probe_block(
        50.0, None, 100.0, side="yes", asset="ETH",
        entry_price_basis="bid",
    ) == "late_edge_probe_low_ev"
    # At/above the floor -> pass (cap has budget).
    assert dr.late_edge_probe_block(
        50.0, 3.0, 100.0, side="yes", asset="ETH",
        entry_price_basis="bid",
    ) is None
    assert dr.late_edge_probe_block(
        50.0, 10.0, 100.0, side="yes", asset="ETH",
        entry_price_basis="bid",
    ) is None


def test_block_daily_cap(_probe_env, monkeypatch):
    monkeypatch.setenv("MERID_LATE_EDGE_PROBE_DAILY_MAX", "2")
    monkeypatch.setenv("MERID_LATE_EDGE_PROBE_MIN_EV_CENTS", "3.0")
    p = os.environ["MERID_LATE_EDGE_PROBE_STATE_PATH"]
    dr.record_late_edge_probe_submission(p)
    dr.record_late_edge_probe_submission(p)
    assert dr.late_edge_probe_fills_today(p) == 2
    assert dr.late_edge_probe_cap_remaining(p) == 0
    assert dr.late_edge_probe_block(
        50.0, 10.0, 100.0, side="yes", asset="ETH",
        entry_price_basis="bid",
    ) == "late_edge_probe_daily_cap"
    # Counter resets on a new UTC day.
    import time as _t
    _tomorrow = _t.time() + 90000.0
    assert dr.late_edge_probe_cap_remaining(p, now=_tomorrow) == 2


def test_block_probe_floor_stricter_than_normal(_probe_env, monkeypatch):
    """The probe bar is additive: +2.5c clears a typical ordinary bound but
    fails the lane's +3c floor — the late window demands MORE claimed edge,
    not less."""
    monkeypatch.setenv("MERID_LATE_EDGE_PROBE_MIN_EV_CENTS", "3.0")
    assert dr.late_edge_probe_block(
        50.0, 2.5, 100.0, side="yes", asset="ETH",
        entry_price_basis="bid",
    ) == "late_edge_probe_low_ev"
    monkeypatch.setenv("MERID_LATE_EDGE_PROBE_MIN_EV_CENTS", "2.0")
    assert dr.late_edge_probe_block(
        50.0, 2.5, 100.0, side="yes", asset="ETH",
        entry_price_basis="bid",
    ) is None


def test_admits_stamp_helper(_probe_env):
    assert dr.late_edge_probe_admits(
        50.0, 100.0, side="yes", asset="ETH", entry_price_basis="bid"
    ) is True
    # Above the floor or wrong basis -> not a probe admission.
    assert dr.late_edge_probe_admits(
        50.0, 150.0, side="yes", asset="ETH", entry_price_basis="bid"
    ) is False
    assert dr.late_edge_probe_admits(
        50.0, 100.0, side="yes", asset="ETH", entry_price_basis="ask"
    ) is False
    assert dr.late_edge_probe_admits(
        80.0, 100.0, side="yes", asset="ETH", entry_price_basis="bid"
    ) is False


def test_lane_in_bounded_set():
    """Bounded sizing is non-negotiable: membership gives the 1-contract
    cap + post-only contract for the unproven late-window cohort."""
    assert "late_edge_probe" in _td.BOUNDED_POST_ONLY_LANES


def test_counter_rollover_and_fail_closed(tmp_path, monkeypatch):
    """Durable budget semantics mirror pinned_fav: same-day count reads
    back, a corrupt/future-dated file fails closed to the daily max."""
    monkeypatch.setenv("MERID_LATE_EDGE_PROBE_DAILY_MAX", "5")
    p = str(tmp_path / "probe_budget.json")
    assert dr.record_late_edge_probe_submission(p) == 1
    assert dr.record_late_edge_probe_submission(p) == 2
    assert dr.late_edge_probe_fills_today(p) == 2
    # Corrupt file -> fail closed (count = daily max -> cap_remaining 0).
    with open(p, "w") as f:
        f.write("{bad json")
    assert dr.late_edge_probe_cap_remaining(p) == 0
    # Future-dated file -> fail closed.
    import json, time
    day = __import__("datetime").datetime.fromtimestamp(
        time.time() + 90000, tz=__import__("datetime").timezone.utc
    ).date().isoformat()
    with open(p, "w") as f:
        json.dump({"date": day, "count": 3}, f)
    assert dr.late_edge_probe_cap_remaining(p) == 0


# ------------------------------------------------------- engine admission ----

def test_floor_binds_when_probe_disabled(monkeypatch):
    """Lane off: the generic floor still rejects the in-band late-window
    candidate — the exemption is the lane's, not a global relaxation.
    (_iso pins the lane off; only the floor is re-armed here.)"""
    monkeypatch.setenv("MERID_ENTRY_MIN_SECONDS_TO_EXPIRY", "120")
    monkeypatch.setattr(_td, "MERID_ENTRY_MIN_SECONDS_TO_EXPIRY", 120.0)
    d = _decision()
    assert d.selected_outcome is None
    assert d.no_trade_reason == "min_tte_entry_disabled" or (
        "min_tte" in str(d.no_trade_reason)
    ), (d.no_trade_reason, d.indicators.get("yes_block"))


def test_floor_exempted_when_probe_armed_bid_basis(_probe_env):
    """Lane armed + own-side bid in band + bid basis + TTE in window: the
    candidate passes the generic floor and reaches the engine's per-side
    gates — whatever the downstream verdict, it is NOT the floor reject."""
    d = _decision()
    assert d.no_trade_reason != "min_tte_entry_disabled", (
        d.no_trade_reason, d.indicators.get("yes_block"),
        d.indicators.get("late_probe_tte_exempt"),
    )
    # The exemption marker is stamped for audit.
    assert d.indicators.get("late_probe_tte_exempt") is True


def test_floor_still_binds_ask_basis(_probe_env):
    """Same candidate evaluated on the ask (taker) basis keeps the generic
    floor — the probe is maker-only by construction."""
    d = _decision(entry_price_basis="ask", route="taker")
    assert d.selected_outcome is None
    assert d.no_trade_reason == "min_tte_entry_disabled" or (
        "min_tte" in str(d.no_trade_reason)
    ), (d.no_trade_reason, d.indicators.get("yes_block"))


def test_floor_still_binds_out_of_band(_probe_env):
    """Both own-side bids outside the probe band keep the floor — the
    exemption is scoped, not a blanket late-window opening.  (A realistic
    book cannot put one bid above 69.99c without putting the other inside
    the 10-69.99c band: yes_bid 78c implies no_bid ~20c, which IS probe
    domain.  The 78/75 pair used here is individually sane per side.)"""
    d = _decision(
        yes_bid_cents=78.0, yes_ask_cents=80.0,
        no_bid_cents=75.0, no_ask_cents=77.0,
    )
    assert d.selected_outcome is None
    assert d.no_trade_reason == "min_tte_entry_disabled" or (
        "min_tte" in str(d.no_trade_reason)
    ), (d.no_trade_reason, d.indicators.get("yes_block"))


def test_floor_exempts_complement_side(_probe_env):
    """The exemption is candidate-level: a NO bid inside the band (20c)
    keeps the whole evaluation probe-reachable even when the YES bid is
    above it — downstream gates then own the verdict (here, economics).
    This is the realistic-book counterpart of the out-of-band test."""
    d = _decision(
        yes_bid_cents=78.0, yes_ask_cents=80.0,
        no_bid_cents=20.0, no_ask_cents=22.0,
    )
    assert d.no_trade_reason != "min_tte_entry_disabled", (
        d.no_trade_reason, d.indicators.get("no_block"),
    )
    assert d.indicators.get("late_probe_tte_exempt") is True


def test_floor_still_binds_above_window_tte(_probe_env):
    """TTE above the floor is the normal path's domain — no probe stamp,
    no probe veto; the candidate evaluates exactly as before."""
    d = _decision(seconds_to_expiry=200.0)
    assert d.indicators.get("late_probe_tte_exempt") is None
    assert d.indicators.get("decision_lane") != "late_edge_probe"


def test_probe_low_ev_indicator_and_label(_probe_env, monkeypatch):
    """An in-band side whose reserve-stacked EV misses the probe's +3c
    floor reports the lane's own reason in the per-side block field —
    the honest attribution for why the late window stayed closed."""
    monkeypatch.setenv("MERID_LATE_EDGE_PROBE_MIN_EV_CENTS", "30.0")
    # Absurd floor: no candidate can clear it -> deterministic veto.
    d = _decision()
    assert d.indicators.get("yes_late_probe_block") == "late_edge_probe_low_ev"
    assert d.indicators.get("yes_block") == "late_edge_probe_low_ev"


def test_probe_admit_stamps_lane(tmp_path, monkeypatch, _probe_env):
    """Full admission path: in-band own-side bid at TTE 100s with claimed
    edge clearing both the ordinary bound and the probe floor selects the
    side and stamps decision_lane=late_edge_probe — the cohort stays
    separable in outcome joins."""
    monkeypatch.setenv(
        "MERID_LIVE_EVIDENCE_PATH", _write_live_evidence(tmp_path, {})
    )
    d = _decision()
    assert d.selected_outcome == "yes", (
        d.indicators.get("yes_block"), d.no_trade_reason,
        d.indicators.get("yes_late_probe_block"),
        d.indicators.get("yes_ev_net_cents"),
    )
    assert d.indicators.get("decision_lane") == "late_edge_probe"
    assert d.indicators.get("entry_lane") == "late_edge_probe"


def test_probe_admit_blocked_by_ordinary_gates(_probe_env):
    """The probe is additive, never substitutive: an in-band candidate
    whose claimed edge clears the probe floor but fails a structural gate
    (here: out-of-scope asset via env) still cannot admit through the
    lane — every ordinary veto still binds."""
    d = _decision(asset="BNB")
    # BNB is out of the default asset scope -> no exemption, floor binds.
    assert d.no_trade_reason == "min_tte_entry_disabled" or (
        "min_tte" in str(d.no_trade_reason)
    ), (d.no_trade_reason, d.indicators.get("yes_block"))


# --------------------------------------------------------- cross-cutting ----

def test_terminal_code_mapping():
    from merid.prediction.terminal_codes import canonical_terminal_code
    assert canonical_terminal_code(
        "late_edge_probe_low_ev_yes"
    ) == "EDGE_BELOW_DYNAMIC_THRESHOLD"
    assert canonical_terminal_code(
        "late_edge_probe_daily_cap"
    ) == "EVIDENCE_HARD_BLOCK"
    assert canonical_terminal_code(
        "late_edge_probe_cap_exceeded_at_emission"
    ) == "EVIDENCE_HARD_BLOCK"
    assert canonical_terminal_code(
        "late_edge_probe_budget_unavailable"
    ) == "EVIDENCE_HARD_BLOCK"
    assert canonical_terminal_code(
        "late_edge_probe_tte"
    ) == "STRUCTURAL_RISK_VETO"


def test_gate_evaluation_attributes_lane():
    from merid.prediction.gate_evaluation import _blocking_gate_names
    assert "late_edge_lane" in _blocking_gate_names(
        "late_edge_probe_low_ev_yes", "yes"
    )
    assert "late_edge_lane" in _blocking_gate_names(
        "late_edge_probe_daily_cap", None
    )
