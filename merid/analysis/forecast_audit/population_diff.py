"""Before/after population diff for the boundary migration.

Compares two ``--export-population`` JSONL files (e.g. ledger-mode vs
authoritative-mode forecast audits) and reports:

* entry-status transition matrix on (ticker, horizon) — added / removed /
  status_changed / unchanged, broken down by asset and horizon;
* snapshot-selection changes (different decision_ts selected for the same
  (ticker,horizon));
* scored-unit changes (units present in one run only);
* boundary-class transitions;
* close_ts deltas per ticker.

This is the "which observations changed under the boundary correction"
artifact required by the migration acceptance criteria — it never rewrites
either population; it only reports the diff.

CLI::

    py -3 -m merid.analysis.forecast_audit.population_diff \
        --before reports/pop_ledger.jsonl --after reports/pop_authoritative.jsonl \
        --out reports/population_diff_2026-11-13.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def load_population(path: str | Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    entries: List[Dict[str, Any]] = []
    units: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            rt = row.get("record_type")
            if rt == "entry":
                entries.append(row)
            elif rt == "unit":
                units.append(row)
    return entries, units


def _key_entry(e: Dict[str, Any]) -> Tuple[str, float]:
    return (e["ticker"], float(e["horizon_s"]))


def _key_unit(u: Dict[str, Any]) -> Tuple[str, float]:
    return (u["ticker"], float(u["horizon_s"]))


def diff_entries(
    before: List[Dict[str, Any]],
    after: List[Dict[str, Any]],
) -> Dict[str, Any]:
    bmap = {_key_entry(e): e for e in before}
    amap = {_key_entry(e): e for e in after}
    all_keys = sorted(set(bmap) | set(amap))

    transitions: Counter = Counter()
    by_asset_h: Dict[str, Counter] = defaultdict(Counter)
    snapshot_changes = 0
    offset_changes = 0
    added: List[str] = []
    removed: List[str] = []
    status_changed_examples: List[Dict[str, Any]] = []

    for k in all_keys:
        ticker, h = k
        b, a = bmap.get(k), amap.get(k)
        asset = (a or b or {}).get("asset") or "?"
        slice_key = f"{asset}|h{int(h)}"
        if b is None:
            transitions["added"] += 1
            by_asset_h[slice_key]["added"] += 1
            added.append(ticker)
            continue
        if a is None:
            transitions["removed"] += 1
            by_asset_h[slice_key]["removed"] += 1
            removed.append(ticker)
            continue
        bs, as_ = b.get("status"), a.get("status")
        br, ar = b.get("reason"), a.get("reason")
        bstat = bs if br is None else br
        astat = as_ if ar is None else ar
        if bstat == astat:
            transitions["unchanged"] += 1
            by_asset_h[slice_key]["unchanged"] += 1
        else:
            t = f"{bstat}->{astat}"
            transitions[t] += 1
            by_asset_h[slice_key][t] += 1
            if len(status_changed_examples) < 200:
                status_changed_examples.append({
                    "ticker": ticker, "horizon_s": h,
                    "before": {"status": bs, "reason": br,
                               "snapshot_ts": b.get("snapshot_ts"),
                               "offset": b.get("snapshot_offset_s"),
                               "boundary_class": b.get("boundary_class")},
                    "after": {"status": as_, "reason": ar,
                              "snapshot_ts": a.get("snapshot_ts"),
                              "offset": a.get("snapshot_offset_s"),
                              "boundary_class": a.get("boundary_class")},
                })
        if (b.get("snapshot_ts") or 0) != (a.get("snapshot_ts") or 0):
            snapshot_changes += 1
        if (b.get("snapshot_offset_s") or 0) != (a.get("snapshot_offset_s") or 0):
            offset_changes += 1

    # Boundary-class transitions (per ticker, mode-level)
    bcls_b: Dict[str, str] = {}
    bcls_a: Dict[str, str] = {}
    for e in before:
        if e.get("boundary_class"):
            bcls_b[e["ticker"]] = e["boundary_class"]
    for e in after:
        if e.get("boundary_class"):
            bcls_a[e["ticker"]] = e["boundary_class"]
    cls_trans: Counter = Counter()
    for t in sorted(set(bcls_b) | set(bcls_a)):
        cb, ca = bcls_b.get(t, "-"), bcls_a.get(t, "-")
        if cb != ca:
            cls_trans[f"{cb}->{ca}"] += 1

    return {
        "n_entries_before": len(before),
        "n_entries_after": len(after),
        "n_keys": len(all_keys),
        "transitions": dict(transitions),
        "by_asset_horizon": {k: dict(v) for k, v in sorted(by_asset_h.items())},
        "snapshot_selection_changes": snapshot_changes,
        "snapshot_offset_changes": offset_changes,
        "added_tickers": sorted(set(added)),
        "removed_tickers": sorted(set(removed)),
        "status_changed_examples": status_changed_examples,
        "boundary_class_transitions": dict(cls_trans),
    }


def diff_units(
    before: List[Dict[str, Any]],
    after: List[Dict[str, Any]],
) -> Dict[str, Any]:
    bmap = {_key_unit(u): u for u in before}
    amap = {_key_unit(u): u for u in after}
    all_keys = sorted(set(bmap) | set(amap))
    only_b = [k for k in all_keys if k in bmap and k not in amap]
    only_a = [k for k in all_keys if k in amap and k not in bmap]
    both = [k for k in all_keys if k in bmap and k in amap]

    close_deltas: List[float] = []
    snap_diffs: List[Dict[str, Any]] = []
    source_changes: Counter = Counter()
    for k in both:
        bu, au = bmap[k], amap[k]
        if bu.get("close_ts") is not None and au.get("close_ts") is not None:
            close_deltas.append(float(au["close_ts"]) - float(bu["close_ts"]))
        if (bu.get("snapshot_ts") or 0) != (au.get("snapshot_ts") or 0):
            if len(snap_diffs) < 200:
                snap_diffs.append({
                    "ticker": k[0], "horizon_s": k[1],
                    "before_snapshot_ts": bu.get("snapshot_ts"),
                    "after_snapshot_ts": au.get("snapshot_ts"),
                    "before_close_source": bu.get("close_ts_source"),
                    "after_close_source": au.get("close_ts_source"),
                })
        sb = bu.get("close_ts_source") or "-"
        sa = au.get("close_ts_source") or "-"
        if sb != sa:
            source_changes[f"{sb}->{sa}"] += 1

    import numpy as np
    cd: Dict[str, Any] = {"n": len(close_deltas)}
    if close_deltas:
        arr = np.asarray(close_deltas)
        cd.update({
            "mean": float(arr.mean()), "p50": float(np.percentile(arr, 50)),
            "p90": float(np.percentile(arr, 90)),
            "min": float(arr.min()), "max": float(arr.max()),
            "abs_gt_1s": int((np.abs(arr) > 1).sum()),
            "abs_gt_30s": int((np.abs(arr) > 30).sum()),
        })

    return {
        "n_units_before": len(before),
        "n_units_after": len(after),
        "n_keys": len(all_keys),
        "units_only_before": len(only_b),
        "units_only_after": len(only_a),
        "units_both": len(both),
        "close_ts_delta_after_minus_before_s": cd,
        "close_ts_source_transitions": dict(source_changes),
        "snapshot_selection_diff_examples": snap_diffs,
        "units_only_before_keys": [list(k) for k in only_b[:200]],
        "units_only_after_keys": [list(k) for k in only_a[:200]],
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--before", required=True, help="population JSONL (old regime)")
    ap.add_argument("--after", required=True, help="population JSONL (new regime)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    be, bu = load_population(args.before)
    ae, au = load_population(args.after)
    report = {
        "before": args.before,
        "after": args.after,
        "entries": diff_entries(be, ae),
        "units": diff_units(bu, au),
    }
    text = json.dumps(report, indent=2, default=str)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        e, u = report["entries"], report["units"]
        print(f"entries: {e['n_entries_before']} -> {e['n_entries_after']} "
              f"({e['transitions']})")
        print(f"units: {u['n_units_before']} -> {u['n_units_after']} "
              f"(both={u['units_both']} only_before={u['units_only_before']} "
              f"only_after={u['units_only_after']})")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
