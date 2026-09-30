"""Threshold-cell policy tests (merid/prediction/threshold_cells.py).

The cells are the data-qualified admission regions approved from the settled
counterfactual frontier (2026-09).  These tests prove:

  * cell resolution matches asset x side x price x TTE bounds exactly,
  * the kill switch reverts to the legacy formula,
  * the cell value (not base+convexity+FLB) is the emitted threshold inside a
    qualified cell,
  * non-qualified inputs (YES side, BTC/ETH, out-of-band price/TTE) keep the
    formula result,
  * a cell-admitted selection stamps the threshold_cell decision lane.
"""

from __future__ import annotations

import math
import os

import pytest

import merid.prediction.trade_decision as _td
from merid.prediction.threshold_cells import (
    FUNNEL_STAGES,
    THRESHOLD_CELLS,
    ThresholdCell,
    bind_decision_cell,
    bump_cell_funnel,
    cell_admission,
    cell_for_decision,
    emit_cell_lifecycle,
    explain_cell_miss,
    funnel_counters,
    get_cell_state,
    record_cell_fill,
    record_cell_markout,
    record_cell_router_attempt,
    record_cell_router_reject,
    record_cell_settlement,
    reset_cell_state_cache,
    resolve_threshold_cell,
    threshold_cells_enabled,
    validate_cells_within_price_bands,
)
from merid.prediction.trade_decision import (
    _decompose_dynamic_min_required_edge,
    compute_trade_decision,
)


@pytest.fixture(autouse=True)
def _disable_market_anchor(monkeypatch, tmp_path):
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MIN_W", 0.0)
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MAX_W", 0.0)
    monkeypatch.setattr(_td, "MERID_CALIBRATION_CAP_FULL_RANGE", False)
    monkeypatch.delenv("MERID_THRESHOLD_CELLS", raising=False)
    # Isolate the lane state file per test so caps/suspension don't leak.
    monkeypatch.setenv("MERID_THRESHOLD_CELL_STATE_PATH", str(tmp_path / "cells.json"))
    reset_cell_state_cache()


# ---------------------------------------------------------------------------
# Resolver unit tests
# ---------------------------------------------------------------------------

def test_cells_enabled_by_default():
    assert threshold_cells_enabled() is True


def test_kill_switch_disables(monkeypatch):
    monkeypatch.setenv("MERID_THRESHOLD_CELLS", "0")
    assert threshold_cells_enabled() is False
    assert (
        resolve_threshold_cell("SOL", "no", 45.0, 300.0) is None
    )


def test_sol_no_mid_band_resolves():
    cell = resolve_threshold_cell("SOL", "no", 45.0, 300.0)
    assert cell is not None
    assert cell.cell_id == "sol_no_30_60_t120_600"
    assert cell.min_net_ev_cents == 1.5


def test_cell_bounds_are_half_open():
    # 60c falls out of the 30-60 cell into the 60-80 cell.
    assert resolve_threshold_cell("SOL", "no", 59.99, 300.0).cell_id == "sol_no_30_60_t120_600"
    assert resolve_threshold_cell("SOL", "no", 60.0, 300.0).cell_id == "sol_no_60_80_t120_600"
    assert resolve_threshold_cell("SOL", "no", 80.0, 300.0) is None
    # TTE bounds are INCLUSIVE: 120 <= tte <= 600 (approved contract).
    assert resolve_threshold_cell("SOL", "no", 45.0, 119.9) is None
    assert resolve_threshold_cell("SOL", "no", 45.0, 120.0) is not None
    assert resolve_threshold_cell("SOL", "no", 45.0, 600.0) is not None
    assert resolve_threshold_cell("SOL", "no", 45.0, 600.01) is None


def test_no_cells_for_yes_side():
    for cell in THRESHOLD_CELLS:
        assert cell.side == "no"
    assert resolve_threshold_cell("SOL", "yes", 45.0, 300.0) is None


def test_no_cells_below_20c_or_for_btc_eth():
    for cell in THRESHOLD_CELLS:
        assert cell.price_min_cents >= 20
    assert resolve_threshold_cell("SOL", "no", 15.0, 300.0) is None
    assert resolve_threshold_cell("BTC", "no", 45.0, 300.0) is None
    assert resolve_threshold_cell("ETH", "no", 45.0, 300.0) is None


def test_no_cell_without_tte():
    assert resolve_threshold_cell("SOL", "no", 45.0, None) is None


def test_daily_cap_fails_closed_to_formula(monkeypatch):
    """A matched cell whose daily lane budget is exhausted must NOT relax the
    threshold — it falls back to the formula and flags the suppression."""
    monkeypatch.setenv("MERID_THRESHOLD_CELL_DAILY_MAX", "0")
    d = _decomp("SOL", "no", 45, tte=300.0)
    assert d.cell_id is None
    assert d.cell_cap_exhausted is True
    # Formula total at p=0.45 is ~2.99c — far above the 1.5c cell.
    assert d.total > 0.02


# ---------------------------------------------------------------------------
# Decompose-level integration: cell replaces formula output
# ---------------------------------------------------------------------------

def _decomp(asset, side, px, tte=None):
    return _decompose_dynamic_min_required_edge(
        asset=asset,
        price_cents=px,
        side=side,
        yes_bid_cents=40.0,
        yes_ask_cents=42.0,
        no_bid_cents=53.0,
        no_ask_cents=55.0,
        floor_min_required_edge=0.02,
        seconds_to_expiry=tte,
    )


def test_cell_overrides_formula_total():
    d = _decomp("SOL", "no", 45, tte=300.0)
    assert d.cell_id == "sol_no_30_60_t120_600"
    assert d.cell_min_ev_cents == 1.5
    assert math.isclose(d.total, 0.015, abs_tol=1e-9)
    # The formula components are still emitted for audit: at p=0.45 the
    # convexity term alone is ~0.99c on top of the 2.0c SOL base.
    assert d.convexity > 0.0
    assert d.base_floor >= 0.02


def test_cell_threshold_not_floor_clamped():
    # The cell value (1.5c) is below the legacy 2c floor clamp — the cell is
    # the source of truth, so no clamp applies.
    d = _decomp("SOL", "no", 45, tte=300.0)
    assert d.total < 0.02


def test_out_of_band_price_falls_back_to_formula():
    d = _decomp("SOL", "no", 25, tte=300.0)
    assert d.cell_id is None
    # Formula at p=0.25: base 0.02 + convexity + FLB premium > 0.02.
    assert d.total > 0.02


def test_out_of_band_tte_falls_back_to_formula():
    d = _decomp("SOL", "no", 45, tte=60.0)
    assert d.cell_id is None
    assert d.total > 0.02


def test_btc_no_cell_same_inputs():
    d = _decomp("BTC", "no", 45, tte=300.0)
    assert d.cell_id is None
    # BTC base 1.5c + convexity(0.4*0.6*4%=0.96c) ~ 2.46c.
    assert d.total > 0.02


# ---------------------------------------------------------------------------
# End-to-end: decision carries cell threshold + lane marker
# ---------------------------------------------------------------------------

def test_decision_records_cell_threshold(monkeypatch):
    """SOL NO ask 45c, TTE 300s -> no_min_edge is the 1.5c cell, not ~3c."""
    d = compute_trade_decision(
        run_id="test_run",
        decision_id="test_decision",
        ticker="KXSOL15M-26SEP300900-00",
        asset="SOL",
        spot_price=99.0,
        strike_price=100.0,
        seconds_to_expiry=300.0,
        yes_bid_cents=50.0,
        yes_ask_cents=52.0,
        no_bid_cents=43.0,
        no_ask_cents=45.0,
        yes_depth_cc=200.0,
        no_depth_cc=200.0,
        fee_per_contract_cents=1.0,
        annualized_vol=0.60,
        model_uncertainty=0.0,
        data_quality="live",
        regime="normal",
        min_required_edge=0.02,
        settlement_reference="cfb_rti_live",
        p_yes_model=0.52,
    )
    ind = d.indicators
    assert ind["no_thr_cell_id"] == "sol_no_30_60_t120_600"
    assert math.isclose(ind["no_min_edge"], 0.015, abs_tol=1e-9)
    assert ind["yes_thr_cell_id"] is None
    # The YES side at 52c keeps the formula threshold.
    assert ind["yes_min_edge"] > 0.02


def test_decision_cell_lane_when_selected(monkeypatch):
    """A cell-admitted NO selection stamps decision_lane=threshold_cell."""
    # p_no = 0.50 vs no_ask 45c: net EV ~+2-3c — clears the 1.5c cell but is
    # inside the region where the ~3c formula would have rejected.
    d = compute_trade_decision(
        run_id="test_run",
        decision_id="test_decision",
        ticker="KXSOL15M-26SEP300900-00",
        asset="SOL",
        spot_price=99.0,
        strike_price=100.0,
        seconds_to_expiry=300.0,
        yes_bid_cents=50.0,
        yes_ask_cents=52.0,
        no_bid_cents=43.0,
        no_ask_cents=45.0,
        yes_depth_cc=200.0,
        no_depth_cc=200.0,
        fee_per_contract_cents=1.0,
        annualized_vol=0.60,
        model_uncertainty=0.0,
        data_quality="live",
        regime="normal",
        min_required_edge=0.02,
        settlement_reference="cfb_rti_live",
        p_yes_model=0.50,
    )
    if d.selected_outcome == "no":
        assert d.indicators["threshold_cell_id"] == "sol_no_30_60_t120_600"
        assert d.indicators["decision_lane"] == "threshold_cell"
    else:
        # If a downstream gate (confidence/EV-gate) vetoed, the cell threshold
        # must still be what the record shows the side was measured against.
        assert math.isclose(d.indicators["no_min_edge"], 0.015, abs_tol=1e-9)

# ---------------------------------------------------------------------------
# Boundary miss reasons
# ---------------------------------------------------------------------------

def test_explain_cell_miss_reasons():
    # A real match is not a miss.
    assert explain_cell_miss("SOL", "no", 45.0, 300.0) is None
    assert explain_cell_miss("SOL", "no", 45.0, 100.0) == "threshold_cell_tte_below_min"
    assert explain_cell_miss("SOL", "no", 45.0, 700.0) == "threshold_cell_tte_above_max"
    assert explain_cell_miss("SOL", "no", 15.0, 300.0) == "threshold_cell_price_below_min"
    assert explain_cell_miss("SOL", "no", 85.0, 300.0) == "threshold_cell_price_above_max"
    # DOGE 35c sits between the 20-30 and 40-50 cells: an unqualified gap.
    assert explain_cell_miss("DOGE", "no", 35.0, 300.0) == "threshold_cell_price_in_unqualified_gap"
    assert explain_cell_miss("SOL", "yes", 45.0, 300.0) == "no_cells_for_asset_side"
    assert explain_cell_miss("BTC", "no", 45.0, 300.0) == "no_cells_for_asset_side"
    assert explain_cell_miss("SOL", "no", None, 300.0) == "threshold_cell_price_unknown"
    assert explain_cell_miss("SOL", "no", 45.0, None) == "threshold_cell_tte_unknown"


def test_explain_cell_miss_kill_switch(monkeypatch):
    monkeypatch.setenv("MERID_THRESHOLD_CELLS", "0")
    assert explain_cell_miss("SOL", "no", 45.0, 300.0) == "threshold_cells_disabled"


# ---------------------------------------------------------------------------
# Unambiguous threshold field names on the decision
# ---------------------------------------------------------------------------

def test_decision_emits_unambiguous_threshold_fields():
    d = compute_trade_decision(
        run_id="t", decision_id="t", ticker="KXSOL15M-X",
        asset="SOL", spot_price=99.0, strike_price=100.0,
        seconds_to_expiry=300.0,
        yes_bid_cents=50.0, yes_ask_cents=52.0,
        no_bid_cents=43.0, no_ask_cents=45.0,
        yes_depth_cc=200.0, no_depth_cc=200.0,
        fee_per_contract_cents=1.0, annualized_vol=0.60,
        model_uncertainty=0.0, data_quality="live", regime="normal",
        min_required_edge=0.02, settlement_reference="cfb_rti_live",
        p_yes_model=0.50,
    )
    ind = d.indicators
    # Per-side decomposed fields: formula vs cell vs effective.
    assert math.isclose(ind["no_effective_required_edge_cents"], 1.5, abs_tol=1e-9)
    assert math.isclose(ind["no_cell_required_edge_cents"], 1.5, abs_tol=1e-9)
    assert ind["no_formula_required_edge_cents"] > 1.5
    assert ind["no_threshold_source"] == "threshold_cell"
    # YES side keeps the formula.
    assert ind["yes_threshold_source"] == "formula"
    assert ind["yes_cell_required_edge_cents"] is None


# ---------------------------------------------------------------------------
# Lane state machine + split caps
# ---------------------------------------------------------------------------

def _cell():
    return THRESHOLD_CELLS[0]


def test_cell_admission_ok_by_default():
    ok, blocked = cell_admission(_cell().cell_id)
    assert ok is True and blocked is None
    assert get_cell_state(_cell().cell_id) == "PROVISIONAL"


def test_cell_suspension_blocks_admission():
    cell = _cell()
    # Suspend via rolling-5 negative mean realized PnL (settled outcomes).
    for i in range(5):
        record_cell_settlement(f"d{i}", -5.0, cell_id=cell.cell_id)
    ok, blocked = cell_admission(cell.cell_id)
    assert ok is False and blocked == "cell_suspended"
    assert get_cell_state(cell.cell_id) == "SUSPENDED"


def test_cell_fill_promotes_to_observation():
    cell = _cell()
    record_cell_fill(cell.cell_id, decision_id="d0")
    assert get_cell_state(cell.cell_id) == "OBSERVATION"
    ok, blocked = cell_admission(cell.cell_id)
    assert ok is True and blocked is None


def test_fill_cap_blocks_admission(monkeypatch):
    cell = _cell()
    monkeypatch.setenv("MERID_THRESHOLD_CELL_DAILY_MAX_FILLS", "1")
    record_cell_fill(cell.cell_id, decision_id="d0")
    ok, blocked = cell_admission(cell.cell_id)
    assert ok is False and blocked == "cell_fills_cap_exhausted"


def test_submission_cap_blocks_admission(monkeypatch):
    cell = _cell()
    monkeypatch.setenv("MERID_THRESHOLD_CELL_DAILY_MAX_SUBMISSIONS", "0")
    ok, blocked = cell_admission(cell.cell_id)
    assert ok is False and blocked == "cap_exhausted"


def test_open_order_blocks_admission():
    from merid.prediction.threshold_cells import record_cell_order_open
    cell = _cell()
    record_cell_order_open(cell.cell_id, "ord-1")
    ok, blocked = cell_admission(cell.cell_id)
    assert ok is False and blocked == "cell_open_order_exists"


def test_router_reject_rate_suspends():
    cell = _cell()
    for _ in range(5):
        record_cell_router_attempt(cell.cell_id)
    for _ in range(3):
        record_cell_router_reject(cell.cell_id)
    # 3/5 = 60% > 40% reject ceiling -> SUSPENDED, admission denied.
    ok, blocked = cell_admission(cell.cell_id)
    assert ok is False and blocked == "cell_suspended"
    assert get_cell_state(cell.cell_id) == "SUSPENDED"


def test_markout_suspension():
    cell = _cell()
    for i in range(5):
        record_cell_fill(cell.cell_id, decision_id=f"d{i}")
        record_cell_markout(cell.cell_id, f"d{i}", 5, -2.0)
    ok, blocked = cell_admission(cell.cell_id)
    assert ok is False and blocked == "cell_suspended"


def test_exec_failures_suspend():
    cell = _cell()
    from merid.prediction.threshold_cells import record_cell_exec_failure
    for _ in range(3):
        record_cell_exec_failure(cell.cell_id, "identity_mismatch")
    ok, blocked = cell_admission(cell.cell_id)
    assert ok is False and blocked == "cell_suspended"


def test_positive_outcomes_do_not_suspend():
    cell = _cell()
    for i in range(5):
        record_cell_settlement(f"d{i}", 4.0, cell_id=cell.cell_id)
    ok, blocked = cell_admission(cell.cell_id)
    assert ok is True and blocked is None


def test_funnel_counters():
    cell = _cell()
    bump_cell_funnel("matched", cell.cell_id)
    bump_cell_funnel("matched", cell.cell_id)
    bump_cell_funnel("emitted", cell.cell_id)
    bump_cell_funnel("matched")  # global-only bump
    bump_cell_funnel("not_a_stage", cell.cell_id)  # ignored
    counters = funnel_counters()
    per = counters["funnel_by_cell"][cell.cell_id]
    assert per["matched"] == 2
    assert per["emitted"] == 1
    assert counters["funnel"]["matched"] == 3
    assert "not_a_stage" not in per
    for stage in ("matched", "emitted", "filled"):
        assert stage in FUNNEL_STAGES


def test_band_containment_validation_passes():
    report = validate_cells_within_price_bands()
    assert len(report) == len(THRESHOLD_CELLS)
    assert all(r["reachable"] for r in report)
    ids = {r["cell_id"] for r in report}
    assert ids == {c.cell_id for c in THRESHOLD_CELLS}


def test_decision_cell_binding():
    bind_decision_cell("dec-1", "sol_no_30_60_t120_600")
    assert cell_for_decision("dec-1") == "sol_no_30_60_t120_600"
    assert cell_for_decision("nope") is None


def test_lifecycle_event_schema(tmp_path, monkeypatch):
    import json as _json
    path = tmp_path / "events.jsonl"
    monkeypatch.setenv("MERID_THRESHOLD_CELL_LIFECYCLE_PATH", str(path))
    emit_cell_lifecycle(
        "candidate_emitted",
        threshold_cell_id="sol_no_30_60_t120_600",
        decision_id="d1",
    )
    rows = [_json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert rows and rows[0]["event"] == "threshold_cell_lifecycle"
    assert rows[0]["threshold_cell_id"] == "sol_no_30_60_t120_600"
    assert rows[0]["stage"] == "candidate_emitted"
    assert "ts" in rows[0]

# ---------------------------------------------------------------------------
# Sparse-evidence provisional override (may_bypass_sparse_evidence)
# ---------------------------------------------------------------------------

def test_sparse_override_admits_cell_matched_sparse_block():
    from merid.prediction.threshold_cells import may_bypass_sparse_evidence
    cell = _cell()
    ok, reason = may_bypass_sparse_evidence(
        cell_id=cell.cell_id,
        evidence_code="SPARSE_MATCHED_INSUFFICIENT",
        matching_hard_block=False,
        net_ev_cents=2.0,
        effective_required_edge_cents=1.5,
    )
    assert ok is True and reason is None


def test_sparse_override_never_bypasses_hard_block():
    from merid.prediction.threshold_cells import may_bypass_sparse_evidence
    cell = _cell()
    ok, reason = may_bypass_sparse_evidence(
        cell_id=cell.cell_id,
        evidence_code="SPARSE_MATCHED_INSUFFICIENT",
        matching_hard_block=True,
        net_ev_cents=9.0,
        effective_required_edge_cents=1.5,
    )
    assert ok is False and reason == "matching_hard_block"


def test_sparse_override_rejects_non_sparse_codes():
    from merid.prediction.threshold_cells import may_bypass_sparse_evidence
    cell = _cell()
    for code in ("MATCHING_TOXIC_CELL", "EVIDENCE_EMPTY_INSUFFICIENT",
                 "SOFT_PENALTY_INSUFFICIENT", "SPARSE_MATCHED_PASS"):
        ok, reason = may_bypass_sparse_evidence(
            cell_id=cell.cell_id,
            evidence_code=code,
            matching_hard_block=False,
            net_ev_cents=9.0,
            effective_required_edge_cents=1.5,
        )
        assert ok is False and reason and reason.startswith("evidence_code_not_sparse")


def test_sparse_override_requires_ev_above_cell_threshold():
    from merid.prediction.threshold_cells import may_bypass_sparse_evidence
    cell = _cell()
    ok, reason = may_bypass_sparse_evidence(
        cell_id=cell.cell_id,
        evidence_code="SPARSE_MATCHED_INSUFFICIENT",
        matching_hard_block=False,
        net_ev_cents=1.4,
        effective_required_edge_cents=1.5,
    )
    assert ok is False and reason == "ev_below_cell_threshold"


def test_sparse_override_blocked_when_suspended():
    from merid.prediction.threshold_cells import may_bypass_sparse_evidence
    cell = _cell()
    for i in range(5):
        record_cell_settlement(f"d{i}", -5.0, cell_id=cell.cell_id)
    ok, reason = may_bypass_sparse_evidence(
        cell_id=cell.cell_id,
        evidence_code="SPARSE_MATCHED_INSUFFICIENT",
        matching_hard_block=False,
        net_ev_cents=9.0,
        effective_required_edge_cents=1.5,
    )
    assert ok is False and reason == "cell_state_suspended"


def test_sparse_override_kill_switch(monkeypatch):
    from merid.prediction.threshold_cells import may_bypass_sparse_evidence
    monkeypatch.setenv("MERID_THRESHOLD_CELL_SPARSE_OVERRIDE", "0")
    cell = _cell()
    ok, reason = may_bypass_sparse_evidence(
        cell_id=cell.cell_id,
        evidence_code="SPARSE_MATCHED_INSUFFICIENT",
        matching_hard_block=False,
        net_ev_cents=9.0,
        effective_required_edge_cents=1.5,
    )
    assert ok is False and reason == "sparse_override_disabled"


def test_sparse_override_respects_caps(monkeypatch):
    from merid.prediction.threshold_cells import may_bypass_sparse_evidence
    cell = _cell()
    monkeypatch.setenv("MERID_THRESHOLD_CELL_DAILY_MAX_FILLS", "1")
    record_cell_fill(cell.cell_id, decision_id="d0")
    ok, reason = may_bypass_sparse_evidence(
        cell_id=cell.cell_id,
        evidence_code="SPARSE_MATCHED_INSUFFICIENT",
        matching_hard_block=False,
        net_ev_cents=9.0,
        effective_required_edge_cents=1.5,
    )
    assert ok is False and reason == "cell_fills_cap_exhausted"


# ---------------------------------------------------------------------------
# Tightened caps + emergency suspension rules
# ---------------------------------------------------------------------------

def test_per_cell_submission_cap(monkeypatch):
    cell = _cell()
    monkeypatch.setenv("MERID_THRESHOLD_CELL_PER_CELL_MAX_SUBMISSIONS", "2")
    from merid.prediction.threshold_cells import record_cell_submission
    record_cell_submission(cell_id=cell.cell_id)
    record_cell_submission(cell_id=cell.cell_id)
    ok, blocked = cell_admission(cell.cell_id)
    assert ok is False and blocked == "cell_submissions_cap_exhausted"


def test_total_fills_cap(monkeypatch):
    monkeypatch.setenv("MERID_THRESHOLD_CELL_DAILY_MAX_FILLS_TOTAL", "2")
    c1, c2 = THRESHOLD_CELLS[0], THRESHOLD_CELLS[2]
    record_cell_fill(c1.cell_id, decision_id="d0")
    record_cell_fill(c2.cell_id, decision_id="d1")
    ok, blocked = cell_admission(THRESHOLD_CELLS[4].cell_id)
    assert ok is False and blocked == "cell_fills_total_cap_exhausted"


def test_two_consecutive_router_rejects_suspend():
    cell = _cell()
    record_cell_router_attempt(cell.cell_id)
    record_cell_router_reject(cell.cell_id)
    record_cell_router_attempt(cell.cell_id)
    record_cell_router_reject(cell.cell_id)
    assert get_cell_state(cell.cell_id) == "SUSPENDED"


def test_first_fill_bad_markout_suspends():
    cell = _cell()
    record_cell_fill(cell.cell_id, decision_id="d0")
    record_cell_markout(cell.cell_id, "d0", 5, -3.5)
    assert get_cell_state(cell.cell_id) == "SUSPENDED"


def test_first_fill_loss_exceeds_edge_stress_suspends():
    cell = _cell()
    record_cell_fill(cell.cell_id, decision_id="d0", candidate_ev_cents=2.0)
    # First settled trade loses more than edge+2c stress (bound = -4.0c).
    record_cell_settlement("d0", -4.5, cell_id=cell.cell_id)
    assert get_cell_state(cell.cell_id) == "SUSPENDED"


def test_fill_time_ev_negative_suspends():
    cell = _cell()
    record_cell_fill(cell.cell_id, decision_id="d0",
                     fill_ev_cents=-0.5, candidate_ev_cents=2.0)
    assert get_cell_state(cell.cell_id) == "SUSPENDED"


def test_historical_lcb10_on_cells():
    by_id = {c.cell_id: c for c in THRESHOLD_CELLS}
    assert by_id["sol_no_30_60_t120_600"].historical_lcb10_cents == 8.8
    assert by_id["doge_no_70_90_t120_600"].historical_lcb10_cents == 6.2
    assert all(c.historical_lcb10_cents > 0 for c in THRESHOLD_CELLS)
