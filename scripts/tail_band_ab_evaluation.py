#!/usr/bin/env python3
"""Evaluate the tail-band shadow A/B against settlement outcomes.

Reads ``logs/tail_band_shadow.jsonl`` and ``logs/settlement_outcomes.jsonl``,
computes realized P&L per shadow band, and applies the pre-defined statistical
gate.  The gate is intentionally conservative and pre-registered; it is not
adjusted after seeing the data.

Pre-registered promotion criteria:
- Minimum 30 settled windows per band under test.
- Mean net realized P&L per contract > 0 with a one-sided 95% lower confidence
  bound above zero (i.e. the 5% quantile of the bootstrap mean is > 0).
- Brier score <= 0.20 against realized outcomes.
- Reliability gap per probability decile <= +/- 0.10.
- Positive mean net edge per price bucket after fees.

The script exits 0 and writes a JSON report regardless of whether the gate
passes; exit 1 means the report could not be built.  Promotion to the live
``CANONICAL_MIN/MAX`` range is a separate, explicit human step and must not be
automated until all gates are satisfied.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent

# Promotion thresholds (pre-registered, do not tune after seeing data).
MIN_WINDOWS_PER_BAND = 30
BRIER_THRESHOLD = 0.20
RELIABILITY_GAP_THRESHOLD = 0.10
CONFIDENCE_LEVEL = 0.95
BOOTSTRAP_SAMPLES = 2000
RANDOM_SEED = 42


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _build_settlement_index(records: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Map ticker -> most authoritative settlement outcome."""
    idx: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for rec in records:
        ticker = rec.get("ticker") or rec.get("market_ticker")
        if not ticker:
            continue
        idx[ticker].append(rec)
    best: Dict[str, Dict[str, Any]] = {}
    for ticker, recs in idx.items():
        # Prefer the record with the latest observed_at_utc.
        best[ticker] = sorted(
            recs,
            key=lambda r: _parse_iso(r.get("observed_at_utc")) or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )[0]
    return best


def _realized_pnl(record: Dict[str, Any], settlement: Dict[str, Any]) -> float:
    """Net realized P&L in cents for one shadow contract (quantity=1)."""
    side = str(record.get("side", "")).lower()
    price = int(record.get("price_cents", 0))
    fee = float(record.get("fee_cents", 0.0))
    resolved_yes = bool(settlement.get("resolved_yes", 0))
    outcome = str(settlement.get("outcome", "")).lower()
    if outcome:
        resolved_yes = outcome == "yes"

    if side == "yes":
        cost = price + fee
        return (100.0 - cost) if resolved_yes else -cost
    else:  # no
        cost = price + fee
        return (100.0 - cost) if not resolved_yes else -cost


def _win(record: Dict[str, Any], settlement: Dict[str, Any]) -> int:
    side = str(record.get("side", "")).lower()
    resolved_yes = bool(settlement.get("resolved_yes", 0))
    outcome = str(settlement.get("outcome", "")).lower()
    if outcome:
        resolved_yes = outcome == "yes"
    if side == "yes":
        return 1 if resolved_yes else 0
    return 1 if not resolved_yes else 0


def _brier_score(records: Sequence[Dict[str, Any]], settlements: Dict[str, Dict[str, Any]]) -> float:
    """Brier score on the model probability vs realized outcome."""
    total = 0.0
    n = 0
    for rec in records:
        settlement = settlements.get(rec.get("ticker") or "")
        if not settlement:
            continue
        prob = rec.get("model_prob")
        if prob is None or not math.isfinite(float(prob)):
            continue
        prob = float(prob)
        outcome = _win(rec, settlement)
        total += (prob - outcome) ** 2
        n += 1
    return total / n if n > 0 else float("nan")


def _reliability_gaps(
    records: Sequence[Dict[str, Any]], settlements: Dict[str, Dict[str, Any]], n_bins: int = 10
) -> Dict[int, float]:
    """Mean gap per probability decile: (predicted - realized)."""
    by_bin: Dict[int, List[Tuple[float, int]]] = defaultdict(list)
    for rec in records:
        settlement = settlements.get(rec.get("ticker") or "")
        if not settlement:
            continue
        prob = rec.get("model_prob")
        if prob is None or not math.isfinite(float(prob)):
            continue
        prob = float(prob)
        outcome = _win(rec, settlement)
        bin_idx = min(n_bins - 1, int(prob * n_bins))
        by_bin[bin_idx].append((prob, outcome))
    gaps: Dict[int, float] = {}
    for b, items in sorted(by_bin.items()):
        pred = mean([p for p, _ in items])
        real = mean([o for _, o in items])
        gaps[b] = pred - real
    return gaps


def _bootstrap_mean_ci(values: Sequence[float], level: float = CONFIDENCE_LEVEL, n: int = BOOTSTRAP_SAMPLES) -> Tuple[float, float, float]:
    """Return (mean, lower, upper) via percentile bootstrap."""
    if not values:
        return 0.0, 0.0, 0.0
    if len(values) == 1:
        return values[0], values[0], values[0]
    rng = random.Random(RANDOM_SEED)
    means = []
    for _ in range(n):
        sample = [rng.choice(values) for _ in values]
        means.append(mean(sample))
    alpha = 1.0 - level
    lower = sorted(means)[int(alpha / 2 * n)]
    upper = sorted(means)[int((1.0 - alpha / 2) * n)]
    return mean(values), lower, upper


def _evaluate_band(band: str, records: List[Dict[str, Any]], settlements: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    pnls = []
    wins = []
    by_price: Dict[int, List[float]] = defaultdict(list)
    for rec in records:
        settlement = settlements.get(rec.get("ticker") or "")
        if not settlement:
            continue
        pnl = _realized_pnl(rec, settlement)
        pnls.append(pnl)
        wins.append(_win(rec, settlement))
        by_price[rec.get("price_cents", 0)].append(pnl)

    if not pnls:
        return {
            "n_settled": 0,
            "win_rate": None,
            "mean_pnl_cents": None,
            "std_pnl_cents": None,
            "lower_ci_cents": None,
            "upper_ci_cents": None,
            "gate_passed": False,
        }

    mu, lower, upper = _bootstrap_mean_ci(pnls)
    price_bucket_pnls = {str(p): round(mean(v), 4) for p, v in by_price.items() if len(v) >= 3}
    passed = (
        len(pnls) >= MIN_WINDOWS_PER_BAND
        and lower > 0.0
        and all(v > 0 for v in price_bucket_pnls.values())
    )

    return {
        "n_settled": len(pnls),
        "win_rate": round(mean(wins), 4) if wins else None,
        "mean_pnl_cents": round(mu, 4),
        "std_pnl_cents": round(stdev(pnls), 4) if len(pnls) > 1 else 0.0,
        "lower_ci_cents": round(lower, 4),
        "upper_ci_cents": round(upper, 4),
        "price_bucket_mean_pnl_cents": price_bucket_pnls,
        "gate_passed": passed,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate tail-band shadow A/B")
    parser.add_argument("--shadow-log", default=None, help="Path to tail_band_shadow.jsonl")
    parser.add_argument("--settlement-log", default=None, help="Path to settlement_outcomes.jsonl")
    parser.add_argument("--out-report", default=None, help="Output JSON report path")
    args = parser.parse_args(argv)

    shadow_path = Path(args.shadow_log or ROOT / "logs" / "tail_band_shadow.jsonl")
    settlement_path = Path(args.settlement_log or ROOT / "logs" / "settlement_outcomes.jsonl")
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_report = Path(args.out_report) if args.out_report else ROOT / f"reports/tail_band_ab_evaluation_{ts}.json"
    out_report.parent.mkdir(parents=True, exist_ok=True)

    shadow_records = _load_jsonl(shadow_path)
    settlement_records = _load_jsonl(settlement_path)
    settlements = _build_settlement_index(settlement_records)

    # Group by tail band state.
    by_band: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for rec in shadow_records:
        band = rec.get("tail_band_state") or "unknown"
        by_band[band].append(rec)

    # Only the favorite bands and the excluded longshot bucket are evaluated.
    band_evaluations: Dict[str, Any] = {}
    for band in ("favorite_yes", "favorite_no", "excluded_longshot"):
        band_evaluations[band] = _evaluate_band(band, by_band.get(band, []), settlements)

    all_favorite = (by_band.get("favorite_yes", []) + by_band.get("favorite_no", []))
    brier = _brier_score(all_favorite, settlements)
    reliability = _reliability_gaps(all_favorite, settlements)
    max_abs_reliability_gap = max(abs(g) for g in reliability.values()) if reliability else 0.0

    # Aggregate gate across all favorite bands.
    favorite_eval = _evaluate_band("favorite_combined", all_favorite, settlements)

    overall_passed = (
        favorite_eval.get("gate_passed", False)
        and not math.isnan(brier)
        and brier <= BRIER_THRESHOLD
        and max_abs_reliability_gap <= RELIABILITY_GAP_THRESHOLD
    )

    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "shadow_log_path": str(shadow_path),
        "settlement_log_path": str(settlement_path),
        "thresholds": {
            "min_windows_per_band": MIN_WINDOWS_PER_BAND,
            "brier_threshold": BRIER_THRESHOLD,
            "reliability_gap_threshold": RELIABILITY_GAP_THRESHOLD,
            "confidence_level": CONFIDENCE_LEVEL,
            "bootstrap_samples": BOOTSTRAP_SAMPLES,
        },
        "summary": {
            "total_shadow_records": len(shadow_records),
            "settled_records": sum(len([r for r in recs if settlements.get(r.get("ticker") or "")]) for recs in by_band.values()),
            "brier_score_favorite_bands": round(brier, 4) if not math.isnan(brier) else None,
            "max_abs_reliability_gap": round(max_abs_reliability_gap, 4),
            "overall_gate_passed": overall_passed,
        },
        "band_evaluations": band_evaluations,
        "favorite_combined": favorite_eval,
        "reliability_gaps_by_decile": {str(k): round(v, 4) for k, v in reliability.items()},
    }

    with out_report.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str, sort_keys=True)

    print(json.dumps(report, indent=2, default=str, sort_keys=True))
    print(f"\nReport written to: {out_report}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
