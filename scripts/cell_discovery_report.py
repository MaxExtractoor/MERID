"""Five-asset threshold-cell discovery report.

Uniform discovery pipeline for BTC, ETH, SOL, XRP, DOGE: every settled,
research-eligible decision in data/decision_audit.db is bucketed by

    asset x side x price bucket x TTE bucket x execution mode

and evaluated against the shared promotion rule:

    eligible bucket  iff  n >= n_min
                     and  LCB10(net PnL)            > 0
                     and  LCB10(net PnL, +1c stress) > 0
                     and  all chronological folds   > 0

Counterfactual net PnL uses the decision-time executable ask (taker bound —
the conservative bound for the post-only lane):

    net_c = settlement_payoff - entry_ask - entry_fee - exit_fee

The report writes data/cell_discovery.json, which the live parity heartbeat
reads via threshold_cells.cell_discovery_status() so every asset reports
WHY it is or is not on the cell path — 'evaluated / not yet qualified' is
never confused with 'silently excluded'.

Per-asset terminal status:
    qualified:N_cells        registry already holds approved cells
    QUALIFIES_UNDER_RULE     bucket(s) pass the promotion rule but are not
                             yet registered — promotion candidates
    INSUFFICIENT_SAMPLE      every bucket below n_min
    INSUFFICIENT_POSITIVE_LCB best bucket's LCB10 <= 0
    FAILS_+1C_STRESS         LCB10 > 0 but fails +1c adverse-execution stress
    FOLD_INSTABILITY         stats pass but chronological folds disagree
    NO_SETTLED_DATA          no research-eligible settled rows

Usage:
    python scripts/cell_discovery_report.py [--min-n 10]
"""

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB = "data/decision_audit.db"
OUT = "data/cell_discovery.json"

ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")
SIDES = ("yes", "no")
PRICE_BUCKETS = [(lo, lo + 10) for lo in range(0, 100, 10)]
TTE_BUCKETS = [(0, 120), (120, 300), (300, 600), (600, 900)]
N_FOLDS = 3

# Execution mode for all rows in this report: counterfactual taker-at-ask.
# Live post-only fills get their own mode column once lane fill data accrues.
EXEC_MODE = "cf_taker_ask"


def _stats(pnls):
    """(n, mean, median, lcb10) in cents; lcb10 = mean - 1.2816*se."""
    n = len(pnls)
    if n == 0:
        return 0, 0.0, 0.0, 0.0
    s = sorted(pnls)
    mean = sum(s) / n
    median = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0
    var = sum((x - mean) ** 2 for x in s) / n
    se = (var ** 0.5) / (n ** 0.5)
    return n, mean, median, mean - 1.2816 * se


def _fold_means(pnls_ts, folds=N_FOLDS):
    """Per-fold means over chronological thirds (adjacent, never shuffled)."""
    vals = [cf for _, cf in pnls_ts]
    n = len(vals)
    if n < folds * 2:
        return [None] * folds
    k = n // folds
    out = []
    for i in range(folds):
        seg = vals[i * k: (i + 1) * k if i < folds - 1 else n]
        out.append(sum(seg) / len(seg) if seg else None)
    return out


def _bucket(lo_hi_list, v):
    for lo, hi in lo_hi_list:
        if lo <= v < hi:
            return lo, hi
    return None


def _eval_bucket(pnls_ts, min_n):
    """Apply the shared promotion rule to one bucket.

    Returns (status_detail, stats_dict) where status_detail is one of
    PROMOTES / INSUFFICIENT_SAMPLE / INSUFFICIENT_POSITIVE_LCB /
    FAILS_+1C_STRESS / FOLD_INSTABILITY.
    """
    pnls = [cf for _, cf in pnls_ts]
    n, mean, med, lcb = _stats(pnls)
    folds = _fold_means(pnls_ts)
    rec = {
        "n": n, "mean": round(mean, 3), "median": round(med, 3),
        "lcb10": round(lcb, 3), "lcb10_plus1c": round(lcb - 1.0, 3),
        "mean_plus2c": round(mean - 2.0, 3),
        "folds": [round(f, 3) if f is not None else None for f in folds],
    }
    if n < min_n:
        return "INSUFFICIENT_SAMPLE", rec
    if lcb <= 0:
        return "INSUFFICIENT_POSITIVE_LCB", rec
    if lcb - 1.0 <= 0:
        return "FAILS_+1C_STRESS", rec
    if any(f is None or f <= 0 for f in folds):
        return "FOLD_INSTABILITY", rec
    return "PROMOTES", rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-n", type=int, default=10)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = c.execute(
        """
        SELECT d.ticker, d.asset, d.decision_ts, d.seconds_to_close,
               se.side, se.executable_entry_price_cents px,
               se.expected_net_ev_cents nev,
               o.counterfactual_yes_pnl_cents cy,
               o.counterfactual_no_pnl_cents cn
        FROM strategy_decisions d
        JOIN strategy_decision_side_ev se ON se.decision_id = d.decision_id
        JOIN strategy_decision_outcomes o ON o.decision_id = d.decision_id
        WHERE o.outcome_status = 'SETTLED'
          AND d.is_eligible_for_research = 1
          AND se.executable_entry_price_cents IS NOT NULL
          AND se.expected_net_ev_cents IS NOT NULL
        ORDER BY d.decision_ts
        """
    ).fetchall()

    # One candidate per (ticker, side, 60s bucket).
    seen = set()
    obs = []
    for tick, asset, ts, tte, side, px, nev, cy, cn in rows:
        key = (tick, side, int(ts // 60))
        if key in seen:
            continue
        seen.add(key)
        cf = cy if side == "yes" else cn
        if cf is None or px is None or tte is None:
            continue
        obs.append((str(asset).upper(), side, float(px), float(tte),
                    float(cf), float(ts)))

    # Bucket every observation.
    buckets = defaultdict(list)  # (asset, side, px_lo, px_hi, t_lo, t_hi) -> [(ts, cf)]
    asset_seen = defaultdict(int)
    for asset, side, px, tte, cf, ts in obs:
        asset_seen[asset] += 1
        pb = _bucket(PRICE_BUCKETS, px)
        tb = _bucket(TTE_BUCKETS, tte)
        if pb is None or tb is None:
            continue
        buckets[(asset, side, pb[0], pb[1], tb[0], tb[1])].append((ts, cf))
    for v in buckets.values():
        v.sort()

    from merid.prediction.threshold_cells import CELLS_BY_ASSET  # noqa: E402

    per_asset = {}
    promotes = defaultdict(list)  # asset -> [bucket keys that PROMOTE]

    for asset in ASSETS:
        registry = list(CELLS_BY_ASSET.get(asset, ()))
        buckets_rec = []
        best = None  # (lcb10, key, detail, stats) among n>=min_n buckets
        has_min_n = False
        for side in SIDES:
            for plo, phi in PRICE_BUCKETS:
                for tlo, thi in TTE_BUCKETS:
                    key = (asset, side, plo, phi, tlo, thi)
                    pts = buckets.get(key)
                    if not pts:
                        continue
                    detail, stats = _eval_bucket(pts, args.min_n)
                    bkey = f"{asset}|{side}|{plo:02d}-{phi:02d}|t{tlo}_{thi}|{EXEC_MODE}"
                    stats["bucket"] = bkey
                    stats["verdict"] = detail
                    buckets_rec.append(stats)
                    if stats["n"] >= args.min_n:
                        has_min_n = True
                        if detail == "PROMOTES":
                            promotes[asset].append(bkey)
                        if best is None or stats["lcb10"] > best[0]:
                            best = (stats["lcb10"], bkey, detail, stats)

        if registry:
            status = f"qualified:{len(registry)}_cells"
        elif asset_seen.get(asset, 0) == 0:
            status = "NO_SETTLED_DATA"
        elif promotes.get(asset):
            status = "QUALIFIES_UNDER_RULE"
        elif not has_min_n:
            status = "INSUFFICIENT_SAMPLE"
        elif best is not None:
            status = best[2]  # INSUFFICIENT_POSITIVE_LCB / FAILS_+1C_STRESS / FOLD_INSTABILITY
        else:
            status = "INSUFFICIENT_SAMPLE"

        per_asset[asset] = {
            "status": status,
            "registry_cells": registry,
            "n_obs": asset_seen.get(asset, 0),
            "promoting_buckets": promotes.get(asset, []),
            "best_bucket": best[1] if best else None,
            "buckets": buckets_rec,
        }

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "min_n": args.min_n,
        "promotion_rule": "n>=min_n AND lcb10>0 AND lcb10-1c>0 AND all folds>0",
        "exec_mode": EXEC_MODE,
        "per_asset": per_asset,
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)

    # Console table.
    print(f"\n== cell discovery (min_n={args.min_n}, mode={EXEC_MODE}) ==")
    for asset in ASSETS:
        rec = per_asset[asset]
        print(f"\n-- {asset}: {rec['status']} "
              f"(obs={rec['n_obs']}, registry={rec['registry_cells'] or 'none'})")
        print(f"   {'bucket':44} {'n':>5} {'mean':>7} {'lcb10':>7} "
              f"{'lcb+1c':>7} {'folds':>22} verdict")
        for b in sorted(rec["buckets"], key=lambda x: -x["lcb10"]):
            folds = ",".join(
                f"{f:+.1f}" if f is not None else "nan" for f in b["folds"]
            )
            print(f"   {b['bucket']:44} {b['n']:>5d} {b['mean']:>+7.2f} "
                  f"{b['lcb10']:>+7.2f} {b['lcb10_plus1c']:>+7.2f} "
                  f"{folds:>22} {b['verdict']}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
