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
    # Provisional-lane env overrides must not leak from .env — these tests
    # assert formula-vs-cell resolution on the default threshold table.
    monkeypatch.delenv("MERID_PROVISIONAL_MIN_EV_FLOOR_C", raising=False)
    monkeypatch.delenv("MERID_PROVISIONAL_MIN_EV_C", raising=False)
    for _a in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
        for _s in ("YES", "NO"):
            monkeypatch.delenv(
                f"MERID_PROVISIONAL_MIN_EV_C_{_a}_{_s}", raising=False
            )
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


def test_no_cells_below_20c_and_btc_eth_tte_window():
    for cell in THRESHOLD_CELLS:
        assert cell.price_min_cents >= 20
    assert resolve_threshold_cell("SOL", "no", 15.0, 300.0) is None
    # BTC/ETH have PROVISIONAL cells since 2026-09-30 batch 1 — in-band
    # quotes resolve, out-of-TTE (their cells are t120-300) fall back.
    assert resolve_threshold_cell("BTC", "no", 45.0, 300.0).cell_id == \
        "btc_no_40_50_t120_300"
    assert resolve_threshold_cell("ETH", "no", 55.0, 200.0).cell_id == \
        "eth_no_50_60_t120_300"
    assert resolve_threshold_cell("BTC", "no", 45.0, 400.0) is None
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
    """BTC at 45c/300s resolves the btc_no_40_50_t120_300 PROVISIONAL cell —
    its own 2.5c floor is the threshold, not the BTC formula."""
    d = _decomp("BTC", "no", 45, tte=300.0)
    assert d.cell_id == "btc_no_40_50_t120_300"
    assert math.isclose(d.cell_min_ev_cents, 2.5, abs_tol=1e-9)
    assert math.isclose(d.total, 0.025, abs_tol=1e-9)


def test_btc_outside_cell_tte_uses_formula():
    """BTC cells cover only 120-300s; at 400s the current-build provisional
    lane (BTC-NO 2.0c) owns the unregistered region, and past the provisional
    600s bound the formula decides."""
    d = _decomp("BTC", "no", 45, tte=400.0)
    assert d.cell_id is None
    assert d.provisional_cell_id == "cbp_btc_no_40_50_t300_600"
    assert math.isclose(d.total, 0.020, abs_tol=1e-9)
    d2 = _decomp("BTC", "no", 45, tte=700.0)
    assert d2.cell_id is None
    assert d2.provisional_cell_id is None
    assert d2.total > 0.02


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
    # BTC has cells now: 45c/300s matches; 45c/400s misses on TTE; 75c/200s
    # is a genuine unqualified gap between the 50-60 cell and nothing.
    assert explain_cell_miss("BTC", "no", 45.0, 300.0) is None
    assert explain_cell_miss("BTC", "no", 45.0, 400.0) == "threshold_cell_tte_above_max"
    # 75c exceeds BTC's highest cell band (50-60) -> above_max; 25c is below
    # the lowest (30-40) -> below_min.  The domain floor is 20c.
    assert explain_cell_miss("BTC", "no", 75.0, 200.0) == "threshold_cell_price_above_max"
    assert explain_cell_miss("BTC", "no", 25.0, 200.0) == "threshold_cell_price_below_min"
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
    # YES side at 52c/300s has no registry cell but sits inside the
    # current-build provisional domain (SOL-YES provisional bar: 3.0c).
    assert ind["yes_threshold_source"] == "current_build_provisional"
    assert ind["yes_cell_required_edge_cents"] is None
    assert ind["yes_thr_prov_cell_id"] == "cbp_sol_yes_50_60_t120_300"
    assert math.isclose(ind["yes_provisional_required_edge_cents"], 3.0, abs_tol=1e-9)


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


# ---------------------------------------------------------------------------
# PROBATION: controlled release of stale SUSPENDED cells (2026-10-05)
# ---------------------------------------------------------------------------

def test_probation_reset_releases_aged_suspension(monkeypatch):
    from merid.prediction.threshold_cells import (
        probation_reset_cell,
        set_cell_state,
    )
    cell = _cell()
    monkeypatch.setenv("MERID_THRESHOLD_CELL_PROBATION_MIN_SUSPEND_S", "0")
    set_cell_state(cell.cell_id, "SUSPENDED", "test")
    moved, block = probation_reset_cell(cell.cell_id)
    assert moved is True and block is None
    assert get_cell_state(cell.cell_id) == "PROBATION"
    ok, blocked = cell_admission(cell.cell_id)
    assert ok is True and blocked is None


def test_probation_reset_blocked_by_cooldown():
    from merid.prediction.threshold_cells import (
        probation_reset_cell,
        set_cell_state,
    )
    cell = _cell()
    set_cell_state(cell.cell_id, "SUSPENDED", "test")
    moved, block = probation_reset_cell(cell.cell_id)
    assert moved is False
    assert block.startswith("probation_cooldown")
    assert get_cell_state(cell.cell_id) == "SUSPENDED"


def test_probation_reset_rejects_non_suspended():
    from merid.prediction.threshold_cells import probation_reset_cell
    cell = _cell()
    moved, block = probation_reset_cell(cell.cell_id)
    assert moved is False
    assert block == "not_suspended:PROVISIONAL"


def test_probation_single_strike_resuspends(monkeypatch):
    from merid.prediction.threshold_cells import (
        probation_reset_cell,
        set_cell_state,
    )
    cell = _cell()
    monkeypatch.setenv("MERID_THRESHOLD_CELL_PROBATION_MIN_SUSPEND_S", "0")
    set_cell_state(cell.cell_id, "SUSPENDED", "test")
    moved, _ = probation_reset_cell(cell.cell_id)
    assert moved is True
    # One fresh router strike re-suspends — no second chance.
    record_cell_router_reject(cell.cell_id)
    assert get_cell_state(cell.cell_id) == "SUSPENDED"


def test_probation_submission_cap_tighter(monkeypatch):
    from merid.prediction.threshold_cells import (
        probation_reset_cell,
        record_cell_submission,
        set_cell_state,
    )
    cell = _cell()
    monkeypatch.setenv("MERID_THRESHOLD_CELL_PROBATION_MIN_SUSPEND_S", "0")
    set_cell_state(cell.cell_id, "SUSPENDED", "test")
    moved, _ = probation_reset_cell(cell.cell_id)
    assert moved is True
    record_cell_submission(cell_id=cell.cell_id)
    ok, blocked = cell_admission(cell.cell_id)
    assert ok is False and blocked == "probation_submission_cap"


def test_probation_resuspend_uses_longer_cooldown(monkeypatch):
    from merid.prediction.threshold_cells import (
        probation_reset_cell,
        set_cell_state,
    )
    cell = _cell()
    monkeypatch.setenv("MERID_THRESHOLD_CELL_PROBATION_MIN_SUSPEND_S", "0")
    set_cell_state(cell.cell_id, "SUSPENDED", "test")
    moved, _ = probation_reset_cell(cell.cell_id)
    assert moved is True
    record_cell_router_reject(cell.cell_id)
    assert get_cell_state(cell.cell_id) == "SUSPENDED"
    # Probation-triggered suspension needs the long cooldown — the short
    # min-age floor must not immediately release it again.
    moved, block = probation_reset_cell(cell.cell_id)
    assert moved is False
    assert block.startswith("probation_cooldown")


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


def test_soft_override_rejects_non_soft_codes():
    from merid.prediction.threshold_cells import may_bypass_sparse_evidence
    cell = _cell()
    for code in ("MATCHING_TOXIC_CELL", "EVIDENCE_EMPTY_INSUFFICIENT",
                 "CELL_EVIDENCE_INSUFFICIENT", "SPARSE_MATCHED_PASS",
                 "ESCAPE_LANE_DISABLED", "SOFT_PENALTY_LANE_DISABLED",
                 "CHALLENGE_LANE_DISABLED"):
        ok, reason = may_bypass_sparse_evidence(
            cell_id=cell.cell_id,
            evidence_code=code,
            matching_hard_block=False,
            net_ev_cents=9.0,
            effective_required_edge_cents=1.5,
        )
        assert ok is False and reason and reason.startswith("evidence_code_not_soft")


@pytest.mark.parametrize("code", sorted({
    "SPARSE_MATCHED_INSUFFICIENT", "SOFT_PENALTY_INSUFFICIENT",
    "CHALLENGE_INSUFFICIENT", "ESCAPE_CAP_EXHAUSTED",
    "CHALLENGE_CAP_EXHAUSTED",
}))
def test_soft_override_admits_all_soft_codes(code):
    """The generic escape budget must not gate a qualified cell candidate."""
    from merid.prediction.threshold_cells import may_bypass_sparse_evidence
    cell = _cell()
    ok, reason = may_bypass_sparse_evidence(
        cell_id=cell.cell_id,
        evidence_code=code,
        matching_hard_block=False,
        net_ev_cents=2.0,
        effective_required_edge_cents=1.5,
    )
    assert ok is True and reason is None


def test_soft_override_rejects_unknown_cell_id():
    from merid.prediction.threshold_cells import may_bypass_sparse_evidence
    ok, reason = may_bypass_sparse_evidence(
        cell_id="btc_no_50_60_t120_600",  # not in the registry (t120_600)
        evidence_code="SPARSE_MATCHED_INSUFFICIENT",
        matching_hard_block=False,
        net_ev_cents=9.0,
        effective_required_edge_cents=1.5,
    )
    assert ok is False and reason == "unknown_cell_id"


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
    assert ok is False and reason == "soft_override_disabled"


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


def test_markout_arriving_before_fill_row_merges_and_suspends():
    """Submit-relative markouts emit while the order still looks unfilled;
    the fill recorder absorbs the standalone markout rows so the immediate
    first-fill rule sees them."""
    cell = _cell()
    record_cell_markout(cell.cell_id, "d0", 1, -4.0)
    record_cell_markout(cell.cell_id, "d0", 5, -3.5)
    assert get_cell_state(cell.cell_id) != "SUSPENDED"
    record_cell_fill(cell.cell_id, decision_id="d0")
    assert get_cell_state(cell.cell_id) == "SUSPENDED"


def test_settlement_idempotent_on_repeated_attribution():
    cell = _cell()
    record_cell_fill(cell.cell_id, decision_id="d0", candidate_ev_cents=2.0)
    record_cell_settlement("d0", 1.5, cell_id=cell.cell_id)
    record_cell_settlement("d0", 1.5, cell_id=cell.cell_id)
    from merid.prediction.threshold_cells import _load_state
    outs = _load_state()["outcomes"][cell.cell_id]
    settled = [o for o in outs if o.get("kind") == "settled" and o.get("decision_id") == "d0"]
    assert len(settled) == 1 and settled[0]["net_pnl_cents"] == 1.5


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

# ---------------------------------------------------------------------------
# Five-asset parity: every asset uses the same admission resolver
# ---------------------------------------------------------------------------

ALL_FIVE = ("BTC", "ETH", "SOL", "XRP", "DOGE")
SOFT_CODES = (
    "SPARSE_MATCHED_INSUFFICIENT",
    "SOFT_PENALTY_INSUFFICIENT",
    "CHALLENGE_INSUFFICIENT",
    "ESCAPE_CAP_EXHAUSTED",
    "CHALLENGE_CAP_EXHAUSTED",
)


def _register_cell(monkeypatch, asset):
    """Attach a synthetic approved cell for ANY asset — proves the resolver
    treats asset as data, not as a policy branch."""
    import merid.prediction.threshold_cells as _tc_mod
    cell = ThresholdCell(
        f"{asset.lower()}_no_40_60_t120_600", asset, "no",
        40, 60, 120.0, 600.0, 2.0, "test", 5.0,
    )
    monkeypatch.setattr(_tc_mod, "THRESHOLD_CELLS",
                        list(_tc_mod.THRESHOLD_CELLS) + [cell])
    return cell


@pytest.mark.parametrize("asset", ALL_FIVE)
@pytest.mark.parametrize("code", SOFT_CODES)
def test_any_asset_cell_owns_soft_evidence(monkeypatch, asset, code):
    """A registered cell + EV clearing its bar + soft evidence -> cell lane
    admits, for every asset including BTC/ETH (no asset-specific branches)."""
    from merid.prediction.threshold_cells import may_bypass_sparse_evidence
    cell = _register_cell(monkeypatch, asset)
    ok, reason = may_bypass_sparse_evidence(
        cell_id=cell.cell_id,
        evidence_code=code,
        matching_hard_block=False,
        net_ev_cents=3.0,
        effective_required_edge_cents=2.0,
    )
    assert ok is True and reason is None


@pytest.mark.parametrize("asset", ALL_FIVE)
def test_hard_block_cannot_be_bypassed_any_asset(monkeypatch, asset):
    from merid.prediction.threshold_cells import may_bypass_sparse_evidence
    cell = _register_cell(monkeypatch, asset)
    for code in ("MATCHING_TOXIC_CELL", "CELL_EVIDENCE_INSUFFICIENT",
                 "SPARSE_MATCHED_INSUFFICIENT"):
        ok, reason = may_bypass_sparse_evidence(
            cell_id=cell.cell_id,
            evidence_code=code,
            matching_hard_block=True,
            net_ev_cents=9.0,
            effective_required_edge_cents=2.0,
        )
        assert ok is False and reason == "matching_hard_block"


@pytest.mark.parametrize("asset", ALL_FIVE)
def test_non_soft_codes_rejected_any_asset(monkeypatch, asset):
    from merid.prediction.threshold_cells import may_bypass_sparse_evidence
    cell = _register_cell(monkeypatch, asset)
    for code in ("MATCHING_TOXIC_CELL", "CELL_EVIDENCE_INSUFFICIENT",
                 "EVIDENCE_EMPTY_INSUFFICIENT", "ESCAPE_LANE_DISABLED"):
        ok, reason = may_bypass_sparse_evidence(
            cell_id=cell.cell_id,
            evidence_code=code,
            matching_hard_block=False,
            net_ev_cents=9.0,
            effective_required_edge_cents=2.0,
        )
        assert ok is False and reason.startswith("evidence_code_not_soft")


@pytest.mark.parametrize("asset", ALL_FIVE)
def test_negative_ev_never_uses_override_any_asset(monkeypatch, asset):
    from merid.prediction.threshold_cells import may_bypass_sparse_evidence
    cell = _register_cell(monkeypatch, asset)
    for ev in (-0.1, 0.0, 1.99):
        ok, reason = may_bypass_sparse_evidence(
            cell_id=cell.cell_id,
            evidence_code="SPARSE_MATCHED_INSUFFICIENT",
            matching_hard_block=False,
            net_ev_cents=ev,
            effective_required_edge_cents=2.0,
        )
        assert ok is False and reason == "ev_below_cell_threshold"


def test_registry_covers_all_five_assets():
    from merid.prediction.threshold_cells import (
        ALL_ASSETS, CELLS_BY_ASSET, cells_for_asset,
    )
    assert set(CELLS_BY_ASSET) == set(ALL_ASSETS) == set(ALL_FIVE)
    # 2026-09-30 batch 1: every asset now carries live registry cells.
    assert len(cells_for_asset("BTC")) == 3
    assert len(cells_for_asset("ETH")) == 2
    assert len(cells_for_asset("SOL")) == 2
    assert len(cells_for_asset("XRP")) == 2
    assert len(cells_for_asset("DOGE")) == 3
    # BTC/ETH resolve through the same shared resolver as SOL/XRP/DOGE.
    assert resolve_threshold_cell("BTC", "no", 45.0, 300.0).cell_id == \
        "btc_no_40_50_t120_300"
    assert explain_cell_miss("BTC", "no", 45.0, 300.0) is None
    # ETH 45c is below every ETH cell floor (50c) — a miss, but an
    # explicit, attributed one.
    assert explain_cell_miss("ETH", "no", 45.0, 300.0) == \
        "threshold_cell_price_below_min"


def test_invariant_violation_suspends_immediately():
    from merid.prediction.threshold_cells import record_cell_invariant_violation
    cell = _cell()
    record_cell_invariant_violation(cell.cell_id, "side_flip:no_fill_on_yes_leg")
    assert get_cell_state(cell.cell_id) == "SUSPENDED"


def test_zero_fill_time_ev_suspends():
    """Nonpositive (<=0) revalidated fill-time EV suspends on first fill."""
    cell = _cell()
    record_cell_fill(cell.cell_id, decision_id="d0",
                     fill_ev_cents=0.0, candidate_ev_cents=2.0)
    assert get_cell_state(cell.cell_id) == "SUSPENDED"


def test_decayed_report_fields(monkeypatch):
    """decayed_evidence_report emits H7/H21 horizons + drift aliases."""
    from merid.prediction import evidence_policy as ep
    ev_artifact = {
        "cells": {
            "7": {"SOL|no|25-49|mid": {"w": 4.0, "l": 1.0, "n_eff": 5.0,
                                       "n_raw": 5, "entry_wsum": 200.0}},
            "21": {"SOL|no|25-49|mid": {"w": 9.0, "l": 4.0, "n_eff": 13.0,
                                        "n_raw": 13, "entry_wsum": 520.0}},
        }
    }
    rep = ep.decayed_evidence_report(ev_artifact, "SOL", "no", 40.0, 350.0, 0.0)
    assert rep["h7_n_eff"] == 5.0 and rep["h21_n_eff"] == 13.0
    assert rep["recent_n_eff"] == rep["h7_n_eff"]
    assert rep["historical_prior_n_eff"] == rep["h21_n_eff"]
    assert "recent_lcb" in rep and "historical_lcb" in rep
    assert "drift_score" in rep
