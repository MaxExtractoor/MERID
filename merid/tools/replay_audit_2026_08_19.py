"""Deterministic replay audit for 2026-08-19 13:24-13:28 losing trades.

This script reconstructs the three specific losing trades from the persisted
log state and runs them through the current ``compute_trade_decision`` engine
with the release-gate invariants enabled.  It demonstrates that the historical
orders should have been rejected as either:

  * cost-basis overrides (model probability for the selected side <= 0.5), or
  * invalid confidence / non-CF-RTI settlement reference.

Run:

    .\.venv\Scripts\python.exe -m merid.tools.replay_audit_2026_08_19
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

from merid.prediction.trade_decision import TradeDecision, compute_trade_decision


# Reconstructed from logs\full.log and the order-trace records.
# Prices are in cents; probabilities/edges are fractions.
_TRADES: list[Dict[str, Any]] = [
    {
        "ticker": "KXDOGE15M-26AUG190930-30",
        "asset": "DOGE",
        "decision_ts_utc": "2026-08-19T13:24:02.238307+00:00",
        "fill_ts_utc": "2026-08-19T13:24:06.445676+00:00",
        "spot": 0.07056,
        "strike": 0.070631,
        "seconds_to_expiry": 658.0,
        "yes_bid_cents": 15.0,
        "yes_ask_cents": 16.0,
        "no_bid_cents": 84.0,
        "no_ask_cents": 85.0,
        "fee_per_contract_cents": 1.0,
        "annualized_vol": 1.20,
        "selected_side_logged": "yes",
        "price_cents_logged": 16,
        "p_selected_logged": 0.403,
        "edge_logged": 0.173,
        "fill_avg_yes_price_cents": 16,
        "intended_exposure": "long_yes",
        "settled_result": "no_win",
    },
    {
        "ticker": "KXETH15M-26AUG190930-30",
        "asset": "ETH",
        "decision_ts_utc": "2026-08-19T13:26:01.203185+00:00",
        "fill_ts_utc": "2026-08-19T13:26:03.778842+00:00",
        "spot": 1935.68,
        "strike": 1935.55,
        "seconds_to_expiry": 539.0,
        "yes_bid_cents": 71.0,
        "yes_ask_cents": 72.0,
        "no_bid_cents": 28.0,
        "no_ask_cents": 29.0,
        "fee_per_contract_cents": 2.0,
        "annualized_vol": 0.80,
        "selected_side_logged": "no",
        "price_cents_logged": 29,
        "p_selected_logged": 0.488,
        "edge_logged": 0.108,
        "fill_avg_yes_price_cents": 77,
        "intended_exposure": "long_no",
        "settled_result": "yes_win",
    },
    {
        "ticker": "KXBTC15M-26AUG190930-30",
        "asset": "BTC",
        "decision_ts_utc": "2026-08-19T13:28:30.261358+00:00",
        "fill_ts_utc": "2026-08-19T13:28:33.856494+00:00",
        "spot": 64918.42,
        "strike": 64903.82,
        "seconds_to_expiry": 270.0,
        "yes_bid_cents": 72.0,
        "yes_ask_cents": 73.0,
        "no_bid_cents": 27.0,
        "no_ask_cents": 28.0,
        "fee_per_contract_cents": 2.0,
        "annualized_vol": 0.60,
        "selected_side_logged": "no",
        "price_cents_logged": 28,
        "p_selected_logged": 0.448,
        "edge_logged": 0.078,
        "fill_avg_yes_price_cents": 89,
        "intended_exposure": "long_no",
        "settled_result": "yes_win",
    },
]


def _decimal_safe(obj: Any) -> Any:
    """Make TradeDecision JSON-serializable."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, TradeDecision):
        return _decimal_safe(asdict(obj))
    if isinstance(obj, dict):
        return {k: _decimal_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimal_safe(v) for v in obj]
    return obj


def _run_trade(trade: Dict[str, Any], settlement_reference: str) -> TradeDecision:
    return compute_trade_decision(
        run_id="replay_2026_08_19",
        decision_id=f"replay_{trade['ticker']}",
        ticker=trade["ticker"],
        asset=trade["asset"],
        spot_price=trade["spot"],
        strike_price=trade["strike"],
        seconds_to_expiry=trade["seconds_to_expiry"],
        yes_bid_cents=trade["yes_bid_cents"],
        yes_ask_cents=trade["yes_ask_cents"],
        no_bid_cents=trade["no_bid_cents"],
        no_ask_cents=trade["no_ask_cents"],
        yes_depth_cc=200.0,
        no_depth_cc=200.0,
        fee_per_contract_cents=trade["fee_per_contract_cents"],
        annualized_vol=trade["annualized_vol"],
        model_uncertainty=0.05,
        data_quality="live",
        regime="normal",
        indicators={},
        min_required_edge=0.03,
        settlement_reference=settlement_reference,
    )


def main() -> None:
    print("=" * 80)
    print("MERID 2026-08-19 losing-trade deterministic replay audit")
    print("=" * 80)

    overall_passed = True
    all_reports = []

    for trade in _TRADES:
        print(f"\n--- {trade['ticker']} ---")
        print(
            f"Logged: side={trade['selected_side_logged']} "
            f"price={trade['price_cents_logged']}c "
            f"p_selected={trade['p_selected_logged']} "
            f"edge={trade['edge_logged']}"
        )

        # Run with the historical public-spot fallback (truthful provenance).
        decision = _run_trade(trade, settlement_reference="public_spot_fallback:null")

        report = {
            "ticker": trade["ticker"],
            "logged": trade,
            "recomputed_public_spot": _decimal_safe(decision),
            "invariants": {
                "p_yes_plus_p_no_is_one": math.isclose(
                    float(decision.p_yes_calibrated) + float(decision.p_no_calibrated),
                    1.0,
                    abs_tol=1e-9,
                ),
                "p_selected_matches_selected_outcome": (
                    (decision.selected_outcome == "yes" and decision.p_selected == decision.p_yes_calibrated)
                    or (decision.selected_outcome == "no" and decision.p_selected == decision.p_no_calibrated)
                    or decision.selected_outcome is None
                ),
                "price_matches_logged_when_selected": (
                    decision.selected_outcome is None
                    or (
                        decision.selected_outcome_price is not None
                        and int(round(float(decision.selected_outcome_price) * 100.0))
                        == trade["price_cents_logged"]
                    )
                ),
            },
        }

        # Print concise deterministic result.
        if decision.selected_outcome is None:
            print(f"REPLAY RESULT: NO_TRADE  reason={decision.no_trade_reason}")
            print(f"  p_yes={float(decision.p_yes_calibrated):.4f}  "
                  f"p_no={float(decision.p_no_calibrated):.4f}")
            print(f"  confidence_valid={decision.confidence_valid}  "
                  f"confidence={decision.confidence}  "
                  f"confidence_reasons={decision.confidence_reasons}")
            print(f"  invariants: {report['invariants']}")
        else:
            print(f"REPLAY RESULT: SELECTED {decision.selected_outcome}  "
                  f"price={int(round(float(decision.selected_outcome_price) * 100.0))}c")
            print(f"  p_selected={float(decision.p_selected):.4f}  "
                  f"net_edge={float(decision.net_edge):.4f}  "
                  f"confidence_valid={decision.confidence_valid}")
            overall_passed = False

        # Also run with a hypothetical CF-RTI live reference to show the
        # cost-basis override gate is independent of the settlement source.
        decision_live = _run_trade(trade, settlement_reference="cfb_rti_live")
        report["recomputed_cfb_rti_live"] = _decimal_safe(decision_live)

        if decision_live.selected_outcome is None:
            print(f"CF-RTI-LIVE REPLAY: NO_TRADE  reason={decision_live.no_trade_reason}")
        else:
            print(f"CF-RTI-LIVE REPLAY: SELECTED {decision_live.selected_outcome}  "
                  f"p_selected={float(decision_live.p_selected):.4f}")

        all_reports.append(report)

    print("\n" + "=" * 80)
    if overall_passed:
        print("AUDIT CONCLUSION: All three trades are correctly rejected by the")
        print("release-gate invariants.  No live entry should resume until the")
        print("underlying model, CF-RTI settlement, and confidence engine are trusted.")
    else:
        print("AUDIT WARNING: At least one trade was still selected.  The gates are")
        print("not yet strong enough.")
    print("=" * 80)

    report_path = Path("data/audit/replay_2026_08_19_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(all_reports, indent=2, default=str))
    print(f"\nDetailed report written to {report_path}")


if __name__ == "__main__":
    main()
