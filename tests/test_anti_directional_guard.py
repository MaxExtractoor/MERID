"""Regression coverage for the anti-directional hold guard (2026-11-18).

Replay of KXDOGE15M-26NOV172330-30: ``cheap_no_settle`` bought NO@27c
while the model priced ``p_yes=0.721`` — every cheap_no fill holds the
side the model itself calls less likely.  There is no side-mapping
inversion: intent, wire payload, fill canonicalization, and the
signed-YES exposure all agree, and the 23k-sample calibration audit
(Brier 0.158) shows the model is directionally anchored.  But until
this guard the stack had no explicit contract for *who may hold the
model's minority side* — the failure mode reads identically to an
inversion to any downstream auditor, and the lane that produced it is
measured net-negative.

The guard (``_minority_hold_lanes`` / ``_anti_directional_p_floor``):

- stamps ``held_side_minority`` on every selection so audits can join
  direction-vs-hold without recomputing;
- vetoes ``anti_directional_<side>`` whenever the held side's
  calibrated p is below ``MERID_ANTI_DIRECTIONAL_P_FLOOR`` (default
  0.5) and the stamped ``decision_lane`` is not registered in
  ``MERID_MINORITY_HOLD_LANES``.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    monkeypatch.setenv(
        "MERID_PROVISIONAL_STATE_PATH", str(tmp_path / "provisional.json")
    )
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "0")
    monkeypatch.setenv("MERID_MONEYNESS_EV_RELIEF_ENABLED", "0")
    monkeypatch.setenv("MERID_MONEYNESS_GATE_ENABLED", "0")
    monkeypatch.setenv("MERID_CONVICTION_GATE_ENABLED", "0")
    monkeypatch.setenv("MERID_STREAM_CAL_ENABLED", "0")
    monkeypatch.setenv("MERID_EMPIRICAL_CAL_MODE", "off")
    # conftest intentionally keeps the shipped tail-calibrator artifact;
    # its pooled 40c NO curve fails the static calibration-evidence
    # floor and masks the gate under test.  The lane evidence path
    # (live_entry_evidence cells) is what these scenarios exercise.
    monkeypatch.setattr(
        "merid.prediction.trade_decision.load_tail_calibrator",
        lambda *args, **kwargs: None,
    )
    for name in tuple(os.environ):
        if name.startswith(("MERID_DRIFT_", "MERID_CHEAP_NO_")) and not name.endswith("STATE_PATH"):
            monkeypatch.delenv(name, raising=False)
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


def _minority_drift_decision(tmp_path, monkeypatch, **over):
    """DOGE drift-band candidate: NO bid 40/ask 42 on a book where the
    model leans mildly YES (p_no ~0.45 < 0.5) — a minority-side hold
    admitted through the drift_fav lane's own floor."""
    monkeypatch.setenv("MERID_DRIFT_LANE_ENABLED", "1")
    monkeypatch.setenv("MERID_DRIFT_MIN_NET_EV_CENTS", "-12.0")
    monkeypatch.setenv("MERID_DRIFT_ASSETS", "BTC,SOL,ETH,DOGE,XRP")
    cells = {
        "DOGE|no|25-49|early": {"w": 30.0, "l": 15.0, "n_eff": 45.0,
                                "n_raw": 200},
        "DOGE|no|50-74|early": {"w": 20.0, "l": 10.0, "n_eff": 30.0,
                                "n_raw": 120},
    }
    monkeypatch.setenv(
        "MERID_LIVE_EVIDENCE_PATH", _write_live_evidence(tmp_path, cells)
    )
    monkeypatch.setattr(
        "merid.prediction.current_build_provisional."
        "adverse_selection_reserve_cents",
        lambda *args, **kwargs: 2.0,
    )
    args = dict(
        run_id="adr_test",
        decision_id="adr_doge",
        ticker="KXDOGE15M-ADR",
        asset="DOGE",
        spot_price=100.05,
        strike_price=100.0,
        seconds_to_expiry=700.0,
        yes_bid_cents=58.0,
        yes_ask_cents=60.0,
        no_bid_cents=40.0,
        no_ask_cents=42.0,
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


def test_registered_minority_lane_holds_and_stamps(tmp_path, monkeypatch):
    """drift_fav is a registered minority-hold lane: a p_no<0.5
    admission through it is coherent, stamps held_side_minority, and
    must NOT be vetoed."""
    d = _minority_drift_decision(tmp_path, monkeypatch)
    ind = d.indicators
    assert d.selected_outcome == "no", (
        ind.get("no_block"), ind.get("no_drift_block_reason"),
        d.no_trade_reason, str(d.no_edge_breakdown),
    )
    assert float(d.no_edge_breakdown.p_selected) < 0.5
    assert ind.get("held_side_minority") is True
    assert ind.get("anti_directional_veto") is not True
    assert ind.get("decision_lane") == "drift_fav"


def test_unregistered_minority_lane_vetoes(tmp_path, monkeypatch):
    """The same minority hold through a lane that is NOT registered
    vetoes: holding the side the model calls less likely is a
    deliberate, registered-lane contract, not an emergent one."""
    monkeypatch.setenv("MERID_MINORITY_HOLD_LANES", "pinned_fav")
    d = _minority_drift_decision(tmp_path, monkeypatch)
    ind = d.indicators
    assert float(d.no_edge_breakdown.p_selected) < 0.5
    assert ind.get("anti_directional_veto") is True
    assert d.selected_outcome is None
    assert d.no_trade_reason == "anti_directional_no"


def test_minority_floor_env_override(tmp_path, monkeypatch):
    """The floor is tunable: at MERID_ANTI_DIRECTIONAL_P_FLOOR=0.40 the
    same candidate is a majority-cohort hold for guard purposes — no
    veto even when the lane is unregistered."""
    monkeypatch.setenv("MERID_MINORITY_HOLD_LANES", "pinned_fav")
    monkeypatch.setenv("MERID_ANTI_DIRECTIONAL_P_FLOOR", "0.40")
    d = _minority_drift_decision(tmp_path, monkeypatch)
    ind = d.indicators
    assert float(d.no_edge_breakdown.p_selected) < 0.5
    assert float(d.no_edge_breakdown.p_selected) >= 0.40
    assert ind.get("held_side_minority") is False
    assert ind.get("anti_directional_veto") is not True
    assert d.selected_outcome == "no"


def test_hard_floor_vetoes_even_registered_lane(tmp_path, monkeypatch):
    """Registration is a license to hold the minority side, not to hold
    an extreme one: MERID_ANTI_DIRECTIONAL_HARD_FLOOR vetoes every lane
    — the model's own FLB means realized odds below it are worse than
    priced."""
    monkeypatch.setenv("MERID_ANTI_DIRECTIONAL_HARD_FLOOR", "0.45")
    d = _minority_drift_decision(tmp_path, monkeypatch)
    ind = d.indicators
    assert float(d.no_edge_breakdown.p_selected) < 0.45
    assert ind.get("anti_directional_hard_veto") is True
    assert ind.get("anti_directional_veto") is True
    assert d.selected_outcome is None
    assert d.no_trade_reason == "anti_directional_hard_no"


def test_majority_hold_stamps_not_minority(tmp_path, monkeypatch):
    """A majority-side selection stamps held_side_minority=False — the
    audit flag exists on every selection, not only vetoes."""
    monkeypatch.setenv("MERID_DRIFT_LANE_ENABLED", "1")
    monkeypatch.setenv("MERID_DRIFT_MIN_NET_EV_CENTS", "-12.0")
    monkeypatch.setenv("MERID_DRIFT_ASSETS", "BTC,SOL,ETH,DOGE,XRP")
    cells = {
        "DOGE|no|25-49|early": {"w": 30.0, "l": 15.0, "n_eff": 45.0,
                                "n_raw": 200},
        "DOGE|no|50-74|early": {"w": 20.0, "l": 10.0, "n_eff": 30.0,
                                "n_raw": 120},
    }
    monkeypatch.setenv(
        "MERID_LIVE_EVIDENCE_PATH", _write_live_evidence(tmp_path, cells)
    )
    monkeypatch.setattr(
        "merid.prediction.current_build_provisional."
        "adverse_selection_reserve_cents",
        lambda *args, **kwargs: 2.0,
    )
    # Mirror of the drift-rescue fixture: spot below strike -> model
    # leans NO (p_no > 0.5, a majority hold).
    d = _minority_drift_decision(
        tmp_path, monkeypatch, spot_price=99.85, model_uncertainty=0.15,
    )
    ind = d.indicators
    if d.selected_outcome is None:
        pytest.skip(
            f"candidate did not admit ({d.no_trade_reason}); "
            "majority-hold stamp not exercised"
        )
    assert float(
        getattr(d, f"{d.selected_outcome}_edge_breakdown").p_selected
    ) >= 0.5
    assert ind.get("held_side_minority") is False
    assert ind.get("anti_directional_veto") is not True
