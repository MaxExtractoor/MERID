"""Assemble the boundary-migration evidence package.

Runs (or ingests) the three artifacts the migration acceptance criteria
require and writes one versioned report:

1. ``boundary_resolution`` — resolver summary (sources, verification,
   boundary-minus-ledger deltas) from ``--resolution``.
2. ``population_diff`` — observation-level transitions between the
   ledger-mode and authoritative-mode ``--export-population`` JSONLs.
3. ``common_score`` — forecast verdicts on the common eligible population
   and each run's full population.

This module does NOT rerun the audits; it composes their outputs.  The
population JSONLs are produced by ``forecast_audit --export-population``.

CLI::

    py -3 -m merid.analysis.forecast_audit.migration_report \
        --resolution reports/boundary_resolution_2026-11-13.json \
        --before reports/pop_ledger_2026-11-14.jsonl \
        --after reports/pop_authoritative_2026-11-14.jsonl \
        --boundaries data/contract_boundaries_v1.jsonl \
        --out reports/boundary_migration_2026-11-14.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .population_diff import diff_entries, diff_units, load_population
from .common_score import (
    BLOCK_LENS, MIN_SUPPORT, PRIMARY_BLOCK_LEN_S, PRIMARY_METRIC,
    REPLICATES, SEED, _score_set, _units_by_key,
)
from .bootstrap import block_ids_for_units


def build_report(
    *,
    resolution_path: Optional[str],
    before_path: str,
    after_path: str,
    boundaries_path: Optional[str],
    out_path: Optional[str],
) -> Dict[str, Any]:
    be, bu = load_population(before_path)
    ae, au = load_population(after_path)

    # Shared calendar blocks via resolved contract boundary per ticker.
    boundary_close: Dict[str, float] = {}
    if boundaries_path:
        try:
            from .boundaries import load_boundaries
            for t, rec in load_boundaries(boundaries_path).items():
                if rec.contract_boundary_ts is not None:
                    boundary_close[t] = float(rec.contract_boundary_ts)
        except Exception as exc:
            print(f"WARNING: boundaries load failed: {exc}")

    def block_ids(units):
        close = [boundary_close.get(u["ticker"], u.get("close_ts"))
                 for u in units]
        return block_ids_for_units(close, PRIMARY_BLOCK_LEN_S)

    b_ids, b_n = block_ids(bu)
    a_ids, a_n = block_ids(au)
    full_before = _score_set(bu, block_of=b_ids, n_blocks=b_n,
                             label="before_full")
    full_after = _score_set(au, block_of=a_ids, n_blocks=a_n,
                            label="after_full")

    bmap = _units_by_key(bu)
    amap = _units_by_key(au)
    common_keys = sorted(k for k in set(bmap) & set(amap)
                         if bmap[k].get("y") is not None
                         and amap[k].get("y") is not None)
    cu_b = [bmap[k] for k in common_keys]
    cu_a = [amap[k] for k in common_keys]
    c_ids, c_n = block_ids(cu_b)
    common_before = _score_set(cu_b, block_of=c_ids, n_blocks=c_n,
                               label="common_before")
    common_after = _score_set(cu_a, block_of=c_ids, n_blocks=c_n,
                              label="common_after")

    resolution = None
    if resolution_path and Path(resolution_path).exists():
        resolution = json.loads(Path(resolution_path).read_text())

    report: Dict[str, Any] = {
        "schema": "boundary_migration_report_v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "acceptance_criteria": {
            "before_after_migration_report": True,
            "original_ledger_preserved": "sidecar only; decision_audit.db untouched",
            "changed_tickers_units_by_asset_horizon": "population_diff.by_asset_horizon",
            "threshold_crossings": "population_diff status/snapshot transitions + common_score verdict_transitions",
            "post_boundary_decisions": "entries with status/reason preserved in population export",
            "trusted_source_disagreements": "boundary_resolution.verification + quarantine classes",
            "verdicts_common_and_full": ["common_before", "common_after",
                                          "full_before", "full_after"],
        },
        "inputs": {
            "resolution": resolution_path,
            "before_population": before_path,
            "after_population": after_path,
            "boundaries": boundaries_path,
        },
        "resolution_summary": (
            {k: resolution.get(k) for k in (
                "n_tickers", "by_source", "by_verification_status",
                "boundary_minus_ledger_close_s")}
            if isinstance(resolution, dict) else None),
        "population_diff": {
            "entries": diff_entries(be, ae),
            "units": diff_units(bu, au),
        },
        "scoring": {
            "primary_block_len_s": PRIMARY_BLOCK_LEN_S,
            "block_lens_s": list(BLOCK_LENS),
            "replicates": REPLICATES, "seed": SEED,
            "min_support": MIN_SUPPORT, "primary_metric": PRIMARY_METRIC,
            "n_units_before": len(bu), "n_units_after": len(au),
            "n_common_scored": len(common_keys),
            "full_before": full_before["comparisons"],
            "full_after": full_after["comparisons"],
            "common_before": common_before["comparisons"],
            "common_after": common_after["comparisons"],
            "verdict_transitions": {
                comp: {
                    "full": (f"{full_before['comparisons'][comp].get('statistical_verdict')}"
                             f" -> {full_after['comparisons'][comp].get('statistical_verdict')}"),
                    "common": (f"{common_before['comparisons'][comp].get('statistical_verdict')}"
                               f" -> {common_after['comparisons'][comp].get('statistical_verdict')}"),
                } for comp in full_before["comparisons"]
            },
        },
        "diagnostic_note": (
            "The 'before' (ledger-mode) run uses the OLD reconstructed "
            "close_ts implementation. Its verdicts are DIAGNOSTIC under the "
            "defective boundary regime — not a clean confirmation or "
            "rejection of the forecast."),
    }
    text = json.dumps(report, indent=2, default=str)
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(text, encoding="utf-8")
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--resolution", default=None)
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    ap.add_argument("--boundaries", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    rep = build_report(
        resolution_path=args.resolution,
        before_path=args.before, after_path=args.after,
        boundaries_path=args.boundaries, out_path=args.out)
    sc = rep["scoring"]
    print(f"units before={sc['n_units_before']} after={sc['n_units_after']} "
          f"common={sc['n_common_scored']}")
    for comp, vt in sc["verdict_transitions"].items():
        print(f"  {comp:<18} full {vt['full']:<30} common {vt['common']}")
    if args.out:
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
