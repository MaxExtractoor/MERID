"""Empirical price-calibration overlay (favorite-longshot correction).

Contract:
  * only VALIDATED cells match; anything else (or a stale/missing artifact)
    fails closed to no-match;
  * shadow mode records the estimate without changing probabilities;
  * live mode raises the matched side's probability to the shrunk empirical
    win rate (upward only) and keeps the complement coherent;
  * every downstream gate still runs.
"""
import json
import os
import time

import pytest

import merid.prediction.empirical_price_calibration as epc
import merid.prediction.trade_decision as _td
from merid.prediction.trade_decision import compute_trade_decision


def _artifact(tmp_path, cells, age_s=0.0):
    p = tmp_path / "epc.json"
    p.write_text(json.dumps({"schema": "empirical_price_calibration/v1",
                             "fitted_at_utc": "2026-10-04T00:00:00Z", "cells": cells}))
    if age_s:
        t = time.time() - age_s
        os.utime(p, (t, t))
    return p


def _cell(side="no", lo=60, minute=4, p=0.75, validated=True):
    return {"cell_id": f"epc_{side}_{lo}_{lo + 9}_m{minute}", "side": side, "price_lo_c": lo,
            "price_hi_c": lo + 10, "tte_min_s": minute * 60, "tte_max_s": (minute + 1) * 60,
            "n": 200, "wins": 150, "avg_price_c": lo + 4, "win_rate": p, "edge_c": 8.0,
            "edge_se_c": 3.0, "edge_lcb_c": 2.1, "p_shrunk": p, "validated": validated}


@pytest.fixture(autouse=True)
def _iso(monkeypatch, tmp_path):
    epc.reset_cache_for_tests()
    monkeypatch.setenv("MERID_EMPIRICAL_CAL_LOG_PATH", str(tmp_path / "obs.jsonl"))
    yield
    epc.reset_cache_for_tests()


def test_lookup_matches_only_validated_cells(monkeypatch, tmp_path):
    path = _artifact(tmp_path, [_cell(), _cell(lo=70, validated=False)])
    monkeypatch.setenv("MERID_EMPIRICAL_CAL_PATH", str(path))
    monkeypatch.setenv("MERID_EMPIRICAL_CAL_MODE", "shadow")
    est = epc.lookup("no", 64.0, 4 * 60 + 30)
    assert est is not None and est.cell_id == "epc_no_60_69_m4" and est.p == 0.75
    assert epc.lookup("no", 74.0, 270) is None          # unvalidated cell
    assert epc.lookup("yes", 64.0, 270) is None         # wrong side
    assert epc.lookup("no", 64.0, 6 * 60 + 5) is None   # wrong TTE minute


def test_off_mode_and_stale_or_missing_artifact_fail_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("MERID_EMPIRICAL_CAL_MODE", "off")
    monkeypatch.setenv("MERID_EMPIRICAL_CAL_PATH", str(_artifact(tmp_path, [_cell()])))
    assert epc.lookup("no", 64.0, 270) is None
    monkeypatch.setenv("MERID_EMPIRICAL_CAL_MODE", "live")
    epc.reset_cache_for_tests()
    monkeypatch.setenv("MERID_EMPIRICAL_CAL_PATH", str(tmp_path / "missing.json"))
    assert epc.lookup("no", 64.0, 270) is None
    stale = tmp_path / "stale"
    stale.mkdir()
    epc.reset_cache_for_tests()
    monkeypatch.setenv("MERID_EMPIRICAL_CAL_PATH", str(_artifact(stale, [_cell()], age_s=30 * 86400)))
    assert epc.lookup("no", 64.0, 270) is None


def test_bad_schema_fails_closed(monkeypatch, tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"schema": "v0", "cells": [_cell()]}))
    monkeypatch.setenv("MERID_EMPIRICAL_CAL_PATH", str(p))
    monkeypatch.setenv("MERID_EMPIRICAL_CAL_MODE", "live")
    assert epc.lookup("no", 64.0, 270) is None


# ---- decision-level integration ------------------------------------------

def _decision(**over):
    # NO favourite at 64c, 4.5 minutes left; spot slightly below strike so the
    # Bachelier/market both put NO near 64%.
    args = dict(
        run_id="epc", decision_id="epc_t", ticker="KXETH15M-EPC", asset="ETH",
        spot_price=99.97, strike_price=100.0, seconds_to_expiry=270.0,
        yes_bid_cents=35.0, yes_ask_cents=36.0, no_bid_cents=63.0, no_ask_cents=64.0,
        yes_depth_cc=500.0, no_depth_cc=500.0, fee_per_contract_cents=1.5,
        annualized_vol=0.60, model_uncertainty=0.05, data_quality="live",
        regime="normal", min_required_edge=0.02, settlement_reference="cfb_rti_live",
    )
    args.update(over)
    return compute_trade_decision(**args)


@pytest.fixture
def _neutral(monkeypatch, tmp_path):
    monkeypatch.setattr(_td, "MERID_CALIBRATION_CAP_FULL_RANGE", False)
    monkeypatch.setenv("MERID_EVIDENCE_ESCAPE_STATE_PATH", str(tmp_path / "escape.json"))
    monkeypatch.setenv("MERID_EMPIRICAL_CAL_PATH", str(_artifact(tmp_path, [_cell(p=0.75)])))


def test_shadow_records_but_does_not_change_probability(monkeypatch, tmp_path, _neutral):
    monkeypatch.setenv("MERID_EMPIRICAL_CAL_MODE", "off")
    base = _decision()
    epc.reset_cache_for_tests()
    monkeypatch.setenv("MERID_EMPIRICAL_CAL_MODE", "shadow")
    sh = _decision()
    ind = sh.indicators
    assert ind["no_epc_cell"] == "epc_no_60_69_m4"
    assert ind["no_epc_applied"] is False
    assert ind["p_no_for_no"] == pytest.approx(base.indicators["p_no_for_no"])
    lines = (tmp_path / "obs.jsonl").read_text().splitlines()
    rec = json.loads(lines[-1])
    assert rec["cell_id"] == "epc_no_60_69_m4" and rec["applied"] is False
    assert rec["ev_empirical_c"] == pytest.approx(100 * 0.75 - 64.0 - 1.5)


def test_live_raises_matched_side_probability_upward_only(monkeypatch, _neutral):
    monkeypatch.setenv("MERID_EMPIRICAL_CAL_MODE", "live")
    d = _decision()
    ind = d.indicators
    assert ind["no_epc_applied"] is True
    assert ind["p_no_for_no_pre_cap"] == pytest.approx(0.75)
    # complement stays coherent
    assert ind["p_yes_for_yes_pre_cap"] <= 0.25 + 1e-9


def test_live_never_lowers_a_higher_model_probability(monkeypatch, tmp_path, _neutral):
    monkeypatch.setenv("MERID_EMPIRICAL_CAL_PATH", str(_artifact(tmp_path, [_cell(p=0.30)])))
    epc.reset_cache_for_tests()
    monkeypatch.setenv("MERID_EMPIRICAL_CAL_MODE", "live")
    d = _decision()
    assert d.indicators["no_epc_applied"] is False
    assert d.indicators["p_no_for_no_pre_cap"] > 0.30
