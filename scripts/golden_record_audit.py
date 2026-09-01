#!/usr/bin/env python3
"""CLI to build the per-trade golden record and emit a summary report.

Reads the durable telemetry emitted by the live 15m stack and writes a joined
intent → order → fill → settlement → P&L view to ``data/golden_records.jsonl``
and ``data/golden_records.db``.  The report at ``reports/golden_record_audit_*.json``
contains the high-level divergence counts.

This script is read-only; it never connects to Kalshi or modifies trading state.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Allow running from the repo root directly.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from merid.monitoring.golden_record_rollup import build_golden_records


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str, sort_keys=True)


def main(argv: Optional[Any] = None) -> int:
    parser = argparse.ArgumentParser(description="Build the MERID per-trade golden record.")
    parser.add_argument("--fact-db", default=None, help="Path to trade_attribution_fact.db")
    parser.add_argument("--decision-telemetry", default=None, help="Path to decision_telemetry.jsonl")
    parser.add_argument("--settlement-outcomes", default=None, help="Path to settlement_outcomes.jsonl")
    parser.add_argument("--fills-db", default=None, help="Path to kalshi_fills.db (fallback enrichment)")
    parser.add_argument("--lookback-hours", type=int, default=72, help="How far back to read telemetry")
    parser.add_argument("--out-jsonl", default=None, help="Output golden records JSONL")
    parser.add_argument("--out-db", default=None, help="Output golden records SQLite DB")
    parser.add_argument("--out-report", default=None, help="Output JSON summary report")
    parser.add_argument(
        "--append-db",
        action="store_true",
        default=False,
        help="Append to the output DB instead of rebuilding",
    )
    args = parser.parse_args(argv)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_report = Path(args.out_report) if args.out_report else Path(f"reports/golden_record_audit_{ts}.json")

    records, summary = build_golden_records(
        fact_db=args.fact_db,
        decision_telemetry=args.decision_telemetry,
        settlement_outcomes=args.settlement_outcomes,
        fills_db=args.fills_db,
        lookback_hours=args.lookback_hours,
        out_jsonl=args.out_jsonl,
        out_db=args.out_db,
        rebuild_db=not args.append_db,
    )

    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "summary": summary.to_dict(),
        "top_divergences": [
            {
                "record_id": r.record_id,
                "ticker": r.ticker,
                "intent_id": r.intent_id,
                "lifecycle_status": r.lifecycle_status,
                "divergence_flags": r.divergence_flags,
            }
            for r in records
            if r.divergence_flags
        ][:100],
    }

    _write_json(out_report, report)

    print(f"Wrote {len(records)} golden records")
    print(f"  JSONL:  {summary.out_jsonl}")
    print(f"  DB:     {summary.out_db}")
    print(f"  Report: {out_report}")
    print(
        f"  Status: selected={summary.intent_count} ordered={summary.ordered_count} "
        f"filled={summary.filled_count} settled={summary.settled_count} "
        f"rejected={summary.rejected_count} exit={summary.exit_count}"
    )
    print(
        f"  Divergences: {summary.divergence_count} "
        f"(missing_settlement={summary.missing_settlement_for_settled_market}, "
        f"missing_pnl={summary.missing_pnl}, side_mismatch={summary.side_mismatch_count}, "
        f"qty_mismatch={summary.qty_mismatch_count}, settlement_mismatch={summary.settlement_mismatch_count})"
    )

    if summary.errors:
        print(f"  Errors: {len(summary.errors)}")
        for err in summary.errors[:10]:
            print(f"    - {err}")

    return 0 if not summary.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
