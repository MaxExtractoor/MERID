"""Join rejected candidates to realized settlement outcomes and classify them.

Reads ``logs/rejected_candidates.jsonl`` (emitted by
``merid/prediction/rejection_counterfactual.py``) and
``logs/settlement_outcomes.jsonl``, then for each rejected candidate computes
the counterfactual P&L of having taken the trade:

- If the held side resolved:  gross = 100 - held_price_cents per contract
- Otherwise:                  gross = -held_price_cents per contract
- Net subtracts the recorded entry fee (default ~1.5c when missing).

Classification:
- ``missed``         net counterfactual P&L > +1c (wrong rejection)
- ``saved``          net counterfactual P&L < -1c (correct rejection)
- ``flat``           within +/-1c
- ``unclassifiable`` no settlement outcome for the ticker yet

Aggregates by held-price bucket and TTE bucket so threshold calibration
decisions are driven by data, not hand-tuning.

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\rejection_counterfactual_report.py
    .\\.venv\\Scripts\\python.exe scripts\\rejection_counterfactual_report.py --min-age-min 30
"""
from __future__ import annotations

import argparse
import collections
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

_FLAT_EPS_CENTS = 1.0
_DEFAULT_FEE_CENTS = 1.5


def _load_jsonl(path: str):
    if not os.path.exists(path):
        return
    with open(path, "r", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def _price_bucket(cents: Optional[float]) -> str:
    if cents is None:
        return "unknown"
    lo = int(cents // 10) * 10
    return f"{lo:02d}-{lo + 9:02d}c"


def _tte_bucket(secs: Optional[float]) -> str:
    if secs is None:
        return "unknown"
    if secs < 180:
        return "<3m"
    if secs < 420:
        return "3-7m"
    if secs < 720:
        return "7-12m"
    return "12-15m"


def main() -> int:
    ap = argparse.ArgumentParser(description="Rejection counterfactual report")
    ap.add_argument("--candidates", default=os.path.join("logs", "rejected_candidates.jsonl"))
    ap.add_argument("--outcomes", default=os.path.join("logs", "settlement_outcomes.jsonl"))
    ap.add_argument(
        "--min-age-min",
        type=float,
        default=0.0,
        help="Skip candidates newer than this many minutes (market may not have settled)",
    )
    args = ap.parse_args()

    # ticker -> outcome ("yes"/"no")
    outcomes: Dict[str, str] = {}
    for d in _load_jsonl(args.outcomes):
        if d.get("event_type") == "settlement_outcome" and d.get("ticker") and d.get("outcome"):
            outcomes[d["ticker"]] = str(d["outcome"]).lower()

    now = datetime.now(timezone.utc)
    by_reason = collections.Counter()
    by_price_bucket: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    by_tte_bucket: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    pnl_by_price: Dict[str, float] = collections.defaultdict(float)
    total = 0
    classified = 0
    total_cf_net_cents = 0.0

    for d in _load_jsonl(args.candidates):
        if d.get("type") != "rejected_candidate":
            continue
        if args.min_age_min > 0 and d.get("event_ts_utc"):
            try:
                ts = datetime.fromisoformat(str(d["event_ts_utc"]).replace("Z", "+00:00"))
                if (now - ts).total_seconds() < args.min_age_min * 60:
                    continue
            except Exception:
                pass
        total += 1
        ticker = d.get("ticker")
        side = (d.get("side") or "").lower()
        held = d.get("held_price_cents")
        fee = d.get("fee_cents") or _DEFAULT_FEE_CENTS

        if not ticker or side not in ("yes", "no") or held is None or ticker not in outcomes:
            label = "unclassifiable"
            cf_net = None
        else:
            won = outcomes[ticker] == side
            gross = (100.0 - float(held)) if won else -float(held)
            cf_net = gross - float(fee)
            if cf_net > _FLAT_EPS_CENTS:
                label = "missed"
            elif cf_net < -_FLAT_EPS_CENTS:
                label = "saved"
            else:
                label = "flat"
            classified += 1
            total_cf_net_cents += cf_net
            pnl_by_price[_price_bucket(held)] += cf_net

        by_reason[(d.get("reject_reason") or "unknown").split(":")[0]][label] += 1
        by_price_bucket[_price_bucket(held)][label] += 1
        by_tte_bucket[_tte_bucket(d.get("tte_seconds"))][label] += 1

    def _render(counter_map, title):
        print(f"\n== {title} ==")
        print(f"{'key':<28} {'saved':>6} {'missed':>6} {'flat':>6} {'unclass':>8}")
        for key in sorted(counter_map):
            c = counter_map[key]
            print(
                f"{key:<28} {c.get('saved', 0):>6} {c.get('missed', 0):>6} "
                f"{c.get('flat', 0):>6} {c.get('unclassifiable', 0):>8}"
            )

    print(f"Rejected candidates: {total}  (classified: {classified})")
    if classified:
        print(
            f"Counterfactual net P&L if ALL rejected trades had been taken: "
            f"{total_cf_net_cents:+.1f}c total, {total_cf_net_cents / classified:+.2f}c/trade"
        )
    _render(by_reason, "By rejection gate")
    _render(by_price_bucket, "By held-price bucket")
    _render(by_tte_bucket, "By time-to-expiry bucket")

    print("\n== Counterfactual net P&L by price bucket (cents/contract, all classified) ==")
    for key in sorted(pnl_by_price):
        print(f"{key:<10} {pnl_by_price[key]:+8.1f}c")

    print(
        "\nInterpretation: a high 'missed' rate concentrated in one bucket/TTE band is "
        "evidence the gate is too strict THERE; a high 'saved' rate means the gate is "
        "working. Do not loosen any threshold on a bucket whose missed P&L does not "
        "clear the fee stack."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
