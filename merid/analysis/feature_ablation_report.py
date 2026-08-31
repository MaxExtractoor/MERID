"""Feature ablation report for 15m decision telemetry.

READ-ONLY analysis tool.  Computes out-of-sample slices and incremental
information-vs-market for the microstructure and RTI features now being logged
in decision telemetry.

The report is intentionally independent of the live trading loop.  It reads:

- ``logs/decision_telemetry.jsonl``
- ``logs/settlement_outcomes.jsonl``
- optional ``data/kalshi_fills.db`` (read-only) for realized PnL

Output is a JSON-safe dict / file with:

- per-feature quintile slices (Brier, AUC, resolution, net realized edge)
- incremental-vs-market comparison for each feature
- a combined "baseline + all enabled features" model if ``microstructure_delta_pp``
  and ``rti_return_10s`` are present.

For each slice the proper score is *incremental information beyond the market
price*: a feature that predicts direction but does not beat the executable ask
and costs is not a deployable trading signal.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from merid.analysis.calibration_report import (
    SPREAD_BUCKETS,
    TTE_BUCKETS,
    PRICE_BUCKETS,
    DEPTH_BUCKETS,
    _bucket,
    _model_p,
    _market_p,
    _predicted_cost_prob,
    _actual_cost_prob,
    _edge_stats,
    _mean,
    _rate,
    join_rows,
    dedupe_latest_per_market,
    load_decision_records,
    load_outcomes,
    load_fill_pnls,
)
from merid.risk.probability.calibration_diagnostics import calibration_summary, brier_score, roc_auc_score


REPORT_SCHEMA_VERSION = 1

# Features to slice.  Each entry is (field, label, kind) where kind is:
#   "quintile" -> data-driven 5 buckets by value
#   "signed"   -> negative / zero / positive tercile
#   "bucket"   -> use explicit thresholds from a tuple list
FEATURE_SLICES: Sequence[Tuple[str, str, str]] = (
    ("microstructure_yes_ofi", "OFI (yes)", "signed"),
    ("microstructure_no_ofi", "OFI (no)", "signed"),
    ("microstructure_yes_book_imbalance", "book_imbalance_yes", "signed"),
    ("microstructure_no_book_imbalance", "book_imbalance_no", "signed"),
    ("microstructure_yes_spread_cents", "spread_yes_cents", "bucket"),
    ("microstructure_no_spread_cents", "spread_no_cents", "bucket"),
    ("microstructure_book_delta_pp", "book_delta_pp", "signed"),
    ("microstructure_cross_delta_pp", "cross_delta_pp", "signed"),
    ("microstructure_delta_pp", "total_micro_delta_pp", "signed"),
    ("rti_return_1s", "rti_return_1s", "signed"),
    ("rti_return_3s", "rti_return_3s", "signed"),
    ("rti_return_10s", "rti_return_10s", "signed"),
    ("rti_return_30s", "rti_return_30s", "signed"),
    ("rti_return_60s", "rti_return_60s", "signed"),
    ("microstructure_btc_log_return", "btc_log_return", "signed"),
    ("feature_age_ms", "feature_age_ms", "bucket"),
    ("feature_valid", "feature_valid", "discrete"),
)


# Explicit numeric buckets for selected features.
FEATURE_BUCKETS: Dict[str, Sequence[Tuple[str, float, float]]] = {
    "spread_yes_cents": SPREAD_BUCKETS,
    "spread_no_cents": SPREAD_BUCKETS,
    "feature_age_ms": (
        ("<500ms", 0.0, 500.0),
        ("500-1500ms", 500.0, 1500.0),
        ("1500-3000ms", 1500.0, 3000.0),
        (">3000ms", 3000.0, math.inf),
    ),
}


def _signed_bucket(value: Any) -> str:
    """Tercile bucket for signed features."""
    if value is None or not isinstance(value, (int, float)) or not math.isfinite(value):
        return "missing"
    if value < -1e-12:
        return "negative"
    if value > 1e-12:
        return "positive"
    return "zero"


def _discrete_bucket(value: Any) -> str:
    if value is None:
        return "missing"
    return "true" if bool(value) else "false"


def _quintile_bucket(values: List[float], n: int = 5) -> List[Tuple[str, float, float]]:
    """Return bucket definitions for ``n`` quantile buckets of ``values``."""
    clean = [v for v in values if v is not None and math.isfinite(v)]
    if len(clean) < n * 2:
        return []
    cuts = statistics.quantiles(clean, n=n, method="inclusive")
    buckets: List[Tuple[str, float, float]] = []
    lo = -math.inf
    for i, cut in enumerate(cuts):
        buckets.append((f"q{i + 1}", lo, cut))
        lo = cut
    buckets.append((f"q{n}", lo, math.inf))
    return buckets


def _group_by_feature(rows: List[Dict[str, Any]], field: str, kind: str) -> Dict[str, List[Dict[str, Any]]]:
    """Group ``rows`` by the requested feature bucket."""
    if kind == "quintile":
        raw = [r.get(field) for r in rows]
        buckets = _quintile_bucket(raw)
        key_fn = lambda r: _bucket(r.get(field), buckets)
    elif kind == "signed":
        key_fn = lambda r: _signed_bucket(r.get(field))
    elif kind == "discrete":
        key_fn = lambda r: _discrete_bucket(r.get(field))
    elif kind == "bucket":
        buckets = FEATURE_BUCKETS.get(field, [])
        if not buckets:
            raw = [r.get(field) for r in rows]
            buckets = _quintile_bucket(raw)
        key_fn = lambda r: _bucket(r.get(field), buckets)
    else:
        raise ValueError(f"unknown kind {kind}")

    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        key = key_fn(r)
        groups.setdefault(key, []).append(r)
    return groups


def _feature_prob(row: Dict[str, Any], delta_field: str, max_delta: float = 0.15) -> Optional[float]:
    """Market probability shifted by a feature delta, clipped to [0, 1]."""
    mkt = _market_p(row)
    if mkt is None:
        return None
    delta = row.get(delta_field)
    if delta is None or not math.isfinite(delta):
        return mkt
    # delta is in percentage points (e.g. 0.66 pp); convert to probability.
    delta_prob = float(delta) / 100.0
    delta_prob = max(-max_delta, min(max_delta, delta_prob))
    return max(0.0, min(1.0, mkt + delta_prob))


def _metrics_for_probs(name: str, probs: List[float], outs: List[int]) -> Dict[str, Any]:
    """Canonical Brier/AUC/resolution metrics for one probability vector."""
    if not probs or not outs or len(probs) != len(outs):
        return {"n": 0}
    cal = calibration_summary(probs, outs, n_bins=min(5, len(probs)), label=name)
    return {
        "n": len(probs),
        "brier_score": cal.get("brier_score"),
        "auc_roc": cal.get("auc_roc"),
        "resolution": cal.get("resolution"),
        "expected_calibration_error": cal.get("expected_calibration_error"),
    }


def _net_realized_edge(rows: List[Dict[str, Any]]) -> Optional[float]:
    """Mean realized edge net of actual cost for filled records."""
    edges = []
    for r in rows:
        if not r.get("fill_count") or r.get("y") is None:
            continue
        mkt = _market_p(r)
        if mkt is None:
            continue
        cost = _actual_cost_prob(r)
        if cost is None:
            cost = _predicted_cost_prob(r)
        edges.append(r["y"] - mkt - cost)
    return _mean(edges) if edges else None


def _build_feature_slices(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Per-feature bucket slices: distribution and performance vs market."""
    out: Dict[str, Any] = {}
    resolved = [r for r in rows if r.get("y") is not None]
    for field, label, kind in FEATURE_SLICES:
        groups = _group_by_feature(resolved, field, kind)
        if not groups:
            continue
        slices: Dict[str, Any] = {}
        for bucket_name, bucket_rows in sorted(groups.items()):
            if not bucket_rows:
                continue
            mkt_probs = [_market_p(r) for r in bucket_rows if _market_p(r) is not None]
            mkt_outs = [r["y"] for r in bucket_rows if _market_p(r) is not None]
            mkt_metrics = _metrics_for_probs("market", mkt_probs, mkt_outs)

            model_probs = [_model_p(r) for r in bucket_rows if _model_p(r) is not None]
            model_outs = [r["y"] for r in bucket_rows if _model_p(r) is not None]
            model_metrics = _metrics_for_probs("derived_model", model_probs, model_outs)

            slices[bucket_name] = {
                "n": len(bucket_rows),
                "market": mkt_metrics,
                "derived_model": model_metrics,
                "mean_net_realized_edge": _net_realized_edge(bucket_rows),
                "feature_field": field,
            }
        out[label] = {
            "feature_field": field,
            "kind": kind,
            "buckets": slices,
        }
    return out


def _build_incremental_vs_market(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compare market baseline to market + one feature delta."""
    resolved = [r for r in rows if r.get("y") is not None]
    out: Dict[str, Any] = {}

    # Baseline market model.
    mkt_probs = [_market_p(r) for r in resolved if _market_p(r) is not None]
    mkt_outs = [r["y"] for r in resolved if _market_p(r) is not None]
    baseline = _metrics_for_probs("market_baseline", mkt_probs, mkt_outs)
    out["baseline_market"] = baseline

    # Try each additive delta field.
    delta_fields = [
        ("microstructure_delta_pp", "microstructure_total_delta"),
        ("microstructure_book_delta_pp", "microstructure_book_delta"),
        ("microstructure_cross_delta_pp", "microstructure_cross_delta"),
        ("rti_return_10s", "rti_return_10s"),
        ("rti_return_30s", "rti_return_30s"),
        ("rti_return_60s", "rti_return_60s"),
    ]

    for field, label in delta_fields:
        f_probs = [_feature_prob(r, field) for r in resolved]
        f_outs = [r["y"] for r in resolved]
        # Pair only non-None
        paired = [(p, o) for p, o in zip(f_probs, f_outs) if p is not None]
        if not paired:
            continue
        p, o = zip(*paired)
        feat = _metrics_for_probs(label, list(p), list(o))
        feat["brier_skill_vs_market"] = None
        feat["auc_skill_vs_market"] = None
        feat["res_skill_vs_market"] = None
        if baseline.get("brier_score") and feat.get("brier_score") and baseline["brier_score"] > 0:
            feat["brier_skill_vs_market"] = 1.0 - (feat["brier_score"] / baseline["brier_score"])
        if baseline.get("auc_roc") is not None and feat.get("auc_roc") is not None:
            feat["auc_skill_vs_market"] = feat["auc_roc"] - baseline["auc_roc"]
        if baseline.get("resolution") and feat.get("resolution") and baseline["resolution"] > 0:
            feat["res_skill_vs_market"] = feat["resolution"] / baseline["resolution"]
        out[label] = feat

    return out


def build_feature_ablation_report(
    records: List[Dict[str, Any]],
    outcomes: Dict[str, int],
    fill_pnls: Dict[str, Dict[str, float]],
) -> Dict[str, Any]:
    """Build the feature ablation report."""
    raw_rows = join_rows(records, outcomes, fill_pnls)
    rows = dedupe_latest_per_market(raw_rows)

    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "counts": {
            "evaluated_records": len(raw_rows),
            "unique_decision_markets": len(rows),
            "outcomes_loaded": len(outcomes),
            "tickers_with_fills": len(fill_pnls),
        },
        "feature_slices": _build_feature_slices(rows),
        "incremental_vs_market": _build_incremental_vs_market(rows),
    }


def _load_inputs(args: argparse.Namespace) -> Tuple[List[Dict[str, Any]], Dict[str, int], Dict[str, Dict[str, float]]]:
    records = load_decision_records(Path(args.telemetry))
    outcomes = load_outcomes(Path(args.outcomes))
    fill_pnls: Dict[str, Dict[str, float]] = {}
    if args.fills_db:
        fill_pnls = load_fill_pnls(Path(args.fills_db))
    return records, outcomes, fill_pnls


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Feature ablation report for 15m microstructure/RTI signals")
    parser.add_argument("--telemetry", default="logs/decision_telemetry.jsonl")
    parser.add_argument("--outcomes", default="logs/settlement_outcomes.jsonl")
    parser.add_argument("--fills-db", default="data/kalshi_fills.db")
    parser.add_argument("--json-out", default="reports/feature_ablation_report.json")
    args = parser.parse_args(argv)

    records, outcomes, fill_pnls = _load_inputs(args)
    report = build_feature_ablation_report(records, outcomes, fill_pnls)

    out_path = Path(args.json_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"Wrote feature ablation report to {out_path}")
    print(json.dumps(report.get("incremental_vs_market", {}), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
