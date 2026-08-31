#!/usr/bin/env python3
"""Round-trip PnL forensic decomposition for MERID Kalshi 15m crypto.

Reads durable, already-reconciled round-trip artifacts produced by the ledger
and hybrid_audit.py:

- reports/last_24h_round_trips_and_open_positions_*.csv
- reports/decision_to_settlement_audit.csv

Outputs a JSON decomposition + a per-round-trip CSV enriched with the
directional layer (economic_side, directionally_correct, entry_hour).

The script is read-only and does not touch the exchange, order router, or
ledger state.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, List, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        v = float(value)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        s = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _derive_economic_side(row: Dict[str, Any]) -> str:
    """YES = long YES, NO = long NO."""
    side = str(row.get("economic_side", "")).upper()
    if side in ("YES", "NO"):
        return side
    cside = str(row.get("canonical_position_side", "")).lower()
    caction = str(row.get("canonical_position_action", "")).lower()
    if (cside == "yes" and caction == "buy") or (cside == "no" and caction == "sell"):
        return "YES"
    if (cside == "yes" and caction == "sell") or (cside == "no" and caction == "buy"):
        return "NO"
    return "UNKNOWN"


def _load_csv(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _find_latest(root: Path, pattern: str) -> Optional[Path]:
    matches = sorted(root.glob(pattern), key=lambda p: p.name, reverse=True)
    return matches[0] if matches else None


# ---------------------------------------------------------------------------
# Core aggregation helpers
# ---------------------------------------------------------------------------

def _empty_group() -> Dict[str, Any]:
    return {
        "round_trips": 0,
        "contracts": 0.0,
        "gross_pnl_cents": 0.0,
        "fee_cents": 0.0,
        "net_pnl_cents": 0.0,
        "gross_wins": 0,
        "gross_losses": 0,
        "net_wins": 0,
        "net_losses": 0,
        "gross_win_rate": 0.0,
        "fee_inclusive_win_rate": 0.0,
        "avg_hold_seconds": 0.0,
        "_hold_time_sum": 0.0,
        "_gross_win_pnl_cents": 0.0,
        "_gross_win_contracts": 0.0,
        "_gross_loss_pnl_cents": 0.0,
        "_gross_loss_contracts": 0.0,
    }


def _add_to_group(group: Dict[str, Any], rt: Dict[str, Any]) -> None:
    group["round_trips"] += 1
    group["contracts"] += _safe_float(rt.get("quantity_contracts", 0))
    group["gross_pnl_cents"] += _safe_float(rt.get("gross_pnl_cents", 0))
    group["fee_cents"] += _safe_float(rt.get("fee_cents", 0))
    group["net_pnl_cents"] += _safe_float(rt.get("net_pnl_cents", 0))
    group["_hold_time_sum"] += _safe_float(rt.get("hold_time_seconds", 0))

    gross = _safe_float(rt.get("gross_pnl_cents", 0))
    net = _safe_float(rt.get("net_pnl_cents", 0))
    contracts = _safe_float(rt.get("quantity_contracts", 0))

    if gross > 0:
        group["gross_wins"] += 1
        group["_gross_win_pnl_cents"] += gross
        group["_gross_win_contracts"] += contracts
    elif gross < 0:
        group["gross_losses"] += 1
        group["_gross_loss_pnl_cents"] += abs(gross)
        group["_gross_loss_contracts"] += contracts

    if net > 0:
        group["net_wins"] += 1
    elif net < 0:
        group["net_losses"] += 1


def _finalize_group(group: Dict[str, Any]) -> Dict[str, Any]:
    rt = group["round_trips"]
    if rt:
        group["gross_win_rate"] = group["gross_wins"] / rt
        group["fee_inclusive_win_rate"] = group["net_wins"] / rt
        group["avg_hold_seconds"] = group["_hold_time_sum"] / rt

    if group["_gross_win_contracts"]:
        group["avg_gross_win_per_contract_cents"] = (
            group["_gross_win_pnl_cents"] / group["_gross_win_contracts"]
        )
    else:
        group["avg_gross_win_per_contract_cents"] = 0.0

    if group["_gross_loss_contracts"]:
        group["avg_gross_loss_per_contract_cents"] = (
            group["_gross_loss_pnl_cents"] / group["_gross_loss_contracts"]
        )
    else:
        group["avg_gross_loss_per_contract_cents"] = 0.0

    if group["contracts"]:
        group["gross_pnl_per_contract_cents"] = group["gross_pnl_cents"] / group["contracts"]
        group["fee_per_contract_cents"] = group["fee_cents"] / group["contracts"]
        group["net_pnl_per_contract_cents"] = group["net_pnl_cents"] / group["contracts"]
    else:
        group["gross_pnl_per_contract_cents"] = 0.0
        group["fee_per_contract_cents"] = 0.0
        group["net_pnl_per_contract_cents"] = 0.0

    if group["round_trips"]:
        group["gross_pnl_per_trade_cents"] = group["gross_pnl_cents"] / group["round_trips"]
        group["net_pnl_per_trade_cents"] = group["net_pnl_cents"] / group["round_trips"]
    else:
        group["gross_pnl_per_trade_cents"] = 0.0
        group["net_pnl_per_trade_cents"] = 0.0

    # Cleanup internal counters
    group.pop("_hold_time_sum", None)
    group.pop("_gross_win_pnl_cents", None)
    group.pop("_gross_win_contracts", None)
    group.pop("_gross_loss_pnl_cents", None)
    group.pop("_gross_loss_contracts", None)
    return group


# ---------------------------------------------------------------------------
# Decomposition logic
# ---------------------------------------------------------------------------

def build_round_trip_table(round_trips_path: Path, decisions_path: Path) -> List[Dict[str, Any]]:
    """Join round-trip records with decision side data."""
    decisions: Dict[str, Dict[str, Any]] = {}
    for row in _load_csv(decisions_path):
        fill_id = row.get("fill_id")
        if fill_id:
            decisions[fill_id] = row

    table: List[Dict[str, Any]] = []
    for row in _load_csv(round_trips_path):
        entry_fill_id = row.get("entry_fill_id", "")
        decision = decisions.get(entry_fill_id, {})

        economic_side = _derive_economic_side(decision)

        entry_time = _parse_iso(row.get("entry_time") or row.get("created_time"))
        market_result = str(decision.get("market_result") or row.get("market_result") or "").upper()

        rt: Dict[str, Any] = {
            "round_trip_id": row.get("round_trip_id", ""),
            "market_ticker": row.get("ticker", ""),
            "asset": row.get("asset", "UNKNOWN"),
            "status": str(row.get("status", "")).lower(),
            "economic_side": economic_side,
            "quantity_cc": _safe_int(row.get("quantity_cc", 0)),
            "quantity_contracts": _safe_float(row.get("quantity_contracts", 0)),
            "entry_price_cents": _safe_int(row.get("entry_price_cents", 0)),
            "exit_price_cents": _safe_int(row.get("exit_price_cents", 0)),
            "gross_pnl_cents": _safe_float(row.get("gross_pnl_cents", 0)),
            "fee_cents": _safe_float(row.get("total_fee_cents", 0)),
            "net_pnl_cents": _safe_float(row.get("net_pnl_cents", 0)),
            "market_result": market_result,
            "hold_time_seconds": _safe_float(row.get("hold_time_seconds", 0)),
            "entry_time": row.get("entry_time") or row.get("created_time", ""),
            "entry_hour_utc": entry_time.hour if entry_time else None,
            "directionally_correct": (economic_side == market_result)
            if market_result in ("YES", "NO") and economic_side in ("YES", "NO")
            else None,
            "entry_fill_id": entry_fill_id,
        }
        table.append(rt)

    return table


def compute_decomposition(table: List[Dict[str, Any]]) -> Dict[str, Any]:
    overall = _empty_group()
    by_asset: Dict[str, Dict[str, Any]] = defaultdict(_empty_group)
    by_side: Dict[str, Dict[str, Any]] = defaultdict(_empty_group)
    by_status: Dict[str, Dict[str, Any]] = defaultdict(_empty_group)
    by_asset_side: Dict[Tuple[str, str], Dict[str, Any]] = defaultdict(_empty_group)
    by_asset_status: Dict[Tuple[str, str], Dict[str, Any]] = defaultdict(_empty_group)
    by_hour: Dict[int, Dict[str, Any]] = defaultdict(_empty_group)

    net_pnls: List[float] = []
    gross_pnls: List[float] = []
    hold_times: List[float] = []

    for rt in table:
        _add_to_group(overall, rt)
        _add_to_group(by_asset[rt["asset"]], rt)
        _add_to_group(by_side[rt["economic_side"]], rt)
        _add_to_group(by_status[rt["status"]], rt)
        _add_to_group(by_asset_side[(rt["asset"], rt["economic_side"])], rt)
        _add_to_group(by_asset_status[(rt["asset"], rt["status"])], rt)
        if rt["entry_hour_utc"] is not None:
            _add_to_group(by_hour[rt["entry_hour_utc"]], rt)

        net_pnls.append(_safe_float(rt.get("net_pnl_cents", 0)))
        gross_pnls.append(_safe_float(rt.get("gross_pnl_cents", 0)))
        hold_times.append(_safe_float(rt.get("hold_time_seconds", 0)))

    # Finalize groups
    _finalize_group(overall)
    for d in by_asset.values():
        _finalize_group(d)
    for d in by_side.values():
        _finalize_group(d)
    for d in by_status.values():
        _finalize_group(d)
    for d in by_asset_side.values():
        _finalize_group(d)
    for d in by_asset_status.values():
        _finalize_group(d)
    for d in by_hour.values():
        _finalize_group(d)

    # Distribution stats
    def _dist(values: List[float]) -> Dict[str, Any]:
        if not values:
            return {}
        return {
            "n": len(values),
            "mean": round(mean(values), 4) if len(values) > 1 else round(values[0] or 0.0, 4),
            "median": round(median(values), 4) if values else 0.0,
            "min": round(min(values), 4),
            "max": round(max(values), 4),
            "p10": round(sorted(values)[max(0, len(values) * 10 // 100 - 1)] if len(values) >= 10 else values[0] if values else 0.0, 4),
            "p25": round(sorted(values)[max(0, len(values) * 25 // 100 - 1)] if values else 0.0, 4),
            "p75": round(sorted(values)[max(0, len(values) * 75 // 100 - 1)] if values else 0.0, 4),
            "p90": round(sorted(values)[max(0, len(values) * 90 // 100 - 1)] if values else 0.0, 4),
        }

    # Held-to-settlement (open_settled) directional accuracy
    open_settled = [rt for rt in table if rt["status"] in ("open_settled", "settled_open")]
    closed = [rt for rt in table if rt["status"] == "closed_by_exit"]
    dir_correct_open = [rt for rt in open_settled if rt["directionally_correct"] is True]
    dir_incorrect_open = [rt for rt in open_settled if rt["directionally_correct"] is False]

    # Top winners / losers
    sorted_by_net = sorted(table, key=lambda r: _safe_float(r.get("net_pnl_cents", 0)))
    worst = sorted_by_net[:10]
    best = sorted_by_net[-10:][::-1]

    return {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "round_trips_count": len(table),
            "open_settled_count": len(open_settled),
            "closed_count": len(closed),
        },
        "overall": overall,
        "by_asset": {k: v for k, v in sorted(by_asset.items())},
        "by_direction": {k: v for k, v in sorted(by_side.items())},
        "by_exit_type": {k: v for k, v in sorted(by_status.items())},
        "by_asset_and_direction": {
            f"{asset}__{side}": v for (asset, side), v in sorted(by_asset_side.items())
        },
        "by_asset_and_exit_type": {
            f"{asset}__{status}": v for (asset, status), v in sorted(by_asset_status.items())
        },
        "by_entry_hour_utc": {str(k): v for k, v in sorted(by_hour.items())},
        "pnl_distribution_cents": {
            "net_pnl": _dist(net_pnls),
            "gross_pnl": _dist(gross_pnls),
            "hold_time_seconds": _dist(hold_times),
        },
        "held_to_settlement_directional_accuracy": {
            "n": len(open_settled),
            "correct": len(dir_correct_open),
            "incorrect": len(dir_incorrect_open),
            "accuracy": round(len(dir_correct_open) / len(open_settled), 4) if open_settled else 0.0,
        },
        "worst_round_trips_net_cents": worst,
        "best_round_trips_net_cents": best,
    }


def _reconcile_with_summary(round_trips_path: Path, report: Dict[str, Any]) -> Dict[str, Any]:
    """Diff our overall net PnL against the existing last_24h_round_trip_summary JSON."""
    summary_pattern = "last_24h_round_trip_summary_*.json"
    summary_file = _find_latest(round_trips_path.parent, summary_pattern)
    if not summary_file:
        return {"summary_file": None, "reconciled": False, "reason": "no summary file found"}

    try:
        with open(summary_file, "r", encoding="utf-8") as f:
            summary = json.load(f)
    except Exception as exc:
        return {"summary_file": str(summary_file), "reconciled": False, "reason": str(exc)}

    reported_net = _safe_float(summary.get("overall", {}).get("total_net_pnl_cents"), 0.0)
    computed_net = _safe_float(report["overall"].get("net_pnl_cents"), 0.0)
    diff = round(computed_net - reported_net, 4)
    return {
        "summary_file": str(summary_file),
        "reconciled": abs(diff) < 0.01,
        "reported_total_net_pnl_cents": reported_net,
        "computed_total_net_pnl_cents": computed_net,
        "diff_cents": diff,
    }


def write_enriched_csv(table: List[Dict[str, Any]], path: Path) -> None:
    if not table:
        return
    columns = [
        "round_trip_id", "market_ticker", "asset", "status", "economic_side",
        "quantity_contracts", "entry_price_cents", "exit_price_cents",
        "gross_pnl_cents", "fee_cents", "net_pnl_cents", "market_result",
        "directionally_correct", "hold_time_seconds", "entry_hour_utc", "entry_time",
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for rt in table:
            writer.writerow({c: rt.get(c, "") for c in columns})


def main() -> None:
    parser = argparse.ArgumentParser(description="Round-trip PnL forensic decomposition")
    parser.add_argument(
        "--round-trips",
        type=Path,
        default=None,
        help="Path to last_24h_round_trips_and_open_positions_*.csv (default: latest in reports/)",
    )
    parser.add_argument(
        "--decisions",
        type=Path,
        default=None,
        help="Path to decision_to_settlement_audit.csv (default: latest in reports/)",
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=None,
        help="Output JSON path (default: reports/round_trip_pnl_forensic_YYYYmmdd_HHMMSS.json)",
    )
    parser.add_argument(
        "--out-csv",
        type=Path,
        default=None,
        help="Optional enriched per-round-trip CSV path",
    )
    args = parser.parse_args()

    reports_dir = PROJECT_ROOT / "reports"
    round_trips_path = args.round_trips or _find_latest(reports_dir, "last_24h_round_trips_and_open_positions_*.csv")
    decisions_path = args.decisions or (reports_dir / "decision_to_settlement_audit.csv")

    if not round_trips_path or not round_trips_path.exists():
        print(f"Round-trips CSV not found: {round_trips_path}")
        sys.exit(1)
    if not decisions_path or not decisions_path.exists():
        print(f"Decisions CSV not found: {decisions_path}")
        sys.exit(1)

    table = build_round_trip_table(round_trips_path, decisions_path)
    if not table:
        print("No round-trip records found.")
        sys.exit(1)

    report = compute_decomposition(table)
    report["_reconcile"] = _reconcile_with_summary(round_trips_path, report)

    out_json = args.out_json or reports_dir / f"round_trip_pnl_forensic_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"Wrote: {out_json}")

    if args.out_csv:
        write_enriched_csv(table, args.out_csv)
        print(f"Wrote: {args.out_csv}")


if __name__ == "__main__":
    main()
