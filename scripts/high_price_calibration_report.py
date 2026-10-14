"""High-price model calibration report (Brier + reliability bins).

Answers: does the model systematically underprice >80c contracts?  Bins each
evaluated candidate's model_p (held side) into 5-point bins, compares mean
predicted probability against realized settlement frequency, and reports
Brier score and reliability error per bin.  Splits by asset / side / TTE /
executable-price bucket.

Data source: ``logs/rejected_candidates.jsonl`` records joined to
``logs/settlement_outcomes.jsonl``.  NOTE the sample is the *rejected*
candidate set — selected/filled candidates are a small minority, so the
bins measure calibration of the model's probability estimates on the cohort
the gates actually saw.  Selection effects are bounded: a bin's mean prob
vs realized frequency is still a valid calibration statement.

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\high_price_calibration_report.py
    .\\.venv\\Scripts\\python.exe scripts\\high_price_calibration_report.py --tail-mb 300 --min-price 80
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
from typing import Any, Dict, Optional


def _load_jsonl(path: str, tail_bytes: Optional[int] = None):
    if not os.path.exists(path):
        return
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        if tail_bytes and size > tail_bytes:
            f.seek(size - tail_bytes)
            f.readline()  # drop partial first line
        for raw in f:
            try:
                yield json.loads(raw)
            except Exception:
                continue


def _bin5(p: float) -> str:
    lo = int(p // 5) * 5
    return f"{lo}-{lo+4}"


def _bucket_price(c: Optional[float]) -> str:
    if c is None:
        return "unk"
    lo = int(float(c) // 10) * 10
    return f"{lo:02d}-{lo+9:02d}c"


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
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default=os.path.join("logs", "rejected_candidates.jsonl"))
    ap.add_argument("--outcomes", default=os.path.join("logs", "settlement_outcomes.jsonl"))
    ap.add_argument("--tail-mb", type=float, default=0.0,
                    help="Only read the last N MB of candidates (0 = whole file)")
    ap.add_argument("--min-price", type=float, default=80.0,
                    help="Only candidates whose held-side executable ask >= this many cents")
    args = ap.parse_args()

    outcomes: Dict[str, str] = {}
    for d in _load_jsonl(args.outcomes):
        if d.get("event_type") == "settlement_outcome" and d.get("ticker") and d.get("outcome"):
            outcomes[d["ticker"]] = str(d["outcome"]).lower()

    tail = int(args.tail_mb * 1024 * 1024) or None

    # accumulators
    def _acc():
        return {"n": 0, "sum_p": 0.0, "wins": 0, "brier": 0.0}

    bins: Dict[str, Dict] = collections.defaultdict(_acc)
    by_asset: Dict[str, Dict[str, Dict]] = collections.defaultdict(
        lambda: collections.defaultdict(_acc))
    by_side: Dict[str, Dict] = collections.defaultdict(_acc)
    by_tte: Dict[str, Dict] = collections.defaultdict(_acc)
    by_pxb: Dict[str, Dict] = collections.defaultdict(_acc)
    total_seen = 0

    for d in _load_jsonl(args.candidates, tail):
        if d.get("type") != "rejected_candidate":
            continue
        held = d.get("held_price_cents")
        p = d.get("model_p_selected")
        side = (d.get("side") or "").lower()
        ticker = d.get("ticker")
        if held is None or p is None or side not in ("yes", "no"):
            continue
        held = float(held)
        if held < args.min_price:
            continue
        if ticker not in outcomes:
            continue
        try:
            p = float(p)
        except (TypeError, ValueError):
            continue
        if not (0.0 <= p <= 1.0):
            continue
        realized = 1.0 if outcomes[ticker] == side else 0.0
        total_seen += 1

        def add(a):
            a["n"] += 1
            a["sum_p"] += p
            a["wins"] += realized
            a["brier"] += (p - realized) ** 2

        add(bins[_bin5(p * 100)])
        add(by_asset[d.get("asset") or "?"][_bin5(p * 100)])
        add(by_side[side])
        add(by_tte[_tte_bucket(d.get("tte_seconds"))])
        add(by_pxb[_bucket_price(held)])

    def row(label, a):
        n = a["n"]
        if n == 0:
            return f"{label:<12} n=0"
        mp = a["sum_p"] / n
        freq = a["wins"] / n
        brier = a["brier"] / n
        return (f"{label:<12} n={n:<6} mean_p={mp * 100:5.1f}%  "
                f"win_freq={freq * 100:5.1f}%  gap={100 * (freq - mp):+5.1f}pp  "
                f"brier={brier:.4f}")

    print(f"High-price candidates (held ask >= {args.min_price}c): {total_seen} classified")
    print("\n== Calibration by model-probability bin (held side) ==")
    for b in sorted(bins):
        print(row(b, bins[b]))

    print("\n== By side ==")
    for s in sorted(by_side):
        print(row(s, by_side[s]))

    print("\n== By TTE bucket ==")
    for t in ("12-15m", "7-12m", "3-7m", "<3m", "unknown"):
        if t in by_tte:
            print(row(t, by_tte[t]))

    print("\n== By executable-price bucket ==")
    for b in sorted(by_pxb):
        print(row(b, by_pxb[b]))

    print("\n== By asset (prob bins) ==")
    for asset in sorted(by_asset):
        print(f"[{asset}]")
        for b in sorted(by_asset[asset]):
            print("  " + row(b, by_asset[asset][b]))

    print(
        "\nInterpretation: gap>0 means the model UNDERPRICES that bin "
        "(realized frequency exceeds predicted). A persistent positive gap in "
        "the 80-100 bins supports a calibration fix (e.g. isotonic/Platt on the "
        "high tail), not an edge-gate relaxation."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
