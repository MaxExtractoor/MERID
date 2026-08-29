"""Release-gate tests for the TradeDecision engine.

These tests verify the hard invariants that must pass before live entries can
resume:
  1. p_yes + p_no == 1
  2. selected side uses p_selected, not p_yes or p_no
  3. net edge = p_selected - entry - fee - exit - model_risk
  4. a side is selected only if p_selected > 0.5 and net edge >= min_required_edge
  5. cost-basis overrides (p <= 0.5 with positive edge) are rejected
  6. confidence is valid only from the uncertainty engine, never a 0.95 default
  7. non-CF-RTI settlement reference blocks entries
"""
from __future__ import annotations

import math
import os
from decimal import Decimal

import pytest

from merid.prediction.trade_decision import compute_edge, compute_trade_decision


def _make_decision(
    *,
    spot: float = 100.0,
    strike: float = 100.0,
    seconds_to_expiry: float = 900.0,
    yes_bid: float = 40.0,
    yes_ask: float = 42.0,
    no_bid: float = 58.0,
    no_ask: float = 60.0,
    fee_cents: float = 1.0,
    vol: float = 0.60,
    model_uncertainty: float = 0.05,
    data_quality: str = "live",
    regime: str = "normal",
    min_edge: float = 0.03,
    settlement_reference: str = "cfb_rti_live",
):
    """Helper to create a decision with sensible defaults."""
    return compute_trade_decision(
        run_id="test_run",
        decision_id="test_decision",
        ticker="KXBTC15M-26AUG190930-30",
        asset="BTC",
        spot_price=spot,
        strike_price=strike,
        seconds_to_expiry=seconds_to_expiry,
        yes_bid_cents=yes_bid,
        yes_ask_cents=yes_ask,
        no_bid_cents=no_bid,
        no_ask_cents=no_ask,
        yes_depth_cc=200.0,
        no_depth_cc=200.0,
        fee_per_contract_cents=fee_cents,
        annualized_vol=vol,
        model_uncertainty=model_uncertainty,
        data_quality=data_quality,
        regime=regime,
        min_required_edge=min_edge,
        settlement_reference=settlement_reference,
    )


def test_compute_edge_invariants():
    """EdgeBreakdown must obey p_yes + p_no == 1 and the explicit net-edge formula."""
    bd = compute_edge(
        p_yes=0.60,
        selected_side="yes",
        entry_price=0.42,
        entry_fee=0.01,
        exit_cost_reserve=0.01,
        model_risk_reserve=0.05,
    )
    assert math.isclose(bd.p_yes + bd.p_no, 1.0, abs_tol=1e-9)
    assert math.isclose(bd.p_selected, 0.60, abs_tol=1e-9)
    assert math.isclose(bd.gross_edge, 0.60 - 0.42, abs_tol=1e-9)
    assert math.isclose(bd.net_edge, 0.60 - 0.42 - 0.01 - 0.01 - 0.05, abs_tol=1e-9)

    bd_no = compute_edge(
        p_yes=0.60,
        selected_side="no",
        entry_price=0.40,
        entry_fee=0.01,
        exit_cost_reserve=0.01,
        model_risk_reserve=0.05,
    )
    assert math.isclose(bd_no.p_selected, 0.40, abs_tol=1e-9)
    assert math.isclose(bd_no.p_opposite, 0.60, abs_tol=1e-9)
    assert math.isclose(bd_no.gross_edge, 0.40 - 0.40, abs_tol=1e-9)


def test_probability_sum_to_one():
    """TradeDecision must expose p_yes and p_no that sum to 1."""
    d = _make_decision()
    assert math.isclose(float(d.p_yes_calibrated) + float(d.p_no_calibrated), 1.0, abs_tol=1e-9)


def test_selects_yes_when_believed_and_cheap():
    """When p_yes > 0.5 and the YES ask is cheap, select YES."""
    # spot > strike -> p_yes > 0.5; YES ask 42 gives positive net edge.
    d = _make_decision(spot=100.5, strike=100.0, yes_ask=42.0, no_ask=58.0)
    assert d.selected_outcome == "yes"
    assert d.confidence_valid is True
    assert d.p_selected is not None
    assert float(d.p_selected) == float(d.p_yes_calibrated)
    assert d.edge_breakdown is not None
    assert math.isclose(
        float(d.gross_edge),
        float(d.p_selected) - float(d.yes_entry_vwap),
        abs_tol=1e-9,
    )


def test_selects_no_when_believed_and_cheap():
    """When p_no > 0.5 and the NO ask is cheap, select NO."""
    d = _make_decision(spot=99.5, strike=100.0, yes_ask=42.0, no_ask=58.0)
    assert d.selected_outcome == "no"
    assert d.p_selected is not None
    assert float(d.p_selected) == float(d.p_no_calibrated)


def test_rejects_cost_basis_override_yes(monkeypatch):
    """A cheap YES contract with p_yes <= 0.5 must be rejected."""
    # spot == strike -> p_yes == 0.5.  YES ask 20 is cheap, but the model
    # does not believe YES is > 50%.
    monkeypatch.setattr(
        "merid.prediction.trade_decision.TRADE_DECISION_MIN_P_SELECTED",
        Decimal("0.50"),
    )
    d = _make_decision(spot=100.0, strike=100.0, yes_ask=20.0, no_ask=80.0)
    assert d.selected_outcome is None
    assert d.no_trade_reason == "cost_basis_override_yes"


def test_rejects_cost_basis_override_no(monkeypatch):
    """A NO contract with p_no <= 0.5 and positive raw edge must be rejected."""
    monkeypatch.setattr(
        "merid.prediction.trade_decision.TRADE_DECISION_MIN_P_SELECTED",
        Decimal("0.50"),
    )
    # Use a NO ask above the tail-calibration floor so the test isolates the
    # cost-basis gate.  At p_no == 0.5 the model does not believe NO, so a
    # positive net edge must still be rejected.
    d = _make_decision(spot=100.0, strike=100.0, yes_ask=65.0, no_ask=35.0)
    assert d.selected_outcome is None
    assert d.no_trade_reason == "cost_basis_override_no"


def test_rejects_insufficient_edge():
    """A believed side with net edge below threshold must be rejected."""
    # Keep the NO ask above the tail-calibration floor so the YES edge-below
    # threshold path is the clean rejection reason (not a calibrated tie).
    d = _make_decision(
        spot=100.5,
        strike=100.0,
        yes_ask=95.0,  # very expensive, tiny edge
        no_ask=35.0,
        min_edge=0.10,
    )
    assert d.selected_outcome is None
    assert "edge" in (d.no_trade_reason or "")


def test_rejects_public_spot_fallback():
    """A trade using public spot instead of CF-RTI must have invalid confidence."""
    d = _make_decision(
        spot=100.5,
        strike=100.0,
        yes_ask=42.0,
        no_ask=58.0,
        settlement_reference="public_spot_fallback:null",
    )
    assert d.selected_outcome is None
    assert d.no_trade_reason == "invalid_confidence"
    assert d.confidence_valid is False
    assert "settlement_reference" in " ".join(d.confidence_reasons)


def test_rejects_stale_data():
    """Stale data must fail the data-state gate and block the trade."""
    d = _make_decision(spot=100.5, strike=100.0, yes_ask=42.0, data_quality="stale")
    assert d.selected_outcome is None
    assert d.no_trade_reason == "data_state_not_healthy"


def test_rejects_thin_depth():
    """Thin order-book depth must invalidate confidence."""
    d = compute_trade_decision(
        run_id="test",
        decision_id="test",
        ticker="KXBTC15M-26AUG190930-30",
        asset="BTC",
        spot_price=100.5,
        strike_price=100.0,
        seconds_to_expiry=900.0,
        yes_bid_cents=40.0,
        yes_ask_cents=42.0,
        no_bid_cents=58.0,
        no_ask_cents=60.0,
        yes_depth_cc=0.0,
        no_depth_cc=0.0,
        fee_per_contract_cents=1.0,
        data_quality="live",
        regime="normal",
        settlement_reference="cfb_rti_live",
    )
    assert d.confidence_valid is False
    assert "depth" in " ".join(d.confidence_reasons)


def test_expired_market_no_trade():
    """Expired contracts must be no_trade immediately."""
    d = compute_trade_decision(
        run_id="test",
        decision_id="test",
        ticker="KXBTC15M-26AUG190930-30",
        asset="BTC",
        spot_price=100.0,
        strike_price=100.0,
        seconds_to_expiry=0.0,
        yes_bid_cents=40.0,
        yes_ask_cents=42.0,
        no_bid_cents=58.0,
        no_ask_cents=60.0,
        settlement_reference="cfb_rti_live",
    )
    assert d.selected_outcome is None
    assert d.no_trade_reason == "expired_or_no_time"


def test_confidence_never_exact_default_sentinel():
    """A valid confidence should never be exactly the old 0.95 default sentinel."""
    d = _make_decision(spot=100.5, strike=100.0, yes_ask=42.0)
    assert d.confidence is not None
    assert float(d.confidence) != 0.95


def test_rejects_final_minute():
    """No entries are permitted inside the final-minute cutoff window."""
    os.environ["MERID_FINAL_MINUTE_CUTOFF_S"] = "60"
    d = _make_decision(spot=100.5, strike=100.0, seconds_to_expiry=30.0, yes_ask=42.0)
    assert d.selected_outcome is None
    assert d.no_trade_reason == "final_minute_entry_disabled"


def test_held_side_entry_price_floor_blocks_cheap_yes(monkeypatch):
    """A YES-held contract below the entry-price floor is rejected."""
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_TAIL_CALIBRATION_ENABLED", False
    )
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_MIN_HELD_PRICE_CENTS", 20.0
    )
    # Use a tight bid/ask spread so confidence is valid and the floor is the
    # only rejection reason.
    d = _make_decision(
        spot=100.5,
        strike=100.0,
        yes_bid=9.0,
        yes_ask=10.0,
        no_bid=89.0,
        no_ask=90.0,
    )
    assert d.selected_outcome is None
    assert "held_entry_price_below_floor" in (d.no_trade_reason or "")


def test_held_side_entry_price_floor_blocks_cheap_no(monkeypatch):
    """A NO-held contract below the entry-price floor is rejected."""
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_TAIL_CALIBRATION_ENABLED", False
    )
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_MIN_HELD_PRICE_CENTS", 20.0
    )
    d = _make_decision(
        spot=99.5,
        strike=100.0,
        yes_bid=89.0,
        yes_ask=90.0,
        no_bid=9.0,
        no_ask=10.0,
    )
    assert d.selected_outcome is None
    assert "held_entry_price_below_floor" in (d.no_trade_reason or "")


def test_tail_calibration_caps_cheap_yes_belief(monkeypatch):
    """The isotonic tail calibration caps p_yes for cheap YES contracts."""
    # Keep the floor low so the tail calibration itself is what blocks the trade.
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_MIN_HELD_PRICE_CENTS", 5.0
    )
    d = _make_decision(
        spot=100.5,
        strike=100.0,
        yes_bid=9.0,
        yes_ask=10.0,
        no_bid=89.0,
        no_ask=90.0,
    )
    assert d.selected_outcome is None
    # The raw model p_yes would be ~0.94, but the tail calibration forces it
    # close to the observed actual win rate in the 0-19c bucket (near 0).
    assert float(d.p_yes_calibrated) <= 0.10

