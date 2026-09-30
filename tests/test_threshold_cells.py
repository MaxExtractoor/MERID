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
    THRESHOLD_CELLS,
    ThresholdCell,
    resolve_threshold_cell,
    threshold_cells_enabled,
)
from merid.prediction.trade_decision import (
    _decompose_dynamic_min_required_edge,
    compute_trade_decision,
)


@pytest.fixture(autouse=True)
def _disable_market_anchor(monkeypatch):
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MIN_W", 0.0)
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MAX_W", 0.0)
    monkeypatch.setattr(_td, "MERID_CALIBRATION_CAP_FULL_RANGE", False)
    monkeypatch.delenv("MERID_THRESHOLD_CELLS", raising=False)


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
    # TTE bounds: 120 inclusive, 600 exclusive.
    assert resolve_threshold_cell("SOL", "no", 45.0, 119.9) is None
    assert resolve_threshold_cell("SOL", "no", 45.0, 120.0) is not None
    assert resolve_threshold_cell("SOL", "no", 45.0, 600.0) is None


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
