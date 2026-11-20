"""Edge audit v2 — causal sampling, correct fees, window clustering,
walk-forward cell memory, real-money fills P&L.

Fixes vs first pass:
  * causal snapshots: first obs per (market-side, TTE bucket) and last-minute
    snapshot, instead of non-causal 'latest per mkey' only
  * fee = logged fee_cents else unrounded parabolic 0.07*p*(1-p)*100 cents
    (the ceil() per-contract ceiling overcharged ~0.5-1c)
  * cluster unit = settlement window (all 5 assets share 15m boundaries)
  * walk-forward cell-memory test: does trailing cell edge predict next-day
    realized edge out-of-sample?
  * within-band model-skill regression: does p_model add edge beyond price?
  * real money from kalshi_fills ledger (YES-delta accounting, settlement
    rows excluded, terminal = residual exposure x settlement value)

    python scripts/audit_edge_v2.py --boot 1000
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_edge_vs_memory import (  # noqa: E402
    bh_fdr, cell_key, cluster_boot, price_bucket, tte_bucket,
)


def parabolic_fee_cents(price_cents: float) -> float:
    """Unrounded Kalshi taker fee per contract, cents."""
    p = max(0.0, min(1.0, float(price_cents) / 100.0))
    return 0.07 * p * (1.0 - p) * 100.0


def window_key(ticker: str) -> str:
    """Settlement-window cluster id shared across the 5 assets."""
    try:
        return str(ticker).split("-")[1]
    except Exception:
        return str(ticker)


def load_panel(cal_path: str, out_path: str) -> pd.DataFrame:
    rows = []
    with open(cal_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    cal = pd.DataFrame(rows)
    outs = {}
    with open(out_path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("event_type") == "settlement_outcome":
                outs[d["ticker"]] = d["resolved_yes"]
    df = cal[cal["ticker"].isin(outs)].copy()
    df["resolved_yes"] = df["ticker"].map(outs)
    return df


def prep(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    side = df["side"].astype(str).str.lower()
    df["side"] = side
    df["win"] = np.where(side == "yes", df["resolved_yes"] == 1,
                         df["resolved_yes"] == 0)
    df["entry"] = pd.to_numeric(df["entry_price_cents"], errors="coerce")
    logged_fee = pd.to_numeric(df["fee_cents"], errors="coerce")
    df["fee"] = logged_fee.fillna(df["entry"].map(parabolic_fee_cents))
    df["payout"] = np.where(df["win"], 100.0, 0.0)
    df["real_edge"] = df["payout"] - df["entry"] - df["fee"]
    df["claim_gap"] = pd.to_numeric(df["gross_edge_c"], errors="coerce") - df["fee"]
    df["mkey"] = df["ticker"].astype(str) + "|" + side
    df["wkey"] = df["ticker"].map(window_key)
    df["tte_bucket"] = df["seconds_to_expiry"].map(tte_bucket)
    df["price_bucket"] = df["entry"].map(price_bucket)
    df["cell"] = [cell_key(a, s, p, t) for a, s, p, t in
                  zip(df["asset"], side, df["entry"], df["seconds_to_expiry"])]
    df["day"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.floor("D")
    return df


def causal_snapshots(df: pd.DataFrame) -> dict:
    out = {}
    # first obs per (mkey, tte_bucket): earliest causal read in each bucket
    first = (df.sort_values("ts")
               .groupby(["mkey", "tte_bucket"], as_index=False).head(1))
    out["first_per_tte_bucket"] = first
    # last-minute snapshot: max ts per mkey (the TTE<60 read)
    last = df.sort_values("ts").groupby("mkey", as_index=False).tail(1)
    out["last_minute"] = last
    # first obs per mkey overall (earliest signal)
    earliest = df.sort_values("ts").groupby("mkey", as_index=False).head(1)
    out["first_overall"] = earliest
    return out


def cell_table(d: pd.DataFrame, n_boot: int, rng, min_mk: int = 10) -> pd.DataFrame:
    rows = []
    for ck, g in d.groupby("cell"):
        st = cluster_boot(g, "real_edge", n_boot, rng)
        if st["n_markets"] < min_mk:
            continue
        a, s, pb, tb = ck.split("|")
        p_bar = float(g["entry"].mean())
        fee_bar = float(g["fee"].mean())
        wins = int(g["win"].sum())
        n_mk = int(g["ticker"].nunique())
        from scipy.stats import beta as bd
        wr_lo = float(bd.ppf(0.05, wins + 0.5, n_mk - wins + 0.5))
        rows.append({
            "cell": ck, "asset": a, "side": s, "price_bucket": pb,
            "tte_bucket": tb, **st,
            "mean_entry": p_bar, "mean_fee": fee_bar,
            "wins": wins, "wr": wins / n_mk if n_mk else np.nan,
            "wr_breakeven": (p_bar + fee_bar) / 100.0,
            "wr_lo5": wr_lo,
            "ev_at_wr_lo": wr_lo * 100.0 - p_bar - fee_bar,
        })
    t = pd.DataFrame(rows)
    if len(t):
        t["p_pos"] = t["p_le_0"].fillna(1.0)
        pos = t["mean"] > 0
        t["q_bh"] = np.nan
        if pos.any():
            t.loc[pos, "q_bh"] = bh_fdr(t.loc[pos, "p_pos"].to_numpy())
        t["sig_neg"] = t["ci_hi"] < 0
        t = t.sort_values("mean", ascending=False)
    return t


def walkforward_memory(df: pd.DataFrame, cell_col: str = "cell",
                       min_hist: int = 30, min_fwd: int = 10) -> dict:
    """Trailing-cell edge -> next-day realized edge (the memory skill test).

    For each day D: cells are 'remembered' if their trailing realized edge
    (all days < D) has mean>0 and n_markets>=min_hist.  Measure day-D edge
    of remembered cells vs the rest.  Aggregate daily OOS spreads.
    """
    d = df.copy()
    d["day"] = pd.to_datetime(d["ts"], unit="s", utc=True).dt.floor("D")
    days = sorted(d["day"].unique())
    oos_rows = []
    for i, day in enumerate(days):
        hist = d[d["day"] < day]
        fwd = d[d["day"] == day]
        if len(hist) < 500 or len(fwd) < 200:
            continue
        hstats = hist.groupby(cell_col)["real_edge"].agg(["mean", "count"])
        remembered = set(hstats[(hstats["mean"] > 0) &
                                (hstats["count"] >= min_hist)].index)
        fwd = fwd.copy()
        fwd["remembered"] = fwd[cell_col].isin(remembered)
        for flag, g in fwd.groupby("remembered"):
            oos_rows.append({
                "day": str(day.date()), "remembered": bool(flag),
                "mean_edge": float(g["real_edge"].mean()),
                "n": int(len(g)), "n_markets": int(g["ticker"].nunique()),
            })
    oos = pd.DataFrame(oos_rows)
    if len(oos) == 0:
        return {"note": "insufficient days"}
    piv = oos.pivot_table(index="day", columns="remembered",
                          values="mean_edge", aggfunc="mean")
    piv.columns = [f"rem_{c}" for c in piv.columns]
    piv["spread"] = piv.get("rem_True", np.nan) - piv.get("rem_False", np.nan)
    rep = {
        "n_days": int(len(piv)),
        "mean_oos_edge_remembered": float(piv["rem_True"].mean())
        if "rem_True" in piv else None,
        "mean_oos_edge_forgotten": float(piv["rem_False"].mean())
        if "rem_False" in piv else None,
        "mean_spread": float(piv["spread"].mean()),
        "spread_ci_note": "daily spread series, see json",
        "daily": piv.reset_index().to_dict("records"),
    }
    # sign consistency of the spread
    rep["spread_positive_days"] = int((piv["spread"] > 0).sum())
    rep["spread_total_days"] = int(piv["spread"].notna().sum())
    return rep


def within_band_skill(df: pd.DataFrame, rng, n_boot: int = 500) -> dict:
    """Within price bands: does claim_gap (p_model*100 - entry - fee) predict
    realized edge?  Clustered slope via block bootstrap on windows."""
    out = {}
    for pb in ["25-49", "50-74", "75-89", "90-100"]:
        g = df[df["price_bucket"] == pb].dropna(subset=["claim_gap", "real_edge"])
        if len(g) < 500:
            continue
        # dedup: one obs per (mkey, tte_bucket) causal snapshot
        g = g.sort_values("ts").groupby(["mkey", "tte_bucket"],
                                      as_index=False).head(1)
        x = g["claim_gap"].to_numpy()
        y = g["real_edge"].to_numpy()
        # OLS slope y ~ a + b*x
        X = np.column_stack([np.ones(len(x)), x])
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        # block bootstrap over windows — weight-based (each row's weight =
        # how many times its window was drawn) to avoid O(n*m) isin scans
        codes, uniq = pd.factorize(g["wkey"].to_numpy())
        n_cl = len(uniq)
        slopes = np.empty(n_boot)
        ok = np.zeros(n_boot, dtype=bool)
        for b in range(n_boot):
            cnt = np.bincount(rng.integers(0, n_cl, size=n_cl),
                              minlength=n_cl)
            w = cnt[codes].astype(float)
            sw = np.sqrt(w)
            Xw = X * sw[:, None]
            yw = y * sw
            try:
                bb, *_ = np.linalg.lstsq(Xw, yw, rcond=None)
                slopes[b] = bb[1]
                ok[b] = w.sum() >= 100
            except Exception:
                ok[b] = False
        slopes = slopes[ok]
        out[pb] = {
            "n": int(len(g)), "n_windows": int(n_cl),
            "slope": float(beta[1]),
            "intercept": float(beta[0]),
            "slope_ci": [float(np.percentile(slopes, 2.5)),
                         float(np.percentile(slopes, 97.5))]
            if len(slopes) else None,
        }
    return out


def real_money_fills(db_path: str, outcomes_path: str) -> dict:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=60)
    df = pd.read_sql_query(
        "SELECT market_ticker, canonical_leg_price_cents, "
        "canonical_yes_delta_cc, fee_cost, liquidity_role, fill_source, "
        "created_time FROM kalshi_fills", conn)
    conn.close()
    outs = {}
    with open(outcomes_path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("event_type") == "settlement_outcome":
                outs[d["ticker"]] = d["resolved_yes"]
    df["is_settle"] = df["liquidity_role"].eq("settlement") | \
        df["fill_source"].eq("settlement")
    real = df[~df["is_settle"]].copy()
    real["cash_c"] = (-(real["canonical_yes_delta_cc"] / 100.0)
                      * real["canonical_leg_price_cents"]
                      - real["fee_cost"] * 100.0)
    real["d"] = real["canonical_yes_delta_cc"] / 100.0
    g = real.groupby("market_ticker").agg(
        cash_c=("cash_c", "sum"), E=("d", "sum"), n=("d", "size"),
        first_ts=("created_time", "min"))
    g["settle_yes"] = g.index.map(outs)
    g = g[g["settle_yes"].notna()].copy()
    g["terminal_c"] = g["E"] * 100.0 * g["settle_yes"]
    g["pnl_c"] = g["cash_c"] + g["terminal_c"]
    g["month"] = g["first_ts"].str[:7]
    g["asset"] = g.index.str.extract(r"KX([A-Z]+)15M", expand=False)
    rep = {
        "n_markets": int(len(g)),
        "total_pnl_cents": float(g["pnl_c"].sum()),
        "mean_pnl_cents": float(g["pnl_c"].mean()),
        "win_rate": float((g["pnl_c"] > 0).mean()),
        "by_month": g.groupby("month")["pnl_c"]
        .agg(["count", "sum", "mean"]).reset_index().to_dict("records"),
        "by_asset": g.groupby("asset")["pnl_c"]
        .agg(["count", "sum", "mean"]).reset_index().to_dict("records"),
        "fee_total_usd_recorded": float(df["fee_cost"].sum()),
        "note": "settlement pseudo-fills excluded; terminal = residual "
                "YES exposure x settlement value; fee_cost coverage partial",
    }
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cal", default="logs/model_calibration_observations.jsonl")
    ap.add_argument("--outcomes", default="logs/settlement_outcomes.jsonl")
    ap.add_argument("--fills-db", default="data/kalshi_fills.db")
    ap.add_argument("--out", default="reports/edge_audit_v2.json")
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=20261119)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    print("[v2] loading panel ...", flush=True)
    df = prep(load_panel(args.cal, args.outcomes))
    print(f"[v2] {len(df)} evals, {df['ticker'].nunique()} markets", flush=True)

    rep: dict = {"population": {
        "n_evals": int(len(df)), "n_markets": int(df["ticker"].nunique()),
        "n_market_sides": int(df["mkey"].nunique()),
        "ts_span": [float(df["ts"].min()), float(df["ts"].max())],
    }}

    snaps = causal_snapshots(df)
    print("[v2] snapshots built", flush=True)
    snap_stats = {}
    for name, d in snaps.items():
        snap_stats[name] = cluster_boot(d, "real_edge", args.boot, rng)
        snap_stats[name]["n_rows"] = int(len(d))
        print(f"[v2] boot {name} done", flush=True)
    rep["snapshots"] = snap_stats

    # cells on causal snapshots
    for name in ["first_per_tte_bucket", "last_minute", "first_overall"]:
        d = snaps[name]
        print(f"[v2] cells {name} ...", flush=True)
        cells = cell_table(d, args.boot, rng, min_mk=10)
        rep[f"cells_{name}"] = {
            "summary": {
                "n_cells": int(len(cells)),
                "n_ci_above_0": int((cells["ci_lo"] > 0).sum()) if len(cells) else 0,
                "n_pos_q_bh": int((cells["q_bh"] < 0.05).sum()) if len(cells) else 0,
                "n_pos_mean": int((cells["mean"] > 0).sum()) if len(cells) else 0,
                "pos_cells_ev_neg_at_wr_lo": int(
                    ((cells["mean"] > 0) & (cells["ev_at_wr_lo"] < 0)).sum())
                if len(cells) else 0,
            },
            "cells": cells.head(40).to_dict("records") if len(cells) else [],
        }

    print("[v2] marginals ...", flush=True)
    # marginals on last_minute snapshot
    last = snaps["last_minute"]
    for col, name in [("price_bucket", "by_price_bucket"),
                      ("tte_bucket", "by_tte_bucket"),
                      ("asset", "by_asset"), ("side", "by_side")]:
        t = cluster_boot_table(last, col, "real_edge", args.boot, rng)
        rep[f"marginal_{name}"] = t.to_dict("records") if len(t) else []

    print("[v2] weekly + claim deciles ...", flush=True)
    # weekly trend on all evals (dedup per mkey,tte_bucket)
    alld = snaps["first_per_tte_bucket"]
    alld["week"] = pd.to_datetime(alld["ts"], unit="s", utc=True).dt.strftime("%G-W%V")
    wk = cluster_boot_table(alld.assign(week=alld["week"].fillna("?")),
                            "week", "real_edge", args.boot, rng)
    rep["by_week"] = wk.to_dict("records") if len(wk) else []

    # claim deciles on causal snapshot
    claim = snaps["first_per_tte_bucket"].dropna(subset=["claim_gap"])
    if len(claim):
        claim = claim.copy()
        claim["dec"] = pd.qcut(claim["claim_gap"], 10, duplicates="drop")
        rows = []
        for dec, g in claim.groupby("dec", observed=True):
            st = cluster_boot(g, "real_edge", args.boot, rng)
            rows.append({"decile": str(dec),
                         "claim_mean": float(g["claim_gap"].mean()),
                         "real_mean": st["mean"], "ci_lo": st["ci_lo"],
                         "ci_hi": st["ci_hi"], "n": st["n"],
                         "n_markets": st["n_markets"]})
        rep["claim_deciles_first_per_bucket"] = rows
        from scipy.stats import spearmanr
        rho, p = spearmanr(claim["claim_gap"], claim["real_edge"])
        rep["claim_spearman_all_evals"] = {"rho": float(rho), "p": float(p),
                                           "n": int(len(claim))}

    print("[v2] within-band skill ...", flush=True)
    rep["within_band_skill"] = within_band_skill(snaps["first_per_tte_bucket"],
                                                 rng, n_boot=400)
    print("[v2] walk-forward memory ...", flush=True)
    rep["walkforward_memory_first_per_bucket"] = walkforward_memory(
        snaps["first_per_tte_bucket"])

    print("[v2] real money ...", flush=True)
    rep["real_money"] = real_money_fills(args.fills_db, args.outcomes)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2, default=str)
    print(f"[v2] wrote {out}")

    print("\n=== SNAPSHOT REALIZED EDGE (net fee, cents/contract) ===")
    for k, v in snap_stats.items():
        print(f"{k:26s} mean={v['mean']:+.2f} CI[{v['ci_lo']:+.2f},{v['ci_hi']:+.2f}] "
              f"n={v['n']} mk={v['n_markets']}")
    rm = rep["real_money"]
    print(f"\n=== REAL MONEY (fills ledger) === total={rm['total_pnl_cents']:+.0f}c "
          f"n_mkts={rm['n_markets']} mean={rm['mean_pnl_cents']:+.2f}c")
    for m in rm["by_month"]:
        print(f"  {m['month']}: n={m['count']} sum={m['sum']:+.0f}c mean={m['mean']:+.2f}")
    wfm = rep["walkforward_memory_first_per_bucket"]
    print("\nwalk-forward memory:", {k: v for k, v in wfm.items() if k != "daily"})
    print("within-band skill:", json.dumps(rep["within_band_skill"], indent=1))
    return 0


def cluster_boot_table(df: pd.DataFrame, key: str, val: str,
                       n_boot: int, rng) -> pd.DataFrame:
    rows = []
    for k, g in df.groupby(key, dropna=False):
        st = cluster_boot(g, val, n_boot, rng)
        if st["n_markets"] < 5:
            continue
        rows.append({key: str(k), **st})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    sys.exit(main())
