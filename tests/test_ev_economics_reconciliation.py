"""EV reconciliation: one authoritative economics stack, attributable vetoes.

Contract (settlement-horizon binary EV, per contract, probability units):

    net_edge = p_selected - a - (entry_fee + exit_reserve
                                 + model_risk_reserve + adverse_selection)
    pi*      = a + all costs + required_margin
    surplus  = net_edge - required_margin   (vs the *enforced* bound)

Every consumer — the margin gate, the p_selected cost-basis floor, the pi*
hurdle, the authoritative executable-cost EV gate, and the audit side_ev
rows — must read the same components from the same EdgeBreakdown.  The
adverse-selection reserve is a resting-fill (maker) cost and must not be
charged to ask-priced (taker) candidates.

Regression target: the 2026-10-02..06 cohort where ``passed_edge_gate=1``
side_ev rows were vetoed by ``net_ev_below_min_dollar`` because the EV gate
recomputed a measured ASR that the recorded EdgeBreakdown never carried
(median hidden charge ~2.5c; 70% of the vetoes were ask-priced entries).
"""
from __future__ import annotations

import math
from decimal import Decimal
from typing import Optional

import pytest

from merid.prediction.trade_decision import (
    EntryCostStack,
    _min_p_for_side,
    compute_edge,
    compute_trade_decision,
    entry_cost_stack_from_breakdown,
)
from merid.risk.executable_cost_ev_gate import (
    EVInput,
    evaluate_executable_cost_ev,
)


# ── helpers ──────────────────────────────────────────────────────────


def _patch_economics_isolation(monkeypatch) -> None:
    """Same isolation the pi_star suite uses: kill market-lean gates."""
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
        "merid.prediction.trade_decision.MERID_FADE_BLOCK_MIN_LEAN_CENTS", 99.0
    )
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_MARKET_ANCHOR_MIN_W", 0.0
    )
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_MARKET_ANCHOR_MAX_W", 0.0
    )


def _make_decision(
    monkeypatch,
    *,
    asset: str = "BTC",
    yes_bid: float = 83.0,
    yes_ask: float = 83.0,
    no_bid: float = 17.0,
    no_ask: float = 17.0,
    fee_cents: float = 1.0,
    min_edge: float = 0.02,
    model_uncertainty: float = 0.05,
    p_yes_model: Optional[float] = 0.637,
    entry_price_basis: str = "ask",
    adverse_selection_reserve: float = 0.0,
    route: str = "taker",
    measured_asr_cents: Optional[float] = None,
    seconds_to_expiry: float = 600.0,
):
    """Decision under the shared isolation patch; EV gate stays authoritative."""
    _patch_economics_isolation(monkeypatch)
    if measured_asr_cents is not None:
        monkeypatch.setattr(
            "merid.prediction.current_build_provisional.adverse_selection_reserve_cents",
            lambda *a, **k: measured_asr_cents,
        )
    return compute_trade_decision(
        run_id="test_run",
        decision_id="test_decision",
        ticker="KXBTC15M-26SEP200000-15",
        asset=asset,
        spot_price=100.0,
        strike_price=100.0,
        seconds_to_expiry=seconds_to_expiry,
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
        entry_price_basis=entry_price_basis,
        adverse_selection_reserve=adverse_selection_reserve,
        route=route,
    )


# ── identity: pi* == net_edge - required on both sides ───────────────


@pytest.mark.parametrize("side", ["yes", "no"])
@pytest.mark.parametrize("asr", [0.0, 0.025])
def test_pi_star_identity_holds_with_adverse_selection(side, asr):
    """p - pi* must equal net_edge - required for YES and NO, ASR included."""
    bd = compute_edge(
        p_yes=0.637,
        selected_side=side,
        entry_price=0.17 if side == "no" else 0.60,
        entry_fee=0.01,
        exit_cost_reserve=0.01,
        model_risk_reserve=0.05,
        adverse_selection_reserve=asr,
    )
    stack = entry_cost_stack_from_breakdown(bd, required_net_edge=0.04)
    assert math.isclose(
        stack.net_edge_before_required(bd.p_selected), bd.net_edge,
        abs_tol=1e-12,
    )
    assert math.isclose(
        stack.net_edge_after_required(bd.p_selected),
        bd.net_edge - 0.04,
        abs_tol=1e-12,
    )
    # pi* = price + fee + exit + unc + asr + required — every cost once.
    assert math.isclose(
        stack.pi_star,
        bd.executable_entry_price
        + bd.entry_fee
        + bd.exit_cost_reserve
        + bd.model_risk_reserve
        + bd.adverse_selection_reserve
        + 0.04,
        abs_tol=1e-12,
    )


def test_min_p_floor_is_all_in_including_adverse_selection():
    """The positive-EV floor must equal the EV gate's strict-positive bound."""
    bd = compute_edge(
        p_yes=0.637,
        selected_side="no",
        entry_price=0.17,
        entry_fee=0.01,
        exit_cost_reserve=0.01,
        model_risk_reserve=0.05,
        adverse_selection_reserve=0.02,
    )
    floor = _min_p_for_side(bd, floor=0.0)
    expected = 0.17 + 0.01 + 0.01 + 0.05 + 0.02
    assert math.isclose(floor, expected, abs_tol=1e-12)
    # p just above the all-in basis has strictly positive net edge.
    assert bd.p_selected > floor or bd.net_edge <= 0.0  # sanity fixture
    bd_hi = compute_edge(
        p_yes=1.0 - (expected + 0.001),
        selected_side="no",
        entry_price=0.17,
        entry_fee=0.01,
        exit_cost_reserve=0.01,
        model_risk_reserve=0.05,
        adverse_selection_reserve=0.02,
    )
    assert bd_hi.p_selected > floor
    assert bd_hi.net_edge > 0.0
    # and just below it the net edge is strictly non-positive.
    bd_lo = compute_edge(
        p_yes=1.0 - (expected - 0.001),
        selected_side="no",
        entry_price=0.17,
        entry_fee=0.01,
        exit_cost_reserve=0.01,
        model_risk_reserve=0.05,
        adverse_selection_reserve=0.02,
    )
    assert bd_lo.p_selected < floor
    assert bd_lo.net_edge < 0.0


# ── EV gate: same components in, identical verdict out ───────────────


def _gate_input_from_breakdown(bd, qty_cc: int) -> EVInput:
    return EVInput(
        p_model=Decimal(str(bd.p_selected)),
        p_exec=Decimal(str(bd.executable_entry_price)),
        qty_cc=qty_cc,
        entry_fee_per_contract=Decimal(str(bd.entry_fee)),
        expected_exit_cost_per_contract=Decimal(str(bd.exit_cost_reserve)),
        adverse_selection_reserve_per_contract=Decimal(
            str(bd.adverse_selection_reserve)
        ),
        uncertainty_reserve_per_contract=Decimal(str(bd.model_risk_reserve)),
        ticker="KXT",
        decision_id="t",
    )


@pytest.mark.parametrize("qty_cc", [100, 300])
def test_ev_gate_net_ev_equals_breakdown_net_edge_times_count(qty_cc):
    """Authoritative gate must reproduce the breakdown's per-contract EV."""
    bd = compute_edge(
        p_yes=0.637,
        selected_side="no",
        entry_price=0.17,
        entry_fee=0.01,
        exit_cost_reserve=0.01,
        model_risk_reserve=0.05,
        adverse_selection_reserve=0.02,
    )
    res = evaluate_executable_cost_ev(_gate_input_from_breakdown(bd, qty_cc))
    count = Decimal(qty_cc) / Decimal("100")
    expected = Decimal(str(bd.net_edge)) * count
    assert abs(res.net_ev - expected) < Decimal("0.0001")
    assert res.allowed is (bd.net_edge > 0.0)


def test_ev_gate_boundary_is_strict_zero():
    """net_ev == 0 exactly must reject; +1e-4 must pass (strict positivity)."""
    bd = compute_edge(
        p_yes=0.637, selected_side="no", entry_price=0.17,
        entry_fee=0.01, exit_cost_reserve=0.01,
        model_risk_reserve=0.05, adverse_selection_reserve=0.02,
    )
    # p_selected = 0.363, all-in cost = 0.26 -> net_edge = 0.103.  Push the
    # price so net_ev lands exactly on zero.
    inp = _gate_input_from_breakdown(bd, 100)
    inp.p_exec = inp.p_model - (
        inp.entry_fee_per_contract
        + inp.expected_exit_cost_per_contract
        + inp.adverse_selection_reserve_per_contract
        + inp.uncertainty_reserve_per_contract
    )
    res = evaluate_executable_cost_ev(inp)
    assert res.net_ev == Decimal("0.0000") or res.net_ev == Decimal("0")
    assert res.allowed is False
    assert any("net_ev_below_min_dollar" in r for r in res.reasons)

    inp.p_exec = inp.p_exec - Decimal("0.0001")
    res2 = evaluate_executable_cost_ev(inp)
    assert res2.net_ev > 0
    assert res2.allowed is True


@pytest.mark.parametrize("qty_cc", [100, 300])
def test_ev_gate_verdict_is_quantity_invariant_at_zero_min_dollar(qty_cc):
    """qty scales gross and costs together; sign cannot flip at min_ev=0."""
    bd = compute_edge(
        p_yes=0.52, selected_side="yes", entry_price=0.50,
        entry_fee=0.01, exit_cost_reserve=0.005,
        model_risk_reserve=0.02, adverse_selection_reserve=0.0,
    )
    a = evaluate_executable_cost_ev(_gate_input_from_breakdown(bd, qty_cc))
    b = evaluate_executable_cost_ev(_gate_input_from_breakdown(bd, 100))
    assert a.allowed == b.allowed
    assert abs(a.net_ev - b.net_ev * (Decimal(qty_cc) / 100)) < Decimal("0.0001")


def test_ev_gate_stale_quote_is_attributable_revalidation_verdict():
    """A stale re-quote produces a named verdict, not a silent sign flip."""
    inp = EVInput(
        p_model=Decimal("0.60"), p_exec=Decimal("0.50"), qty_cc=300,
        entry_fee_per_contract=Decimal("0.01"),
        quote_age_ms=60_000, quote_stale_threshold_ms=10_000,
    )
    res = evaluate_executable_cost_ev(inp)
    assert res.allowed is False
    assert res.reasons and res.reasons[0].startswith("stale_executable_price")


# ── route separation: measured ASR is a maker-route cost ─────────────


@pytest.mark.parametrize("asset", ["BTC", "ETH", "SOL", "XRP", "DOGE"])
def test_taker_basis_never_carries_measured_asr(monkeypatch, asset):
    """Ask-priced candidates must not be charged the post-only pick-off
    reserve — this was the hidden veto on the recorded-pass cohort."""
    d = _make_decision(
        monkeypatch,
        asset=asset,
        entry_price_basis="ask",
        route="taker",
        measured_asr_cents=4.0,  # would be vetoed if wrongly charged
    )
    assert d.no_edge_breakdown is not None
    assert float(d.no_edge_breakdown.adverse_selection_reserve) == 0.0
    # The decision-level scalar mirrors the selected side's breakdown.
    assert float(d.adverse_selection_reserve or 0) == 0.0


def test_maker_basis_charges_max_of_prior_and_measured(monkeypatch):
    """Bid-priced lanes charge max(caller prior, measured) — never relax."""
    # measured (4c) above the 2c lane prior -> measured wins.
    d = _make_decision(
        monkeypatch,
        entry_price_basis="bid",
        route="maker_bid",
        adverse_selection_reserve=0.02,
        measured_asr_cents=4.0,
    )
    assert math.isclose(
        float(d.no_edge_breakdown.adverse_selection_reserve), 0.04,
        abs_tol=1e-12,
    )
    # measured below the prior -> prior floor holds.
    d2 = _make_decision(
        monkeypatch,
        entry_price_basis="bid",
        route="maker_bid",
        adverse_selection_reserve=0.02,
        measured_asr_cents=1.0,
    )
    assert math.isclose(
        float(d2.no_edge_breakdown.adverse_selection_reserve), 0.02,
        abs_tol=1e-12,
    )


def test_ev_gate_uses_breakdown_asr_not_a_second_recompute(monkeypatch):
    """The decision's recorded ASR must equal what the breakdown charged —
    the pre-fix gate recomputed a different reserve post-selection."""
    d = _make_decision(
        monkeypatch,
        entry_price_basis="bid",
        route="maker_bid",
        adverse_selection_reserve=0.02,
        measured_asr_cents=3.5,
    )
    sel = d.selected_outcome or d.best_side
    if d.selected_outcome is not None:
        assert float(d.adverse_selection_reserve) == pytest.approx(
            float(
                (d.yes_edge_breakdown if sel == "yes" else d.no_edge_breakdown)
                .adverse_selection_reserve
            )
        )


# ── decision-level identity on the live path ─────────────────────────


@pytest.mark.parametrize("asset", ["BTC", "ETH", "SOL", "XRP", "DOGE"])
def test_accepted_decision_has_zero_identity_difference(monkeypatch, asset):
    """pi_star_identity_difference must be float noise, not a hidden reserve."""
    d = _make_decision(monkeypatch, asset=asset)
    assert d.selected_outcome == "no"
    diff = float(d.indicators["pi_star_identity_difference"])
    assert abs(diff) < 1e-9


# ── side_ev audit rows reproduce the enforced verdict ────────────────


def test_side_ev_row_uses_per_side_breakdown_asr(monkeypatch):
    from merid.execution.decision_audit_ledger import _build_side_ev_row

    d = _make_decision(
        monkeypatch,
        entry_price_basis="bid",
        route="maker_bid",
        adverse_selection_reserve=0.02,
        measured_asr_cents=3.0,
    )
    row = _build_side_ev_row(d, "no", dict(d.indicators or {}), None, None)
    assert row["adverse_selection_haircut_cents"] == pytest.approx(
        float(d.no_edge_breakdown.adverse_selection_reserve) * 100.0
    )
    # Enforced-comparison stamps are persisted alongside the raw pair.
    assert row["gate_ev_cents"] is not None
    assert row["enforced_edge_bound_cents"] is not None
    assert row["passed_edge_gate"] == (
        row["gate_ev_cents"] >= row["enforced_edge_bound_cents"] - 1e-9
    )
