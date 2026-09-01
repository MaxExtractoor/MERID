#!/usr/bin/env python3
"""Plan D: skip-classification and model-drift pass.

Reads ``logs/decision_telemetry.jsonl`` and classifies every skipped decision
record into one of four buckets:

- ``signal_skip``      — genuine no-edge / probability-below-threshold rejections.
- ``design_skip``      — deliberate canonical-range or tail exclusions (the long-
                         shot-bias question: are we skipping trades where edge
                         may actually live?).
- ``infrastructure_skip`` — market not available, stale/missing/illiquid book,
                            warmup, or expiry-too-short.
- ``other``            — anything not captured above.

Outputs a JSON report to ``reports/plan_d_skip_classification_*.json``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Classification rules (applied in order; first match wins)
# ---------------------------------------------------------------------------

INFRASTRUCTURE_PATTERNS = [
    r"market_discovered:",
    r"market_open:",
    r"no market available",
    r"market validation failed",
    r"stale|missing|illiquid",
    r"price_history=0",
    r"warmup",
    r"time_to_expiry=.*< min",
    r"market_open:",
    r"no contract in entry window",
    r"market_state",
    r"rest_polling",
    r"book not initialized",
    r"ws subscription",
    r"venue_unavailable",
]

DESIGN_PATTERNS = [
    r"out_of_canonical_range",
    r"price_out_of_range",
    r"deep_otm",
    r"deep_itm",
    r"tail_",
    r"canonical_range",
    r"longshot",
    r"cheap_tail",
    r"tail_calibration",
]

SIGNAL_PATTERNS = [
    r"edge_below_threshold",
    r"p_selected_below_pi_star",
    r"parity_edge_threshold",
    r"edge_threshold",
    r"edge_validation_failed",
    r"robust_ev",
    r"expected_value",
    r"net_edge",
    r"gross_edge",
    r"no_edge",
    r"negative_ev",
    r"ev_net",
    r"below_threshold",
    r"position_exists",
    r"resting_order_exists",
    r"duplicate_order",
    r"parity_",
    r"router_rejected",
    r"router_exception",
    r"profile_blocked",
    r"firewall_",
    r"exit_policy",
    r"risk_",
]


def _compile(patterns: List[str]) -> List[re.Pattern[str]]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


INFRA_RE = _compile(INFRASTRUCTURE_PATTERNS)
DESIGN_RE = _compile(DESIGN_PATTERNS)
SIGNAL_RE = _compile(SIGNAL_PATTERNS)


def _classify(reason: Optional[str]) -> str:
    reason = reason or ""
    for pattern in INFRA_RE:
        if pattern.search(reason):
            return "infrastructure_skip"
    for pattern in DESIGN_RE:
        if pattern.search(reason):
            return "design_skip"
    for pattern in SIGNAL_RE:
        if pattern.search(reason):
            return "signal_skip"
    return "other"


def _extract_reasons(record: Dict[str, Any]) -> List[str]:
    """Collect all human-readable rejection reasons from a telemetry record."""
    reasons: List[str] = []
    if record.get("rejection_reason"):
        reasons.append(record["rejection_reason"])
    for link in record.get("rejection_chain", []) or []:
        if isinstance(link, dict) and link.get("reason"):
            reasons.append(link["reason"])
    return reasons


def _bucket_for_record(record: Dict[str, Any]) -> str:
    """Return the dominant bucket for a single telemetry record."""
    reasons = _extract_reasons(record)
    # A record may contain multiple reasons; classify each and pick the first
    # non-other bucket.  Infrastructure/design/signal order intentionally.
    buckets = [_classify(r) for r in reasons]
    for bucket in ("infrastructure_skip", "design_skip", "signal_skip"):
        if bucket in buckets:
            return bucket
    return buckets[0] if buckets else "other"


def main(argv: Optional[Any] = None) -> int:
    parser = argparse.ArgumentParser(description="Plan D skip classification pass")
    parser.add_argument(
        "--telemetry",
        default=None,
        help="Path to decision_telemetry.jsonl (default: logs/decision_telemetry.jsonl)",
    )
    parser.add_argument(
        "--out-report",
        default=None,
        help="Output JSON report path",
    )
    parser.add_argument(
        "--golden-records-db",
        default=None,
        help="Path to golden_records.db for selected/ordered cross-check (default: data/golden_records.db)",
    )
    args = parser.parse_args(argv)

    telemetry_path = Path(args.telemetry or ROOT / "logs" / "decision_telemetry.jsonl")
    if not telemetry_path.exists():
        print(f"Telemetry file not found: {telemetry_path}", file=sys.stderr)
        return 1

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_report = Path(args.out_report) if args.out_report else ROOT / f"reports/plan_d_skip_classification_{ts}.json"
    out_report.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    skipped = 0
    selected = 0
    bucket_counts: Counter = Counter()
    bucket_by_asset: Dict[str, Counter] = defaultdict(Counter)
    reason_counts: Counter = Counter()
    bucket_reasons: Dict[str, Counter] = defaultdict(Counter)

    with telemetry_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("type") != "decision_record":
                continue

            total += 1
            if record.get("signal_generated"):
                selected += 1
                continue

            skipped += 1
            asset = record.get("asset") or "unknown"
            bucket = _bucket_for_record(record)
            bucket_counts[bucket] += 1
            bucket_by_asset[asset][bucket] += 1

            # Aggregate primary rejection reason and the first reason per bucket.
            primary_reason = record.get("rejection_reason") or "unknown"
            reason_counts[primary_reason] += 1
            bucket_reasons[bucket][primary_reason] += 1

    def _top(counter: Counter, n: int = 20) -> Dict[str, int]:
        return dict(counter.most_common(n))

    # Cross-check against golden records.  decision_telemetry.jsonl currently
    # only logs skipped records, so the selected/ordered counts are taken from
    # the durable golden record as the ground-truth complement.
    golden_db_path = Path(args.golden_records_db or ROOT / "data" / "golden_records.db")
    golden_summary: Dict[str, Any] = {
        "golden_records_db_path": str(golden_db_path),
        "note": "decision_telemetry.jsonl appears to contain only skipped records; selected/ordered counts are from golden_records.db",
        "distinct_intents": 0,
        "intents_with_order": 0,
        "intents_filled": 0,
        "intents_settled": 0,
        "selected_by_asset": {},
    }
    if golden_db_path.exists():
        try:
            import sqlite3

            conn = sqlite3.connect(str(golden_db_path))
            golden_summary["distinct_intents"] = conn.execute(
                "SELECT COUNT(DISTINCT intent_id) FROM golden_records"
            ).fetchone()[0]
            golden_summary["intents_with_order"] = conn.execute(
                "SELECT COUNT(DISTINCT intent_id) FROM golden_records WHERE has_order=1"
            ).fetchone()[0]
            golden_summary["intents_filled"] = conn.execute(
                "SELECT COUNT(DISTINCT intent_id) FROM golden_records WHERE has_fill=1"
            ).fetchone()[0]
            golden_summary["intents_settled"] = conn.execute(
                "SELECT COUNT(DISTINCT intent_id) FROM golden_records WHERE has_settlement=1"
            ).fetchone()[0]
            for ticker, count in conn.execute(
                "SELECT COALESCE(asset,ticker) as a, COUNT(DISTINCT intent_id) FROM golden_records GROUP BY a"
            ).fetchall():
                # Extract asset from ticker (KX<BTC>15M-...) if asset column is null.
                asset = ticker or "unknown"
                if asset.startswith("KX") and "15M" in asset:
                    asset = asset.split("15M")[0][2:]
                elif asset.startswith("KX"):
                    asset = asset[2:]
                golden_summary["selected_by_asset"][asset] = (
                    golden_summary["selected_by_asset"].get(asset, 0) + count
                )
            conn.close()
        except Exception as exc:
            golden_summary["error"] = str(exc)

    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "telemetry_path": str(telemetry_path),
        "summary": {
            "total_decision_records": total,
            "selected_signals": selected,
            "skipped_signals": skipped,
            "skip_rate_pct": round(100.0 * skipped / total, 2) if total else 0.0,
            "bucket_counts": dict(bucket_counts),
            "bucket_pct": {
                bucket: round(100.0 * count / skipped, 2) if skipped else 0.0
                for bucket, count in bucket_counts.items()
            },
        },
        "top_skip_reasons": _top(reason_counts),
        "top_reasons_by_bucket": {
            bucket: _top(counter) for bucket, counter in bucket_reasons.items()
        },
        "bucket_by_asset": {
            asset: dict(counter) for asset, counter in bucket_by_asset.items()
        },
        "golden_records_cross_check": golden_summary,
    }

    with out_report.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str, sort_keys=True)

    print(f"Plan D skip classification complete")
    print(f"  Records: {total}  Selected: {selected}  Skipped: {skipped}")
    for bucket, count in bucket_counts.most_common():
        pct = 100.0 * count / skipped if skipped else 0.0
        print(f"  {bucket}: {count} ({pct:.1f}%)")
    print(f"  Report: {out_report}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
