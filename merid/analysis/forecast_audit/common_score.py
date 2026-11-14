"""Score forecast-audit populations on common vs full support.

Loads two ``--export-population`` JSONL files and recomputes the report's
comparisons with the SAME block-bootstrap machinery, answering the boundary
migration's key question:

* verdicts on the FULL population of each run (self-check vs the report);
* verdicts on the COMMON eligible population — (ticker, horizon) units
  scored in BOTH runs — the like-for-like comparison that separates
  "measurement changed" from "sample composition changed".

Block assignment uses the resolved contract boundary per ticker (sidecar)
when available so both runs share identical calendar blocks even when
their internal close_ts differ; units without a sidecar boundary fall back
to their own close_ts (edge effect only).

CLI::

    py -3 -m merid.analysis.forecast_audit.common_score \
        --before pop_ledger.jsonl --after pop_authoritative.jsonl \
        --boundaries data/contract_boundaries_v1.jsonl \
        --out reports/common_score_2026-11-13.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .bootstrap import (
    CompBlocks, block_ids_for_units, make_comp_blocks, paired_bootstrap,
)
from .inference import LOSSES
from .report import COMPARISONS, VERDICT_PASS, VERDICT_FAIL, \
    VERDICT_INCONCLUSIVE, VERDICT_INSUFFICIENT
from .population_diff import load_population

MIN_SUPPORT = 50
PRIMARY_BLOCK_LEN_S = 3600.0
REPLICATES = 2000
SEED = 20261023
BLOCK_LENS = (1800.0, 3600.0, 7200.0, 14400.0)
PRIMARY_METRIC = "brier"


def _verdict(res: Dict[str, Any]) -> str:
    if res.get("n_units", 0) < MIN_SUPPORT:
        return VERDICT_INSUFFICIENT
    ci = res.get("mean_loss_diff_ci")
    if ci is None:
        return VERDICT_INSUFFICIENT
    if ci[0] > 0:
        return VERDICT_PASS
    if ci[1] < 0:
        return VERDICT_FAIL
    return VERDICT_INCONCLUSIVE


def _res_dict(br: Any) -> Dict[str, Any]:
    return {
        "n_units": br.n_units,
        "n_blocks": br.n_blocks_used,
        "mean_loss_diff": br.point_mean_d,
        "mean_loss_diff_ci": list(br.ci_d) if br.ci_d else None,
        "bss": br.point_bss,
        "bss_ci": list(br.ci_bss) if br.ci_bss else None,
    }


def _score_set(
    units: List[Dict[str, Any]],
    *,
    block_of: np.ndarray,
    n_blocks: int,
    label: str,
) -> Dict[str, Any]:
    """Run all comparisons over one unit set with precomputed block ids."""
    out: Dict[str, Any] = {}
    comps: Dict[str, CompBlocks] = {}
    meta: Dict[str, Tuple[str, str]] = {}
    # Precompute per-comparison support + losses once (block-independent).
    supports: Dict[str, Dict[str, Any]] = {}
    for comp_name, cand, base, _q in COMPARISONS:
        idx, pc, pb, y = [], [], [], []
        for i, u in enumerate(units):
            if u.get("y") is None:
                continue
            st = u.get("stages") or {}
            pc_i, pb_i = st.get(cand), st.get(base)
            if pc_i is None or pb_i is None:
                continue
            idx.append(i)
            pc.append(float(pc_i))
            pb.append(float(pb_i))
            y.append(int(u["y"]))
        if not idx:
            supports[comp_name] = {"n": 0}
            continue
        yarr = np.asarray(y, dtype=float)
        pca, pba = np.asarray(pc), np.asarray(pb)
        losses = {}
        for lname, lfn in LOSSES.items():
            lc = np.array([lfn(a, int(b)) for a, b in zip(pca, yarr)])
            lb = np.array([lfn(a, int(b)) for a, b in zip(pba, yarr)])
            losses[lname] = (lc, lb)
        supports[comp_name] = {
            "n": len(idx), "idx": idx, "losses": losses,
            "cand": cand, "base": base,
        }
        for lname, (lc, lb) in losses.items():
            comps[f"{comp_name}|{lname}"] = make_comp_blocks(
                block_of, idx, lb - lc, lc, lb, n_blocks)
        meta[comp_name] = (cand, base)

    if comps:
        bres = paired_bootstrap(comps, replicates=REPLICATES, seed=SEED)
    else:
        bres = {}
    for comp_name, sup in supports.items():
        if sup.get("n", 0) == 0:
            out[comp_name] = {"n_units": 0, "verdict": VERDICT_INSUFFICIENT}
            continue
        cand, base = meta[comp_name]
        row: Dict[str, Any] = {
            "candidate": cand, "baseline": base, "n_support": sup["n"],
        }
        for lname in LOSSES:
            br = bres.get(f"{comp_name}|{lname}")
            row[lname] = _res_dict(br) if br is not None else {"n_units": 0}
        row["statistical_verdict"] = _verdict(row[PRIMARY_METRIC])
        out[comp_name] = row
    return {"label": label, "comparisons": out}


def _units_by_key(units: List[Dict[str, Any]]) -> Dict[Tuple[str, float], Dict[str, Any]]:
    return {(u["ticker"], float(u["horizon_s"])): u for u in units}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    ap.add_argument("--boundaries", default=None,
                    help="boundary sidecar for shared calendar blocks")
    ap.add_argument("--out", default=None)
    ap.add_argument("--primary-block-len", type=float, default=PRIMARY_BLOCK_LEN_S)
    args = ap.parse_args(argv)

    _be, bu = load_population(args.before)
    _ae, au = load_population(args.after)

    # Shared calendar blocks: resolved contract boundary per ticker when the
    # sidecar is provided, else each unit's own close_ts.
    boundary_close: Dict[str, float] = {}
    if args.boundaries:
        try:
            from .boundaries import load_boundaries
            for t, rec in load_boundaries(args.boundaries).items():
                if rec.contract_boundary_ts is not None:
                    boundary_close[t] = float(rec.contract_boundary_ts)
        except Exception as exc:
            print(f"WARNING: boundaries load failed: {exc}")

    def block_ids_for(units: List[Dict[str, Any]]):
        close = [
            boundary_close.get(u["ticker"], u.get("close_ts"))
            for u in units
        ]
        return block_ids_for_units(close, args.primary_block_len)

    # ---- full populations (each run scored on its own units) ---------------
    b_ids, b_n = block_ids_for(bu)
    a_ids, a_n = block_ids_for(au)
    full_before = _score_set(bu, block_of=b_ids, n_blocks=b_n, label="before_full")
    full_after = _score_set(au, block_of=a_ids, n_blocks=a_n, label="after_full")

    # ---- common eligible population ----------------------------------------
    bmap = _units_by_key(bu)
    amap = _units_by_key(au)
    common_keys = sorted(set(bmap) & set(amap))
    # A unit is common-eligible only if it has a label and is scored in both.
    common_units_b = [bmap[k] for k in common_keys
                      if bmap[k].get("y") is not None]
    common_units_a = [amap[k] for k in common_keys
                      if amap[k].get("y") is not None]
    # Keep runs aligned: same key set, same order.
    common_keys_scored = [
        k for k in common_keys
        if bmap[k].get("y") is not None and amap[k].get("y") is not None
    ]
    cu_b = [bmap[k] for k in common_keys_scored]
    cu_a = [amap[k] for k in common_keys_scored]
    # Shared block ids from the BEFORE run's closes (same contracts).
    c_ids, c_n = block_ids_for(cu_b)
    common_before = _score_set(cu_b, block_of=c_ids, n_blocks=c_n,
                               label="common_before")
    common_after = _score_set(cu_a, block_of=c_ids, n_blocks=c_n,
                              label="common_after")

    report = {
        "before": args.before,
        "after": args.after,
        "boundaries": args.boundaries,
        "primary_block_len_s": args.primary_block_len,
        "replicates": REPLICATES,
        "seed": SEED,
        "min_support": MIN_SUPPORT,
        "primary_metric": PRIMARY_METRIC,
        "n_units_before": len(bu),
        "n_units_after": len(au),
        "n_common_keys": len(common_keys),
        "n_common_scored": len(common_keys_scored),
        "full_before": full_before["comparisons"],
        "full_after": full_after["comparisons"],
        "common_before": common_before["comparisons"],
        "common_after": common_after["comparisons"],
        "verdict_transitions": {
            comp: {
                "full": f"{full_before['comparisons'][comp].get('statistical_verdict')}"
                        f" -> {full_after['comparisons'][comp].get('statistical_verdict')}",
                "common": f"{common_before['comparisons'][comp].get('statistical_verdict')}"
                          f" -> {common_after['comparisons'][comp].get('statistical_verdict')}",
            } for comp, *_ in COMPARISONS
        },
    }
    text = json.dumps(report, indent=2, default=str)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"units: before={len(bu)} after={len(au)} common_scored={len(common_keys_scored)}")
        for comp, *_ in COMPARISONS:
            vt = report["verdict_transitions"][comp]
            print(f"  {comp:<18} full {vt['full']:<28} common {vt['common']}")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
