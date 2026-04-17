#!/usr/bin/env python3
"""C5: Post-close automation script.

Runs after each trading session:
  1. Export fills to CSV (data/fills_<date>.csv)
  2. Run Brier update for any markets resolved today
  3. Print top-5 trades by PnL for hand-review

Usage:
    python scripts/post_close.py [--date YYYY-MM-DD] [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _export_fills(date_str: str, dry_run: bool) -> int:
    """Export today's fills to CSV. Returns number of fills exported."""
    try:
        from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
        tracker = get_agent_performance_tracker()
        all_metrics = tracker.get_all_metrics()

        rows = []
        for agent_id, metrics in all_metrics.items():
            for record in getattr(tracker, "_trades", {}).get(agent_id, []):
                rows.append({
                    "date": date_str,
                    "agent_id": agent_id,
                    "market_id": getattr(record, "market_id", ""),
                    "side": getattr(record, "side", ""),
                    "entry_price_cents": getattr(record, "entry_price_cents", 0),
                    "exit_price_cents": getattr(record, "exit_price_cents", "") or "",
                    "contracts": getattr(record, "contracts", 0),
                    "predicted_edge": round(getattr(record, "predicted_edge", 0.0), 4),
                    "realized_edge": round(getattr(record, "realized_edge", 0.0) or 0.0, 4),
                    "profit_usd": str(getattr(record, "profit_usd", "") or ""),
                    "outcome": getattr(record, "outcome", "") or "",
                })

        if not rows:
            print(f"[post_close] No fill records found for {date_str}")
            return 0

        out_dir = Path("data")
        out_dir.mkdir(exist_ok=True)
        csv_path = out_dir / f"fills_{date_str}.csv"

        if dry_run:
            print(f"[post_close] DRY RUN: would write {len(rows)} fills to {csv_path}")
        else:
            with open(csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            print(f"[post_close] Exported {len(rows)} fills → {csv_path}")

        return len(rows)

    except Exception as exc:
        print(f"[post_close] Fill export failed: {exc}")
        return 0


def _run_brier_update(dry_run: bool) -> None:
    """Trigger Brier score recomputation for resolved markets."""
    try:
        from merid.prediction.consensus import get_prediction_consensus_store
        store = get_prediction_consensus_store()
        scores = store.compute_brier_scores(window=100)

        swarm = scores.get("swarm_brier")
        resolved = scores.get("resolved_count", 0)
        agent_briers = scores.get("agent_briers", {})

        print(f"\n[post_close] Brier Update — {resolved} resolved markets")
        if swarm is not None:
            print(f"  Swarm Brier:   {swarm:.4f}  (lower is better; random=0.25)")
        else:
            print("  Swarm Brier:   no resolved markets yet")

        if agent_briers:
            print("  Per-agent Brier:")
            for agent, b in sorted(agent_briers.items(), key=lambda x: x[1]):
                tag = "✓" if b < 0.15 else ("!" if b > 0.25 else " ")
                print(f"    {tag} {agent:<40} {b:.4f}")

        if not dry_run:
            # Invalidate the weight cache so next consensus uses fresh weights
            store._brier_weights_ts = 0.0
            print("  [post_close] Brier weight cache invalidated.")

    except Exception as exc:
        print(f"[post_close] Brier update failed: {exc}")


def _print_top_trades(n: int = 5) -> None:
    """Print the top-N trades by PnL for manual review."""
    try:
        from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
        from decimal import Decimal
        tracker = get_agent_performance_tracker()

        all_trades = []
        for agent_id, trade_list in getattr(tracker, "_trades", {}).items():
            for record in trade_list:
                pnl = getattr(record, "profit_usd", None)
                if pnl is not None:
                    all_trades.append((agent_id, record, float(pnl)))

        if not all_trades:
            print("\n[post_close] No closed trades to review.")
            return

        all_trades.sort(key=lambda x: x[2], reverse=True)
        top_n = all_trades[:n]
        worst_n = all_trades[-n:]

        print(f"\n[post_close] Top {n} trades by PnL:")
        for agent_id, rec, pnl in top_n:
            print(
                f"  +{pnl:+.2f}  {agent_id}  {getattr(rec, 'market_id', '')}  "
                f"{getattr(rec, 'side', '')}  entry={getattr(rec, 'entry_price_cents', 0)}c"
            )

        print(f"\n[post_close] Worst {n} trades by PnL:")
        for agent_id, rec, pnl in worst_n:
            print(
                f"  {pnl:+.2f}  {agent_id}  {getattr(rec, 'market_id', '')}  "
                f"{getattr(rec, 'side', '')}  entry={getattr(rec, 'entry_price_cents', 0)}c"
            )

    except Exception as exc:
        print(f"[post_close] Trade review failed: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="MERID post-close automation")
    parser.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        help="Session date (YYYY-MM-DD), default=today")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print actions without writing files")
    parser.add_argument("--top", type=int, default=5,
                        help="Number of top/worst trades to display")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"MERID Post-Close Report — {args.date}")
    print(f"{'='*60}")

    n_fills = _export_fills(args.date, dry_run=args.dry_run)
    _run_brier_update(dry_run=args.dry_run)
    _print_top_trades(n=args.top)

    print(f"\n[post_close] Done. {n_fills} fills processed.")


if __name__ == "__main__":
    main()
