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


# ---- price-adjusted empirical LCB gates -----------------------------------

def _tail_decision(*, adj_lcb, applied=True, price=0.81, net_edge=0.015,
                   model_risk=0.02, seconds=240):
    """Minimal selected-NO decision at a tail price for the bounded-domain gate."""
    from decimal import Decimal
    from datetime import datetime, timezone
    from merid.prediction.trade_decision import EdgeBreakdown, TradeDecision
    bd = EdgeBreakdown(
        p_yes=1.0 - price, p_no=price, selected_side="no",
        p_selected=0.86, p_opposite=0.14,
        executable_entry_price=price, entry_fee=0.015,
        exit_cost_reserve=0.02, model_risk_reserve=model_risk,
        gross_edge=0.86 - price, net_edge=net_edge,
    )
    return TradeDecision(
        run_id="epc", decision_id="epc_tail", ticker="KXETH15M-EPC",
        asset="ETH", timestamp_utc=datetime.now(timezone.utc),
        p_yes_raw=Decimal("0.2"), p_yes_calibrated=Decimal("0.2"),
        p_yes_uncertainty=Decimal("0"), p_no_calibrated=Decimal("0.8"),
        data_state="healthy", regime_label="normal",
        selected_outcome="no", selected_action="buy",
        seconds_to_expiry=Decimal(str(seconds)),
        no_edge_breakdown=bd, edge_breakdown=bd,
        indicators={
            "epc_mode": "live" if applied else "shadow",
            "no_epc_applied": applied,
            "no_epc_cell": "epc_no_80_89_m6",
            "no_epc_adj_lcb_cents": adj_lcb,
        },
    )


def _thr(total=0.02):
    from merid.prediction.trade_decision import EdgeThresholdDecomposition
    return EdgeThresholdDecomposition(
        total=total, base_floor=total, global_floor=total, asset_base=0.0,
        convexity=0.0, flb_premium=0.0, clamped_floor=False,
        clamped_ceiling=False,
    )


def test_tail_lcb_gate_accepts_price_adjusted_epc_lcb():
    from merid.prediction.trade_decision import apply_bounded_live_domain_gate
    # Model LCB = (0.015 - 0.02)*100 = -0.5c — below the 2.0c required edge.
    # Cell epc_no_80_89_m6 LCB 1.53c, held 81c vs avg 84.8c -> adj 5.33c.
    d = _tail_decision(adj_lcb=5.33)
    out = apply_bounded_live_domain_gate(d, no_threshold=_thr(0.02))
    assert out.selected_outcome == "no"
    rec = out.indicators["bounded_domain_gate"]
    assert rec["epc_lcb_cents"] == pytest.approx(5.33)
    assert rec["epc_cell"] == "epc_no_80_89_m6"


def test_tail_lcb_gate_rejects_entry_priced_above_cell_average():
    from merid.prediction.trade_decision import apply_bounded_live_domain_gate
    # Same cell LCB but held 88c vs avg 84.8c -> adj -1.67c: no rescue.
    d = _tail_decision(adj_lcb=-1.67, price=0.88)
    out = apply_bounded_live_domain_gate(d, no_threshold=_thr(0.02))
    assert out.selected_outcome is None
    rec = out.indicators["bounded_domain_gate"]
    assert rec["gate"] == "tail_lcb" and rec["epc_lcb_cents"] is None


def test_tail_lcb_gate_shadow_mode_never_substitutes_epc_lcb():
    from merid.prediction.trade_decision import apply_bounded_live_domain_gate
    d = _tail_decision(adj_lcb=9.9, applied=False)
    out = apply_bounded_live_domain_gate(d, no_threshold=_thr(0.02))
    assert out.selected_outcome is None
    assert out.indicators["bounded_domain_gate"]["epc_lcb_cents"] is None


def test_adj_lcb_indicator_and_eff_edge_recorded(monkeypatch, _neutral):
    monkeypatch.setenv("MERID_EMPIRICAL_CAL_MODE", "live")
    d = _decision()
    ind = d.indicators
    # cell: edge_lcb 2.1c, avg_price 64c; held 64c -> adj 2.1c
    assert ind["no_epc_adj_lcb_cents"] == pytest.approx(2.1)
    # effective edge = max(reserve-stacked net, adj_lcb) in cents
    exp = max(float(d.no_edge_breakdown.net_edge) * 100.0, 2.1)
    assert ind["no_epc_eff_edge_cents"] == pytest.approx(exp)
