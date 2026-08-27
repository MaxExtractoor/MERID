#!/usr/bin/env python3
"""Layer 4 cost-wall threshold audit against realized 24h round-trip data.

Reads:
- reports/last_24h_round_trips_and_open_positions_*.csv

Produces:
- reports/edge_cost_wall_audit_YYYYmmdd_HHMMSS.json
- reports/edge_cost_wall_audit_YYYYmmdd_HHMMSS.csv

The audit compares the *implied gross edge* the code requires (net edge +
modeled round-trip fees + reserve) to the actual all-in round-trip fee drag and
the realized gross edge per contract. It is designed to answer: "Is the edge
gate actually above the cost wall?" and "Are realized edges covering the
threshold?"

The modeled fee is computed with the canonical Kalshi fee formula. The
"cost wall" is ex-post: the realized round-trip fee per contract. The
"realized gross edge" is the actual price move captured per contract
(gross_pnl / contracts). A trade is below the cost wall when realized gross
edge < round-trip fee, because the price move did not pay for its own
execution.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Ensure merid is importable when run from repo root.
if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
from merid.prediction.trade_decision import TRADE_DECISION_MIN_REQUIRED_EDGE


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None or value == "":
        return default
    try:
        f = float(value)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _modeled_fee_cents(price_cents: float) -> float:
    """Canonical Kalshi fee for one contract at the given price."""
    try:
        return float(calculate_kalshi_fee_cents(1, int(round(price_cents))))
    except Exception:
        return 0.0


def _load_round_trips(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def _enrich_round_trip(row: Dict[str, Any], min_edge: float, reserve_cents: float) -> Dict[str, Any]:
    """Add cost-wall and edge-threshold economics to a round trip."""
    asset = str(row.get("asset") or "").upper()
    quantity_contracts = _safe_float(row.get("quantity_contracts")) or 0.0
    quantity_cc = _safe_int(row.get("quantity_cc")) or 0
    gross_pnl = _safe_float(row.get("gross_pnl_cents")) or 0.0
    total_fee = _safe_float(row.get("total_fee_cents")) or 0.0
    net_pnl = _safe_float(row.get("net_pnl_cents")) or 0.0
    entry_price = _safe_float(row.get("entry_price_cents")) or 0.0
    exit_price = _safe_float(row.get("exit_price_cents")) or 0.0
    hold_seconds = _safe_float(row.get("hold_time_seconds")) or 0.0
    status = str(row.get("status") or "")

    realized_gross_edge_cents = gross_pnl / quantity_contracts if quantity_contracts else 0.0
    realized_net_edge_cents = net_pnl / quantity_contracts if quantity_contracts else 0.0
    fee_drag_cents = total_fee / quantity_contracts if quantity_contracts else 0.0

    # The code's gross edge threshold = 2*fee + reserve + min_edge.
    modeled_entry_fee = _modeled_fee_cents(entry_price)
    code_gross_edge_required_cents = (
        2.0 * modeled_entry_fee
        + reserve_cents
        + min_edge * 100.0
    )

    # Ex-post cost wall: the gross edge needed to pay for round-trip fees.
    cost_wall_cents = fee_drag_cents
    below_cost_wall = realized_gross_edge_cents < cost_wall_cents
    below_code_threshold = realized_gross_edge_cents < code_gross_edge_required_cents

    return {
        **row,
        "asset": asset,
        "realized_gross_edge_cents": round(realized_gross_edge_cents, 4),
        "realized_net_edge_cents": round(realized_net_edge_cents, 4),
        "fee_drag_cents": round(fee_drag_cents, 4),
        "modeled_entry_fee_cents": round(modeled_entry_fee, 4),
        "code_gross_edge_required_cents": round(code_gross_edge_required_cents, 4),
        "cost_wall_cents": round(cost_wall_cents, 4),
        "below_cost_wall": below_cost_wall,
        "below_code_threshold": below_code_threshold,
        "edge_surplus_over_cost_wall_cents": round(realized_gross_edge_cents - cost_wall_cents, 4),
        "edge_surplus_over_code_threshold_cents": round(
            realized_gross_edge_cents - code_gross_edge_required_cents, 4
        ),
        "hold_seconds": hold_seconds,
        "status": status,
    }


def _aggregate(
    trades: Sequence[Dict[str, Any]],
    group_key: str,
) -> Dict[str, Any]:
    """Aggregate cost-wall metrics for a group of round trips."""
    n = len(trades)
    if n == 0:
        return {
            "round_trips": 0,
            "contracts": 0.0,
            "gross_pnl_cents": 0.0,
            "total_fees_cents": 0.0,
            "net_pnl_cents": 0.0,
            "gross_win_rate": 0.0,
            "net_win_rate": 0.0,
            "avg_realized_gross_edge_cents": None,
            "avg_fee_drag_cents": None,
            "avg_realized_net_edge_cents": None,
            "avg_code_gross_edge_required_cents": None,
            "median_realized_gross_edge_cents": None,
            "pct_below_cost_wall": 0.0,
            "pct_below_code_threshold": 0.0,
        }

    def _sum(key: str) -> float:
        return sum((_safe_float(t.get(key)) or 0.0) for t in trades)

    def _mean(key: str) -> Optional[float]:
        vals = [(_safe_float(t.get(key)) or 0.0) for t in trades]
        return round(mean(vals), 4) if vals else None

    def _median(key: str) -> Optional[float]:
        vals = [(_safe_float(t.get(key)) or 0.0) for t in trades]
        return round(median(vals), 4) if vals else None

    gross_wins = sum(1 for t in trades if (_safe_float(t.get("gross_pnl_cents")) or 0.0) > 0)
    net_wins = sum(1 for t in trades if (_safe_float(t.get("net_pnl_cents")) or 0.0) > 0)
    below_cost_wall = sum(1 for t in trades if t.get("below_cost_wall"))
    below_code_threshold = sum(1 for t in trades if t.get("below_code_threshold"))

    total_contracts = _sum("quantity_contracts")
    weighted_gross_edge = round(_sum("gross_pnl_cents") / total_contracts, 4) if total_contracts else None
    weighted_fee_drag = round(_sum("total_fee_cents") / total_contracts, 4) if total_contracts else None
    weighted_net_edge = round(_sum("net_pnl_cents") / total_contracts, 4) if total_contracts else None

    return {
        "round_trips": n,
        "contracts": total_contracts,
        "gross_pnl_cents": round(_sum("gross_pnl_cents"), 4),
        "total_fees_cents": round(_sum("total_fee_cents"), 4),
        "net_pnl_cents": round(_sum("net_pnl_cents"), 4),
        "gross_win_rate": round(gross_wins / n, 4) if n else 0.0,
        "net_win_rate": round(net_wins / n, 4) if n else 0.0,
        "avg_realized_gross_edge_cents": weighted_gross_edge,
        "avg_fee_drag_cents": weighted_fee_drag,
        "avg_realized_net_edge_cents": weighted_net_edge,
        "unweighted_avg_realized_gross_edge_cents": _mean("realized_gross_edge_cents"),
        "unweighted_avg_fee_drag_cents": _mean("fee_drag_cents"),
        "unweighted_avg_realized_net_edge_cents": _mean("realized_net_edge_cents"),
        "avg_code_gross_edge_required_cents": _mean("code_gross_edge_required_cents"),
        "median_realized_gross_edge_cents": _median("realized_gross_edge_cents"),
        "pct_below_cost_wall": round(below_cost_wall / n, 4) if n else 0.0,
        "pct_below_code_threshold": round(below_code_threshold / n, 4) if n else 0.0,
    }


def _latest_file(pattern: str, root: Path = Path("reports")) -> Optional[Path]:
    """Return the most recently written file matching the glob pattern."""
    candidates = list(root.glob(pattern))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def run_audit(
    round_trips_path: Optional[Path] = None,
    min_edge: float = TRADE_DECISION_MIN_REQUIRED_EDGE,
    reserve_cents: float = 1.0,
    output_dir: Path = Path("reports"),
) -> Dict[str, Any]:
    """Run the cost-wall audit and return a structured report."""
    if round_trips_path is None:
        round_trips_path = _latest_file("last_24h_round_trips_and_open_positions_*.csv")
    if round_trips_path is None or not round_trips_path.exists():
        raise FileNotFoundError(
            "No round-trip CSV found. Pass --round-trips or place one in reports/"
        )

    rows = _load_round_trips(round_trips_path)
    trades = [_enrich_round_trip(r, min_edge, reserve_cents) for r in rows]

    overall = _aggregate(trades, "all")
    by_asset: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for t in trades:
        by_asset[t["asset"]].append(t)

    by_asset_summary = {asset: _aggregate(group, asset) for asset, group in by_asset.items()}

    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"edge_cost_wall_audit_{now}.json"
    csv_path = output_dir / f"edge_cost_wall_audit_{now}.csv"
    output_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "round_trips_source": str(round_trips_path),
            "min_required_edge": min_edge,
            "reserve_cents": reserve_cents,
            "total_round_trips": len(trades),
            "assets": sorted(by_asset.keys()),
            "output_json": str(json_path),
            "output_csv": str(csv_path),
        },
        "overall": overall,
        "by_asset": by_asset_summary,
        "cost_wall_verdict": {
            "pct_below_code_threshold": overall["pct_below_code_threshold"],
            "pct_below_cost_wall": overall["pct_below_cost_wall"],
            "avg_realized_gross_edge_cents": overall["avg_realized_gross_edge_cents"],
            "avg_fee_drag_cents": overall["avg_fee_drag_cents"],
            "avg_realized_net_edge_cents": overall["avg_realized_net_edge_cents"],
        },
    }

    # Write JSON.
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    # Write per-trade CSV.
    if trades:
        keys = [
            "round_trip_id", "asset", "ticker", "status",
            "entry_price_cents", "exit_price_cents",
            "quantity_contracts", "quantity_cc",
            "gross_pnl_cents", "total_fee_cents", "net_pnl_cents",
            "realized_gross_edge_cents", "fee_drag_cents", "realized_net_edge_cents",
            "modeled_entry_fee_cents", "code_gross_edge_required_cents",
            "cost_wall_cents", "below_cost_wall", "below_code_threshold",
            "edge_surplus_over_cost_wall_cents", "edge_surplus_over_code_threshold_cents",
            "hold_time_seconds",
        ]
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            writer.writeheader()
            for t in trades:
                writer.writerow({k: t.get(k, "") for k in keys})

    return report


def _print_report(report: Dict[str, Any]) -> None:
    meta = report["_meta"]
    overall = report["overall"]
    by_asset = report["by_asset"]

    print("Edge cost-wall audit")
    print(f"  source: {meta['round_trips_source']}")
    print(f"  min_required_edge: {meta['min_required_edge']*100:.2f}c")
    print(f"  reserve_cents: {meta['reserve_cents']}")
    print(f"  round_trips: {overall['round_trips']}")
    print()

    print("Overall:")
    print(f"  avg realized gross edge / contract: {overall['avg_realized_gross_edge_cents']:.4f}c")
    print(f"  avg fee drag / contract:            {overall['avg_fee_drag_cents']:.4f}c")
    print(f"  avg realized net edge / contract:   {overall['avg_realized_net_edge_cents']:.4f}c")
    print(f"  avg code gross threshold / contract: {overall['avg_code_gross_edge_required_cents']:.4f}c")
    print(f"  gross win rate:                     {overall['gross_win_rate']:.2%}")
    print(f"  net win rate:                       {overall['net_win_rate']:.2%}")
    print(f"  % realized gross < fee drag:        {overall['pct_below_cost_wall']:.2%}")
    print(f"  % realized gross < code threshold:  {overall['pct_below_code_threshold']:.2%}")
    print(f"  (unweighted avg gross edge:         {overall['unweighted_avg_realized_gross_edge_cents']:.4f}c)")
    print()

    print("By asset:")
    for asset in sorted(by_asset.keys()):
        a = by_asset[asset]
        gross = a['avg_realized_gross_edge_cents']
        fee = a['avg_fee_drag_cents']
        net = a['avg_realized_net_edge_cents']
        thresh = a['avg_code_gross_edge_required_cents']
        print(
            f"  {asset:5s}  n={a['round_trips']:3d}  "
            f"gross_edge={gross:7.4f}c  "
            f"fee_drag={fee:7.4f}c  "
            f"net_edge={net:7.4f}c  "
            f"code_thresh={thresh:7.4f}c  "
            f"gross_wr={a['gross_win_rate']:.2%}  "
            f"<fee={a['pct_below_cost_wall']:.2%}"
        )
    print()

    print("Cost-wall verdict:")
    print(
        f"  Code's implied gross edge threshold: {overall['avg_code_gross_edge_required_cents']:.4f}c "
        f"(2x fee + reserve + net edge)"
    )
    print(
        f"  Actual realized gross edge: {overall['avg_realized_gross_edge_cents']:.4f}c /contract "
        f"(weighted by contracts)"
    )
    print(
        f"  Actual round-trip fee drag: {overall['avg_fee_drag_cents']:.4f}c /contract"
    )
    print(
        f"  {overall['pct_below_cost_wall']:.1%} of round trips had realized gross edge "
        f"below the round-trip fee drag (negative EV ex-post)."
    )
    if overall["avg_realized_gross_edge_cents"] < overall["avg_code_gross_edge_required_cents"]:
        print(
            "  The average realized gross edge is far below the code's implied gross threshold. "
            "This is a model-calibration / edge-decay / execution issue, not a threshold set too low."
        )
    if overall["avg_realized_gross_edge_cents"] < overall["avg_fee_drag_cents"]:
        print(
            f"  Average realized gross edge ({overall['avg_realized_gross_edge_cents']:.4f}c) "
            f"is below the average round-trip fee ({overall['avg_fee_drag_cents']:.4f}c). "
            "The price movement captured does not pay for execution."
        )
    print(f"  Reports written: {meta['output_json']} and {meta['output_csv']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Layer-4 cost-wall threshold audit")
    parser.add_argument(
        "--round-trips",
        type=Path,
        default=None,
        help="Round-trip CSV (defaults to most recent reports/last_24h_round_trips_and_open_positions_*.csv)",
    )
    parser.add_argument(
        "--min-edge",
        type=float,
        default=TRADE_DECISION_MIN_REQUIRED_EDGE,
        help="Minimum required net edge in dollars (default 0.03)",
    )
    parser.add_argument(
        "--reserve-cents",
        type=float,
        default=1.0,
        help="Model risk reserve in cents (default 1.0)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports"),
        help="Directory for output reports",
    )
    args = parser.parse_args()

    report = run_audit(
        round_trips_path=args.round_trips,
        min_edge=args.min_edge,
        reserve_cents=args.reserve_cents,
        output_dir=args.output_dir,
    )
    _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
