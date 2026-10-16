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
import merid.prediction.trade_decision as _td
from merid.risk.probability.calibration_diagnostics import (
    brier_score,
    expected_calibration_error,
    reliability_curve,
    calibration_summary,
)


@pytest.fixture(autouse=True)
def _disable_market_anchor(monkeypatch):
    """These tests exercise decision mechanics (invariants, gates, tail caps);

    the market-anchor shrinkage is covered separately in
    tests/test_entry_execution_hardening.py.  Disabling it keeps each test
    focused on the mechanism it names.
    """
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MIN_W", 0.0)
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MAX_W", 0.0)
    # 2026-09-25: keep tail-only calibration scope here — these tests exercise
    # selection/gate mechanics in price cells the full-range evidence floor
    # now legitimately blocks.  Full-range coverage lives in
    # tests/test_calibration_full_range.py.
    monkeypatch.setattr(_td, "MERID_CALIBRATION_CAP_FULL_RANGE", False)


def _make_decision(
    *,
    spot: float = 100.0,
    strike: float = 100.0,
    seconds_to_expiry: float = 400.0,
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
    p_yes_model: Optional[float] = None,
    p_no_model: Optional[float] = None,
    directional_regime=None,
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
        p_yes_model=p_yes_model,
        p_no_model=p_no_model,
        directional_regime=directional_regime,
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
    # The dense per-side tail fit (n~70K obs) prices a 20c YES contract at a
    # ~19-24% observed win rate, so the edge gate now rejects before the
    # cost-basis min-p gate is reached; both are valid rejections of a
    # cheap sub-50% YES.
    assert d.no_trade_reason in (
        "cost_basis_override_yes",
        "yes_edge_below_threshold",
        # 2026-09-30: economics-first ordering reports a non-positive-EV
        # side honestly instead of attributing it to the evidence policy.
        "no_positive_executable_edge",
    )


def test_rejects_cost_basis_override_no(monkeypatch):
    """A NO contract with p_no <= 0.5 and positive raw edge must be rejected."""
    monkeypatch.setattr(
        "merid.prediction.trade_decision.TRADE_DECISION_MIN_P_SELECTED",
        Decimal("0.50"),
    )
    # Use a NO ask above the tail-calibration floor so the test isolates the
    # cost-basis gate.  With the drift-corrected d2, ATM gives p_no slightly
    # above 0.5; spot just above strike keeps p_no <= 0.5 (model does not
    # believe NO) while the 36c ask still yields positive net edge, so the
    # cost-basis gate is the rejection reason.
    d = _make_decision(spot=100.009, strike=100.0, yes_ask=65.0, no_ask=36.0)
    assert d.selected_outcome is None
    # 2026-10-15: the counter-model directional gate now owns the p<0.5
    # rejection class when the cost-basis floor is EPC-exempted or cleared —
    # "claimed-positive edge on the model's underdog side" is vetoed as a
    # directional invariant violation, which is the more informative label.
    assert d.no_trade_reason in (
        "cost_basis_override_no",
        "counter_model_below_p_floor_no",
        "counter_model_edge_below_premium_no",
    )


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
    # The 9/10c YES quotes put the market mid at ~9.5c (lean -40.5c), which the
    # 2026-09-27 market-lean fade gate would block before the price floor runs.
    # Neutralize it here so this test isolates the held-price floor.
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_FADE_BLOCK_MIN_LEAN_CENTS", 1000.0
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
    # Same fade-gate interference as the YES case above: 90c YES mid implies a
    # +40c lean that would trigger market_fade_blocked_no first.
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_FADE_BLOCK_MIN_LEAN_CENTS", 1000.0
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
    # to the observed actual win rate + 5% buffer.  The dense refit (70K obs)
    # measures ~9.7-12% WR at ~10c -> cap ~0.15, still crushing the model belief.
    assert float(d.p_yes_calibrated) <= 0.20


def test_real_no_tail_cap_applies_moderate_raw_p_no(monkeypatch):
    """With a real per-side NO curve (2026-09-25 refit), a moderate raw p_no on
    a 5c NO ask is capped to the observed NO-held win rate + buffer.

    The 39K-observation fit says a 5c NO-held contract wins ~0% of the time, so
    the cap applies directly — no dual shrinkage softening needed since the
    curve is no longer a YES mirror.
    """
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_MIN_HELD_PRICE_CENTS", 0.0
    )
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_CHEAP_TAIL_P_EXCEPTION", 0.0
    )
    # Spot ~0.18% above strike gives a moderate raw p_no (~0.25) for a 5c NO ask.
    d = _make_decision(
        spot=100.18,
        strike=100.0,
        yes_bid=90.0,
        yes_ask=95.0,
        no_bid=1.0,
        no_ask=5.0,
    )
    _ind = d.indicators or {}
    assert _ind.get("tail_cap_no_reason") == "real_curve"
    assert _ind.get("tail_calibration_no_weight") == 0.0
    assert _ind.get("tail_calibration_no_applied") is True
    # Observed WR at 5c NO ≈ 0% + 5% buffer -> cap ≈ 0.05 (min-p floor).
    assert float(d.p_no_calibrated) <= 0.10


def test_real_no_tail_cap_applies_cheap_raw_p_no(monkeypatch):
    """A cheap raw p_no on the real NO curve is capped to the observed tail."""
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_MIN_HELD_PRICE_CENTS", 0.0
    )
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_CHEAP_TAIL_P_EXCEPTION", 0.0
    )
    # Spot far above strike makes the Bachelier model itself believe NO is very
    # unlikely, so p_no is in the cheap-tail region and the cap applies.
    d = _make_decision(
        spot=102.0,
        strike=100.0,
        yes_bid=90.0,
        yes_ask=95.0,
        no_bid=1.0,
        no_ask=5.0,
    )
    _ind = d.indicators or {}
    assert _ind.get("tail_cap_no_reason") == "real_curve"
    assert _ind.get("tail_calibration_no_weight") == 0.0
    # The raw p_no is already at/below the observed tail cap, so the cap need
    # not move it — p_no stays near the 0.05 floor.
    assert float(d.p_no_calibrated) <= 0.10


def test_calibration_diagnostics_perfect_calibration():
    """A perfectly calibrated model has zero ECE and Brier equal to p(1-p)."""
    # 100 samples with p=0.2 where exactly 20% win -> perfectly calibrated.
    probs = [0.2] * 100
    outcomes = [1] * 20 + [0] * 80
    summary = calibration_summary(probs, outcomes, n_bins=5)
    assert math.isclose(summary["expected_calibration_error"], 0.0, abs_tol=1e-9)
    assert math.isclose(summary["brier_score"], 0.2 * 0.8, rel_tol=1e-6)


def test_calibration_diagnostics_uncalibrated_yes_no():
    """A model that is underconfident on YES and overconfident on NO shows
    ECE on both sides.
    """
    # YES side: all predictions 0.45 but true rate 0.60 -> ECE 0.15.
    yes_probs = [0.45] * 100
    yes_outcomes = [1] * 60 + [0] * 40
    yes_summary = calibration_summary(yes_probs, yes_outcomes, n_bins=1, label="yes")
    assert math.isclose(yes_summary["expected_calibration_error"], 0.15, abs_tol=1e-9)

    # NO side: all predictions 0.70 but true rate 0.40 -> ECE 0.30.
    no_probs = [0.70] * 100
    no_outcomes = [1] * 40 + [0] * 60
    no_summary = calibration_summary(no_probs, no_outcomes, n_bins=1, label="no")
    assert math.isclose(no_summary["expected_calibration_error"], 0.30, abs_tol=1e-9)


# 4c LCB(EV_net) canary threshold tests.

def test_canary_selects_when_lcb_clears_4c(monkeypatch):
    """A side whose LCB clears the conditional 4c floor is selected in canary mode."""
    monkeypatch.setattr("merid.prediction.trade_decision.MERID_CANARY_4C_LCB", True)
    monkeypatch.setattr("merid.prediction.trade_decision.MERID_TRADE_DECISION_ALLOW_HYBRID_P", True)
    monkeypatch.setenv("MERID_ANNUALIZED_VOL_BTC", "0.60")
    d = _make_decision(
        min_edge=0.02,
        p_yes_model=0.60,
        yes_ask=42.0,
        no_ask=58.0,
        model_uncertainty=0.02,
    )
    assert d.selected_outcome == "yes"
    shadow = d.indicators["shadow_cohort"]
    assert shadow["would_enter_at_canary"] is True
    assert shadow["would_enter_at_prior_threshold"] is True
    assert int(d.approved_size_cc) == 100


def test_canary_blocks_when_lcb_below_4c(monkeypatch):
    """A side that clears the prior threshold but not the 4c LCB floor is downgraded."""
    monkeypatch.setattr("merid.prediction.trade_decision.MERID_CANARY_4C_LCB", True)
    monkeypatch.setattr("merid.prediction.trade_decision.MERID_TRADE_DECISION_ALLOW_HYBRID_P", True)
    monkeypatch.setenv("MERID_ANNUALIZED_VOL_BTC", "0.60")
    d = _make_decision(
        min_edge=0.02,
        p_yes_model=0.55,
        yes_ask=42.0,
        no_ask=58.0,
        model_uncertainty=0.05,
    )
    assert d.selected_outcome is None
    assert d.no_trade_reason == "lcb_below_canary_threshold"
    shadow = d.indicators["shadow_cohort"]
    assert shadow["would_enter_at_canary"] is False
    assert shadow["would_enter_at_prior_threshold"] is True
    assert shadow["delta_reason"] == "lcb_below_canary_threshold"


def test_canary_blocks_unvalidated_vol_source(monkeypatch):
    """The canary must reject any entry whose volatility source is the unvalidated fallback."""
    monkeypatch.setattr("merid.prediction.trade_decision.MERID_CANARY_4C_LCB", True)
    monkeypatch.setattr("merid.prediction.trade_decision.MERID_TRADE_DECISION_ALLOW_HYBRID_P", True)
    # No MERID_ANNUALIZED_VOL_BTC env override -> _resolve_annualized_vol falls to "default".
    d = _make_decision(
        min_edge=0.02,
        p_yes_model=0.60,
        yes_ask=42.0,
        no_ask=58.0,
    )
    assert d.selected_outcome is None
    shadow = d.indicators["shadow_cohort"]
    assert shadow["would_enter_at_canary"] is False
    assert shadow["yes_threshold_cents"] == "inf"


def test_canary_excludes_tail_prices(monkeypatch):
    """The canary must exclude the 0-9c and 76-99c tail buckets."""
    monkeypatch.setattr("merid.prediction.trade_decision.MERID_CANARY_4C_LCB", True)
    monkeypatch.setattr("merid.prediction.trade_decision.MERID_TRADE_DECISION_ALLOW_HYBRID_P", True)
    monkeypatch.setenv("MERID_ANNUALIZED_VOL_BTC", "0.60")
    d = _make_decision(
        min_edge=0.02,
        p_yes_model=0.95,
        yes_ask=8.0,
        no_ask=92.0,
    )
    assert d.selected_outcome is None
    shadow = d.indicators["shadow_cohort"]
    assert shadow["would_enter_at_canary"] is False
    assert shadow["yes_threshold_cents"] == "inf"


def test_canary_off_leaves_decision_unchanged(monkeypatch):
    """When the canary flag is disabled, compute_trade_decision ignores it entirely."""
    monkeypatch.setattr("merid.prediction.trade_decision.MERID_CANARY_4C_LCB", False)
    monkeypatch.setattr("merid.prediction.trade_decision.MERID_TRADE_DECISION_ALLOW_HYBRID_P", True)
    d = _make_decision(
        min_edge=0.02,
        p_yes_model=0.60,
        yes_ask=42.0,
        no_ask=58.0,
        model_uncertainty=0.02,
    )
    assert d.selected_outcome == "yes"
    assert "shadow_cohort" not in d.indicators


# ---------------------------------------------------------------------------
# Counter-model directional gate (2026-10-15).
#
# Last-96 fill alignment audit: argmax(net_edge) selected the model's own
# underdog side in 14/96 entries; 11 were model-right/exec-wrong (~-$5.5).
# The gate vetoes a selected side whose calibrated p_selected < 0.5 unless
# its effective edge clears the counter-model premium; p < 0.45 is a hard
# floor regardless of claimed edge.
# ---------------------------------------------------------------------------


def test_counter_model_no_below_hard_floor_vetoed(monkeypatch):
    """Model says UP (p_yes=0.62) but NO@28c looks +10c cheap -> veto.

    Reproduces the ETH-1315 loss shape: p_yes=0.616, NO bought at 33c on a
    phantom bid-basis edge, market resolved YES.
    """
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_TRADE_DECISION_ALLOW_HYBRID_P", True
    )
    d = _make_decision(
        p_yes_model=0.62,
        yes_bid=66.0,
        yes_ask=68.0,
        no_bid=27.0,
        no_ask=28.0,
        min_edge=0.02,
        model_uncertainty=0.02,
    )
    assert d.selected_outcome is None
    assert d.indicators.get("directional_veto_no") == "counter_model_below_p_floor"


def test_counter_model_no_below_premium_vetoed(monkeypatch):
    """Premium band: p_no in [0.45, 0.5) with ordinary edge -> veto."""
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_TRADE_DECISION_ALLOW_HYBRID_P", True
    )
    d = _make_decision(
        p_yes_model=0.54,          # p_no = 0.46 -> premium band
        yes_bid=50.0,
        yes_ask=54.0,              # no YES edge
        no_bid=37.0,
        no_ask=40.0,               # ~6c gross edge — clears lane bound, not premium
        min_edge=0.02,
        model_uncertainty=0.02,
    )
    assert d.selected_outcome is None
    veto = d.indicators.get("directional_veto_no")
    assert veto is not None
    assert veto.startswith("counter_model_")


def test_counter_model_underdog_with_large_edge_can_pass(monkeypatch):
    """Premium-band underdog with >=8c effective edge clears the dir gate.

    Tail calibration is disabled so the asserted p stays in the [0.45, 0.5)
    premium band; other gates may still veto — the assertion is only that
    the directional gate itself is not the blocker.
    """
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_TRADE_DECISION_ALLOW_HYBRID_P", True
    )
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_TAIL_CALIBRATION_ENABLED", False
    )
    d = _make_decision(
        p_yes_model=0.53,          # p_no = 0.47 -> premium band
        yes_bid=55.0,
        yes_ask=60.0,
        no_bid=27.0,
        no_ask=30.0,               # ~17c gross edge — clears the 8c premium
        min_edge=0.02,             #   even after measured giveback/shortfall
        model_uncertainty=0.02,    #   reserves tighten the effective edge
    )
    assert d.indicators.get("directional_veto_no") is None


def test_counter_model_gate_disabled_restores_argmax(monkeypatch):
    """MERID_COUNTER_MODEL_GATE=0 restores pure net-edge argmax."""
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_COUNTER_MODEL_GATE", False
    )
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_TRADE_DECISION_ALLOW_HYBRID_P", True
    )
    d = _make_decision(
        p_yes_model=0.62,
        yes_bid=66.0,
        yes_ask=68.0,
        no_bid=27.0,
        no_ask=28.0,
        min_edge=0.02,
        model_uncertainty=0.02,
    )
    assert d.indicators.get("directional_veto_no") is None
    reason = d.no_trade_reason or ""
    assert not reason.startswith("counter_model_")


def test_model_aligned_side_unaffected(monkeypatch):
    """p_selected >= 0.5 sides pass the directional gate unconditionally."""
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_TRADE_DECISION_ALLOW_HYBRID_P", True
    )
    d = _make_decision(
        p_yes_model=0.62,
        yes_bid=60.0,
        yes_ask=62.0,              # YES is favorite-priced; edge ~0
        no_bid=30.0,
        no_ask=38.0,               # NO underdog with p_no=0.38 -> vetoed
        min_edge=0.02,
        model_uncertainty=0.02,
    )
    assert d.indicators.get("directional_veto_yes") is None


# ---------------------------------------------------------------------------
# Per-side counter-regime mode (2026-10-15, FIX 8).
#
# Veto counterfactual on 278k settled rejected candidates measured the two
# countertrend directions asymmetrically: countertrend YES into a confirmed
# selloff ran -3.32c/tr (veto is the honest policy) while countertrend NO
# into a rally forfeited +5.48c/tr (bounded penalty admission is honest).
# MERID_COUNTER_REGIME_MODE_{YES,NO} let each side pick veto vs penalty.
# ---------------------------------------------------------------------------


def _selloff_regime():
    from merid.prediction.directional_regime import DirectionalRegime

    return DirectionalRegime(
        label="SELL_OFF_CONFIRMED",
        breadth60_pos=0,
        breadth60_total=5,
        btc_r60=-0.004,
        asset_r60={"BTC": -0.004},
        ts=0.0,
        reason="test",
    )


def _selloff_yes_candidate(directional_regime):
    """YES candidate with a claimed edge, buying into a confirmed selloff.

    spot < strike -> p_yes < 0.5 for a driftless model, so give the model a
    modest YES lean via p_yes_model and price the ask below it.  Not deep-ITM
    (|z| small), so regime_entry_block fires for side=yes.
    """
    return _make_decision(
        p_yes_model=0.60,
        yes_bid=48.0,
        yes_ask=50.0,              # ~10c gross edge — clears the 4c penalty
        no_bid=45.0,
        no_ask=50.0,
        min_edge=0.02,
        model_uncertainty=0.02,
        directional_regime=directional_regime,
    )


def test_counter_regime_yes_veto_mode_blocks_selloff_catch(monkeypatch):
    """MODE_YES=veto makes the YES floor irrelevant — the block is
    categorical regardless of claimed edge."""
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_TRADE_DECISION_ALLOW_HYBRID_P", True
    )
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_COUNTER_REGIME_MODE_YES", "veto"
    )
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_COUNTER_REGIME_MODE_NO", "penalty"
    )
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_COUNTER_REGIME_ALLOW_DEGRADED", True
    )
    d = _selloff_yes_candidate(_selloff_regime())
    ind = d.indicators or {}
    assert ind.get("yes_counter_regime_admitted") is False
    # The YES side may still lose to another gate; the assertion is that
    # the regime block was NOT penalty-admitted.
    assert d.selected_outcome != "yes"


def test_counter_regime_yes_penalty_mode_admits_large_edge(monkeypatch):
    """Shared penalty mode still admits the same candidate at >=4c eff edge."""
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_TRADE_DECISION_ALLOW_HYBRID_P", True
    )
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_COUNTER_REGIME_MODE_YES", "penalty"
    )
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_COUNTER_REGIME_ALLOW_DEGRADED", True
    )
    d = _selloff_yes_candidate(_selloff_regime())
    ind = d.indicators or {}
    assert ind.get("yes_counter_regime_admitted") is True
    # The counter-model NO underdog is still vetoed even though YES is the
    # model-aligned side here.
    assert d.indicators.get("directional_veto_no") is not None


def test_pi_star_uses_exact_fractional_fee(monkeypatch):
    """The canonical cost stack preserves fractional fee economics."""
    calls = []
    monkeypatch.setattr(
        "merid.prediction.trade_decision.log_rejected_candidate",
        lambda **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_TRADE_DECISION_ALLOW_HYBRID_P", True
    )

    # 40c NO contract, maker fee = 0.0175 * 1 * 0.40 * 0.60 * 100 = 0.42c.
    fee_cents = 0.42
    # p_no = 0.5041 clears the canonical cost stack and required edge.
    d = _make_decision(
        min_edge=0.02,
        p_yes_model=0.4959,
        yes_bid=59.0,
        yes_ask=60.0,
        no_bid=39.0,
        no_ask=40.0,
        fee_cents=fee_cents,
        data_quality="live",
        regime="normal",
    )
    assert d.selected_outcome == "no"
    assert d.indicators["entry_cost_stack"]["venue_fee_prob"] == fee_cents / 100.0
    assert math.isclose(
        float(d.indicators["pi_star_identity_difference"]),
        0.0,
        abs_tol=1e-9,
    )
    assert not calls

