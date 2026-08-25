#!/usr/bin/env python3
"""
Backtest stop-loss rules against the corrected 7-day trade data.

This script is intentionally limited by the data it has:
- entry time, entry price, held side, quantity, fee
- final settlement (win/loss)

It does NOT have the intraday price path or the live model probability,
so it cannot faithfully replay an edge-decay stop.  Instead it:
1. Computes the baseline PnL (no stop).
2. Computes the hard-stop PnL (all losers exit at entry - STOP_BUFFER).
3. Computes an edge-decay sensitivity table: how the PnL changes if the
   edge-decay stop fills at hard + k cents for k=0..5.  This is the
   realistic range a model-based exit can improve over the hard stop.
4. Reports market calibration by entry-price bucket so you can see whether
   the model has any edge to harvest.

Usage:
    python scripts/backtest_stop_loss_7d.py \
        --input trade_analysis_raw_7d.json \
        --output output/backtest_stop_loss_7d.json
"""

import argparse
import json
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))


STOP_BUFFER_DOLLARS = Decimal("0.05")  # default MERID_STOP_PRICE_BUFFER_CENTS = 5c
TICK = Decimal("0.01")
MAX_EDGE_SENSE_CENTS = 5


def held_entry_dollars(row: Dict[str, Any]) -> Decimal:
    """Return the held-side entry price in dollars.

    BUY YES  -> price is yes_price, held side is YES.
    BUY NO   -> price is no_price, held side is NO.
    SELL NO  -> price is no_price, held side is YES, value = 1 - no_price.
    SELL YES -> price is yes_price, held side is NO, value = 1 - yes_price.
    """
    price = Decimal(str(row["price"]))
    action = (row.get("action") or "").lower()
    if action == "buy":
        return price
    return Decimal("1") - price


def held_settlement_dollars(row: Dict[str, Any]) -> Decimal:
    """Held side settles at 1 if it won, 0 if it lost."""
    return Decimal("1") if row.get("win") else Decimal("0")


def actual_pnl(row: Dict[str, Any]) -> Decimal:
    return Decimal(str(row["pnl"]))


def pnl_for_exit(
    row: Dict[str, Any],
    held_exit: Decimal,
    fee: Decimal,
) -> Decimal:
    """PnL for closing a long position at held_exit (held-side price)."""
    held_entry = held_entry_dollars(row)
    qty = Decimal(str(row["quantity"]))
    return (held_exit - held_entry) * qty - fee


def hard_stop_exit(held_entry: Decimal, buffer: Decimal = STOP_BUFFER_DOLLARS) -> Decimal:
    return max(TICK, held_entry - buffer)


def run_backtest(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    baseline = sum(actual_pnl(r) for r in rows)

    hard_pnls: List[Decimal] = []
    for r in rows:
        fee = Decimal(str(r["fee"]))
        if r.get("loss"):
            held_entry = held_entry_dollars(r)
            exit_price = hard_stop_exit(held_entry)
            hard_pnls.append(pnl_for_exit(r, exit_price, fee))
        else:
            hard_pnls.append(actual_pnl(r))
    hard_total = sum(hard_pnls)

    # Edge-decay sensitivity: exit at hard + k cents, up to the held entry.
    # This answers the question: "if the model lets us fill k cents above the
    # hard stop, how much better is the 7-day PnL?"
    sensitivity: List[Dict[str, Any]] = []
    for k_cents in range(0, MAX_EDGE_SENSE_CENTS + 1):
        k_dollars = Decimal(k_cents) / Decimal(100)
        edge_pnls: List[Decimal] = []
        for r in rows:
            fee = Decimal(str(r["fee"]))
            if r.get("loss"):
                held_entry = held_entry_dollars(r)
                hard_exit = hard_stop_exit(held_entry)
                # Better fill by k cents, but never above the entry price.
                # Exiting above entry would turn a loser into a profit; the
                # backtest marks that as an unclamped "edge" fill.
                exit_price = min(held_entry, hard_exit + k_dollars)
                exit_price = max(TICK, exit_price)
                edge_pnls.append(pnl_for_exit(r, exit_price, fee))
            else:
                edge_pnls.append(actual_pnl(r))
        edge_total = sum(edge_pnls)
        sensitivity.append(
            {
                "k_cents_above_hard": k_cents,
                "total_pnl": float(edge_total),
                "improvement_vs_hard": float(edge_total - hard_total),
                "improvement_vs_baseline": float(edge_total - baseline),
            }
        )

    # Market calibration by held-side entry price bucket.
    # If the market is already calibrated, the model must add edge on top of it.
    buckets = defaultdict(lambda: {"n": 0, "wins": 0, "pnl": Decimal("0")})
    for r in rows:
        held_entry = held_entry_dollars(r)
        bucket = int(held_entry / Decimal("0.10")) * 10  # 0-9, 10-19, ... cents
        buckets[bucket]["n"] += 1
        if r.get("win"):
            buckets[bucket]["wins"] += 1
        buckets[bucket]["pnl"] += actual_pnl(r)

    calibration = []
    for b in sorted(buckets):
        data = buckets[b]
        n = data["n"]
        calibration.append(
            {
                "held_entry_cents_min": b,
                "held_entry_cents_max": b + 9,
                "trades": n,
                "wins": data["wins"],
                "actual_win_rate": round(data["wins"] / n * 100, 1) if n else None,
                "implied_win_rate": round((b + 5), 1),  # mid-point of bucket
                "pnl": float(data["pnl"]),
            }
        )

    return {
        "summary": {
            "total_trades": len(rows),
            "wins": sum(1 for r in rows if r.get("win")),
            "losses": sum(1 for r in rows if r.get("loss")),
            "baseline_pnl": float(baseline),
            "hard_stop_pnl": float(hard_total),
            "hard_stop_improvement": float(hard_total - baseline),
            "stop_buffer_cents": int(STOP_BUFFER_DOLLARS * 100),
        },
        "edge_decay_sensitivity_cents": sensitivity,
        "market_calibration_by_entry_cents": calibration,
        "notes": [
            "Edge-decay backtest uses a sensitivity table because the 7-day JSON does not include the live model probability or intraday price path.",
            "A real edge-decay stop sits between the hard stop and the held-side entry price; the table shows the PnL impact of filling k cents above the hard stop.",
            "To backtest the actual model path, add StopCandidate telemetry (fair_value_cents, current_edge_cents, stop_level_cents) to the stop ledger and re-run after the next 7-day period.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest stop rules against 7-day trade data")
    parser.add_argument("--input", type=str, default="trade_analysis_raw_7d.json", help="Input JSON from analyze_trade_outcomes")
    parser.add_argument("--output", type=str, default="output/backtest_stop_loss_7d.json", help="Output JSON file")
    args = parser.parse_args()

    with open(args.input, "r") as f:
        data = json.load(f)

    rows = data.get("trades", data if isinstance(data, list) else [])
    if not rows:
        print("No trades found in input.")
        return 1

    result = run_backtest(rows)

    print("=" * 70)
    print("7-DAY STOP-LOSS BACKTEST")
    print("=" * 70)
    s = result["summary"]
    print(f"Total trades: {s['total_trades']} (wins={s['wins']}, losses={s['losses']})")
    print(f"Baseline PnL (no stop):     ${s['baseline_pnl']:+.2f}")
    print(f"Hard stop PnL (-{s['stop_buffer_cents']}c buffer):  ${s['hard_stop_pnl']:+.2f}")
    print(f"Hard stop improvement:      ${s['hard_stop_improvement']:+.2f}")
    print()
    print("Edge-decay sensitivity (fill k cents above hard stop):")
    for row in result["edge_decay_sensitivity_cents"]:
        print(
            f"  +{row['k_cents_above_hard']:d}c: PnL=${row['total_pnl']:+.2f}  "
            f"(vs hard {row['improvement_vs_hard']:+.2f}, vs baseline {row['improvement_vs_baseline']:+.2f})"
        )
    print()
    print("Market calibration by held-side entry price:")
    for c in result["market_calibration_by_entry_cents"][:6]:
        print(
            f"  {c['held_entry_cents_min']:2d}-{c['held_entry_cents_max']:2d}c: "
            f"n={c['trades']:3d}  actual_wr={c['actual_win_rate']:5.1f}%  "
            f"implied_wr={c['implied_win_rate']:5.1f}%  pnl=${c['pnl']:+.2f}"
        )
    print()
    print(result["notes"][0])
    print(result["notes"][1])
    print()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"Saved full results to {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
