"""Fit the empirical price-calibration artifact (favorite-longshot overlay).

Signal-quality audit 2026-10-04: the Kalshi 15m price is systematically
mis-calibrated — NO-side favorites (held 50-89c) with 3-7 min to expiry win
more often than their price implies, consistently across independent halves
of the sample, while the Bachelier model (shrunk toward the market mid)
cannot see it.  This script turns that evidence into a lookup table.

Observations: logs/rejected_candidates.jsonl (executable held price, side,
TTE) joined to logs/settlement_outcomes.jsonl.  Dedup to the first record per
(ticker, side, TTE minute) so long-lived rejections are not over-weighted.

Cell = (side, 10c held-price bucket, TTE minute).  A cell is VALIDATED only
if, net of fee:
  * n >= --min-n,
  * the edge is positive in BOTH chronological halves (stability), and
  * pooled edge minus 1.96 standard errors >= --min-lcb-edge.

Published probability per validated cell is beta-shrunk toward the cell's
average price (prior strength --prior-k), so a thin cell cannot claim more
than its evidence supports:
    p = (wins + k * avg_price) / (n + k)

Usage:
  .\\.venv\\Scripts\\python.exe scripts\\fit_empirical_price_calibration.py
  .\\.venv\\Scripts\\python.exe scripts\\fit_empirical_price_calibration.py --end 2026-09-24 --out data/epc_train.json
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
from datetime import datetime, timezone

FEE_C = 1.5


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-09-01")
    ap.add_argument("--end", default="9999")
    ap.add_argument("--min-n", type=int, default=60)
    ap.add_argument("--min-lcb-edge", type=float, default=0.0)
    # Stronger shrinkage: first OOS pass realised ~0 of a +7.4c predicted
    # edge at k=50, so the published p must stay much closer to price.
    ap.add_argument("--prior-k", type=float, default=200.0)
    # Structural hypothesis (2026-10-04 audit): the stable, OOS-surviving
    # mispricing is NO-side favorites late in the window — YES-side cells
    # repeatedly failed walk-forward.  Defaults encode that hypothesis; the
    # 3-minute floor sits above MERID_ENTRY_MIN_SECONDS_TO_EXPIRY=180.
    ap.add_argument("--sides", default="no")
    ap.add_argument("--price-min", type=int, default=50)
    ap.add_argument("--price-max", type=int, default=89)
    ap.add_argument("--min-tte-min", type=int, default=3)
    ap.add_argument("--max-tte-min", type=int, default=6)
    ap.add_argument("--candidates", default=os.path.join("logs", "rejected_candidates.jsonl"))
    ap.add_argument("--outcomes", default=os.path.join("logs", "settlement_outcomes.jsonl"))
    ap.add_argument("--out", default=os.path.join("data", "empirical_price_calibration.json"))
    args = ap.parse_args()

    outcomes = {}
    for line in open(args.outcomes, "r", errors="replace"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("event_type") == "settlement_outcome" and d.get("ticker") and d.get("outcome"):
            outcomes[d["ticker"]] = str(d["outcome"]).lower()

    obs = []
    seen = set()
    for line in open(args.candidates, "r", errors="replace"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        ts = d.get("event_ts_utc") or ""
        if d.get("type") != "rejected_candidate" or not (args.start <= ts < args.end):
            continue
        t, side = d.get("ticker"), (d.get("side") or "").lower()
        px, tte = d.get("held_price_cents"), d.get("tte_seconds")
        if t not in outcomes or side not in ("yes", "no") or px is None or tte is None:
            continue
        px, tte = float(px), float(tte)
        mi = int(tte // 60)
        if not (args.price_min <= px <= args.price_max) or not (args.min_tte_min <= mi <= args.max_tte_min):
            continue
        if side not in args.sides.split(","):
            continue
        k = (t, side, mi)
        if k in seen:
            continue
        seen.add(k)
        obs.append((ts, side, int(px // 10) * 10, mi, px, outcomes[t] == side, t))
    obs.sort()
    if not obs:
        print("no observations")
        return 1
    mid_ts = obs[len(obs) // 2][0]

    agg = collections.defaultdict(lambda: {"n": 0, "w": 0, "px": 0.0, "h": [[0, 0, 0.0], [0, 0, 0.0]], "tickers": set()})
    for ts, side, pb, mi, px, won, t in obs:
        a = agg[(side, pb, mi)]
        a["n"] += 1
        a["w"] += won
        a["px"] += px
        a["tickers"].add(t)
        h = a["h"][0 if ts < mid_ts else 1]
        h[0] += 1
        h[1] += won
        h[2] += px

    def edge(n, w, sp):
        return 100.0 * w / n - sp / n - FEE_C if n else float("nan")

    cells = []
    for (side, pb, mi), a in sorted(agg.items()):
        n, w, sp = a["n"], a["w"], a["px"]
        if n < args.min_n:
            continue
        e = edge(n, w, sp)
        wr = w / n
        se = 100.0 * math.sqrt(max(wr * (1 - wr), 1e-6) / n)
        h1, h2 = a["h"]
        e1 = edge(*h1) if h1[0] else float("nan")
        e2 = edge(*h2) if h2[0] else float("nan")
        lcb = e - 1.96 * se
        stable = h1[0] >= 20 and h2[0] >= 20 and e1 > 0 and e2 > 0
        validated = stable and lcb >= args.min_lcb_edge
        avg_px = sp / n
        p_shrunk = (w + args.prior_k * avg_px / 100.0) / (n + args.prior_k)
        cells.append({
            "cell_id": f"epc_{side}_{pb:02d}_{pb + 9:02d}_m{mi}",
            "side": side,
            "price_lo_c": pb,
            "price_hi_c": pb + 10,
            "tte_min_s": mi * 60,
            "tte_max_s": (mi + 1) * 60,
            "n": n,
            "wins": w,
            "avg_price_c": round(avg_px, 3),
            "win_rate": round(wr, 5),
            "edge_c": round(e, 3),
            "edge_se_c": round(se, 3),
            "edge_lcb_c": round(lcb, 3),
            "edge_half1_c": round(e1, 3),
            "edge_half2_c": round(e2, 3),
            "p_shrunk": round(p_shrunk, 5),
            "validated": validated,
            "distinct_windows": len(a["tickers"]),
        })

    val = [c for c in cells if c["validated"]]
    days = max(1, len({o[0][:10] for o in obs}))
    windows_per_day = len({o[6] for o in obs if (o[1], o[2], o[3]) in {(c["side"], c["price_lo_c"], c["tte_min_s"] // 60) for c in val}}) / days
    artifact = {
        "schema": "empirical_price_calibration/v1",
        "fitted_at_utc": datetime.now(timezone.utc).isoformat(),
        "sample_start": obs[0][0],
        "sample_end": obs[-1][0],
        "split_ts": mid_ts,
        "n_observations": len(obs),
        "params": {
            "sides": args.sides,
            "price_min_c": args.price_min,
            "price_max_c": args.price_max,
            "tte_min_minute": args.min_tte_min,
            "tte_max_minute": args.max_tte_min,
            "min_n": args.min_n,
            "min_lcb_edge_c": args.min_lcb_edge,
            "prior_k": args.prior_k,
            "fee_c": FEE_C,
            "price_bucket_c": 10,
            "tte_bucket_s": 60,
        },
        "cells": cells,
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=1)
    os.replace(tmp, args.out)

    print(f"observations={len(obs)} {obs[0][0][:10]}..{obs[-1][0][:10]} cells(n>={args.min_n})={len(cells)} validated={len(val)}")
    print(f"validated-cell windows/day ~{windows_per_day:.1f}  -> {args.out}")
    for c in val:
        print(f"  {c['cell_id']:<24} n={c['n']:4d} px={c['avg_price_c']:5.1f} win={c['win_rate']:.3f} "
              f"edge={c['edge_c']:+5.1f}c lcb={c['edge_lcb_c']:+5.1f} halves=({c['edge_half1_c']:+.1f},{c['edge_half2_c']:+.1f}) "
              f"p_shrunk={c['p_shrunk']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
