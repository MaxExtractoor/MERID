"""Deep-history edge audit on model_calibration_observations.jsonl.

The evidence store only covers ~40h.  This script replays the same
realized-vs-claimed edge battery over the full calibration log
(~5 weeks, Oct->Nov) joined to settlement_outcomes.jsonl, using the
canonical evidence-cell bucketing.  Read-only.

    python scripts/audit_edge_history.py \
        --cal logs/model_calibration_observations.jsonl \
        --outcomes logs/settlement_outcomes.jsonl \
        --out reports/edge_history_audit.json --boot 1000
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_edge_vs_memory import (  # noqa: E402
    bh_fdr, cell_key, cluster_boot, cohort_table, price_bucket, tte_bucket,
    taker_fee_cents,
)


def load_cal(path: str) -> pd.DataFrame:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    df = pd.DataFrame(rows)
    return df


def load_outcomes(path: str) -> pd.DataFrame:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("event_type") == "settlement_outcome":
                rows.append({
                    "ticker": d.get("ticker"),
                    "resolved_yes": d.get("resolved_yes"),
                    "settlement_ts": d.get("settlement_timestamp_utc"),
                })
    return pd.DataFrame(rows).drop_duplicates("ticker")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cal", default="logs/model_calibration_observations.jsonl")
    ap.add_argument("--outcomes", default="logs/settlement_outcomes.jsonl")
    ap.add_argument("--out", default="reports/edge_history_audit.json")
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=20261119)
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    print("[hist] loading calibration obs ...", flush=True)
    cal = load_cal(args.cal)
    print(f"[hist] {len(cal)} obs; loading outcomes ...", flush=True)
    out = load_outcomes(args.outcomes)
    print(f"[hist] {len(out)} settlement outcomes", flush=True)

    df = cal.merge(out, on="ticker", how="inner")
    df = df[df["resolved_yes"].isin([0, 1])].copy()
    print(f"[hist] {len(df)} evals joined to settlements "
          f"({df['ticker'].nunique()} markets)", flush=True)

    side = df["side"].astype(str).str.lower()
    df["win"] = np.where(side == "yes", df["resolved_yes"] == 1,
                         df["resolved_yes"] == 0)
    entry = pd.to_numeric(df["entry_price_cents"], errors="coerce")
    fee = pd.to_numeric(df["fee_cents"], errors="coerce")
    df["entry_cents"] = entry
    df["fee_cents"] = fee.fillna(entry.map(taker_fee_cents))
    df["payout"] = np.where(df["win"], 100.0, 0.0)
    df["real_edge"] = df["payout"] - entry - df["fee_cents"]
    df["claim_gross"] = pd.to_numeric(df["gross_edge_c"], errors="coerce")
    df["claim_net"] = df["claim_gross"] - df["fee_cents"]
    df["mkey"] = df["ticker"].astype(str) + "|" + side
    df["cell"] = [
        cell_key(a, s, p, t)
        for a, s, p, t in zip(df["asset"], side, entry, df["seconds_to_expiry"])
    ]
    df["price_bucket"] = entry.map(price_bucket)
    df["tte_bucket"] = df["seconds_to_expiry"].map(tte_bucket)
    df["week"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.strftime("%G-W%V")

    rep: dict = {"population": {
        "n_evals": int(len(df)), "n_markets": int(df["ticker"].nunique()),
        "n_market_sides": int(df["mkey"].nunique()),
        "ts_span": [float(df["ts"].min()), float(df["ts"].max())],
    }}

    rep["overall_all_evals"] = cluster_boot(df, "real_edge", args.boot, rng)

    latest = df.sort_values("ts").groupby("mkey", as_index=False).tail(1)
    rep["overall_latest_per_mkey"] = cluster_boot(latest, "real_edge", args.boot, rng)

    # claimed-vs-realized deciles (all evals)
    claim = df.dropna(subset=["claim_net"])
    if len(claim):
        claim = claim.copy()
        claim["dec"] = pd.qcut(claim["claim_net"], 10, duplicates="drop")
        rows = []
        for dec, g in claim.groupby("dec", observed=True):
            st = cluster_boot(g, "real_edge", args.boot, rng)
            rows.append({"decile": str(dec),
                         "claim_mean": float(g["claim_net"].mean()),
                         "real_mean": st["mean"], "ci_lo": st["ci_lo"],
                         "ci_hi": st["ci_hi"], "n": st["n"],
                         "n_markets": st["n_markets"]})
        rep["claim_deciles"] = rows
        cl = claim.sort_values("ts").groupby("mkey", as_index=False).tail(1)
        from scipy.stats import spearmanr
        rho, p = spearmanr(cl["claim_net"], cl["real_edge"])
        rep["claim_rank"] = {"spearman_rho": float(rho), "p": float(p),
                             "n": int(len(cl))}
        rep["overclaim"] = {
            "mean_claim_net": float(claim["claim_net"].mean()),
            "mean_realized": float(claim["real_edge"].mean()),
        }

    # canonical cells on latest-per-mkey
    cell_df = latest.copy()
    rows = []
    for ck, g in cell_df.groupby("cell"):
        st = cluster_boot(g, "real_edge", args.boot, rng)
        if st["n_markets"] < 10:
            continue
        a, s, pb, tb = ck.split("|")
        p_bar = float(pd.to_numeric(g["entry_cents"], errors="coerce").mean())
        fee_bar = float(pd.to_numeric(g["fee_cents"], errors="coerce").mean())
        wins = int(g["win"].sum())
        n_mk = int(g["ticker"].nunique())
        from scipy.stats import beta as beta_dist
        wr_lo = float(beta_dist.ppf(0.05, wins + 0.5, n_mk - wins + 0.5))
        wr_star = (p_bar + fee_bar) / 100.0
        rows.append({
            "cell": ck, "asset": a, "side": s, "price_bucket": pb,
            "tte_bucket": tb, **st,
            "mean_entry_c": p_bar, "mean_fee_c": fee_bar,
            "wins": wins, "n_markets_wr": n_mk,
            "wr_observed": wins / n_mk if n_mk else np.nan,
            "wr_breakeven": wr_star, "wr_posterior_lo5": wr_lo,
            "ev_at_wr_lo_c": wr_lo * 100.0 - p_bar - fee_bar,
            "mean_claim_net": float(g["claim_net"].mean())
            if g["claim_net"].notna().any() else None,
        })
    cells = pd.DataFrame(rows)
    if len(cells):
        cells["p_pos"] = cells["p_le_0"].fillna(1.0)
        pos = cells["mean"] > 0
        cells["q_bh_pos"] = np.nan
        if pos.any():
            cells.loc[pos, "q_bh_pos"] = bh_fdr(cells.loc[pos, "p_pos"].to_numpy())
        cells["sig_neg"] = cells["ci_hi"] < 0
        cells = cells.sort_values("mean", ascending=False)
        rep["cells"] = cells.to_dict("records")
        rep["cells_summary"] = {
            "n_cells": int(len(cells)),
            "n_ci_above_0": int((cells["ci_lo"] > 0).sum()),
            "n_pos_q_bh_05": int((cells["q_bh_pos"] < 0.05).sum()),
            "n_sig_neg": int(cells["sig_neg"].sum()),
            "n_pos_mean": int(pos.sum()),
            "pos_cells_ev_neg_at_wr_lo": int(
                ((cells["mean"] > 0) & (cells["ev_at_wr_lo_c"] < 0)).sum()),
            "pos_cells_total": int(pos.sum()),
        }

    # marginals
    for col, name in [("asset", "by_asset"), ("side", "by_side"),
                      ("price_bucket", "by_price_bucket"),
                      ("tte_bucket", "by_tte_bucket"), ("week", "by_week")]:
        t = cohort_table(latest.assign(**{col: latest[col].fillna("?")}),
                         [col], "real_edge", args.boot, rng, min_markets=10)
        rep[name] = t.to_dict("records") if len(t) else []

    # cell persistence across time (median split)
    med = float(df["ts"].median())
    h1 = cell_df[cell_df["ts"] <= med]
    h2 = cell_df[cell_df["ts"] > med]
    h1c = h1.groupby("cell")["real_edge"].agg(["mean", "count"])
    h2c = h2.groupby("cell")["real_edge"].agg(["mean", "count"])
    both = h1c.join(h2c, lsuffix="_h1", rsuffix="_h2", how="inner")
    both = both[(both["count_h1"] >= 5) & (both["count_h2"] >= 5)]
    if len(both) >= 5:
        from scipy.stats import spearmanr
        rho, p = spearmanr(both["mean_h1"], both["mean_h2"])
        rep["cell_persistence"] = {
            "n_cells": int(len(both)), "spearman": float(rho), "p": float(p),
            "sign_agreement": float(
                ((both["mean_h1"] > 0) == (both["mean_h2"] > 0)).mean()),
        }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2, default=str)
    print(f"[hist] wrote {out}")

    print("\n=== HISTORY REALIZED EDGE (net of fee, cents/contract) ===")
    for k in ["overall_all_evals", "overall_latest_per_mkey"]:
        v = rep.get(k, {})
        print(f"{k:32s} mean={v.get('mean', float('nan')):+.2f} "
              f"CI[{v.get('ci_lo', float('nan')):+.2f},{v.get('ci_hi', float('nan')):+.2f}] "
              f"n={v.get('n',0)} mkts={v.get('n_markets',0)}")
    print("cells:", rep.get("cells_summary"))
    print("persistence:", rep.get("cell_persistence"))
    if "overclaim" in rep:
        print("overclaim:", rep["overclaim"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
