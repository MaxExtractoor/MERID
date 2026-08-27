"""Layer 1 edge-formula correctness audit for `merid.prediction.trade_decision`.

This script does not require trade data. It exercises the canonical edge
functions with controlled inputs and reports any sign, unit, gross-vs-net, or
calibration inconsistencies. It is intended to be run whenever the edge math is
changed or when calibrating thresholds.

Usage:
    .\.venv\Scripts\python.exe scripts\edge_formula_audit.py
    .\.venv\Scripts\python.exe scripts\edge_formula_audit.py --min-edge 0.03 --fee-cents 2 --reserve 0.01
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

# Ensure merid is importable when run from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from merid.prediction.trade_decision import (
    TRADE_DECISION_MIN_REQUIRED_EDGE,
    compute_edge,
    compute_trade_decision,
)


@dataclass
class AuditCheck:
    name: str
    passed: bool
    details: Dict[str, Any] = field(default_factory=dict)
    recommendation: str = ""


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _fmt_cents(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(value * 100.0, 4)


def _audit_sign_flip() -> AuditCheck:
    """Verify YES/NO edge signs flip correctly around a symmetric 50c book.

    For a long-YES entry we want p_yes > ask_yes (underpriced);
    for a short-YES / long-NO entry we want p_no > ask_no,
    which is equivalent to p_yes < bid_yes.
    """
    # Symmetric 50c fade: yes ask = 53c, no ask = 47c.
    yes_breakdown = compute_edge(
        p_yes=0.60,
        selected_side="yes",
        entry_price=0.53,
        entry_fee=0.0,
        exit_cost_reserve=0.0,
        model_risk_reserve=0.0,
    )
    no_breakdown = compute_edge(
        p_yes=0.60,
        selected_side="no",
        entry_price=0.47,
        entry_fee=0.0,
        exit_cost_reserve=0.0,
        model_risk_reserve=0.0,
    )

    ok = (
        yes_breakdown.gross_edge > 0
        and no_breakdown.gross_edge < 0
        and math.isclose(yes_breakdown.gross_edge, -no_breakdown.gross_edge, rel_tol=1e-9)
    )

    # Reverse: model believes NO (p_yes=0.40).
    yes_breakdown_rev = compute_edge(
        p_yes=0.40,
        selected_side="yes",
        entry_price=0.53,
        entry_fee=0.0,
        exit_cost_reserve=0.0,
        model_risk_reserve=0.0,
    )
    no_breakdown_rev = compute_edge(
        p_yes=0.40,
        selected_side="no",
        entry_price=0.47,
        entry_fee=0.0,
        exit_cost_reserve=0.0,
        model_risk_reserve=0.0,
    )

    ok = ok and (
        yes_breakdown_rev.gross_edge < 0
        and no_breakdown_rev.gross_edge > 0
        and math.isclose(yes_breakdown_rev.gross_edge, -no_breakdown_rev.gross_edge, rel_tol=1e-9)
    )

    return AuditCheck(
        name="edge_sign_and_symmetry",
        passed=ok,
        details={
            "p_yes_0.60_yes_edge_cents": _fmt_cents(yes_breakdown.gross_edge),
            "p_yes_0.60_no_edge_cents": _fmt_cents(no_breakdown.gross_edge),
            "p_yes_0.40_yes_edge_cents": _fmt_cents(yes_breakdown_rev.gross_edge),
            "p_yes_0.40_no_edge_cents": _fmt_cents(no_breakdown_rev.gross_edge),
        },
        recommendation=(
            "If sign symmetry fails, the YES/NO side selection logic is inverting the "
            "entire strategy. Inspect compute_edge's p_selected derivation."
        ),
    )


def _audit_gross_vs_net(min_required_edge: float, fee_cents: float, reserve_cents: float) -> AuditCheck:
    """Verify that the gate is applied to net edge, not gross."""
    fee = fee_cents / 100.0
    reserve = reserve_cents / 100.0

    # Build a trade with gross edge exactly equal to the all-in cost of 2*fee + reserve.
    # Net edge should then be zero and the trade must not qualify.
    entry_price = 0.53
    gross_edge_target = 2.0 * fee + reserve  # net = gross - 2*fee - reserve = 0
    p_yes = entry_price + gross_edge_target

    yes_breakdown = compute_edge(
        p_yes=p_yes,
        selected_side="yes",
        entry_price=entry_price,
        entry_fee=fee,
        exit_cost_reserve=fee,  # match compute_trade_decision behavior
        model_risk_reserve=reserve,
    )

    net_edge_matches_formula = math.isclose(
        yes_breakdown.net_edge,
        yes_breakdown.gross_edge - 2.0 * fee - reserve,
        rel_tol=1e-9,
    )
    net_is_zero = math.isclose(yes_breakdown.net_edge, 0.0, abs_tol=1e-9)

    # Now create a TradeDecision at the exact threshold.
    decision = compute_trade_decision(
        run_id="audit",
        decision_id="audit_01",
        ticker="KXTEST",
        asset="TEST",
        spot_price=54000.0,
        strike_price=54000.0,
        seconds_to_expiry=600.0,
        yes_bid_cents=52.0,
        yes_ask_cents=53.0,
        no_bid_cents=47.0,
        no_ask_cents=48.0,
        yes_depth_cc=500.0,
        no_depth_cc=500.0,
        fee_per_contract_cents=fee_cents,
        annualized_vol=0.80,
        model_uncertainty=0.0,
        data_quality="good",
        data_state="healthy",
        regime="normal",
        regime_label="normal",
        regime_probability=1.0,
        p_yes_model=p_yes,
        p_no_model=1.0 - p_yes,
        min_required_edge=min_required_edge,
        settlement_reference="cfb_rti_live",
    )

    ok = (
        net_edge_matches_formula
        and decision.selected_outcome is None  # net edge 0 cannot pass positive min_required_edge
    )

    # Re-run with a gross edge large enough to clear net threshold.
    p_yes_win = entry_price + 2.0 * fee + reserve + min_required_edge + 0.01
    decision_win = compute_trade_decision(
        run_id="audit",
        decision_id="audit_02",
        ticker="KXTEST",
        asset="TEST",
        spot_price=54000.0,
        strike_price=54000.0,
        seconds_to_expiry=600.0,
        yes_bid_cents=52.0,
        yes_ask_cents=53.0,
        no_bid_cents=47.0,
        no_ask_cents=48.0,
        yes_depth_cc=500.0,
        no_depth_cc=500.0,
        fee_per_contract_cents=fee_cents,
        annualized_vol=0.80,
        model_uncertainty=0.0,
        data_quality="good",
        data_state="healthy",
        regime="normal",
        regime_label="normal",
        regime_probability=1.0,
        p_yes_model=p_yes_win,
        p_no_model=1.0 - p_yes_win,
        min_required_edge=min_required_edge,
        settlement_reference="cfb_rti_live",
    )

    ok = ok and (decision_win.selected_outcome == "yes")

    return AuditCheck(
        name="gross_vs_net_edge_gate",
        passed=ok,
        details={
            "gross_edge_cents": _fmt_cents(yes_breakdown.gross_edge),
            "net_edge_cents": _fmt_cents(yes_breakdown.net_edge),
            "gross_minus_2fee_reserve_cents": _fmt_cents(
                yes_breakdown.gross_edge - 2.0 * fee - reserve
            ),
            "min_required_edge_cents": round(min_required_edge * 100.0, 4),
            "net_zero_trade_selected": bool(decision.selected_outcome),
            "sufficient_net_trade_selected": str(decision_win.selected_outcome or "none"),
        },
        recommendation=(
            "If the gate used gross edge, trades with positive gross but negative net "
            "would execute and lose to fees. Verify compute_trade_decision uses "
            "yes_breakdown.net_edge >= min_required_edge."
        ),
    )


def _audit_fair_value_consistency() -> AuditCheck:
    """Verify that fair_value / model_prob is the probability used for edge."""
    p_yes = 0.62
    entry_price = 0.55
    yes_breakdown = compute_edge(
        p_yes=p_yes,
        selected_side="yes",
        entry_price=entry_price,
        entry_fee=0.0,
        exit_cost_reserve=0.0,
        model_risk_reserve=0.0,
    )

    fair_value = p_yes
    expected_gross = fair_value - entry_price

    ok = math.isclose(yes_breakdown.gross_edge, expected_gross, rel_tol=1e-9)

    # Also verify p_yes + p_no == 1 invariant.
    ok = ok and math.isclose(yes_breakdown.p_yes + yes_breakdown.p_no, 1.0, rel_tol=1e-9)

    return AuditCheck(
        name="fair_value_consistency",
        passed=ok,
        details={
            "p_yes": p_yes,
            "p_no": yes_breakdown.p_no,
            "fair_value_dollars": fair_value,
            "entry_price_dollars": entry_price,
            "expected_gross_edge_cents": _fmt_cents(expected_gross),
            "actual_gross_edge_cents": _fmt_cents(yes_breakdown.gross_edge),
        },
        recommendation=(
            "If gross_edge != fair_value - entry_price, the edge is being computed from "
            "a different quantity than the model probability."
        ),
    )


def _audit_unit_consistency() -> AuditCheck:
    """Catch cents-vs-dollars or pct-vs-dollars bugs."""
    p_yes = 0.60
    entry_price_cents = 55.0

    # Passing dollars to compute_edge.
    yes_breakdown_dollars = compute_edge(
        p_yes=p_yes,
        selected_side="yes",
        entry_price=entry_price_cents / 100.0,
        entry_fee=0.02,
        exit_cost_reserve=0.02,
        model_risk_reserve=0.01,
    )

    # Passing cents (bug pattern) would push entry_price to 55, which is outside [0,1]
    # and should raise. We guard that edge calculation validates bounds.
    caught_cents_bug = False
    try:
        compute_edge(
            p_yes=p_yes,
            selected_side="yes",
            entry_price=55.0,  # cents passed as dollars -> invalid
            entry_fee=0.02,
            exit_cost_reserve=0.02,
            model_risk_reserve=0.01,
        )
    except ValueError:
        caught_cents_bug = True

    # Verify net edge is a small fraction (~5c) not 500%.
    net_is_reasonable = abs(yes_breakdown_dollars.net_edge) <= 0.15

    ok = caught_cents_bug and net_is_reasonable

    return AuditCheck(
        name="unit_consistency",
        passed=ok,
        details={
            "entry_price_cents": entry_price_cents,
            "entry_price_dollars": entry_price_cents / 100.0,
            "gross_edge_cents": _fmt_cents(yes_breakdown_dollars.gross_edge),
            "net_edge_cents": _fmt_cents(yes_breakdown_dollars.net_edge),
            "cents_as_dollars_input_rejected": caught_cents_bug,
        },
        recommendation=(
            "If net_edge is >1.0, the code is probably mixing dollars and cents. "
            "All compute_edge inputs must be in dollars/fraction units."
        ),
    )


def _audit_calibration_clamp() -> AuditCheck:
    """Verify p_yes is clamped to [0.05, 0.95] before edge calc."""
    # Use a mid-curve price (45c) so tail calibration does not cap the model.
    decision = compute_trade_decision(
        run_id="audit",
        decision_id="audit_03",
        ticker="KXTEST",
        asset="TEST",
        spot_price=54000.0,
        strike_price=54000.0,
        seconds_to_expiry=600.0,
        yes_bid_cents=44.0,
        yes_ask_cents=45.0,
        no_bid_cents=55.0,
        no_ask_cents=56.0,
        yes_depth_cc=500.0,
        no_depth_cc=500.0,
        fee_per_contract_cents=2.0,
        annualized_vol=0.80,
        model_uncertainty=0.0,
        data_quality="good",
        data_state="healthy",
        regime="normal",
        regime_label="normal",
        regime_probability=1.0,
        p_yes_model=0.99,  # extreme confidence
        p_no_model=0.01,
        min_required_edge=0.03,
        settlement_reference="cfb_rti_live",
    )

    # The clamp should have pulled p_yes down to 0.95, making gross edge huge.
    # We mainly care that it did not use 0.99 literally.
    p_calibrated = _safe_float(decision.p_yes_calibrated)
    ok = p_calibrated is not None and math.isclose(p_calibrated, 0.95, rel_tol=1e-9)

    return AuditCheck(
        name="p_yes_calibration_clamp",
        passed=ok,
        details={
            "p_yes_model": 0.99,
            "p_yes_calibrated": p_calibrated,
            "expected_clamp": 0.95,
        },
        recommendation=(
            "If p_yes_calibrated is not clamped to [0.05, 0.95], extreme model "
            "predictions can create phantom edge and over-trade."
        ),
    )


def _audit_min_edge_vs_cost(
    min_required_edge: float,
    fee_cents: float,
    reserve_cents: float,
    spread_estimate_cents: float,
) -> AuditCheck:
    """Flag whether the gross edge implied by the gate clears the all-in cost wall.

    The code gates on *net* edge, where:
        net_edge = gross_edge - entry_fee - exit_cost_reserve - model_risk_reserve
    With entry_fee = exit_cost_reserve = fee and reserve = model_risk_reserve,
    the minimum gross edge the code will accept is:
        gross_min = 2*fee + reserve + min_required_edge
    The all-in transaction cost is roughly:
        all_in_cost = 2*fee + spread
    The buffer above the cost wall is therefore (reserve + min_required_edge - spread).
    """
    fee_dollars = fee_cents / 100.0
    reserve_dollars = reserve_cents / 100.0
    spread_dollars = spread_estimate_cents / 100.0

    modeled_round_trip_fee_dollars = 2.0 * fee_dollars
    implied_gross_threshold = modeled_round_trip_fee_dollars + reserve_dollars + min_required_edge
    all_in_cost = modeled_round_trip_fee_dollars + spread_dollars
    spread_buffer_dollars = reserve_dollars + min_required_edge - spread_dollars

    # The gross threshold must at least cover the all-in cost; otherwise the code
    # is gating on a net edge that cannot overcome fees + spread.
    ok = implied_gross_threshold >= all_in_cost

    return AuditCheck(
        name="min_edge_above_cost_wall",
        passed=ok,
        details={
            "min_required_edge_cents": round(min_required_edge * 100.0, 4),
            "reserve_cents": round(reserve_dollars * 100.0, 4),
            "modeled_fee_per_leg_cents": fee_cents,
            "modeled_round_trip_fee_cents": round(modeled_round_trip_fee_dollars * 100.0, 4),
            "spread_estimate_cents": spread_estimate_cents,
            "implied_gross_edge_required_cents": round(implied_gross_threshold * 100.0, 4),
            "all_in_cost_estimate_cents": round(all_in_cost * 100.0, 4),
            "spread_and_reserve_buffer_cents": round(spread_buffer_dollars * 100.0, 4),
        },
        recommendation=(
            "If implied_gross_edge_required is below 2*fee + spread, the net edge gate "
            "allows trades whose gross edge does not cover the round-trip cost wall."
        ),
    )


def run_audit(
    min_required_edge: float = TRADE_DECISION_MIN_REQUIRED_EDGE,
    fee_cents: float = 2.0,
    reserve_cents: float = 1.0,
    spread_estimate_cents: float = 1.0,
    output_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run all Layer-1 checks and return a structured report."""
    checks = [
        _audit_sign_flip(),
        _audit_gross_vs_net(min_required_edge, fee_cents, reserve_cents),
        _audit_fair_value_consistency(),
        _audit_unit_consistency(),
        _audit_calibration_clamp(),
        _audit_min_edge_vs_cost(min_required_edge, fee_cents, reserve_cents, spread_estimate_cents),
    ]

    report = {
        "_meta": {
            "min_required_edge": min_required_edge,
            "fee_cents": fee_cents,
            "reserve_cents": reserve_cents,
            "spread_estimate_cents": spread_estimate_cents,
            "passed": sum(1 for c in checks if c.passed),
            "failed": sum(1 for c in checks if not c.passed),
            "total": len(checks),
        },
        "checks": [
            {
                "name": c.name,
                "passed": c.passed,
                "details": c.details,
                "recommendation": c.recommendation,
            }
            for c in checks
        ],
    }

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)

    return report


def _print_report(report: Dict[str, Any]) -> None:
    meta = report["_meta"]
    print(f"Edge formula audit: {meta['passed']}/{meta['total']} checks passed")
    print(f"  min_required_edge = {meta['min_required_edge']} ({meta['min_required_edge']*100:.2f}c)")
    print(f"  fee_cents = {meta['fee_cents']}")
    print(f"  reserve_cents = {meta.get('reserve_cents')}")
    print(f"  spread_estimate_cents = {meta.get('spread_estimate_cents')}")
    print()
    for check in report["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        print(f"[{status}] {check['name']}")
        for key, value in check["details"].items():
            print(f"    {key}: {value}")
        if not check["passed"] and check["recommendation"]:
            print(f"    -> {check['recommendation']}")
    print()
    if meta["failed"] > 0:
        print(f"FAILED {meta['failed']} formula checks. Do not adjust thresholds until these are fixed.")
    else:
        print("All formula checks passed. Proceed to cost-wall test with trade data.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Layer-1 edge formula audit")
    parser.add_argument(
        "--min-edge",
        type=float,
        default=TRADE_DECISION_MIN_REQUIRED_EDGE,
        help="Minimum required net edge (dollars, default 0.03)",
    )
    parser.add_argument(
        "--fee-cents",
        type=float,
        default=2.0,
        help="Modeled per-leg taker fee in cents (default 2.0)",
    )
    parser.add_argument(
        "--reserve-cents",
        type=float,
        default=1.0,
        help="Model risk reserve in cents (default 1.0)",
    )
    parser.add_argument(
        "--spread-cents",
        type=float,
        default=1.0,
        help="Estimated one-way spread in cents (default 1.0)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/edge_formula_audit.json"),
        help="Where to write the JSON report",
    )
    args = parser.parse_args()

    report = run_audit(
        min_required_edge=args.min_edge,
        fee_cents=args.fee_cents,
        reserve_cents=args.reserve_cents,
        spread_estimate_cents=args.spread_cents,
        output_path=args.output,
    )
    _print_report(report)
    return 0 if report["_meta"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
