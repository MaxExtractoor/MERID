#!/usr/bin/env python3
"""Re-export the last-24h round-trip summary from the paired round-trips CSV.

Usage:
    python scripts/reexport_round_trip_summary.py \
        --round-trips reports/last_24h_round_trips_and_open_positions_20260826_141146.csv \
        --out reports/last_24h_round_trip_summary_$(date +%Y%m%d_%H%M%S).json
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _safe_float(value: Any) -> float:
    try:
        v = float(value)
        return v if math.isfinite(v) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _classify_win(gross_pnl_cents: float, net_pnl_cents: float) -> tuple:
    gross_win = gross_pnl_cents > 0
    net_win = net_pnl_cents > 0
    gross_loss = gross_pnl_cents < 0
    net_loss = net_pnl_cents < 0
    return gross_win, net_win, gross_loss, net_loss


def reexport(csv_path: Path, fills_source: str | None = None, settlements_source: str | None = None) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    overall = {
        "round_trips": 0,
        "closed": 0,
        "open_settled": 0,
        "open_unsettled": 0,
        "gross_wins": 0,
        "gross_losses": 0,
        "gross_win_rate": 0.0,
        "net_wins": 0,
        "net_losses": 0,
        "fee_inclusive_win_rate": 0.0,
        "total_contracts": 0.0,
        "total_fees_cents": 0.0,
        "total_gross_pnl_cents": 0.0,
        "total_net_pnl_cents": 0.0,
        "avg_hold_seconds": 0.0,
        "avg_gross_win_per_contract_cents": 0.0,
        "avg_gross_loss_per_contract_cents": 0.0,
        "avg_fee_per_contract_cents": 0.0,
        "breakeven_win_rate": 0.0,
        "gross_pnl_per_contract_cents": 0.0,
        "net_pnl_per_contract_cents": 0.0,
        "_gross_win_pnl_cents": 0.0,
        "_gross_win_contracts": 0.0,
        "_gross_loss_pnl_cents": 0.0,
        "_gross_loss_contracts": 0.0,
    }
    by_asset: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        asset = row.get("asset", "UNKNOWN")
        status = row.get("status", "")
        quantity_cc = _safe_int(row.get("quantity_cc", 0))
        quantity_contracts = quantity_cc / 100.0
        gross_pnl = _safe_float(row.get("gross_pnl_cents", 0))
        total_fee = _safe_float(row.get("total_fee_cents", 0))
        net_pnl = _safe_float(row.get("net_pnl_cents", 0))
        hold_time = _safe_float(row.get("hold_time_seconds", 0))

        gross_win, net_win, gross_loss, net_loss = _classify_win(gross_pnl, net_pnl)

        overall["round_trips"] += 1
        overall["total_contracts"] += quantity_contracts
        overall["total_fees_cents"] += total_fee
        overall["total_gross_pnl_cents"] += gross_pnl
        overall["total_net_pnl_cents"] += net_pnl
        overall["avg_hold_seconds"] += hold_time

        if status == "closed_by_exit":
            overall["closed"] += 1
        elif status in ("open_settled", "settled_open"):
            overall["open_settled"] += 1
        elif status in ("open_unsettled", "unsettled_open"):
            overall["open_unsettled"] += 1

        if gross_win:
            overall["gross_wins"] += 1
            overall["_gross_win_pnl_cents"] += gross_pnl
            overall["_gross_win_contracts"] += quantity_contracts
        if gross_loss:
            overall["gross_losses"] += 1
            overall["_gross_loss_pnl_cents"] += abs(gross_pnl)
            overall["_gross_loss_contracts"] += quantity_contracts
        if net_win:
            overall["net_wins"] += 1
        if net_loss:
            overall["net_losses"] += 1

        if asset not in by_asset:
            by_asset[asset] = {
                "round_trips": 0,
                "closed": 0,
                "open_settled": 0,
                "open_unsettled": 0,
                "gross_wins": 0,
                "gross_losses": 0,
                "gross_win_rate": 0.0,
                "net_wins": 0,
                "net_losses": 0,
                "fee_inclusive_win_rate": 0.0,
                "total_contracts": 0.0,
                "total_fees_cents": 0.0,
                "total_gross_pnl_cents": 0.0,
                "total_net_pnl_cents": 0.0,
                "avg_hold_seconds": 0.0,
                "avg_gross_win_per_contract_cents": 0.0,
                "avg_gross_loss_per_contract_cents": 0.0,
                "avg_fee_per_contract_cents": 0.0,
                "breakeven_win_rate": 0.0,
                "gross_pnl_per_contract_cents": 0.0,
                "net_pnl_per_contract_cents": 0.0,
                "_gross_win_pnl_cents": 0.0,
                "_gross_win_contracts": 0.0,
                "_gross_loss_pnl_cents": 0.0,
                "_gross_loss_contracts": 0.0,
            }

        a = by_asset[asset]
        a["round_trips"] += 1
        a["total_contracts"] += quantity_contracts
        a["total_fees_cents"] += total_fee
        a["total_gross_pnl_cents"] += gross_pnl
        a["total_net_pnl_cents"] += net_pnl
        a["avg_hold_seconds"] += hold_time

        if status == "closed_by_exit":
            a["closed"] += 1
        elif status in ("open_settled", "settled_open"):
            a["open_settled"] += 1
        elif status in ("open_unsettled", "unsettled_open"):
            a["open_unsettled"] += 1

        if gross_win:
            a["gross_wins"] += 1
            a["_gross_win_pnl_cents"] += gross_pnl
            a["_gross_win_contracts"] += quantity_contracts
        if gross_loss:
            a["gross_losses"] += 1
            a["_gross_loss_pnl_cents"] += abs(gross_pnl)
            a["_gross_loss_contracts"] += quantity_contracts
        if net_win:
            a["net_wins"] += 1
        if net_loss:
            a["net_losses"] += 1

    # Derive rates and averages
    rt = overall["round_trips"]
    if rt:
        overall["gross_win_rate"] = overall["gross_wins"] / rt
        overall["fee_inclusive_win_rate"] = overall["net_wins"] / rt
        overall["avg_hold_seconds"] /= rt
    if overall["_gross_win_contracts"]:
        overall["avg_gross_win_per_contract_cents"] = overall["_gross_win_pnl_cents"] / overall["_gross_win_contracts"]
    if overall["_gross_loss_contracts"]:
        overall["avg_gross_loss_per_contract_cents"] = overall["_gross_loss_pnl_cents"] / overall["_gross_loss_contracts"]
    if overall["total_contracts"]:
        overall["avg_fee_per_contract_cents"] = overall["total_fees_cents"] / overall["total_contracts"]
        overall["gross_pnl_per_contract_cents"] = overall["total_gross_pnl_cents"] / overall["total_contracts"]
        overall["net_pnl_per_contract_cents"] = overall["total_net_pnl_cents"] / overall["total_contracts"]

    # Breakeven win rate = (avg_loss + avg_fee) / (avg_win + avg_loss)
    avg_win = overall["avg_gross_win_per_contract_cents"] if overall["avg_gross_win_per_contract_cents"] > 0 else 1
    avg_loss = overall["avg_gross_loss_per_contract_cents"] if overall["avg_gross_loss_per_contract_cents"] > 0 else 1
    avg_fee = overall["avg_fee_per_contract_cents"] if overall["avg_fee_per_contract_cents"] > 0 else 0
    if (avg_win + avg_loss) > 0:
        overall["breakeven_win_rate"] = (avg_loss + avg_fee) / (avg_win + avg_loss)

    for a in by_asset.values():
        rt = a["round_trips"]
        if rt:
            a["gross_win_rate"] = a["gross_wins"] / rt
            a["fee_inclusive_win_rate"] = a["net_wins"] / rt
            a["avg_hold_seconds"] /= rt
        if a["_gross_win_contracts"]:
            a["avg_gross_win_per_contract_cents"] = a["_gross_win_pnl_cents"] / a["_gross_win_contracts"]
        if a["_gross_loss_contracts"]:
            a["avg_gross_loss_per_contract_cents"] = a["_gross_loss_pnl_cents"] / a["_gross_loss_contracts"]
        if a["total_contracts"]:
            a["avg_fee_per_contract_cents"] = a["total_fees_cents"] / a["total_contracts"]
            a["gross_pnl_per_contract_cents"] = a["total_gross_pnl_cents"] / a["total_contracts"]
            a["net_pnl_per_contract_cents"] = a["total_net_pnl_cents"] / a["total_contracts"]
        avg_win = a["avg_gross_win_per_contract_cents"] if a["avg_gross_win_per_contract_cents"] > 0 else 1
        avg_loss = a["avg_gross_loss_per_contract_cents"] if a["avg_gross_loss_per_contract_cents"] > 0 else 1
        avg_fee = a["avg_fee_per_contract_cents"] if a["avg_fee_per_contract_cents"] > 0 else 0
        if (avg_win + avg_loss) > 0:
            a["breakeven_win_rate"] = (avg_loss + avg_fee) / (avg_win + avg_loss)

    return {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "round_trips_source": str(csv_path),
            "fills_source": fills_source or "",
            "settlements_source": settlements_source or "",
            "total_round_trips": overall["round_trips"],
        },
        "overall": overall,
        "by_asset": by_asset,
    }


def main():
    parser = argparse.ArgumentParser(description="Re-export round-trip summary from paired CSV")
    parser.add_argument("--round-trips", type=Path, required=True, help="Path to last_24h_round_trips_and_open_positions_*.csv")
    parser.add_argument("--fills-source", type=str, default=None, help="Optional fills source path")
    parser.add_argument("--settlements-source", type=str, default=None, help="Optional settlements source path")
    parser.add_argument("--out", type=Path, required=True, help="Output JSON path")
    args = parser.parse_args()

    summary = reexport(args.round_trips, fills_source=args.fills_source, settlements_source=args.settlements_source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"Wrote summary: {args.out}")


if __name__ == "__main__":
    main()
