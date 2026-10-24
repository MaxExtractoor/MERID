#!/usr/bin/env python
"""Phase-B all-gates audit runner — shadow-only, offline replay.

Streams decision_records from logs/decision_telemetry.jsonl, evaluates the
full gate vector + accounting identity + threshold decomposition (+ named
policy variants) per side, writes per-record audits to
logs/all_gates_audit.jsonl, and prints the ten-lane funnel + sole-blocker
attribution.

Usage:
    python scripts/all_gates_audit.py [--limit N] [--out PATH] [--last N]
"""
import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.prediction.all_gates_audit import (  # noqa: E402
    AuditSummary, evaluate_record, load_decision_records)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default="logs/decision_telemetry.jsonl")
    ap.add_argument("--out", default="logs/all_gates_audit.jsonl")
    ap.add_argument("--limit", type=int, default=0,
                    help="max records to evaluate (0 = all)")
    ap.add_argument("--last", type=int, default=0,
                    help="only the last N records (reads all, keeps tail)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    summ = AuditSummary()
    n_out = 0
    with open(args.out, "w") as fout:
        records = load_decision_records(args.path, limit=args.limit)
        if args.last:
            import collections
            records = iter(collections.deque(records, maxlen=args.last))
        for rec in records:
            try:
                audit = evaluate_record(rec)
            except Exception as exc:
                audit = {"type": "all_gates_audit",
                         "error": f"{type(exc).__name__}: {exc}",
                         "ticker": rec.get("ticker")}
            if audit is None:
                continue
            summ.add(audit) if "error" not in audit else None
            fout.write(json.dumps(audit, default=str) + "\n")
            n_out += 1
    if not args.quiet:
        print(summ.report())
        print(f"\nwrote {n_out} audit records -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
