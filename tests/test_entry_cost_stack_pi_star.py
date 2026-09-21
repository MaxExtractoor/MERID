"""Corrected π* must be the cost-stack transform of the net-edge policy.

A candidate may be accepted if and only if conservative p_selected clears
the full executable cost stack plus the required net edge.  That probability
floor is π*, and it must never disagree with ``net_edge >= min_required_edge``.
"""
from __future__ import annotations

import math
from typing import Optional

import pytest

from merid.prediction.trade_decision import (
    EntryCostStack,
    _dual_tail_shrinkage_weight,
    compute_edge,
    compute_trade_decision,
    entry_cost_stack_from_breakdown,
)


def test_dual_tail_shrinkage_is_continuous_around_provisional_floor():
    below = _dual_tail_shrinkage_weight(0.199)
    at = _dual_tail_shrinkage_weight(0.200)
    above = _dual_tail_shrinkage_weight(0.201)
    assert 1.0 > below > at > above > 0.0
    assert abs(below - above) < 0.1


def test_pi_star_equals_full_cost_stack_plus_required_edge():
    stack = EntryCostStack(
        executable_price_prob=0.17,
        venue_fee_prob=0.0099,
        spread_slippage_prob=0.005,
        model_uncertainty_prob=0.030,
        required_net_edge_prob=0.025,
    )
    assert math.isclose(stack.pi_star, 0.2399, abs_tol=1e-12)


def test_pi_star_accept_equals_net_edge_after_required():
    stack = EntryCostStack(
        executable_price_prob=0.17,
        venue_fee_prob=0.01,
        spread_slippage_prob=0.01,
        model_uncertainty_prob=0.05,
        required_net_edge_prob=0.04,
    )
    p_selected = 0.363
    net_before = stack.net_edge_before_required(p_selected)
    net_after = stack.net_edge_after_required(p_selected)
    assert math.isclose(net_before, 0.363 - 0.17 - 0.01 - 0.01 - 0.05, abs_tol=1e-12)
    assert math.isclose(net_after, net_before - 0.04, abs_tol=1e-12)
    assert (p_selected >= stack.pi_star - 1e-9) == (net_after >= -1e-9)
    assert (p_selected >= stack.pi_star - 1e-9) == (net_before >= 0.04 - 1e-9)


def test_stack_from_breakdown_matches_compute_edge():
    bd = compute_edge(
        p_yes=0.637,
        selected_side="no",
        entry_price=0.17,
        entry_fee=0.01,
        exit_cost_reserve=0.01,
        model_risk_reserve=0.05,
    )
    stack = entry_cost_stack_from_breakdown(bd, required_net_edge=0.04)
    assert math.isclose(bd.p_selected, 0.363, abs_tol=1e-12)
    assert math.isclose(stack.net_edge_before_required(bd.p_selected), bd.net_edge, abs_tol=1e-12)
    assert math.isclose(
        stack.net_edge_after_required(bd.p_selected),
        bd.net_edge - 0.04,
        abs_tol=1e-12,
    )


def _make_decision(
    *,
    asset: str = "BTC",
    yes_bid: float = 83.0,
    yes_ask: float = 83.0,
    no_bid: float = 17.0,
    no_ask: float = 17.0,
    fee_cents: float = 1.0,
    min_edge: float = 0.02,
    model_uncertainty: float = 0.05,
    p_yes_model: Optional[float] = None,
):
    return compute_trade_decision(
        run_id="test_run",
        decision_id="test_decision",
        ticker="KXBTC15M-26SEP200000-15",
        asset=asset,
        spot_price=100.0,
        strike_price=100.0,
        seconds_to_expiry=600.0,
        yes_bid_cents=yes_bid,
        yes_ask_cents=yes_ask,
        no_bid_cents=no_bid,
        no_ask_cents=no_ask,
        yes_depth_cc=200.0,
        no_depth_cc=200.0,
        fee_per_contract_cents=fee_cents,
        annualized_vol=0.60,
        model_uncertainty=model_uncertainty,
        data_quality="live",
        regime="normal",
        min_required_edge=min_edge,
        settlement_reference="cfb_rti_live",
        p_yes_model=p_yes_model,
    )


def _patch_economics_isolation(monkeypatch) -> None:
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_TRADE_DECISION_ALLOW_HYBRID_P", True
    )
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_TAIL_CALIBRATION_ENABLED", False
    )
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_MIN_HELD_PRICE_CENTS", 0.0
    )
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_EV_GATE_AUTHORITATIVE", False
    )


@pytest.mark.parametrize(
    "asset,no_ask,p_no",
    [
        ("BTC", 17.0, 0.363),
        ("XRP", 12.0, 0.322),
        ("DOGE", 17.0, 0.366),
    ],
)
def test_cheap_no_does_not_fail_legacy_tier_pi_star(monkeypatch, asset, no_ask, p_no):
    """Logged 12–17¢ NO candidates must not be vetoed by held+fee+40¢ premium."""
    _patch_economics_isolation(monkeypatch)
    d = _make_decision(
        asset=asset,
        yes_bid=100.0 - no_ask,
        yes_ask=100.0 - no_ask,
        no_bid=no_ask,
        no_ask=no_ask,
        p_yes_model=1.0 - p_no,
        model_uncertainty=0.03,
    )
    reason = d.no_trade_reason or ""
    assert "p_selected_below_pi_star" not in reason
    assert d.indicators.get("pi_star") is not None
    stack_pi = float(d.indicators["pi_star"])
    # Corrected π* is an economic hurdle near price+costs+min_edge, not ~0.57.
    assert stack_pi < 0.40


def test_corrected_pi_star_is_identity_with_net_edge_on_accept(monkeypatch):
    _patch_economics_isolation(monkeypatch)
    d = _make_decision(
        yes_bid=83.0,
        yes_ask=83.0,
        no_bid=17.0,
        no_ask=17.0,
        p_yes_model=0.637,
        model_uncertainty=0.03,
    )
    assert d.selected_outcome == "no"
    assert d.edge_breakdown is not None
    p_sel = float(d.p_selected)
    pi_star = float(d.indicators["pi_star"])
    min_edge = float(d.indicators["no_min_edge"])
    net_after = float(d.indicators["net_edge_after_required"])
    assert p_sel >= pi_star - 1e-9
    assert float(d.net_edge) >= min_edge - 1e-9
    assert math.isclose(net_after, p_sel - pi_star, abs_tol=1e-9)
    assert math.isclose(
        abs(float(d.indicators["pi_star_identity_difference"])),
        0.0,
        abs_tol=1e-9,
    )


def test_eth_near_fair_no_still_fails_required_net_edge(monkeypatch):
    _patch_economics_isolation(monkeypatch)
    d = _make_decision(
        asset="ETH",
        yes_bid=55.0,
        yes_ask=55.0,
        no_bid=45.0,
        no_ask=45.0,
        p_yes_model=0.516,
        model_uncertainty=0.05,
        min_edge=0.05,
    )
    assert d.selected_outcome is None
    assert "p_selected_below_pi_star" not in (d.no_trade_reason or "")
    assert "edge" in (d.no_trade_reason or "")


def test_price_floor_rejection_records_shadow_policy(monkeypatch):
    _patch_economics_isolation(monkeypatch)
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_MIN_HELD_PRICE_CENTS", 35.0
    )
    d = _make_decision(
        no_bid=29.0,
        no_ask=29.0,
        p_yes_model=0.58,
        model_uncertainty=0.03,
    )
    assert d.selected_outcome is None
    assert d.no_trade_reason.startswith("held_entry_price_below_floor")
    assert d.indicators["terminal_decision"] == "REJECT"
    assert d.indicators["terminal_reason"].startswith("held_entry_price_below_floor")
    shadow = d.indicators["shadow_policy"]
    assert shadow["mode"] == "shadow_compare"
    assert shadow["price_cents"] == 29.0
    assert shadow["decision"] == "REJECT"
    assert shadow["terminal_reason"] == "shadow_required_net_edge"


def test_shadow_policy_can_admit_low_price_side_without_live_admission(monkeypatch):
    _patch_economics_isolation(monkeypatch)
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_MIN_HELD_PRICE_CENTS", 35.0
    )
    d = _make_decision(
        no_bid=29.0,
        no_ask=29.0,
        p_yes_model=0.15,
        model_uncertainty=0.01,
    )
    assert d.selected_outcome is None
    shadow = d.indicators["shadow_policy"]
    assert shadow["decision"] == "ACCEPT"
    assert shadow["terminal_reason"] is None
    assert d.no_trade_reason.startswith("held_entry_price_below_floor")


def test_low_price_canary_admits_only_allowlisted_no_side(monkeypatch):
    _patch_economics_isolation(monkeypatch)
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_MIN_HELD_PRICE_CENTS", 35.0
    )
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_ENTRY_POLICY_MODE", "canary"
    )
    d = _make_decision(
        asset="BTC",
        no_bid=29.0,
        no_ask=29.0,
        p_yes_model=0.55,
        model_uncertainty=0.01,
    )
    assert d.selected_outcome == "no"
    assert d.approved_size_cc == 100
    assert d.indicators["canary_policy"]["decision"] == "ACCEPT"
    assert d.indicators["terminal_reason"] == "low_price_canary_shadow_accept"


def test_low_price_canary_rejects_unallowlisted_asset(monkeypatch):
    _patch_economics_isolation(monkeypatch)
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_MIN_HELD_PRICE_CENTS", 35.0
    )
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_ENTRY_POLICY_MODE", "canary"
    )
    d = _make_decision(
        asset="ETH",
        no_bid=29.0,
        no_ask=29.0,
        p_yes_model=0.55,
        model_uncertainty=0.01,
    )
    assert d.selected_outcome is None
    assert d.no_trade_reason.startswith("held_entry_price_below_floor")
    assert "canary_policy" not in d.indicators
