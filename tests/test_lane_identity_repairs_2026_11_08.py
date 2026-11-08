"""Regression tests for the 2026-11-08 lane-identity + lane-band repairs.

Three verified defects are covered:

1. Bid-priced route clobbering: ``entry_price_basis="bid"`` evaluations
   stamped ``decision_lane`` to ``maker_bid``/``empirical_marginal_maker``
   for every lane except pinned_fav/drift_fav/cheap_no_settle — so
   threshold_cell, current_build_provisional, evidence_cell_escape and
   trend_yes_hi admissions lost their lane identity, never fired
   ``candidate_emitted``, burned the generic maker_bid budget, and were
   misattributed in outcome joins.  ``agent_grid_15m`` documents lane-owned
   selections as consuming their own durable counters
   (``_is_generic_maker_bid_lane``) — the clobber contradicted that.

2. ``entry_lane`` was never stamped for the cell/evidence lanes, so the
   universal ``MERID_MODEL_EDGE_FLOOR_CENTS`` raw-gap floor (fitted on the
   formula path) applied to them with no lane exemption — the same failure
   mode the pinned_fav/drift_fav exemptions document.

3. The slot allocator / order_gate / router canonical-range gates only
   knew pinned_fav/window_quota/settlement bands, so lane-admitted orders
   outside the profile 25-80c band died downstream as
   ``slot_allocation_failed`` / ``price_guard`` / deep-OTM rejects.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from decimal import Decimal

import pytest

import merid.prediction.trade_decision as _td
from merid.prediction.trade_decision import (
    EdgeBreakdown,
    TradeDecision,
    apply_model_edge_floor_gate,
    compute_trade_decision,
)
from merid.risk.global_slot_allocator import _lane_entry_band_cents


_fd, _tmp_daily = tempfile.mkstemp(suffix=".json")
os.close(_fd)


@pytest.fixture(autouse=True)
def _configure_lane(monkeypatch, tmp_path):
    monkeypatch.setattr(_td, "MERID_TAIL_CALIBRATION_ENABLED", False)
    monkeypatch.setattr(_td, "MERID_ORDER_DECISION_LEDGER_ENABLED", False)
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MIN_W", 0.0)
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MAX_W", 0.0)
    monkeypatch.setattr(_td, "MERID_CHEAP_TAIL_CANARY_ENABLED", False)
    monkeypatch.setattr(
        _td, "MERID_CHEAP_TAIL_CANARY_DAILY_FILE", _tmp_daily
    )
    # Keep synthetic floor vetoes out of the live counterfactual log.
    monkeypatch.setattr(_td, "log_rejected_candidate", lambda **k: None, raising=False)
    monkeypatch.setenv(
        "MERID_THRESHOLD_CELL_STATE_PATH", str(tmp_path / "cells.json")
    )
    for _v in (
        "MERID_THRESHOLD_CELL_DAILY_MAX_SUBMISSIONS",
        "MERID_THRESHOLD_CELL_DAILY_MAX",
        "MERID_THRESHOLD_CELL_PER_CELL_MAX_SUBMISSIONS",
        "MERID_THRESHOLD_CELL_DAILY_MAX_FILLS",
        "MERID_THRESHOLD_CELL_DAILY_MAX_FILLS_TOTAL",
        "MERID_THRESHOLD_CELL_MAX_OPEN_ORDERS",
        "MERID_THRESHOLD_CELL_MAX_OPEN_ORDERS_TOTAL",
        "MERID_PROVISIONAL_MIN_EV_FLOOR_C",
        "MERID_PROVISIONAL_MIN_EV_C",
    ):
        monkeypatch.delenv(_v, raising=False)
    for _a in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
        for _s in ("YES", "NO"):
            monkeypatch.delenv(
                f"MERID_PROVISIONAL_MIN_EV_C_{_a}_{_s}", raising=False
            )


def _cell_decision(**overrides):
    """SOL NO inside sol_no_30_60_t120_600 — the registered-cell cohort."""
    kw = dict(
        run_id="test_run",
        decision_id="test_lane_id",
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
    kw.update(overrides)
    return compute_trade_decision(**kw)


def test_bid_route_preserves_threshold_cell_lane():
    """A cell-admitted selection evaluated on the bid-priced route must keep
    decision_lane=threshold_cell — the maker_bid/emm stamp is only for
    candidates no lane owns."""
    d = _cell_decision(
        decision_id="test-lane-bid",
        entry_price_basis="bid",
        adverse_selection_reserve=0.02,
    )
    if d.selected_outcome == "no":
        assert d.indicators.get("decision_lane") == "threshold_cell", (
            f"lane clobbered on bid route: "
            f"{d.indicators.get('decision_lane')} "
            f"reason={d.no_trade_reason}"
        )
        assert d.indicators.get("entry_lane") == "threshold_cell"
    else:
        # If a downstream gate vetoed, the cell threshold must still be the
        # recorded bound — but the lane must never read maker_bid/emm for a
        # cell-owned candidate.
        assert d.indicators.get("decision_lane") != "maker_bid"
        assert d.indicators.get("decision_lane") != "empirical_marginal_maker"


def test_ask_route_stamps_entry_lane_for_cell():
    """The same cohort on the ask route stamps both lane fields."""
    d = _cell_decision(decision_id="test-lane-ask")
    if d.selected_outcome == "no":
        assert d.indicators.get("decision_lane") == "threshold_cell"
        assert d.indicators.get("entry_lane") == "threshold_cell"


def test_generic_bid_route_still_stamps_maker_bid():
    """Unstamped candidates on the bid route keep the maker_bid identity —
    the fix only preserves lanes that already own the admission."""
    d = _cell_decision(
        decision_id="test-generic-bid",
        asset="ETH",
        ticker="KXETH15M-26OCT101830-30",
        spot_price=99.9655,
        strike_price=100.0,
        yes_bid_cents=46.0,
        yes_ask_cents=54.0,
        no_bid_cents=46.0,
        no_ask_cents=54.0,
        yes_depth_cc=500.0,
        no_depth_cc=500.0,
        annualized_vol=0.80,
        p_yes_model=0.59,
        entry_price_basis="bid",
        adverse_selection_reserve=0.02,
        fee_per_contract_cents=0.5,
    )
    if d.selected_outcome is not None:
        assert d.indicators.get("decision_lane") == "maker_bid"
        # Generic formula-path selections carry no entry_lane — the raw-gap
        # floor still applies to them.
        assert d.indicators.get("entry_lane") is None


def _floor_decision(entry_lane, side="no"):
    """Synthetic selected decision whose raw model gap is ~1c (< 4c floor)."""
    price = 0.46
    breakdown = EdgeBreakdown(
        p_yes=0.53,
        p_no=0.47,
        selected_side=side,
        p_selected=0.47,
        p_opposite=0.53,
        executable_entry_price=price,
        entry_fee=0.005,
        exit_cost_reserve=0.005,
        model_risk_reserve=0.0,
        gross_edge=0.01,
        net_edge=0.0,
    )
    ind = {
        "p_no_model_raw": 0.47,
        "p_yes_model_raw": 0.53,
    }
    if entry_lane is not None:
        ind["entry_lane"] = entry_lane
    return TradeDecision(
        run_id="t",
        decision_id="t-floor",
        ticker="KXSOL15M-TEST",
        asset="SOL",
        timestamp_utc=datetime.now(timezone.utc),
        p_yes_raw=Decimal("0.53"),
        p_yes_calibrated=Decimal("0.53"),
        p_yes_uncertainty=Decimal("0.01"),
        p_no_calibrated=Decimal("0.47"),
        selected_outcome=side,
        selected_action="buy",
        selected_outcome_price=Decimal(str(price)),
        edge_breakdown=breakdown,
        no_edge_breakdown=breakdown,
        indicators=ind,
    )


@pytest.mark.parametrize(
    "lane",
    [
        "threshold_cell",
        "current_build_provisional",
        "evidence_cell_escape",
        "trend_yes_hi",
        "settlement_convergence",
        "pinned_fav",
        "drift_fav",
        "cheap_no_settle",
    ],
)
def test_model_edge_floor_exempts_lane_owned_entries(monkeypatch, lane):
    """Each lane's own audited bound governs it — the formula-fitted 4c
    raw-gap floor must not veto lane-owned selections."""
    monkeypatch.setattr(_td, "MERID_MODEL_EDGE_FLOOR_CENTS", 4.0)
    monkeypatch.setattr(_td, "MERID_EPC_FLOOR_MIN_LCB_CENTS", 0.0)
    d = _floor_decision(entry_lane=lane)
    out = apply_model_edge_floor_gate(d)
    assert out.selected_outcome == "no", (
        f"{lane} selection vetoed by model_edge_floor: "
        f"{out.no_trade_reason}"
    )


@pytest.mark.parametrize("lane", ["maker_bid", "empirical_marginal_maker", None])
def test_model_edge_floor_still_binds_generic_entries(monkeypatch, lane):
    """Formula-path selections (generic maker_bid/emm, unstamped) keep the
    raw-gap floor — the exemption is lane-scoped, not a global bypass."""
    monkeypatch.setattr(_td, "MERID_MODEL_EDGE_FLOOR_CENTS", 4.0)
    monkeypatch.setattr(_td, "MERID_EPC_FLOOR_MIN_LCB_CENTS", 0.0)
    d = _floor_decision(entry_lane=lane)
    out = apply_model_edge_floor_gate(d)
    assert out.selected_outcome is None
    assert "model_edge_floor" in (out.no_trade_reason or "")


def test_lane_entry_band_cents_covers_bounded_lanes():
    """Every bounded lane resolves to its own verified price band; generic
    lanes return None (profile band applies)."""
    band = _lane_entry_band_cents("current_build_provisional")
    assert band is not None and band[0] <= 20 and band[1] >= 89
    band = _lane_entry_band_cents("threshold_cell")
    assert band is not None and band[0] <= 20 and band[1] >= 89
    band = _lane_entry_band_cents("evidence_cell_escape")
    assert band is not None and band[0] <= 20 and band[1] >= 89
    band = _lane_entry_band_cents("marginal_band")
    assert band is not None and band[0] <= 50 and band[1] >= 89
    band = _lane_entry_band_cents("settlement_convergence")
    assert band is not None and band[1] >= 97
    for lane in (None, "", "maker_bid", "empirical_marginal_maker",
                 "drift_fav", "cheap_no_settle", "formula"):
        assert _lane_entry_band_cents(lane) is None, lane
