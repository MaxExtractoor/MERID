"""Five-asset threshold-cell discovery report (data-only).

Uniform discovery pipeline for BTC, ETH, SOL, XRP, DOGE: every settled,
research-eligible decision in data/decision_audit.db is bucketed by

    asset x side x price bucket x TTE bucket x execution mode

and evaluated against the shared statistical leg of the promotion rule:

    n >= n_min AND LCB10(net PnL) > 0 AND LCB10(+1c stress) > 0
    AND all chronological folds > 0 AND max_day_share <= 0.5

Counterfactual net PnL uses the decision-time executable ask (taker bound —
the conservative bound for the post-only lane):

    net_c = settlement_payoff - entry_ask - entry_fee - exit_fee

DATA-ONLY CONTRACT
------------------
This script must never touch production services.  It reads exactly two
artifacts:  data/decision_audit.db (read-only sqlite) and
config/threshold_cells_live.yaml (the live registry, parsed directly — no
merid package import, no balance fetch, no router, no live config).
It writes data/cell_discovery.json.

Outputs consumed downstream
---------------------------
data/cell_discovery.json is read by
  * scripts/cell_promotion_compiler.py  (5-stage fail-closed gate)
  * merid.prediction.threshold_cells.cell_discovery_status /
    cell_discovery_detail                     (live parity heartbeat)

Per-bucket fields: n, n_markets, max_day_share, mean, median, lcb10,
lcb10_plus1c, mean_plus2c, folds, n_eff_7d, n_eff_21d, mean_7d, mean_21d,
in_domain, verdict.

Per-asset status:
    qualified:N_cells        registry already holds approved cells
    QUALIFIES_UNDER_RULE     in-domain bucket(s) pass the statistical leg —
                             promotion candidates pending stages 2-4
    INSUFFICIENT_SAMPLE      every in-domain bucket below n_min
    INSUFFICIENT_POSITIVE_LCB best in-domain bucket's LCB10 <= 0
    FAILS_+1C_STRESS         LCB10 > 0 but fails +1c adverse-execution stress
    FOLD_INSTABILITY         stats pass but chronological folds disagree
    CONCENTRATED_SAMPLE      one UTC day holds > 50% of the cohort
    NO_SETTLED_DATA          no research-eligible settled rows
    no bucket rows at all    INSUFFICIENT_SAMPLE

Out-of-domain buckets (price outside 20-89c or TTE outside 120-600s) are
recorded for transparency but verdict=EXCLUDED_DOMAIN — near-expiry 0-10c
'wins' are fillability/lookahead artifacts, not promotions.

Usage:
    python scripts/cell_discovery_report.py [--min-n 10]
"""

import argparse
import json
import math
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone

DB = "data/decision_audit.db"
REGISTRY = "config/threshold_cells_live.yaml"
OUT = "data/cell_discovery.json"

ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")
SIDES = ("yes", "no")
PRICE_BUCKETS = [(lo, lo + 10) for lo in range(0, 100, 10)]
TTE_BUCKETS = [(0, 120), (120, 300), (300, 600), (600, 900)]
N_FOLDS = 3

# Promotion-domain contract (stage-2): executable ask in [20, 89]c and
# TTE in [120, 600]s.  0-10c / <120s tail rows are excluded by construction.
DOMAIN_PRICE_MIN, DOMAIN_PRICE_MAX = 20, 90
DOMAIN_TTE_MIN, DOMAIN_TTE_MAX = 120, 600
MAX_DAY_SHARE = 0.5

# Execution mode for all rows in this report: counterfactual taker-at-ask.
EXEC_MODE = "cf_taker_ask"

SECONDS_7D = 7 * 86400.0
SECONDS_21D = 21 * 86400.0


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
    vals = [cf for _, cf, _t in pnls_ts]
    n = len(vals)
    if n < folds * 2:
        return [None] * folds
    k = n // folds
    out = []
    for i in range(folds):
        seg = vals[i * k: (i + 1) * k if i < folds - 1 else n]
        out.append(sum(seg) / len(seg) if seg else None)
    return out


def _decayed(pnls_ts, now_ts):
    """Exponential-decay effective n and mean at 7d/21d horizons."""
    n7 = n21 = wsum7 = wsum21 = 0.0
    for ts, cf, _t in pnls_ts:
        age = max(0.0, now_ts - ts)
        w7 = math.exp(-age / SECONDS_7D)
        w21 = math.exp(-age / SECONDS_21D)
        n7 += w7
        n21 += w21
        wsum7 += w7 * cf
        wsum21 += w21 * cf
    return n7, n21, (wsum7 / n7 if n7 else None), (wsum21 / n21 if n21 else None)


def _day_share(pnls_ts):
    """Largest single-UTC-day share of the cohort (concentration bound)."""
    days = defaultdict(int)
    for ts, _cf, _t in pnls_ts:
        days[int(ts // 86400)] += 1
    n = len(pnls_ts)
    return (max(days.values()) / n) if n else 0.0


def _bucket(lo_hi_list, v):
    for lo, hi in lo_hi_list:
        if lo <= v < hi:
            return lo, hi
    return None


def _in_domain(plo, phi, tlo, thi):
    return (
        DOMAIN_PRICE_MIN <= plo and phi <= DOMAIN_PRICE_MAX
        and DOMAIN_TTE_MIN <= tlo and thi <= DOMAIN_TTE_MAX
    )


def _eval_bucket(pnls_ts, min_n, now_ts, in_domain):
    """Statistical leg of the shared promotion rule for one bucket.

    Returns (verdict, stats_dict).  Out-of-domain buckets are recorded with
    stats but verdict=EXCLUDED_DOMAIN — they never feed promotion.
    """
    pnls = [cf for _, cf, _t in pnls_ts]
    tickers = {t for _ts, _cf, t in pnls_ts}
    n, mean, med, lcb = _stats(pnls)
    folds = _fold_means(pnls_ts)
    n7, n21, m7, m21 = _decayed(pnls_ts, now_ts)
    day_share = _day_share(pnls_ts)
    rec = {
        "n": n, "n_markets": len(tickers),
        "max_day_share": round(day_share, 3),
        "mean": round(mean, 3), "median": round(med, 3),
        "lcb10": round(lcb, 3), "lcb10_plus1c": round(lcb - 1.0, 3),
        "mean_plus2c": round(mean - 2.0, 3),
        "folds": [round(f, 3) if f is not None else None for f in folds],
        "n_eff_7d": round(n7, 2), "n_eff_21d": round(n21, 2),
        "mean_7d": round(m7, 3) if m7 is not None else None,
        "mean_21d": round(m21, 3) if m21 is not None else None,
        "in_domain": in_domain,
    }
    if not in_domain:
        return "EXCLUDED_DOMAIN", rec
    if n < min_n:
        return "INSUFFICIENT_SAMPLE", rec
    if day_share > MAX_DAY_SHARE:
        return "CONCENTRATED_SAMPLE", rec
    if lcb <= 0:
        return "INSUFFICIENT_POSITIVE_LCB", rec
    if lcb - 1.0 <= 0:
        return "FAILS_+1C_STRESS", rec
    if any(f is None or f <= 0 for f in folds):
        return "FOLD_INSTABILITY", rec
    return "PROMOTES", rec


def _load_live_registry(path):
    """Data-only parse of config/threshold_cells_live.yaml -> asset -> [ids]."""
    import yaml
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return {a: [] for a in ASSETS}
    by_asset = {a: [] for a in ASSETS}
    for row in data.get("cells") or []:
        try:
            a = str(row["asset"]).upper()
            if a in by_asset:
                by_asset[a].append(str(row["cell_id"]))
        except Exception:
            continue
    return by_asset


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-n", type=int, default=10)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--registry", default=REGISTRY)
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

    now_ts = datetime.now(timezone.utc).timestamp()

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
                    float(cf), float(ts), tick))

    buckets = defaultdict(list)  # key -> [(ts, cf, ticker)]
    asset_seen = defaultdict(int)
    for asset, side, px, tte, cf, ts, tick in obs:
        asset_seen[asset] += 1
        pb = _bucket(PRICE_BUCKETS, px)
        tb = _bucket(TTE_BUCKETS, tte)
        if pb is None or tb is None:
            continue
        buckets[(asset, side, pb[0], pb[1], tb[0], tb[1])].append((ts, cf, tick))
    for v in buckets.values():
        v.sort()

    registry = _load_live_registry(args.registry)

    per_asset = {}
    promotes = defaultdict(list)

    for asset in ASSETS:
        reg_cells = registry.get(asset, [])
        buckets_rec = []
        best = None  # best IN-DOMAIN bucket by lcb10 with n>=min_n
        has_min_n = False
        for side in SIDES:
            for plo, phi in PRICE_BUCKETS:
                for tlo, thi in TTE_BUCKETS:
                    key = (asset, side, plo, phi, tlo, thi)
                    pts = buckets.get(key)
                    if not pts:
                        continue
                    dom = _in_domain(plo, phi, tlo, thi)
                    detail, stats = _eval_bucket(pts, args.min_n, now_ts, dom)
                    bkey = f"{asset}|{side}|{plo:02d}-{phi:02d}|t{tlo}_{thi}|{EXEC_MODE}"
                    stats["bucket"] = bkey
                    stats["verdict"] = detail
                    buckets_rec.append(stats)
                    if not dom:
                        continue
                    if stats["n"] >= args.min_n:
                        has_min_n = True
                        if detail == "PROMOTES":
                            promotes[asset].append(bkey)
                        if best is None or stats["lcb10"] > best[0]:
                            best = (stats["lcb10"], bkey, detail, stats)

        if reg_cells:
            status = f"qualified:{len(reg_cells)}_cells"
        elif asset_seen.get(asset, 0) == 0:
            status = "NO_SETTLED_DATA"
        elif promotes.get(asset):
            status = "QUALIFIES_UNDER_RULE"
        elif not has_min_n:
            status = "INSUFFICIENT_SAMPLE"
        elif best is not None:
            status = best[2]
        else:
            status = "INSUFFICIENT_SAMPLE"

        per_asset[asset] = {
            "status": status,
            "registry_cells": reg_cells,
            "n_obs": asset_seen.get(asset, 0),
            "promoting_buckets": promotes.get(asset, []),
            "top_candidate": best[1] if best else None,
            "buckets": buckets_rec,
        }

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "min_n": args.min_n,
        "promotion_rule": (
            "in-domain(20-89c,120-600s) AND n>=min_n AND lcb10>0 "
            "AND lcb10-1c>0 AND all folds>0 AND max_day_share<=0.5"
        ),
        "exec_mode": EXEC_MODE,
        "per_asset": per_asset,
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)

    # Console table.
    print(f"\n== cell discovery (min_n={args.min_n}, mode={EXEC_MODE}, "
          f"domain=20-89c/120-600s) ==")
    for asset in ASSETS:
        rec = per_asset[asset]
        print(f"\n-- {asset}: {rec['status']} "
              f"(obs={rec['n_obs']}, registry={rec['registry_cells'] or 'none'}, "
              f"top={rec['top_candidate'] or 'none'})")
        print(f"   {'bucket':44} {'n':>5} {'mkt':>4} {'dshare':>6} "
              f"{'mean':>7} {'lcb10':>7} {'+1c':>6} {'n7d':>6} {'n21d':>6} "
              f"{'m21d':>6} verdict")
        for b in sorted(rec["buckets"], key=lambda x: -x["lcb10"]):
            flag = " " if b["in_domain"] else "X"
            print(f"  {flag}{b['bucket']:44} {b['n']:>5d} {b['n_markets']:>4d} "
                  f"{b['max_day_share']:>6.2f} {b['mean']:>+7.2f} "
                  f"{b['lcb10']:>+7.2f} {b['lcb10_plus1c']:>+6.2f} "
                  f"{b['n_eff_7d']:>6.1f} {b['n_eff_21d']:>6.1f} "
                  f"{(b['mean_21d'] if b['mean_21d'] is not None else 0):>+6.2f} "
                  f"{b['verdict']}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
