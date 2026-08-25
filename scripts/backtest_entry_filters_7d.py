#!/usr/bin/env python3
"""
Backtest the held-side entry-price floor and tail calibration against the
corrected 7-day trade data.

The 7-day data showed that contracts with held-side price <20c lost 0/16,
while 20-29c contracts won 60%.  This script measures how much PnL is saved by
blocking the cheap tail.

Usage:
    python scripts/backtest_entry_filters_7d.py \
        --input trade_analysis_raw_7d.json \
        --floor-cents 20 \
        --output output/backtest_entry_filters_7d.json
"""

import argparse
import json
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))


def held_entry_dollars(row: Dict[str, Any]) -> Decimal:
    price = Decimal(str(row["price"]))
    action = (row.get("action") or "").lower()
    return price if action == "buy" else Decimal(1) - price


def run_backtest(rows: List[Dict[str, Any]], floor_cents: int) -> Dict[str, Any]:
    floor_dollars = Decimal(floor_cents) / Decimal(100)

    baseline = Decimal("0")
    floor_pnl = Decimal("0")
    blocked: List[Dict[str, Any]] = []
    allowed: List[Dict[str, Any]] = []

    for r in rows:
        pnl = Decimal(str(r["pnl"]))
        baseline += pnl
        held = held_entry_dollars(r)
        if held < floor_dollars:
            blocked.append({**r, "held_entry_dollars": float(held)})
        else:
            allowed.append(r)
            floor_pnl += pnl

    # Baseline stats
    cheap = [r for r in rows if held_entry_dollars(r) < floor_dollars]
    cheap_pnl = sum(Decimal(str(r["pnl"])) for r in cheap)

    # Stats by 10c bucket (held side)
    buckets = defaultdict(lambda: {"n": 0, "wins": 0, "pnl": Decimal("0")})
    for r in rows:
        held = held_entry_dollars(r)
        bucket = int(held / Decimal("0.10")) * 10
        buckets[bucket]["n"] += 1
        if r.get("win"):
            buckets[bucket]["wins"] += 1
        buckets[bucket]["pnl"] += Decimal(str(r["pnl"]))

    by_bucket = []
    for b in sorted(buckets):
        data = buckets[b]
        by_bucket.append(
            {
                "held_entry_cents_min": b,
                "held_entry_cents_max": b + 9,
                "trades": data["n"],
                "wins": data["wins"],
                "win_rate": round(data["wins"] / data["n"] * 100, 1) if data["n"] else None,
                "pnl": float(data["pnl"]),
            }
        )

    return {
        "summary": {
            "floor_cents": floor_cents,
            "total_trades": len(rows),
            "trades_blocked_by_floor": len(blocked),
            "trades_allowed": len(allowed),
            "baseline_pnl": float(baseline),
            "floor_pnl": float(floor_pnl),
            "cheap_tail_pnl": float(cheap_pnl),
            "improvement_from_floor": float(floor_pnl - baseline),
        },
        "blocked_trades": blocked,
        "held_side_calibration_by_bucket": by_bucket,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backtest held-side entry floor against 7-day data"
    )
    parser.add_argument("--input", type=str, default="trade_analysis_raw_7d.json")
    parser.add_argument("--floor-cents", type=int, default=20)
    parser.add_argument(
        "--output", type=str, default="output/backtest_entry_filters_7d.json"
    )
    args = parser.parse_args()

    with open(args.input, "r") as f:
        data = json.load(f)
    rows = data.get("trades", data if isinstance(data, list) else [])

    result = run_backtest(rows, args.floor_cents)

    print("=" * 70)
    print("7-DAY ENTRY-FLOOR BACKTEST")
    print("=" * 70)
    s = result["summary"]
    print(f"Floor:              {s['floor_cents']}c held-side price")
    print(f"Total trades:       {s['total_trades']}")
    print(f"Blocked by floor:   {s['trades_blocked_by_floor']}")
    print(f"Allowed:            {s['trades_allowed']}")
    print(f"Baseline PnL:       ${s['baseline_pnl']:+.2f}")
    print(f"Floor-filtered PnL: ${s['floor_pnl']:+.2f}")
    print(f"PnL of blocked:     ${s['cheap_tail_pnl']:+.2f}")
    print(f"Improvement:        ${s['improvement_from_floor']:+.2f}")
    print()
    print("Held-side calibration by entry bucket:")
    for b in result["held_side_calibration_by_bucket"]:
        print(
            f"  {b['held_entry_cents_min']:2d}-{b['held_entry_cents_max']:2d}c: "
            f"n={b['trades']:3d}  wr={b['win_rate']:5.1f}%  pnl=${b['pnl']:+.2f}"
        )
    print()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"Saved full results to {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
