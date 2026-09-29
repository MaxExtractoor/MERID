"""Tests for the walk-forward calibrator layer and cheap-NO research lane."""
import json
import os
import math

import pytest


@pytest.fixture(autouse=True)
def _wf_env(tmp_path, monkeypatch):
    """Point the walk-forward artifact + research log at tmp paths."""
    art = tmp_path / "walkforward_calibrator.json"
    monkeypatch.setenv("MERID_CHEAP_NO_RESEARCH_LOG", str(tmp_path / "cnr.jsonl"))
    monkeypatch.setenv("MERID_CHEAP_NO_RESEARCH_ENABLED", "1")
    yield art


def _write_artifact(path, cells):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": "walkforward_v1", "cells": cells}))


def test_walkforward_disabled_returns_none(monkeypatch, _wf_env):
    monkeypatch.setenv("MERID_WALKFWD_CAL_ENABLED", "0")
    import merid.prediction.trade_decision as td
    monkeypatch.setattr(td, "MERID_WALKFWD_CAL_ENABLED", False)
    assert td._walkforward_calibrate_p_yes("BTC", 400, 0.6) is None


def test_walkforward_missing_artifact_returns_none(monkeypatch, _wf_env):
    import merid.prediction.trade_decision as td
    monkeypatch.setattr(td, "_WALKFWD_CAL_PATH", str(_wf_env))
    monkeypatch.setattr(td, "_walkfwd_cal_cache", {"mtime": None, "artifact": None})
    monkeypatch.setattr(td, "MERID_WALKFWD_CAL_ENABLED", True)
    assert td._walkforward_calibrate_p_yes("BTC", 400, 0.6) is None


def test_walkforward_platt_maps_and_clamps(monkeypatch, _wf_env):
    import merid.prediction.trade_decision as td
    _write_artifact(_wf_env, {"BTC:mid": {"method": "platt", "a": -0.5, "b": 1.2}})
    monkeypatch.setattr(td, "_WALKFWD_CAL_PATH", str(_wf_env))
    monkeypatch.setattr(td, "_walkfwd_cal_cache", {"mtime": None, "artifact": None})
    monkeypatch.setattr(td, "MERID_WALKFWD_CAL_ENABLED", True)
    out = td._walkforward_calibrate_p_yes("BTC", 400, 0.6)  # mid band
    expected = 1.0 / (1.0 + math.exp(-(-0.5 + 1.2 * math.log(0.6 / 0.4))))
    assert abs(out - expected) < 1e-9
    # clamps
    out_hi = td._walkforward_calibrate_p_yes("BTC", 400, 0.999999)
    assert 0.0 < out_hi <= 0.99


def test_walkforward_isotonic_interp_and_identity(monkeypatch, _wf_env):
    import merid.prediction.trade_decision as td
    _write_artifact(_wf_env, {
        "SOL:mid": {"method": "isotonic", "x": [0.2, 0.5, 0.8], "y": [0.1, 0.4, 0.9]},
        "SOL:early": {"method": "identity"},
    })
    monkeypatch.setattr(td, "_WALKFWD_CAL_PATH", str(_wf_env))
    monkeypatch.setattr(td, "_walkfwd_cal_cache", {"mtime": None, "artifact": None})
    monkeypatch.setattr(td, "MERID_WALKFWD_CAL_ENABLED", True)
    # midpoint interp: p=0.35 -> 0.1 + (0.4-0.1)*(0.15/0.3) = 0.25
    assert abs(td._walkforward_calibrate_p_yes("SOL", 400, 0.35) - 0.25) < 1e-9
    # below/above knot bounds clamp to endpoints
    assert td._walkforward_calibrate_p_yes("SOL", 400, 0.05) == 0.1
    assert td._walkforward_calibrate_p_yes("SOL", 400, 0.95) == 0.9
    # identity cell -> None (no-op)
    assert td._walkforward_calibrate_p_yes("SOL", 700, 0.6) is None
    # late cell missing -> None
    assert td._walkforward_calibrate_p_yes("SOL", 100, 0.6) is None


def test_walkforward_monotone_isotonic(monkeypatch, _wf_env):
    import merid.prediction.trade_decision as td
    _write_artifact(_wf_env, {
        "ETH:mid": {"method": "isotonic", "x": [0.1, 0.3, 0.6, 0.9], "y": [0.2, 0.25, 0.5, 0.85]},
    })
    monkeypatch.setattr(td, "_WALKFWD_CAL_PATH", str(_wf_env))
    monkeypatch.setattr(td, "_walkfwd_cal_cache", {"mtime": None, "artifact": None})
    monkeypatch.setattr(td, "MERID_WALKFWD_CAL_ENABLED", True)
    outs = [td._walkforward_calibrate_p_yes("ETH", 400, p) for p in [0.15, 0.4, 0.75]]
    assert outs[0] < outs[1] < outs[2]


# ---- cheap-NO research lane -------------------------------------------------

def test_cheap_no_band_and_tiers():
    from merid.prediction.cheap_no_research import evaluate_eligibility
    # ETH mid in-band positive edge -> primary candidate
    v = evaluate_eligibility(asset="ETH", no_ask_cents=18, no_depth_cc=200,
                           tte_seconds=450, quote_age_ms=100, rti_age_ms=200,
                           net_edge_maker=0.03)
    assert v["eligible"] and v["tier"] == "primary_candidate" and v["tte_bucket"] == "mid"
    # DOGE mid -> quarantined research
    v = evaluate_eligibility(asset="DOGE", no_ask_cents=18, no_depth_cc=200,
                           tte_seconds=450, quote_age_ms=100, rti_age_ms=200,
                           net_edge_maker=0.03)
    assert v["eligible"] and v["tier"] == "quarantined_research"
    # BTC excluded everywhere
    v = evaluate_eligibility(asset="BTC", no_ask_cents=18, no_depth_cc=200,
                           tte_seconds=450, quote_age_ms=100, rti_age_ms=200,
                           net_edge_maker=0.05)
    assert not v["eligible"] and "asset_toxic_cohort" in v["exclusions"]
    # early + late excluded
    for tte in (120, 700):
        v = evaluate_eligibility(asset="ETH", no_ask_cents=18, no_depth_cc=200,
                               tte_seconds=tte, quote_age_ms=100, rti_age_ms=200,
                               net_edge_maker=0.05)
        assert not v["eligible"]


def test_cheap_no_requires_positive_maker_edge():
    from merid.prediction.cheap_no_research import evaluate_eligibility
    v = evaluate_eligibility(asset="ETH", no_ask_cents=18, no_depth_cc=200,
                           tte_seconds=450, quote_age_ms=100, rti_age_ms=200,
                           net_edge_maker=-0.002)
    assert not v["eligible"] and "nonpositive_maker_edge" in v["exclusions"]


def test_cheap_no_record_fields(tmp_path, monkeypatch):
    from merid.prediction.cheap_no_research import log_cheap_no_research
    log_path = tmp_path / "cnr.jsonl"
    monkeypatch.setenv("MERID_CHEAP_NO_RESEARCH_LOG", str(log_path))
    # out-of-band writes nothing
    log_cheap_no_research(run_id="r", decision_id="d", asset="ETH", ticker="T",
                          yes_bid_cents=70, yes_ask_cents=72, no_bid_cents=26,
                          no_ask_cents=30, no_depth_cc=200,
                          p_no_calibrated=0.3, p_no_raw=0.3,
                          net_edge_taker=-1, net_edge_maker=0.5,
                          edge_threshold=3, fee_cents_maker=0.1, fee_cents_taker=0.6,
                          tte_seconds=450)
    assert not log_path.exists()
    # in-band writes with full forensic fields
    log_cheap_no_research(run_id="r", decision_id="d2", asset="ETH", ticker="T2",
                          yes_bid_cents=80, yes_ask_cents=82, no_bid_cents=16,
                          no_ask_cents=18, no_depth_cc=250,
                          p_no_calibrated=0.22, p_no_raw=0.20,
                          net_edge_taker=-1.0, net_edge_maker=0.5,
                          edge_threshold=3, fee_cents_maker=0.05, fee_cents_taker=0.8,
                          tte_seconds=450, quote_age_ms=80, rti_age_ms=150,
                          regime="normal", liquidity_role_eval="maker",
                          decision_reason="live_evidence_asset_no")
    rec = json.loads(log_path.read_text().strip())
    assert rec["side"] == "no" and rec["no_ask_cents"] == 18.0
    assert rec["research_eligible"] is True and rec["research_tier"] == "primary_candidate"
    assert rec["yes_bid_cents"] == 80 and rec["no_depth_cc"] == 250
    assert rec["decision_reason"] == "live_evidence_asset_no"
    assert rec["tte_bucket"] == "mid"
