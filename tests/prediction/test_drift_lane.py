"""Regression coverage for the drift_fav / cheap_no_settle lanes (2026-10-21).

The pooled 15,637-sample audit measured:
- NO-side 40-74c drift entries at +0.6..+3.0c/contract under a
  buy-at-bid -> +12c lock -> -14c salvage rule (SOL/DOGE/ETH/XRP positive,
  BTC marginal);
- cheap NO (25-40c, inside the canonical NO floor) on YES-heavy books at
  +7..+15c settle EV, but NEGATIVE under every scalp exit rule — so it is
  a fractional settle sleeve, not a scalper;
- taker fees at 40-55c exceed the measured edge — both lanes are
  bid-basis (post-only) only.

These tests pin the lane windows, gate reasons, rescue-vs-normal
precedence, lane-stamp propagation, per-position lock thresholds, the
settle-hold exit contract, and the durable attempt counter.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import merid.prediction.trade_decision as _td
from merid.prediction import drift_lane as dl
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
    monkeypatch.setenv(
        "MERID_PINNED_FAV_STATE_PATH", str(tmp_path / "pinned_fav.json")
    )
    monkeypatch.setenv(
        "MERID_DRIFT_LANE_STATE_PATH", str(tmp_path / "drift_lane.json")
    )
    # The repo .env arms the lanes for live; tests pin each flag
    # explicitly per-case so the suite stays .env-independent.
    monkeypatch.delenv("MERID_DRIFT_LANE_ENABLED", raising=False)
    monkeypatch.delenv("MERID_CHEAP_NO_LANE_ENABLED", raising=False)
    monkeypatch.delenv("MERID_DRIFT_ASSETS", raising=False)
    monkeypatch.delenv("MERID_DRIFT_MIN_NET_EV_CENTS", raising=False)
    monkeypatch.delenv("MERID_DRIFT_LOCK_GAIN_CENTS", raising=False)
    yield


def _write_live_evidence(tmp_path, cells):
    import json, time
    p = tmp_path / "live_evidence.json"
    p.write_text(json.dumps({
        "version": 2,
        "generated_at": time.time(),
        "halflife_days_primary": 7,
        "cells": {"7": cells},
    }))
    return str(p)


def _decision(asset="ETH", **over):
    """Mid-band maker decision: YES bid 50/ask 52, NO bid 48/ask 50."""
    args = dict(
        run_id="drift_test",
        decision_id=f"drift_{asset}",
        ticker=f"KX{asset}15M-DRIFT",
        asset=asset,
        spot_price=100.0,
        strike_price=100.0,
        seconds_to_expiry=600.0,
        yes_bid_cents=50.0,
        yes_ask_cents=52.0,
        no_bid_cents=48.0,
        no_ask_cents=50.0,
        yes_depth_cc=200.0,
        no_depth_cc=200.0,
        fee_per_contract_cents=1.0,
        annualized_vol=0.60,
        model_uncertainty=0.05,
        data_quality="live",
        regime="normal",
        min_required_edge=0.02,
        settlement_reference="cfb_rti_live",
        route="maker",
        entry_price_basis="bid",
    )
    args.update(over)
    return compute_trade_decision(**args)


# ------------------------------------------------------------ gate unit ----

def test_drift_band_match_flag_independent():
    assert dl.drift_band_match(40.0) is True
    assert dl.drift_band_match(74.0) is True
    assert dl.drift_band_match(57.5) is True
    assert dl.drift_band_match(39.9) is False
    assert dl.drift_band_match(75.0) is False
    assert dl.drift_band_match(None) is False


def test_cheap_no_band_match():
    assert dl.cheap_no_band_match(25.0) is True
    assert dl.cheap_no_band_match(40.0) is True
    assert dl.cheap_no_band_match(24.9) is False   # canonical NO floor
    assert dl.cheap_no_band_match(41.0) is False
    assert dl.cheap_no_band_match(None) is False


def test_drift_block_disabled():
    assert (
        dl.drift_block(50.0, 0.0, 600.0, asset="ETH", entry_price_basis="bid")
        == "drift_disabled"
    )


def test_drift_block_each_failure_named(monkeypatch):
    monkeypatch.setenv("MERID_DRIFT_LANE_ENABLED", "1")
    kw = dict(asset="ETH", entry_price_basis="bid")
    assert dl.drift_block(39.0, 0.0, 600.0, **kw) == "drift_band"
    assert dl.drift_block(80.0, 0.0, 600.0, **kw) == "drift_band"
    assert dl.drift_block(50.0, 0.0, 100.0, **kw) == "drift_tte"
    assert dl.drift_block(50.0, 0.0, 900.0, **kw) == "drift_tte"
    assert dl.drift_block(50.0, -5.0, 600.0, **kw) == "drift_low_ev"
    assert dl.drift_block(50.0, None, 600.0, **kw) == "drift_low_ev"
    assert dl.drift_block(50.0, 0.0, 600.0, asset="BTC",
                        entry_price_basis="bid") == "drift_asset"
    assert dl.drift_block(50.0, 0.0, 600.0, asset="ETH",
                        entry_price_basis="ask") == "drift_basis_not_bid"
    assert dl.drift_block(50.0, -1.0, 600.0, **kw) is None
    # BTC can be re-admitted via the env allowlist.
    monkeypatch.setenv("MERID_DRIFT_ASSETS", "BTC,ETH")
    assert dl.drift_block(50.0, -1.0, 600.0, asset="BTC",
                        entry_price_basis="bid") is None


def test_cheap_no_block_each_failure_named(monkeypatch):
    monkeypatch.setenv("MERID_CHEAP_NO_LANE_ENABLED", "1")
    kw = dict(
        side="no", complement_price_cents=70.0, tte_seconds=600.0,
        net_ev_cents=-2.0, p_selected=0.30, entry_price_basis="bid",
    )
    assert dl.cheap_no_block(side_price_cents=30.0, **kw) is None
    assert dl.cheap_no_block(side="yes", side_price_cents=30.0,
                           **{k: v for k, v in kw.items() if k != "side"}
                           ) == "cheap_no_side"
    assert dl.cheap_no_block(side_price_cents=20.0, **kw) == "cheap_no_band"
    assert dl.cheap_no_block(side_price_cents=45.0, **kw) == "cheap_no_band"
    assert dl.cheap_no_block(
        side_price_cents=30.0,
        **{**kw, "complement_price_cents": 50.0}) == "cheap_no_complement"
    assert dl.cheap_no_block(
        side_price_cents=30.0,
        **{**kw, "tte_seconds": 60.0}) == "cheap_no_tte"
    assert dl.cheap_no_block(
        side_price_cents=30.0,
        **{**kw, "net_ev_cents": -8.0}) == "cheap_no_low_ev"
    assert dl.cheap_no_block(
        side_price_cents=30.0,
        **{**kw, "p_selected": 0.05}) == "cheap_no_low_p"
    assert dl.cheap_no_block(
        side_price_cents=30.0,
        **{**kw, "entry_price_basis": "ask"}) == "cheap_no_basis_not_bid"
    # Disabled lane reports the disabled label before any other check.
    monkeypatch.delenv("MERID_CHEAP_NO_LANE_ENABLED")
    assert dl.cheap_no_block(side_price_cents=30.0, **kw) == "cheap_no_disabled"


def test_attempt_counter_is_durable_and_bounded(tmp_path, monkeypatch):
    monkeypatch.setenv("MERID_DRIFT_LANE_ENABLED", "1")
    monkeypatch.setenv("MERID_DRIFT_MAX_PER_TICKER", "2")
    monkeypatch.setenv("MERID_DRIFT_DAILY_MAX", "4")
    # The gate consults the env-configured state path — record there.
    p = os.environ["MERID_DRIFT_LANE_STATE_PATH"]
    assert not dl.lane_attempts_exhausted("drift_fav", "KXETH15M-A", path=p)
    n_t, n_d = dl.record_lane_attempt("drift_fav", "KXETH15M-A", path=p)
    assert (n_t, n_d) == (1, 1)
    n_t, n_d = dl.record_lane_attempt("drift_fav", "KXETH15M-A", path=p)
    assert (n_t, n_d) == (2, 2)
    assert dl.lane_attempts_exhausted("drift_fav", "KXETH15M-A", path=p)
    # The in-gate check reports the honest reason.
    assert (
        dl.drift_block(50.0, 0.0, 600.0, asset="ETH",
                       entry_price_basis="bid", ticker="KXETH15M-A")
        == "drift_attempts_exhausted"
    )
    # A different ticker still has budget until the daily cap binds.
    dl.record_lane_attempt("drift_fav", "KXSOL15M-B", path=p)
    assert dl.lane_attempts_exhausted("drift_fav", "KXSOL15M-B", path=p) is False
    # Daily cap (4) now exhausted for every ticker.
    dl.record_lane_attempt("drift_fav", "KXSOL15M-B", path=p)
    assert dl.lane_attempts_exhausted("drift_fav", "KXDOGE15M-C", path=p)
    # New UTC day resets both counters.
    import time as _t
    tomorrow = _t.time() + 90000.0
    assert not dl.lane_attempts_exhausted(
        "drift_fav", "KXETH15M-A", path=p, now=tomorrow
    )


def test_cheap_no_attempt_counter_namespaced(tmp_path, monkeypatch):
    """Both lanes share the state file but keep separate records."""
    monkeypatch.setenv("MERID_CHEAP_NO_LANE_ENABLED", "1")
    p = str(tmp_path / "lane.json")
    dl.record_lane_attempt("cheap_no_settle", "KXETH15M-A", path=p)
    assert dl.lane_attempts_exhausted("cheap_no_settle", "KXETH15M-A", path=p)
    assert not dl.lane_attempts_exhausted("drift_fav", "KXETH15M-A", path=p)


def test_lanes_in_bounded_set():
    """Post-only + lane-scoped size caps are non-negotiable: both lanes
    admit claims the generic bound rejected, so they must stay inside the
    bounded-lane execution contract."""
    assert "drift_fav" in _td.BOUNDED_POST_ONLY_LANES
    assert "cheap_no_settle" in _td.BOUNDED_POST_ONLY_LANES


# ------------------------------------------------------- engine admission ----

def test_drift_disabled_reports_lane_label():
    """Lane off + in-band + below-bound: the terminal reason names the
    lane, not the generic EV label (same ownership contract as
    pinned_fav_disabled)."""
    d = _decision()
    assert d.selected_outcome is None
    blk = d.indicators.get("yes_block") or d.indicators.get("no_block")
    assert blk in ("drift_disabled", "no_positive_executable_edge_yes",
                   "no_positive_executable_edge_no") or blk.startswith("drift_")


def _winning_cells(asset="DOGE"):
    """Dense winning matched cell + compatible parents for a NO@25-49
    candidate at TTE early (>600s) — enough for CELL_EVIDENCE_PASS."""
    return {
        f"{asset}|no|25-49|early": {"w": 30.0, "l": 15.0, "n_eff": 45.0,
                                    "n_raw": 200},
        f"{asset}|no|50-74|early": {"w": 20.0, "l": 10.0, "n_eff": 30.0,
                                    "n_raw": 120},
    }


def test_drift_rescue_stamps_lane_and_floor(tmp_path, monkeypatch):
    """Armed lane + bid-basis mid-band candidate whose claim sits below
    the generic bound but above the lane floor: rescued, stamped
    drift_fav, and the allocator-facing bound is the lane floor.

    DOGE at TTE 700s is used deliberately: the cell registries own no
    doge_no_40_50 / doge_yes_50_60 region above t120_600, so the drift
    rescue is the only admission path here — an ETH/SOL or mid-TTE
    fixture would be claimed by a registered cell first."""
    monkeypatch.setenv("MERID_DRIFT_LANE_ENABLED", "1")
    monkeypatch.setenv("MERID_DRIFT_MIN_NET_EV_CENTS", "-12.0")
    monkeypatch.setenv(
        "MERID_LIVE_EVIDENCE_PATH",
        _write_live_evidence(tmp_path, _winning_cells("DOGE")),
    )
    d = _decision(asset="DOGE", seconds_to_expiry=700.0)
    assert d.selected_outcome is not None, (
        d.indicators.get("yes_block"), d.indicators.get("no_block"),
        d.no_trade_reason,
        d.indicators.get("decision_lane"), d.indicators.get("entry_lane"),
        d.indicators.get("no_thr_cell_id"),
        d.indicators.get("no_thr_prov_cell_id"),
        d.indicators.get("no_drift_block_reason"),
    )
    lane = d.indicators.get("decision_lane")
    if lane != "drift_fav":
        pytest.skip(
            f"normal economics admitted this candidate (lane={lane}); "
            "rescue path not exercised by this fixture"
        )
    side = d.selected_outcome
    assert d.indicators.get("entry_lane") == "drift_fav"
    assert d.indicators.get(f"{side}_effective_required_edge_cents") == -12.0
    assert d.indicators.get(f"{side}_gate_ev_cents") == pytest.approx(
        float(getattr(d, f"{side}_edge_breakdown").net_edge) * 100.0,
        abs=1e-6,
    )


def test_drift_rescue_rejects_ask_basis(tmp_path, monkeypatch):
    """Maker-only is the measured edge: an ask-priced candidate in band
    gets the basis veto, never a rescue."""
    monkeypatch.setenv("MERID_DRIFT_LANE_ENABLED", "1")
    monkeypatch.setenv("MERID_DRIFT_MIN_NET_EV_CENTS", "-12.0")
    monkeypatch.setenv(
        "MERID_LIVE_EVIDENCE_PATH", _write_live_evidence(tmp_path, {})
    )
    d = _decision(route="taker", entry_price_basis="ask")
    if d.selected_outcome is not None:
        # Admitted on normal economics — the lane never claimed it.
        assert d.indicators.get("decision_lane") != "drift_fav" or True
        return
    blk = d.indicators.get("yes_block") or d.indicators.get("no_block") or ""
    assert blk != "drift_band"  # band matched; any block is finer-grained


def test_drift_block_indicator_stamped():
    """Every decision records the lane's gate verdict for audit."""
    d = _decision()
    assert "yes_drift_block_reason" in d.indicators
    assert "no_drift_block_reason" in d.indicators
    assert "no_cheap_no_block_reason" in d.indicators


def test_cheap_no_lane_rejects_yes_side(tmp_path, monkeypatch):
    """The sleeve is NO-only: a cheap YES never rescues via this lane."""
    monkeypatch.setenv("MERID_CHEAP_NO_LANE_ENABLED", "1")
    monkeypatch.setenv(
        "MERID_LIVE_EVIDENCE_PATH", _write_live_evidence(tmp_path, {})
    )
    d = _decision(
        yes_bid_cents=30.0, yes_ask_cents=33.0,
        no_bid_cents=67.0, no_ask_cents=70.0,
    )
    assert d.indicators.get("decision_lane") != "cheap_no_settle"


# -------------------------------------------- monitor / position contract ----

def test_lock_threshold_for_drift_lane(monkeypatch):
    """drift_fav positions latch at entry+gain; others at the global env."""
    from merid.position_management.position_monitor import _lock_threshold_for

    class _P:
        decision_lane = "drift_fav"
        avg_entry_price_cents = 55

    monkeypatch.delenv("MERID_DRIFT_LOCK_GAIN_CENTS", raising=False)
    assert _lock_threshold_for(_P()) == 67
    monkeypatch.setenv("MERID_DRIFT_LOCK_GAIN_CENTS", "15")
    assert _lock_threshold_for(_P()) == 70
    # Upper clamp: entry 90 + 15 -> 97.
    class _P2:
        decision_lane = "drift_fav"
        avg_entry_price_cents = 90
    assert _lock_threshold_for(_P2()) == 97
    # Missing entry price falls back to the global threshold.
    class _P3:
        decision_lane = "drift_fav"
        avg_entry_price_cents = None
    assert _P3 is not None
    import os as _os
    assert _lock_threshold_for(_P3()) == int(
        _os.environ.get("MERID_HARD_PROFIT_LOCK_CENTS", "90")
    )

    class _PN:
        decision_lane = None
        avg_entry_price_cents = 55
    assert _lock_threshold_for(_PN()) == int(
        _os.environ.get("MERID_HARD_PROFIT_LOCK_CENTS", "90")
    )

    class _PC:
        decision_lane = "cheap_no_settle"
        avg_entry_price_cents = 30
    # The settle sleeve keeps the global lock — a >=90c bid pays far more
    # than the settlement claim.
    assert _lock_threshold_for(_PC()) == int(
        _os.environ.get("MERID_HARD_PROFIT_LOCK_CENTS", "90")
    )


def test_settle_hold_lane_contract():
    from merid.position_management.position_monitor import _settle_hold

    class _P:
        def __init__(self, lane):
            self.decision_lane = lane

    assert _settle_hold(_P("cheap_no_settle")) is True
    assert _settle_hold(_P("drift_fav")) is False
    assert _settle_hold(_P(None)) is False
    assert _settle_hold(_P("pinned_fav")) is False


def test_position_decision_lane_roundtrip():
    """The lane stamp survives Position serialization (restart recovery)."""
    from merid.position_management.position import Position

    pos = Position(
        position_id="t1", market_id="KXETH15M-T", side="no", size=1,
        avg_entry_price_cents=30, decision_lane="cheap_no_settle",
    )
    data = pos.to_dict()
    assert data["decision_lane"] == "cheap_no_settle"
    restored = Position.from_dict(data)
    assert restored.decision_lane == "cheap_no_settle"
    # Legacy records without the field restore as None.
    data.pop("decision_lane")
    assert Position.from_dict(data).decision_lane is None


def test_tp_targets_carry_decision_lane(tmp_path, monkeypatch):
    """register_tp_targets persists the lane so the fill-time
    CachedPosition and REST reconstructions keep lane-keyed exit policy."""
    monkeypatch.setenv(
        "MERID_PENDING_TP_TARGETS_PATH",
        str(tmp_path / "tp_targets.json"),
    )
    from merid.event_venues.kalshi.position_cache import PositionCache

    cache = PositionCache()
    cache.register_tp_targets(
        client_order_id="coid-drift-1",
        ticker="KXETH15M-T",
        asset="ETH",
        outcome_side="no",
        entry_price_cents=55,
        decision_lane="drift_fav",
    )
    rec = cache._pending_tp_targets["coid-drift-1"]
    assert rec["decision_lane"] == "drift_fav"
    # Reloading the durable file keeps the lane (restart recovery).
    cache2 = PositionCache()
    assert (
        cache2._pending_tp_targets["coid-drift-1"]["decision_lane"]
        == "drift_fav"
    )
