#!/usr/bin/env python3
"""Interim market-calibration check against 24h fills + settlements.

Reads:
- reports/last_24h_fills_with_pairing_and_settlement_*.csv

Produces:
- reports/interim_market_calibration_YYYYmmdd_HHMMSS.json

This is a lightweight, pre-decision-log calibration test. It asks: "Is the
Kalshi market price (at MERID's entry) a calibrated probability?" For each
entry fill it compares the YES price paid/received to the actual YES/NO
settlement. If the market is efficient, a 55c YES price should settle YES ~55%
of the time.

This does NOT replace the model calibration in Layer 2 — it is a baseline for
whether there is any raw edge in the market price itself. If the market is
calibrated, then MERID's excess returns must come from its model, not from
trading the market's own probability.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, List, Optional, Sequence, Tuple


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None or value == "":
        return default
    try:
        f = float(value)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def _brier(pairs: Sequence[Tuple[float, int]]) -> Optional[float]:
    if not pairs:
        return None
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs)


def _calibration_bias(pairs: Sequence[Tuple[float, int]]) -> Optional[float]:
    if not pairs:
        return None
    return sum(p - y for p, y in pairs) / len(pairs)


def _load_fills(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def _price_bucket(price_cents: float) -> str:
    if price_cents < 10:
        return "<10c"
    if price_cents < 20:
        return "10-19c"
    if price_cents < 30:
        return "20-29c"
    if price_cents < 40:
        return "30-39c"
    if price_cents < 45:
        return "40-44c"
    if price_cents < 50:
        return "45-49c"
    if price_cents < 55:
        return "50-54c"
    if price_cents < 60:
        return "55-59c"
    if price_cents < 70:
        return "60-69c"
    if price_cents < 80:
        return "70-79c"
    if price_cents < 90:
        return "80-89c"
    return "90c+"


def _is_entry_fill(row: Dict[str, Any]) -> bool:
    # Use the immutable entry flag if available.
    if row.get("entry_or_exit") == "entry":
        return True
    if str(row.get("is_exit")) == "0":
        return True
    if str(row.get("fill_role")) == "entry":
        return True
    # Fallback: classify as entry when it has round_trip_ids and is not an exit.
    if row.get("round_trip_ids") and str(row.get("is_exit")) in ("", "0", "False"):
        return True
    return False


def _analyze(pairs: Sequence[Tuple[float, int]]) -> Dict[str, Any]:
    n = len(pairs)
    if n == 0:
        return {
            "n": 0,
            "avg_market_prob": None,
            "observed_yes_rate": None,
            "calibration_bias": None,
            "brier": None,
        }
    return {
        "n": n,
        "avg_market_prob": round(mean(p for p, _ in pairs), 4),
        "observed_yes_rate": round(mean(y for _, y in pairs), 4),
        "calibration_bias": round(_calibration_bias(pairs), 4),
        "brier": round(_brier(pairs), 4),
    }


def run_calibration(
    fills_path: Optional[Path] = None,
    output_dir: Path = Path("reports"),
) -> Dict[str, Any]:
    if fills_path is None:
        candidates = list(Path("reports").glob("last_24h_fills_with_pairing_and_settlement_*.csv"))
        if not candidates:
            raise FileNotFoundError("No fills CSV found. Pass --fills.")
        fills_path = max(candidates, key=lambda p: p.stat().st_mtime)

    fills = _load_fills(fills_path)

    # Collect one observation per entry fill: market YES price vs actual YES outcome.
    by_asset: Dict[str, List[Tuple[float, int]]] = defaultdict(list)
    by_bucket: Dict[str, List[Tuple[float, int]]] = defaultdict(list)
    by_asset_bucket: Dict[Tuple[str, str], List[Tuple[float, int]]] = defaultdict(list)

    # Track MERID's side selection win rate vs the market baseline.
    merid_side: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "buy_yes_wins": 0, "buy_yes_total": 0,
        "sell_yes_wins": 0, "sell_yes_total": 0,
    })

    for row in fills:
        if not _is_entry_fill(row):
            continue

        asset = str(row.get("asset") or "").upper()
        price = _safe_float(row.get("execution_price_cents"))
        market_result = str(row.get("market_result") or "").upper()

        if price is None or market_result not in ("YES", "NO"):
            continue

        yes_prob = price / 100.0
        observed_yes = 1 if market_result == "YES" else 0

        by_asset[asset].append((yes_prob, observed_yes))
        bucket = _price_bucket(price)
        by_bucket[bucket].append((yes_prob, observed_yes))
        by_asset_bucket[(asset, bucket)].append((yes_prob, observed_yes))

        # Track MERID side selection. For side=yes fills:
        #   buy  = long YES  (wins if market_result == YES)
        #   sell = short YES / long NO (wins if market_result == NO)
        action = (row.get("canonical_position_action") or row.get("action") or "").lower()
        if action == "buy":
            merid_side[asset]["buy_yes_total"] += 1
            if market_result == "YES":
                merid_side[asset]["buy_yes_wins"] += 1
        elif action == "sell":
            merid_side[asset]["sell_yes_total"] += 1
            if market_result == "NO":
                merid_side[asset]["sell_yes_wins"] += 1

    overall = _analyze([(p, y) for pairs in by_asset.values() for p, y in pairs])
    bucket_summary = {bucket: _analyze(pairs) for bucket, pairs in sorted(by_bucket.items())}
    asset_summary = {asset: _analyze(pairs) for asset, pairs in sorted(by_asset.items())}

    by_asset_bucket_table: List[Dict[str, Any]] = []
    for (asset, bucket), pairs in sorted(by_asset_bucket.items()):
        stats = _analyze(pairs)
        if stats["n"] > 0:
            by_asset_bucket_table.append({
                "asset": asset,
                "price_bucket": bucket,
                **stats,
            })

    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"interim_market_calibration_{now}.json"
    output_dir.mkdir(parents=True, exist_ok=True)

    merid_side_table = []
    for asset, d in sorted(merid_side.items()):
        buy_wr = d["buy_yes_wins"] / d["buy_yes_total"] if d["buy_yes_total"] else None
        sell_wr = d["sell_yes_wins"] / d["sell_yes_total"] if d["sell_yes_total"] else None
        merid_side_table.append({
            "asset": asset,
            "long_yes_n": d["buy_yes_total"],
            "long_yes_win_rate": round(buy_wr, 4) if buy_wr is not None else None,
            "short_yes_n": d["sell_yes_total"],
            "short_yes_win_rate": round(sell_wr, 4) if sell_wr is not None else None,
        })

    report = {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "fills_source": str(fills_path),
            "total_entry_fills": sum(len(v) for v in by_asset.values()),
            "output_json": str(json_path),
            "caveat": (
                "This tests the market price as a probability, not MERID's model. "
                "It is an interim baseline until decision_telemetry carries "
                "model_prob_selected and raw_edge_cents."
            ),
        },
        "overall": overall,
        "by_asset": asset_summary,
        "by_price_bucket": bucket_summary,
        "by_asset_and_bucket": by_asset_bucket_table,
        "merid_side_selection": merid_side_table,
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    return report


def _print_report(report: Dict[str, Any]) -> None:
    meta = report["_meta"]
    overall = report["overall"]

    print("Interim market calibration (market price as probability)")
    print(f"  source: {meta['fills_source']}")
    print(f"  entry fills: {meta['total_entry_fills']}")
    print()

    print(f"Overall:")
    print(f"  n={overall['n']}")
    print(f"  avg market-implied p(YES): {overall['avg_market_prob']:.2%}")
    print(f"  observed YES rate:          {overall['observed_yes_rate']:.2%}")
    print(f"  calibration bias:           {overall['calibration_bias']:.4f}  (+ = market overpriced YES)")
    print(f"  Brier score:                {overall['brier']:.4f}  (0.25 = coin flip)")
    print()

    if overall["calibration_bias"] is not None and overall["calibration_bias"] > 0.05:
        print("  Market appears to overprice YES relative to observed settlement.")
    elif overall["calibration_bias"] is not None and overall["calibration_bias"] < -0.05:
        print("  Market appears to underprice YES relative to observed settlement.")
    else:
        print("  Market-implied p(YES) is roughly in line with observed settlement rate.")
    print()

    print("By asset:")
    for asset, stats in sorted(report["by_asset"].items()):
        print(
            f"  {asset:5s}  n={stats['n']:3d}  "
            f"market_p={stats['avg_market_prob']:.2%}  "
            f"obs={stats['observed_yes_rate']:.2%}  "
            f"bias={stats['calibration_bias']:+.4f}  "
            f"brier={stats['brier']:.4f}"
        )
    print()

    print("By price bucket:")
    for bucket, stats in report["by_price_bucket"].items():
        print(
            f"  {bucket:8s}  n={stats['n']:3d}  "
            f"market_p={stats['avg_market_prob']:.2%}  "
            f"obs={stats['observed_yes_rate']:.2%}  "
            f"bias={stats['calibration_bias']:+.4f}"
        )
    print()

    print("MERID side selection (does MERID pick the right side?):")
    print("  asset   long_yes_wr  short_yes_wr  expected_yes_rate")
    for asset, stats in sorted(report["by_asset"].items()):
        row = next((r for r in report["merid_side_selection"] if r["asset"] == asset), None)
        if row:
            long = f"{row['long_yes_win_rate']:.2%}" if row['long_yes_win_rate'] is not None else "N/A"
            short = f"{row['short_yes_win_rate']:.2%}" if row['short_yes_win_rate'] is not None else "N/A"
            print(f"  {asset:5s}   {long:>10s}   {short:>13s}   {stats['observed_yes_rate']:.2%}")
    print()
    print(f"  Report written: {meta['output_json']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Interim market calibration check")
    parser.add_argument(
        "--fills",
        type=Path,
        default=None,
        help="Fills CSV (defaults to most recent reports/last_24h_fills_with_pairing_and_settlement_*.csv)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports"),
        help="Directory for output reports",
    )
    args = parser.parse_args()

    report = run_calibration(fills_path=args.fills, output_dir=args.output_dir)
    _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
