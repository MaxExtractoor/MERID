#!/usr/bin/env python3
"""Layer 4 per-asset edge-threshold sensitivity sweep.

Reads:
- reports/last_24h_round_trips_and_open_positions_*.csv

Produces:
- reports/edge_threshold_sensitivity_YYYYmmdd_HHMMSS.json
- reports/edge_threshold_sensitivity_YYYYmmdd_HHMMSS.csv

This is an **ex-post oracle** sensitivity sweep: for each candidate gross-edge
threshold it keeps only round trips whose realized gross edge per contract was
at least that large and recomputes PnL, win rate, and exit fraction. Because it
uses realized (post-settlement) price moves, it is an upper bound on what a
perfect decision-time filter could achieve. It is not a realistic backtest.

The sweep answers: "How sensitive is 24h PnL to the gross-edge gate?" and
"Which thresholds are fragile?" (a small change causes a large PnL swing).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None or value == "":
        return default
    try:
        f = float(value)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def _load_round_trips(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def _enrich_trade(row: Dict[str, Any]) -> Dict[str, Any]:
    """Attach realized gross edge and other fields used by the sweep."""
    asset = str(row.get("asset") or "").upper()
    quantity_contracts = _safe_float(row.get("quantity_contracts")) or 0.0
    quantity_cc = _safe_float(row.get("quantity_cc")) or 0.0
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

    return {
        **row,
        "asset": asset,
        "quantity_contracts": quantity_contracts,
        "quantity_cc": quantity_cc,
        "gross_pnl_cents": gross_pnl,
        "total_fee_cents": total_fee,
        "net_pnl_cents": net_pnl,
        "realized_gross_edge_cents": realized_gross_edge_cents,
        "realized_net_edge_cents": realized_net_edge_cents,
        "fee_drag_cents": fee_drag_cents,
        "hold_seconds": hold_seconds,
        "status": status,
        "is_exit_closed": status == "closed_by_exit",
    }


def _sweep_group(
    trades: Sequence[Dict[str, Any]],
    thresholds_cents: Sequence[float],
) -> List[Dict[str, Any]]:
    """Compute sensitivity metrics for a group of trades across thresholds."""
    results: List[Dict[str, Any]] = []
    for threshold in thresholds_cents:
        keep = [t for t in trades if t["realized_gross_edge_cents"] >= threshold]
        n = len(keep)
        if n == 0:
            results.append({
                "threshold_cents": round(threshold, 4),
                "round_trips": 0,
                "contracts": 0.0,
                "gross_pnl_cents": 0.0,
                "total_fees_cents": 0.0,
                "net_pnl_cents": 0.0,
                "gross_win_rate": 0.0,
                "net_win_rate": 0.0,
                "exit_fraction": 0.0,
                "avg_hold_seconds": None,
                "avg_realized_gross_edge_cents": None,
                "avg_fee_drag_cents": None,
                "avg_realized_net_edge_cents": None,
            })
            continue

        gross_wins = sum(1 for t in keep if t["gross_pnl_cents"] > 0)
        net_wins = sum(1 for t in keep if t["net_pnl_cents"] > 0)
        exits = sum(1 for t in keep if t["is_exit_closed"])

        total_contracts = sum(t["quantity_contracts"] for t in keep)
        total_gross = sum(t["gross_pnl_cents"] for t in keep)
        total_fees = sum(t["total_fee_cents"] for t in keep)
        total_net = sum(t["net_pnl_cents"] for t in keep)

        results.append({
            "threshold_cents": round(threshold, 4),
            "round_trips": n,
            "contracts": round(total_contracts, 4),
            "gross_pnl_cents": round(total_gross, 4),
            "total_fees_cents": round(total_fees, 4),
            "net_pnl_cents": round(total_net, 4),
            "gross_win_rate": round(gross_wins / n, 4),
            "net_win_rate": round(net_wins / n, 4),
            "exit_fraction": round(exits / n, 4),
            "avg_hold_seconds": round(sum(t["hold_seconds"] for t in keep) / n, 2),
            "avg_realized_gross_edge_cents": round(total_gross / total_contracts, 4) if total_contracts else None,
            "avg_fee_drag_cents": round(total_fees / total_contracts, 4) if total_contracts else None,
            "avg_realized_net_edge_cents": round(total_net / total_contracts, 4) if total_contracts else None,
        })
    return results


def _find_optimal_threshold(curve: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return the threshold that maximizes net PnL and the threshold where net turns positive."""
    if not curve:
        return None

    max_net = max((c["net_pnl_cents"] for c in curve), default=None)
    max_net_thresholds = [c for c in curve if c["net_pnl_cents"] == max_net]
    optimal = max_net_thresholds[0] if max_net_thresholds else None

    positive_net = [c for c in curve if c["net_pnl_cents"] > 0 and c["round_trips"] > 0]
    breakeven = positive_net[0] if positive_net else None

    return {
        "max_net_pnl_cents": max_net,
        "max_net_threshold_cents": optimal["threshold_cents"] if optimal else None,
        "max_net_round_trips": optimal["round_trips"] if optimal else None,
        "breakeven_threshold_cents": breakeven["threshold_cents"] if breakeven else None,
        "breakeven_round_trips": breakeven["round_trips"] if breakeven else None,
        "breakeven_net_pnl_cents": breakeven["net_pnl_cents"] if breakeven else None,
    }


def _compute_fragility(curve: Sequence[Dict[str, Any]], base_threshold: float) -> Dict[str, Any]:
    """Compute PnL at ±10% and ±20% around a base threshold to detect overfit."""
    by_threshold = {c["threshold_cents"]: c for c in curve}

    def _net_at(pct: float) -> Optional[float]:
        t = base_threshold * (1.0 + pct)
        # Find the closest threshold in the curve.
        closest = min(by_threshold.keys(), key=lambda k: abs(k - t), default=None)
        if closest is None:
            return None
        return by_threshold[closest]["net_pnl_cents"]

    base_net = by_threshold.get(base_threshold, {}).get("net_pnl_cents")
    if base_net is None:
        return {}

    fragility = {"base_threshold_cents": base_threshold, "base_net_pnl_cents": base_net}
    for label, pct in [("minus_20pct", -0.20), ("minus_10pct", -0.10), ("plus_10pct", 0.10), ("plus_20pct", 0.20)]:
        net = _net_at(pct)
        fragility[f"{label}_threshold_cents"] = round(base_threshold * (1.0 + pct), 4)
        fragility[f"{label}_net_pnl_cents"] = net
        if net is not None:
            fragility[f"{label}_delta_cents"] = round(net - base_net, 4)
    return fragility


def _latest_file(pattern: str, root: Path = Path("reports")) -> Optional[Path]:
    candidates = list(root.glob(pattern))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def run_sweep(
    round_trips_path: Optional[Path] = None,
    threshold_start_cents: float = 0.0,
    threshold_end_cents: float = 15.0,
    threshold_step_cents: float = 0.5,
    base_threshold_cents: Optional[float] = None,
    output_dir: Path = Path("reports"),
) -> Dict[str, Any]:
    if round_trips_path is None:
        round_trips_path = _latest_file("last_24h_round_trips_and_open_positions_*.csv")
    if round_trips_path is None or not round_trips_path.exists():
        raise FileNotFoundError(
            "No round-trip CSV found. Pass --round-trips or place one in reports/"
        )

    rows = _load_round_trips(round_trips_path)
    trades = [_enrich_trade(r) for r in rows]

    thresholds = [
        round(threshold_start_cents + i * threshold_step_cents, 4)
        for i in range(int((threshold_end_cents - threshold_start_cents) / threshold_step_cents) + 1)
    ]

    overall_curve = _sweep_group(trades, thresholds)
    by_asset: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for t in trades:
        by_asset[t["asset"]].append(t)

    by_asset_curve = {asset: _sweep_group(group, thresholds) for asset, group in by_asset.items()}

    # Optimal / breakeven per asset and overall.
    optimal = {"overall": _find_optimal_threshold(overall_curve)}
    for asset, curve in by_asset_curve.items():
        optimal[asset] = _find_optimal_threshold(curve)

    # Fragility around the current code's implied gross threshold or the user base.
    if base_threshold_cents is None:
        # Default base: code's gross threshold = 2*fee + reserve + net edge.
        # Use 2c fee, 1c reserve, 3c net edge = 8c.
        base_threshold_cents = 8.0
    fragility = {
        "overall": _compute_fragility(overall_curve, base_threshold_cents),
    }
    for asset, curve in by_asset_curve.items():
        fragility[asset] = _compute_fragility(curve, base_threshold_cents)

    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"edge_threshold_sensitivity_{now}.json"
    csv_path = output_dir / f"edge_threshold_sensitivity_{now}.csv"
    output_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "round_trips_source": str(round_trips_path),
            "threshold_start_cents": threshold_start_cents,
            "threshold_end_cents": threshold_end_cents,
            "threshold_step_cents": threshold_step_cents,
            "base_threshold_cents": base_threshold_cents,
            "total_round_trips": len(trades),
            "assets": sorted(by_asset.keys()),
            "output_json": str(json_path),
            "output_csv": str(csv_path),
            "caveat": (
                "This is an ex-post oracle sweep: it filters by realized gross edge. "
                "It is an upper bound on what a perfect decision-time filter could achieve, "
                "not a realistic strategy. Use decision-time edge from logs for a true "
                "sensitivity analysis."
            ),
        },
        "overall_curve": overall_curve,
        "by_asset_curve": by_asset_curve,
        "optimal_and_breakeven": optimal,
        "fragility_around_base_threshold": fragility,
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    # Flatten curve to CSV: one row per (asset, threshold).
    flat_rows: List[Dict[str, Any]] = []
    for asset, curve in [("ALL", overall_curve)] + sorted(by_asset_curve.items()):
        for point in curve:
            flat_rows.append({"asset": asset, **point})

    if flat_rows:
        keys = list(flat_rows[0].keys())
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(flat_rows)

    return report


def _print_report(report: Dict[str, Any]) -> None:
    meta = report["_meta"]
    overall_curve = report["overall_curve"]
    by_asset_curve = report["by_asset_curve"]
    optimal = report["optimal_and_breakeven"]
    fragility = report["fragility_around_base_threshold"]

    print("Edge threshold sensitivity sweep (ex-post oracle)")
    print(f"  source: {meta['round_trips_source']}")
    print(f"  thresholds: {meta['threshold_start_cents']}c to {meta['threshold_end_cents']}c step {meta['threshold_step_cents']}c")
    print(f"  base threshold for fragility: {meta['base_threshold_cents']}c")
    print(f"  {meta['caveat']}")
    print()

    def _fmt(value: Any) -> str:
        return f"{value:.2f}" if value is not None else "N/A"

    overall_opt = optimal["overall"]
    print(
        f"Overall optimal (max net PnL): threshold={_fmt(overall_opt['max_net_threshold_cents'])}c "
        f"net={overall_opt['max_net_pnl_cents']:.2f}c "
        f"trades={overall_opt['max_net_round_trips']}"
    )
    print(
        f"Overall breakeven (first net > 0): threshold={_fmt(overall_opt['breakeven_threshold_cents'])}c "
        f"net={overall_opt['breakeven_net_pnl_cents']:.2f}c "
        f"trades={overall_opt['breakeven_round_trips']}"
    )
    print()

    def _fmt_threshold(value: Any) -> str:
        return f"{value:.2f}" if value is not None else "N/A"

    print("Per-asset optimal / breakeven:")
    for asset in sorted(by_asset_curve.keys()):
        opt = optimal[asset]
        max_t = _fmt_threshold(opt['max_net_threshold_cents'])
        breakeven_t = _fmt_threshold(opt['breakeven_threshold_cents'])
        print(
            f"  {asset:5s}  max@ {max_t:>6}c "
            f"net={opt['max_net_pnl_cents'] or 0:>8.2f}c "
            f"n={opt['max_net_round_trips'] or 0:>3}  "
            f"breakeven@ {breakeven_t:>6}c"
        )
    print()

    print("Fragility around base threshold:")
    f_overall = fragility["overall"]
    if f_overall:
        print(f"  Overall base {f_overall['base_threshold_cents']}c net={f_overall['base_net_pnl_cents']:.2f}c")
        for label in ["minus_20pct", "minus_10pct", "plus_10pct", "plus_20pct"]:
            t = f_overall.get(f"{label}_threshold_cents")
            n = f_overall.get(f"{label}_net_pnl_cents")
            d = f_overall.get(f"{label}_delta_cents")
            if t is not None:
                print(f"    {label:12s} {t:6.2f}c -> net={n:8.2f}c  delta={d:+8.2f}c")
    for asset in sorted(by_asset_curve.keys()):
        f = fragility.get(asset, {})
        if not f:
            continue
        print(f"  {asset:5s} base {f.get('base_threshold_cents')}c net={f.get('base_net_pnl_cents'):.2f}c")
        for label in ["minus_20pct", "minus_10pct", "plus_10pct", "plus_20pct"]:
            t = f.get(f"{label}_threshold_cents")
            n = f.get(f"{label}_net_pnl_cents")
            d = f.get(f"{label}_delta_cents")
            if t is not None:
                print(f"    {label:12s} {t:6.2f}c -> net={n:8.2f}c  delta={d:+8.2f}c")
    print()
    print(f"  Reports written: {meta['output_json']} and {meta['output_csv']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Layer-4 edge threshold sensitivity sweep")
    parser.add_argument(
        "--round-trips",
        type=Path,
        default=None,
        help="Round-trip CSV (defaults to most recent reports/last_24h_round_trips_and_open_positions_*.csv)",
    )
    parser.add_argument(
        "--start",
        type=float,
        default=0.0,
        help="Threshold sweep start in cents (default 0.0; use -50.0 to include all losers and see the all-trades baseline)",
    )
    parser.add_argument(
        "--end",
        type=float,
        default=15.0,
        help="Threshold sweep end in cents (default 15.0)",
    )
    parser.add_argument(
        "--step",
        type=float,
        default=0.5,
        help="Threshold sweep step in cents (default 0.5)",
    )
    parser.add_argument(
        "--base-threshold-cents",
        type=float,
        default=None,
        help="Base threshold for fragility analysis (default 8.0, the code's implied gross threshold)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports"),
        help="Directory for output reports",
    )
    args = parser.parse_args()

    base = args.base_threshold_cents if args.base_threshold_cents is not None else 8.0
    report = run_sweep(
        round_trips_path=args.round_trips,
        threshold_start_cents=args.start,
        threshold_end_cents=args.end,
        threshold_step_cents=args.step,
        base_threshold_cents=base,
        output_dir=args.output_dir,
    )
    _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
