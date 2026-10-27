"""CLI for the independent forecast-audit scorer.

    python -m merid.analysis.forecast_audit \
        --db data/decision_audit.db \
        --model-cal logs/model_calibration_observations.jsonl \
        --outcomes logs/settlement_outcomes.jsonl \
        --json-out reports/forecast_audit.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .report import AuditConfig, build_report, print_summary


def _parse_iso(value: str):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _floats(value: str):
    return tuple(float(x) for x in value.split(",") if x.strip())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="merid.analysis.forecast_audit",
        description="Independent paired forecast scorer for Kalshi 15m crypto.",
    )
    ap.add_argument("--db", default="data/decision_audit.db")
    ap.add_argument("--model-cal", default="logs/model_calibration_observations.jsonl")
    ap.add_argument("--outcomes", default="logs/settlement_outcomes.jsonl")
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--horizons", type=_floats, default=None,
                    help="comma list, seconds before close (default 600,300,120,60)")
    ap.add_argument("--max-age", type=float, default=90.0,
                    help="max snapshot age before target (s)")
    ap.add_argument("--folds", type=int, default=4)
    ap.add_argument("--min-train", type=int, default=200)
    ap.add_argument("--replicates", type=int, default=2000)
    ap.add_argument("--block-lens", type=_floats, default=None,
                    help="comma list of block lengths s (default 1800,3600,7200,14400)")
    ap.add_argument("--primary-block-len", type=float, default=3600.0)
    ap.add_argument("--seed", type=int, default=20261023)
    ap.add_argument("--assets", default="BTC,ETH,SOL,XRP,DOGE")
    ap.add_argument("--min-support", type=int, default=50)
    ap.add_argument("--since", default=None,
                    help="ISO lower bound on contract close_ts (inclusion window)")
    ap.add_argument("--until", default=None,
                    help="ISO upper bound on contract close_ts (inclusion window)")
    ap.add_argument("--label-policy", choices=("observed_only", "grace"),
                    default="observed_only",
                    help="walk-forward training label availability policy "
                         "(observed_only = documented observed_at_utc only; "
                         "grace = + settlement_ts + 300s assumption, "
                         "sensitivity only)")
    ap.add_argument("--export-joins", default=None, metavar="PATH",
                    help="write the deterministic anchored-join record "
                         "(accepted/rejected/ambiguous) as JSONL to PATH")
    ap.add_argument("--econ", action="store_true",
                    help="include fill-economics join (full outcomes-table scan)")
    ap.add_argument("--row-counts", action="store_true",
                    help="include total/eligible decision-row counts (full table scan)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    cfg = AuditConfig(
        db_path=args.db,
        model_cal_path=args.model_cal,
        outcomes_path=args.outcomes,
        horizons_s=args.horizons or (600.0, 300.0, 120.0, 60.0),
        max_age_s=args.max_age,
        n_folds=args.folds,
        min_train_n=args.min_train,
        replicates=args.replicates,
        block_lens_s=args.block_lens or (1800.0, 3600.0, 7200.0, 14400.0),
        primary_block_len_s=args.primary_block_len,
        seed=args.seed,
        assets=tuple(a.strip().upper() for a in args.assets.split(",")),
        min_support=args.min_support,
        since_ts=_parse_iso(args.since) if args.since else None,
        until_ts=_parse_iso(args.until) if args.until else None,
        include_row_counts=args.row_counts,
        include_econ=args.econ,
        label_policy=args.label_policy,
        export_joins_path=args.export_joins,
    )
    if cfg.primary_block_len_s not in cfg.block_lens_s:
        ap.error("--primary-block-len must be one of --block-lens")

    report = build_report(cfg, progress=not args.quiet)

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"wrote {out}")
    if not args.quiet:
        print_summary(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
