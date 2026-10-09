"""Three-axis admission-verdict regression tests (2026-10-09 audit).

Covers ``_assemble_side_verdict`` — the telemetry layer that separates
economic qualification, evidence qualification, and exploration
authorization so a bounded negative-floor admit can never be reported as a
profitable production admit.

The canonical XRP case from the live cap-shadow log:
    eff_ev = -3.9c >= bound = -4.0c
is an EXPLORATION_AUTHORIZED verdict with economics_verdict=FAIL — never a
positive-EV admit.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

import merid.prediction.trade_decision as _td
from merid.prediction.trade_decision import (
    ADMISSION_VERDICT_ECON_PASS_EV_INSUFF,
    ADMISSION_VERDICT_ECONOMICS_FAIL,
    ADMISSION_VERDICT_EXPLORATION,
    ADMISSION_VERDICT_HARD_BLOCK,
    ADMISSION_VERDICT_PRODUCTION,
    _assemble_side_verdict,
    _clear_live_evidence_cache,
    compute_trade_decision,
)


def _verdict(**kwargs):
    """Assemble a verdict with benign defaults; kwargs override."""
    args = dict(
        side="yes",
        p_selected=0.70,
        min_p_selected=0.60,
        eff_edge_cents=5.0,
        eff_bound_cents=2.0,
        cbp_neg_floor=False,
        evidence_detail=None,
        admission_owner=None,
        admission_decision=None,
        admission_reason=None,
        gross_edge_cents=8.0,
        net_edge_cents=4.0,
        model_risk_reserve_cents=2.0,
        exit_cost_reserve_cents=0.5,
        adverse_selection_reserve_cents=1.5,
        entry_fee_cents=0.9,
    )
    args.update(kwargs)
    return _assemble_side_verdict(**args)


def _ev_detail(**kwargs):
    d = {
        "evidence_policy_version": "cell_aware_v1",
        "code": "CELL_EVIDENCE_PASS",
        "admission_state": "NORMAL_ADMISSIBLE",
        "allowed": True,
        "cell_key": "XRP|yes|75-89|mid",
        "evidence_level_used": "asset_side_price",
        "effective_independent_n": 30.0,
        "cell_n_eff": 12.0,
        "escape_required": False,
        "matching_hard_block": False,
        "evidence_stale": False,
        "lcb_net_ev_cents": 3.0,
        "required_margin_cents": 1.5,
    }
    d.update(kwargs)
    return d


# ── economics axis ────────────────────────────────────────────────────


def test_economics_pass_when_p_clears_cost_basis():
    v = _verdict()
    assert v["economics_verdict"] == "PASS"


def test_economics_fail_when_p_below_cost_basis():
    v = _verdict(p_selected=0.59)
    assert v["economics_verdict"] == "FAIL"


def test_reserve_decomposition_exposes_central_vs_conservative():
    """conservative = net_edge (all reserves); central adds back the two
    uncertainty reserves (model-risk + adverse-selection) but keeps real
    expected costs (entry fee + expected exit)."""
    v = _verdict(
        net_edge_cents=-3.9,
        model_risk_reserve_cents=3.0,
        adverse_selection_reserve_cents=1.5,
        exit_cost_reserve_cents=0.5,
        entry_fee_cents=0.9,
    )
    assert v["conservative_net_ev_cents"] == pytest.approx(-3.9)
    assert v["central_net_ev_cents"] == pytest.approx(0.6)  # -3.9+3.0+1.5
    assert v["reserves_cents"] == pytest.approx(5.0)  # 3.0+0.5+1.5


# ── the XRP negative-floor case ───────────────────────────────────────


def test_negative_floor_admit_is_exploration_not_profit():
    """eff_ev=-3.9c >= bound=-4.0c on a cbp negative-floor lane is
    EXPLORATION_AUTHORIZED with economics_verdict=FAIL — never profitable."""
    v = _verdict(
        p_selected=0.805,
        min_p_selected=0.87,          # cost basis incl. reserves
        eff_edge_cents=-3.9,
        eff_bound_cents=-4.0,
        cbp_neg_floor=True,
        net_edge_cents=-3.9,
        evidence_detail=_ev_detail(
            code="SPARSE_MATCHED_PASS", allowed=True, escape_required=True
        ),
        admission_owner="current_build_provisional",
        admission_decision="allowed",
        admission_reason="cbp_legacy_evidence_labelled",
    )
    assert v["economics_verdict"] == "FAIL"
    assert v["exploration_verdict"] == "AUTHORIZED:current_build_provisional"
    assert v["admission_verdict"] == ADMISSION_VERDICT_EXPLORATION
    assert v["admission_verdict"] != ADMISSION_VERDICT_PRODUCTION
    assert v["negative_floor_lane"] is True


def test_negative_floor_rule_ok_even_if_owner_not_set():
    """The floor rule itself authorizes exploration even when another gate
    (e.g. depth, throttle) still binds the candidate."""
    v = _verdict(
        p_selected=0.80, min_p_selected=0.87,
        eff_edge_cents=-3.9, eff_bound_cents=-4.0,
        cbp_neg_floor=True, net_edge_cents=-3.9,
    )
    assert v["economics_verdict"] == "FAIL"
    assert v["exploration_verdict"] == "AUTHORIZED:provisional_neg_floor"
    assert v["admission_verdict"] == ADMISSION_VERDICT_EXPLORATION


def test_negative_floor_below_bound_is_floor_fail_econ_fail():
    v = _verdict(
        p_selected=0.80, min_p_selected=0.87,
        eff_edge_cents=-5.1, eff_bound_cents=-4.0,
        cbp_neg_floor=True, net_edge_cents=-5.1,
    )
    assert v["exploration_verdict"] == "FLOOR_FAIL"
    assert v["admission_verdict"] == ADMISSION_VERDICT_ECONOMICS_FAIL


def test_negative_edge_no_lane_is_plain_econ_fail():
    v = _verdict(
        p_selected=0.80, min_p_selected=0.87,
        eff_edge_cents=-2.0, eff_bound_cents=2.0,
        net_edge_cents=-2.0,
    )
    assert v["admission_verdict"] == ADMISSION_VERDICT_ECONOMICS_FAIL


# ── hard safety ───────────────────────────────────────────────────────


def test_toxic_cell_unrescued_is_hard_safety_block():
    v = _verdict(
        evidence_detail=_ev_detail(
            code="MATCHING_TOXIC_CELL",
            admission_state="HARD_BLOCK",
            allowed=False,
            matching_hard_block=True,
            hard_block_ev_cents=-9.2,
        ),
    )
    assert v["evidence_verdict"] == "HARD_BLOCK"
    assert v["admission_verdict"] == ADMISSION_VERDICT_HARD_BLOCK
    assert v["hard_safety_flag"] is True


def test_toxic_cell_demoted_by_cbp_is_not_hard_block():
    """Inside the provisional domain a legacy toxic verdict is a label,
    not a veto — the verdict axes must reflect that demotion while keeping
    the hard_safety_flag visible."""
    v = _verdict(
        p_selected=0.59,                       # econ FAIL
        evidence_detail=_ev_detail(
            code="MATCHING_TOXIC_CELL",
            allowed=False,
            matching_hard_block=True,
        ),
        admission_owner="current_build_provisional",
        admission_decision="allowed",
    )
    assert v["hard_safety_flag"] is True
    assert v["admission_verdict"] != ADMISSION_VERDICT_HARD_BLOCK
    # econ fail + bounded-lane owner -> exploration (or econ fail w/o lane)
    assert v["admission_verdict"] in (
        ADMISSION_VERDICT_EXPLORATION,
        ADMISSION_VERDICT_ECONOMICS_FAIL,
    )


# ── evidence / exploration boundaries ────────────────────────────────


def test_production_pass_requires_dense_evidence():
    v = _verdict(
        evidence_detail=_ev_detail(),
        admission_owner="formula",
        admission_decision="allowed",
    )
    assert v["evidence_verdict"] == "SUFFICIENT"
    assert v["admission_verdict"] == ADMISSION_VERDICT_PRODUCTION


def test_sparse_pass_is_exploration_not_production():
    """A pass that only clears via the bounded escape lane is authorized
    exploration — evidence isn't dense enough for production admission."""
    v = _verdict(
        evidence_detail=_ev_detail(
            code="SPARSE_MATCHED_PASS", escape_required=True,
        ),
        admission_owner="evidence_escape",
        admission_decision="allowed",
    )
    assert v["evidence_verdict"] == "SPARSE_PASS"
    assert v["admission_verdict"] == ADMISSION_VERDICT_EXPLORATION


def test_econ_pass_evidence_insufficient_no_lane():
    v = _verdict(
        evidence_detail=_ev_detail(
            code="CELL_EVIDENCE_INSUFFICIENT", allowed=False,
            lcb_net_ev_cents=-1.0,
        ),
    )
    assert v["economics_verdict"] == "PASS"
    assert v["evidence_verdict"].startswith("INSUFFICIENT")
    assert v["exploration_verdict"] == "NONE"
    assert v["admission_verdict"] == ADMISSION_VERDICT_ECON_PASS_EV_INSUFF


def test_escape_cap_exhausted_is_not_authorization():
    v = _verdict(
        evidence_detail=_ev_detail(
            code="ESCAPE_CAP_EXHAUSTED", allowed=False,
        ),
    )
    assert v["exploration_verdict"] == "CAP_EXHAUSTED"
    assert v["admission_verdict"] == ADMISSION_VERDICT_ECON_PASS_EV_INSUFF


def test_escape_lane_disabled_is_not_authorization():
    v = _verdict(
        evidence_detail=_ev_detail(
            code="ESCAPE_LANE_DISABLED", allowed=False,
        ),
    )
    assert v["exploration_verdict"] == "LANE_DISABLED"


def test_stale_evidence_labelled():
    v = _verdict(
        evidence_detail=_ev_detail(
            code="CELL_EVIDENCE_INSUFFICIENT", allowed=False,
            evidence_stale=True, evidence_age_s=7200.0,
        ),
    )
    assert v["evidence_verdict"].startswith("STALE:")


def test_not_evaluated_when_no_detail():
    v = _verdict()
    assert v["evidence_verdict"] == "NOT_EVALUATED"


# ── compute_trade_decision integration ───────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_evidence(monkeypatch, tmp_path):
    """Point the evidence artifact at a tmp path; same isolation pattern as
    test_live_entry_evidence_gate."""
    path = tmp_path / "live_entry_evidence.json"
    monkeypatch.setenv("MERID_LIVE_EVIDENCE_PATH", str(path))
    monkeypatch.setattr(_td, "MERID_LIVE_EVIDENCE_GATE", True)
    monkeypatch.setattr(_td, "MERID_LIVE_EVIDENCE_MARGIN", 0.03)
    _clear_live_evidence_cache()
    yield path
    _clear_live_evidence_cache()


def _decision(**kwargs):
    args = dict(
        run_id="test_run",
        decision_id="test_decision",
        ticker="KXBTC15M-26SEP282100-00",
        asset="BTC",
        spot_price=99.5,
        strike_price=100.0,
        seconds_to_expiry=400.0,
        yes_bid_cents=40.0,
        yes_ask_cents=42.0,
        no_bid_cents=56.0,
        no_ask_cents=58.0,
        yes_depth_cc=200.0,
        no_depth_cc=200.0,
        fee_per_contract_cents=1.0,
        data_quality="live",
        regime="normal",
        settlement_reference="cfb_rti_live",
    )
    args.update(kwargs)
    return compute_trade_decision(**args)


def test_decision_stamps_side_verdicts(_isolate_evidence):
    """Every decision — admitted or rejected — carries the three axes."""
    d = _decision()
    sv = d.indicators.get("side_verdicts")
    assert sv is not None and set(sv) == {"yes", "no"}
    for side in ("yes", "no"):
        v = sv[side]
        assert v["admission_verdict"] in {
            ADMISSION_VERDICT_PRODUCTION,
            ADMISSION_VERDICT_ECON_PASS_EV_INSUFF,
            ADMISSION_VERDICT_EXPLORATION,
            ADMISSION_VERDICT_ECONOMICS_FAIL,
            ADMISSION_VERDICT_HARD_BLOCK,
        }
        assert v["economics_verdict"] in ("PASS", "FAIL")
        # flattened mirrors exist
        assert d.indicators[f"{side}_admission_verdict"] == v["admission_verdict"]
        assert d.indicators[f"{side}_economics_verdict"] == v["economics_verdict"]


def test_rejected_record_carries_verdicts(_isolate_evidence, tmp_path, monkeypatch):
    """A rejected candidate's JSONL record includes side_verdicts so the
    cohort report can separate econ fail from evidence-insufficient from
    exploration-authorized."""
    rej = tmp_path / "rejected.jsonl"
    monkeypatch.setenv("MERID_REJECTED_CANDIDATES_LOG", str(rej))
    _decision()  # healthy or not — either way verdicts stamp
    # Trigger a rejection path by using an impossible book (no edge).
    d = _decision(yes_ask_cents=99.0, no_ask_cents=99.0)
    assert d.selected_outcome is None
    if rej.exists():
        recs = [json.loads(x) for x in rej.read_text().splitlines() if x.strip()]
        assert recs, "expected at least one rejected-candidate record"
        assert any(r.get("side_verdicts") for r in recs)
