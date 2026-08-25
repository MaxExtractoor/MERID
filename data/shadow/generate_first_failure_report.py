"""Generate first-failure report from CF-RTI shadow telemetry.

Reads all data/shadow/cfb_rti/*.json files, recomputes both YES and NO
executable net edges, and emits a first-failure report with distributions.
This is a temporary diagnostic script; output goes to data/shadow/.
"""
from __future__ import annotations

import glob
import json
import math
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def load_candidates() -> list[dict]:
    paths = sorted(glob.glob(str(Path(__file__).parent / "cfb_rti" / "*.json")))
    records = []
    for p in paths:
        try:
            with open(p, "r", encoding="utf-8") as f:
                records.append(json.load(f))
        except Exception:
            continue
    return records


def recompute_both_edges(rec: dict) -> tuple[float, float] | None:
    """Return (ev_yes, ev_no) in fractional units from a shadow record.

    Prefer the explicit per-side net edge fields when present; fall back to
    recomputing from price/probability/reserve for older records.
    """
    net_yes = rec.get("net_edge_yes")
    net_no = rec.get("net_edge_no")
    if net_yes is not None and net_no is not None:
        return float(net_yes), float(net_no)

    p_yes = float(rec.get("p_yes") or 0.0)
    p_no = float(rec.get("p_no") or (1.0 - p_yes))
    yes_ask = float(rec.get("yes_ask_cents") or 0.0) / 100.0
    no_ask = float(rec.get("no_ask_cents") or 0.0) / 100.0
    fee_cents = float(rec.get("fee_per_contract_cents") or 0.0)
    fee = fee_cents / 100.0
    reserve = float(rec.get("model_risk_reserve") or 0.0)
    # All-in cost per side: entry fee + expected exit fee + model risk reserve.
    # This mirrors trade_decision.compute_edge and the audit formula:
    #   EV = p - ask - entry_fee - exit_cost_reserve - model_risk_reserve
    total_reserve = fee + fee + reserve
    if not (0.0 <= yes_ask <= 1.0 and 0.0 <= no_ask <= 1.0):
        return None
    ev_yes = p_yes - yes_ask - total_reserve
    ev_no = p_no - no_ask - total_reserve
    return ev_yes, ev_no


def first_failed_gate(rec: dict, ev_yes: float, ev_no: float) -> str:
    """Map a shadow record to the first economic/semantic gate that failed."""
    data_state = rec.get("data_state")
    regime_label = rec.get("regime_label")
    regime_probability = rec.get("regime_probability")
    rejection_reason = rec.get("rejection_reason") or ""

    # Upstream data-state / regime gates are first-class fail-closed gates,
    # but only when the record was produced with the new telemetry schema.
    has_new_gate_fields = "data_state" in rec or "regime_label" in rec
    if has_new_gate_fields:
        if data_state and data_state not in ("healthy", "warming_up"):
            return "data_state_not_healthy"
        if regime_label == "unknown" or regime_label is None:
            return "regime_unclassified"
        if regime_probability is not None and float(regime_probability) < 0.5:
            return "regime_uncertain"

    # Legacy / explicit rejection reasons from the new telemetry are canonical.
    if rejection_reason:
        legacy_map = {
            "no_net_edge_above_threshold": "best_net_edge_below_threshold",
        }
        return legacy_map.get(rejection_reason, rejection_reason)

    # Fallback: compute the most likely first-failure gate.
    min_edge = float(rec.get("min_required_edge") or 0.03)
    confidence_valid = bool(rec.get("confidence_valid"))
    if not confidence_valid:
        return "invalid_confidence"
    if rec.get("selected_outcome") in ("yes", "no"):
        return "none"

    best_side = "yes" if ev_yes >= ev_no else "no"
    best_edge = max(ev_yes, ev_no)
    if best_edge < min_edge:
        return "best_net_edge_below_threshold"
    if best_side == "yes" and (float(rec.get("p_yes") or 0.0) <= 0.5):
        return "cost_basis_override_yes"
    if best_side == "no" and (float(rec.get("p_no") or 0.0) <= 0.5):
        return "cost_basis_override_no"

    return "unknown"


def build_report(records: list[dict]) -> dict:
    total = len(records)
    analyses = []
    for rec in records:
        edges = recompute_both_edges(rec)
        if edges is None:
            continue
        ev_yes, ev_no = edges
        best_side = "yes" if ev_yes >= ev_no else "no"
        best_edge = max(ev_yes, ev_no)
        gate = first_failed_gate(rec, ev_yes, ev_no)
        selected = rec.get("selected_outcome") in ("yes", "no")
        a = {
            "timestamp_utc": rec.get("timestamp_utc"),
            "ticker": rec.get("market_ticker"),
            "asset": rec.get("asset"),
            "seconds_to_expiry": rec.get("seconds_to_expiry"),
            "settlement_reference": rec.get("settlement_reference"),
            "yes_bid_cents": rec.get("yes_bid_cents"),
            "yes_ask_cents": rec.get("yes_ask_cents"),
            "no_bid_cents": rec.get("no_bid_cents"),
            "no_ask_cents": rec.get("no_ask_cents"),
            "p_yes": rec.get("p_yes"),
            "p_no": rec.get("p_no"),
            "ev_yes": round(ev_yes, 6),
            "ev_no": round(ev_no, 6),
            "best_side": best_side,
            "best_net_edge": round(best_edge, 6),
            "min_required_edge": rec.get("min_required_edge"),
            "fee_per_contract_cents": rec.get("fee_per_contract_cents"),
            "model_risk_reserve": rec.get("model_risk_reserve"),
            "confidence": rec.get("confidence"),
            "confidence_valid": rec.get("confidence_valid"),
            "confidence_reasons": rec.get("confidence_reasons"),
            "rejection_reason": rec.get("rejection_reason"),
            "first_failed_gate": gate,
            "selected_outcome": rec.get("selected_outcome"),
        }
        analyses.append(a)

    selected = [a for a in analyses if a["selected_outcome"] in ("yes", "no")]
    notrades = [a for a in analyses if a["selected_outcome"] not in ("yes", "no")]
    final_minute = [a for a in notrades if float(a["seconds_to_expiry"] or 0.0) <= 60.0]

    def dist(key, rows):
        return dict(Counter(r.get(key) for r in rows))

    def numeric_stats(key, rows):
        vals = [float(r.get(key) or 0.0) for r in rows if r.get(key) is not None and math.isfinite(float(r.get(key) or 0.0))]
        if not vals:
            return {}
        return {
            "n": len(vals),
            "mean": round(statistics.mean(vals), 6),
            "median": round(statistics.median(vals), 6),
            "min": round(min(vals), 6),
            "max": round(max(vals), 6),
        }

    report = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "segment_utc_begin": min((a["timestamp_utc"] for a in analyses if a["timestamp_utc"]), default=None),
        "segment_utc_end": max((a["timestamp_utc"] for a in analyses if a["timestamp_utc"]), default=None),
        "total_decisions": total,
        "parsed_decisions": len(analyses),
        "selected_count": len(selected),
        "no_trade_count": len(notrades),
        "final_minute_rejects": len(final_minute),
        "selection_rate": round(len(selected) / len(analyses), 4) if analyses else 0.0,
        "distributions": {
            "rejection_reason": dist("rejection_reason", notrades),
            "first_failed_gate": dist("first_failed_gate", notrades),
            "best_side": dist("best_side", notrades),
            "data_state": dist("data_state", analyses),
            "regime_label": dist("regime_label", analyses),
            "confidence_valid": dist("confidence_valid", analyses),
            "settlement_reference": dist("settlement_reference", analyses),
        },
        "statistics": {
            "p_yes": numeric_stats("p_yes", analyses),
            "p_no": numeric_stats("p_no", analyses),
            "yes_ask_cents": numeric_stats("yes_ask_cents", analyses),
            "no_ask_cents": numeric_stats("no_ask_cents", analyses),
            "best_net_edge": numeric_stats("best_net_edge", analyses),
            "ev_yes": numeric_stats("ev_yes", notrades),
            "ev_no": numeric_stats("ev_no", notrades),
            "seconds_to_expiry": numeric_stats("seconds_to_expiry", analyses),
            "confidence": numeric_stats("confidence", [a for a in analyses if a.get("confidence") is not None]),
            "regime_probability": numeric_stats("regime_probability", analyses),
            "confidence_data_penalty": numeric_stats("confidence_data_penalty", analyses),
            "confidence_book_penalty": numeric_stats("confidence_book_penalty", analyses),
            "confidence_model_penalty": numeric_stats("confidence_model_penalty", analyses),
            "confidence_regime_penalty": numeric_stats("confidence_regime_penalty", analyses),
        },
        "deep_book_examples": sorted(
            [a for a in notrades if a["yes_ask_cents"] and a["yes_ask_cents"] >= 99],
            key=lambda x: x["best_net_edge"],
            reverse=True,
        )[:5],
        "near_cutoff_examples": sorted(
            [a for a in notrades if 60.0 <= float(a["seconds_to_expiry"] or 0.0) <= 120.0],
            key=lambda x: float(x["seconds_to_expiry"] or 0.0),
        )[:5],
        "records": analyses,
    }
    return report


def main() -> None:
    records = load_candidates()
    if not records:
        print(json.dumps({"error": "no shadow telemetry files found"}, indent=2))
        return

    report = build_report(records)
    out_dir = Path(__file__).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"first_failure_report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_utc.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    # Print a compact scorecard.
    print("=" * 80)
    print(f"FIRST-FAILURE REPORT: {out_path}")
    print("=" * 80)
    print(json.dumps({
        "segment_utc_begin": report["segment_utc_begin"],
        "segment_utc_end": report["segment_utc_end"],
        "total_decisions": report["total_decisions"],
        "parsed_decisions": report["parsed_decisions"],
        "selected_count": report["selected_count"],
        "no_trade_count": report["no_trade_count"],
        "final_minute_rejects": report["final_minute_rejects"],
        "selection_rate": report["selection_rate"],
        "distributions": report["distributions"],
        "statistics": report["statistics"],
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
