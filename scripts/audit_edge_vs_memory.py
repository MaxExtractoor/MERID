"""Deep audit: realized edge vs model-claimed edge vs evidence-cell memory.

Reads the incremental evidence-outcome store (every settled side-eval the
system considered, traded or not), joins the fill/veto/ebias extracts per
(decision_id, side), and measures:

  * realized per-contract settlement edge (gross and net of Kalshi taker fee)
  * the model's claimed edge (expected_net_ev_cents / calibrated-probability
    implied gross edge)
  * canonical evidence cells (asset|side|price_bucket|tte_bucket) -- the same
    granularity the live_entry_evidence artifact gates on
  * gate value-add (passed_edge_gate split)
  * traded-cohort realized edge by lane (ENTER decisions)
  * actual-money settlement P&L from trade_attribution_fact

Inference: cluster bootstrap by market ticker (yes/no sides of one market
and repeat evals within a market are correlated), BH-FDR + Bonferroni across
the cell family.  Read-only; safe to run against the live store.

Usage:
    python scripts/audit_edge_vs_memory.py [--db data/decision_audit_evidence_outcomes.db]
                                          [--attribution data/trade_attribution_fact.db]
                                          [--evidence data/live_entry_evidence.json]
                                          [--out reports/edge_vs_memory_audit.json]
                                          [--boot 1000] [--seed 20261119]
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

# --------------------------------------------------------------------------
# Canonical cell definitions -- must match merid/prediction/evidence_policy.py
# --------------------------------------------------------------------------

def price_bucket(p: float) -> str:
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "unknown"
    p = int(round(float(p)))
    if p <= 9:
        return "01-09"
    if p <= 24:
        return "10-24"
    if p <= 49:
        return "25-49"
    if p <= 74:
        return "50-74"
    if p <= 89:
        return "75-89"
    return "90-100"


def tte_bucket(t: float) -> str:
    if t is None or (isinstance(t, float) and math.isnan(t)):
        return "unknown"
    t = float(t)
    if t > 600.0:
        return "early"
    if t > 300.0:
        return "mid"
    if t > 120.0:
        return "late"
    return "final"


def cell_key(asset, side, price_cents, tte_seconds) -> str:
    return (
        f"{str(asset).upper()}|{str(side).lower()}|"
        f"{price_bucket(price_cents)}|{tte_bucket(tte_seconds)}"
    )


# --------------------------------------------------------------------------
# Kalshi fee model (parabolic, taker = 0.0175? -> canonical 0.07 taker rate)
# fee_usd = ceil(0.07 * C * P * (1-P) * 100) / 100  (P in dollars)
# => fee_cents for 1 contract = ceil(0.07 * p * (1-p) * 100)  with p in dollars
# --------------------------------------------------------------------------

def taker_fee_cents(price_cents: float) -> float:
    p = max(0.0, min(1.0, float(price_cents) / 100.0))
    return float(math.ceil(0.07 * p * (1.0 - p) * 100.0 - 1e-9))


def maker_fee_cents(price_cents: float) -> float:
    p = max(0.0, min(1.0, float(price_cents) / 100.0))
    return float(math.ceil(0.0175 * p * (1.0 - p) * 100.0 - 1e-9))


# --------------------------------------------------------------------------
# Load + union the three evidence extracts
# --------------------------------------------------------------------------

def load_evals(db_path: str) -> pd.DataFrame:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=60)
    df = pd.read_sql_query(
        "SELECT row_key, src, asset, side, ticker, decision_id, mkey, "
        "seconds_to_close, entry_cents, fill_px_cents, decision_px_cents, "
        "exp_slip_cents, lane, calibrated_probability, settled_yes, "
        "settled_at, decision_ts, exclusion_reason, passed_edge_gate, "
        "cf_status, net_ev, esrc, q_assumed, cf_yes, cf_no "
        "FROM evidence_outcome_rows WHERE settled_at IS NOT NULL",
        conn,
    )
    conn.close()
    return df


def union_evals(df: pd.DataFrame) -> pd.DataFrame:
    """Merge fill/veto/ebias rows sharing (decision_id, side) into one eval."""
    df = df.copy()
    # canonical eval key
    df["eval_key"] = df["decision_id"].fillna("") + "|" + df["side"].fillna("")
    # fields we want, first-non-null across srcs
    fields = [
        "asset", "side", "ticker", "mkey", "seconds_to_close", "entry_cents",
        "fill_px_cents", "decision_px_cents", "exp_slip_cents", "lane",
        "calibrated_probability", "settled_yes", "settled_at", "decision_ts",
        "exclusion_reason", "passed_edge_gate", "cf_status", "net_ev",
        "esrc", "q_assumed", "cf_yes", "cf_no",
    ]
    src_rank = {"fill": 0, "veto": 1, "ebias": 2}
    df["_rank"] = df["src"].map(src_rank).fillna(9)
    # groupby.first() takes the first NON-NULL value per column; sorting by
    # src rank makes fill rows win ties, then veto, then ebias.
    df = df.sort_values(["eval_key", "_rank"], kind="mergesort")
    out = df.groupby("eval_key", sort=False)[fields].first().reset_index()
    # fast per-src membership flags via set lookups
    fill_keys = set(df.loc[df["src"] == "fill", "eval_key"])
    veto_keys = set(df.loc[df["src"] == "veto", "eval_key"])
    ebias_keys = set(df.loc[df["src"] == "ebias", "eval_key"])
    out["is_enter"] = out["eval_key"].isin(fill_keys).astype(int)
    out["has_veto"] = out["eval_key"].isin(veto_keys).astype(int)
    out["has_ebias"] = out["eval_key"].isin(ebias_keys).astype(int)
    out["srcs"] = np.select(
        [out["is_enter"] == 1, out["has_veto"] == 1, out["has_ebias"] == 1],
        ["enter", "veto", "ebias_only"],
        default="unknown",
    )
    # an ENTER decision also emits veto-style side rows? keep srcs simple:
    out.loc[(out["is_enter"] == 1) & (out["has_ebias"] == 1), "srcs"] = "enter+ebias"
    return out


def add_realized(out: pd.DataFrame) -> pd.DataFrame:
    out = out.copy()
    settled_yes = out["settled_yes"]
    side = out["side"].astype(str).str.lower()
    win = pd.Series(
        np.where(
            settled_yes.isna(),
            np.nan,
            np.where(side == "yes", settled_yes == 1, settled_yes == 0),
        ),
        index=out.index,
    )
    out["win"] = win
    entry = pd.to_numeric(out["entry_cents"], errors="coerce")
    payout = np.where(win == True, 100.0, 0.0)  # noqa: E712
    out["real_gross_c"] = pd.Series(
        np.where(win.notna() & entry.notna(), payout - entry, np.nan),
        index=out.index,
    )
    fee_t = entry.map(taker_fee_cents)
    fee_m = entry.map(maker_fee_cents)
    out["real_net_taker_c"] = out["real_gross_c"] - fee_t
    out["real_net_maker_c"] = out["real_gross_c"] - fee_m
    # counterfactual-PnL realized edge (system fee model), per contract
    q = pd.to_numeric(out["q_assumed"], errors="coerce")
    cf = pd.Series(
        np.where(side == "yes", out["cf_yes"], out["cf_no"]), index=out.index
    )
    cf_num = pd.to_numeric(cf, errors="coerce")
    out["real_cf_pc"] = pd.Series(
        np.where(cf_num.notna() & (q > 0), cf_num / q, np.nan), index=out.index
    )
    # model claims
    out["claim_net_ev_c"] = pd.to_numeric(out["net_ev"], errors="coerce")
    calp = pd.to_numeric(out["calibrated_probability"], errors="coerce")
    out["claim_implied_gross_c"] = np.where(
        calp.notna() & entry.notna(), calp * 100.0 - entry, np.nan
    )
    out["cell"] = [
        cell_key(a, s, p, t)
        for a, s, p, t in zip(
            out["asset"], out["side"], out["entry_cents"], out["seconds_to_close"]
        )
    ]
    out["price_bucket"] = out["entry_cents"].map(price_bucket)
    out["tte_bucket"] = out["seconds_to_close"].map(tte_bucket)
    return out


# --------------------------------------------------------------------------
# Cluster bootstrap by ticker
# --------------------------------------------------------------------------

def cluster_boot(
    df: pd.DataFrame, value_col: str, n_boot: int, rng: np.random.Generator
) -> dict:
    """Bootstrap the mean of value_col resampling tickers (clusters)."""
    d = df.dropna(subset=[value_col, "ticker"])
    if len(d) == 0:
        return {"n": 0, "mean": np.nan, "ci_lo": np.nan, "ci_hi": np.nan,
                "p_le_0": np.nan, "n_markets": 0}
    g = d.groupby("ticker")[value_col].agg(["sum", "count"])
    sums = g["sum"].to_numpy()
    cnts = g["count"].to_numpy()
    n_clusters = len(g)
    total_cnt = cnts.sum()
    if n_clusters < 2 or total_cnt == 0:
        return {"n": int(total_cnt), "mean": float(d[value_col].mean()),
                "ci_lo": np.nan, "ci_hi": np.nan, "p_le_0": np.nan,
                "n_markets": int(n_clusters)}
    idx = rng.integers(0, n_clusters, size=(n_boot, n_clusters))
    boot_sum = sums[idx].sum(axis=1)
    boot_cnt = cnts[idx].sum(axis=1)
    boot_mean = boot_sum / np.maximum(boot_cnt, 1)
    mean = float(d[value_col].mean())
    return {
        "n": int(total_cnt),
        "mean": mean,
        "ci_lo": float(np.percentile(boot_mean, 2.5)),
        "ci_hi": float(np.percentile(boot_mean, 97.5)),
        "p_le_0": float(np.mean(boot_mean <= 0.0)),
        "n_markets": int(n_clusters),
    }


def cohort_table(
    df: pd.DataFrame,
    key_cols: list[str],
    value_col: str,
    n_boot: int,
    rng: np.random.Generator,
    min_markets: int = 5,
) -> pd.DataFrame:
    rows = []
    for keys, g in df.groupby(key_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        st = cluster_boot(g, value_col, n_boot, rng)
        if st["n_markets"] < min_markets:
            continue
        rows.append({**dict(zip(key_cols, keys)), **st})
    return pd.DataFrame(rows)


def bh_fdr(pvals: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg adjusted q-values."""
    p = np.asarray(pvals, dtype=float)
    n = len(p)
    order = np.argsort(p)
    ranked = p[order]
    q = ranked * n / (np.arange(n) + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    out = np.empty(n)
    out[order] = np.clip(q, 0, 1)
    return out


# --------------------------------------------------------------------------
# Analyses
# --------------------------------------------------------------------------

def analyze_evals(ev: pd.DataFrame, n_boot: int, rng: np.random.Generator) -> dict:
    rep: dict = {}
    settled = ev[ev["real_net_taker_c"].notna() | ev["real_cf_pc"].notna()].copy()
    # prefer system-fee cf where present? keep taker-fee as primary; cf as alt
    settled["real_edge"] = settled["real_net_taker_c"].fillna(settled["real_cf_pc"])
    rep["population"] = {
        "n_eval_rows_unioned": int(len(ev)),
        "n_settled_evals": int(len(settled)),
        "n_market_sides": int(settled["mkey"].nunique()),
        "n_markets": int(settled["ticker"].nunique()),
        "span_decision_ts": [
            float(settled["decision_ts"].min()),
            float(settled["decision_ts"].max()),
        ],
    }

    # ---- A. overall realized edge (all evals, clustered) ----
    rep["overall_all_evals"] = cluster_boot(settled, "real_edge", n_boot, rng)

    # newest eval per market-side (the system's 'final read')
    latest = (
        settled.sort_values("decision_ts")
        .groupby("mkey", as_index=False)
        .tail(1)
    )
    rep["overall_latest_per_mkey"] = cluster_boot(latest, "real_edge", n_boot, rng)

    # first eval per market-side with TTE <= 600 (entry-window realistic)
    early = settled[settled["seconds_to_close"] <= 600]
    first = (
        early.sort_values("decision_ts")
        .groupby("mkey", as_index=False)
        .head(1)
    )
    rep["overall_first_tte600"] = cluster_boot(first, "real_edge", n_boot, rng)

    # ---- B. by src composition ----
    rep["by_srcs"] = cohort_table(settled.assign(srcs=settled["srcs"].fillna("?")),
                                  ["srcs"], "real_edge", n_boot, rng, min_markets=3)

    # ---- C. claimed vs realized: edge-claim calibration ----
    claim = settled.dropna(subset=["claim_net_ev_c"]).copy()
    rep["claim_coverage"] = {
        "n_with_net_ev": int(len(claim)),
        "n_market_sides": int(claim["mkey"].nunique()),
    }
    if len(claim):
        # deciles of claimed net edge -> realized edge
        claim["claim_decile"] = pd.qcut(
            claim["claim_net_ev_c"], 10, duplicates="drop"
        )
        dec_rows = []
        for dec, g in claim.groupby("claim_decile", observed=True):
            st = cluster_boot(g, "real_edge", n_boot, rng)
            dec_rows.append({
                "decile": str(dec),
                "claim_mean": float(g["claim_net_ev_c"].mean()),
                "real_mean": st["mean"], "ci_lo": st["ci_lo"],
                "ci_hi": st["ci_hi"], "n": st["n"],
                "n_markets": st["n_markets"],
            })
        rep["claim_deciles"] = dec_rows
        # rank correlation claimed vs realized (dedup latest per mkey)
        cl = claim.sort_values("decision_ts").groupby("mkey", as_index=False).tail(1)
        if len(cl) > 30:
            from scipy.stats import spearmanr
            rho, p = spearmanr(cl["claim_net_ev_c"], cl["real_edge"])
            rep["claim_rank"] = {"spearman_rho": float(rho), "p": float(p),
                                 "n": int(len(cl))}
        # over-claim gap = mean(claim) - mean(realized)
        rep["overclaim_gap"] = {
            "mean_claim_net_ev_c": float(claim["claim_net_ev_c"].mean()),
            "mean_realized_net_c": float(claim["real_edge"].mean()),
            "gap_c": float(claim["claim_net_ev_c"].mean() - claim["real_edge"].mean()),
        }

    # implied gross edge calibration (calibrated_probability based)
    imp = settled.dropna(subset=["claim_implied_gross_c"]).copy()
    if len(imp):
        imp["imp_decile"] = pd.qcut(
            imp["claim_implied_gross_c"], 10, duplicates="drop"
        )
        dec_rows = []
        for dec, g in imp.groupby("imp_decile", observed=True):
            st = cluster_boot(g, "real_edge", n_boot, rng)
            dec_rows.append({
                "decile": str(dec),
                "implied_gross_mean": float(g["claim_implied_gross_c"].mean()),
                "real_net_mean": st["mean"], "ci_lo": st["ci_lo"],
                "ci_hi": st["ci_hi"], "n": st["n"],
                "n_markets": st["n_markets"],
            })
        rep["implied_edge_deciles"] = dec_rows

    # ---- D. canonical cells (latest eval per mkey) ----
    cell_df = latest.copy()
    cell_df["cell"] = [
        cell_key(a, s, p, t)
        for a, s, p, t in zip(
            cell_df["asset"], cell_df["side"],
            cell_df["entry_cents"], cell_df["seconds_to_close"],
        )
    ]
    rows = []
    for ck, g in cell_df.groupby("cell"):
        st = cluster_boot(g, "real_edge", n_boot, rng)
        if st["n_markets"] < 8:
            continue
        a, s, pb, tb = ck.split("|")
        rows.append({
            "cell": ck, "asset": a, "side": s, "price_bucket": pb,
            "tte_bucket": tb, **st,
            "mean_claim_net_ev_c": float(g["claim_net_ev_c"].mean())
            if g["claim_net_ev_c"].notna().any() else None,
            "win_rate": float(g["win"].mean()) if g["win"].notna().any() else None,
        })
    cells = pd.DataFrame(rows)
    if len(cells):
        # one-sided p for "+edge" claims; BH-FDR across positive-mean cells only
        cells["p_pos"] = cells["p_le_0"].fillna(1.0)
        pos = cells["mean"] > 0
        cells["q_bh_pos"] = np.nan
        if pos.any():
            cells.loc[pos, "q_bh_pos"] = bh_fdr(
                cells.loc[pos, "p_pos"].to_numpy()
            )
        cells["sig_neg"] = cells["ci_hi"] < 0
        # tail-risk: Beta posterior on win rate -> EV at conservative wr
        cell_stats = []
        for ck, g in cell_df.groupby("cell"):
            st = cluster_boot(g, "real_edge", max(n_boot // 4, 100), rng)
            if st["n_markets"] < 8:
                continue
            entry = pd.to_numeric(g["entry_cents"], errors="coerce")
            p_bar = float(entry.mean()) if entry.notna().any() else np.nan
            fee = float(np.mean([taker_fee_cents(x) for x in entry.dropna()])) \
                if entry.notna().any() else np.nan
            wins = int((g["win"] == True).sum())  # noqa: E712
            n_mk = int(g["ticker"].nunique())
            # Beta(wins+0.5, n-wins+0.5) 5th pct = conservative win rate
            from scipy.stats import beta as beta_dist
            wr_lo = float(beta_dist.ppf(0.05, wins + 0.5, n_mk - wins + 0.5)) \
                if n_mk > 0 else np.nan
            wr_star = (p_bar + fee) / 100.0 if np.isfinite(p_bar) else np.nan
            ev_at_wr_lo = (wr_lo * 100.0 - p_bar - fee) if np.isfinite(
                wr_lo + p_bar + fee) else np.nan  # type: ignore
            cell_stats.append({
                "cell": ck, "mean_entry_c": p_bar, "fee_c": fee,
                "wins": wins, "n_markets_wr": n_mk,
                "wr_observed": wins / n_mk if n_mk else np.nan,
                "wr_breakeven": wr_star, "wr_posterior_lo5": wr_lo,
                "ev_at_wr_lo_c": ev_at_wr_lo,
            })
        tail = pd.DataFrame(cell_stats)
        cells = cells.merge(tail, on="cell", how="left")
        cells = cells.sort_values("mean", ascending=False)
        rep["cells"] = cells.to_dict("records")
        rep["cells_summary"] = {
            "n_cells": int(len(cells)),
            "n_cells_ci_above_0": int((cells["ci_lo"] > 0).sum()),
            "n_cells_pos_q_bh_0.05": int((cells["q_bh_pos"] < 0.05).sum()),
            "n_cells_sig_neg": int(cells["sig_neg"].sum()),
            "n_cells_mean_pos": int(pos.sum()),
            "n_pos_cells_ev_neg_at_wr_lo": int(
                (cells["ev_at_wr_lo_c"] < 0).sum()
            ),
        }

    # ---- E. marginal cuts on latest-per-mkey ----
    for col, name in [
        ("asset", "by_asset"), ("side", "by_side"),
        ("price_bucket", "by_price_bucket"), ("tte_bucket", "by_tte_bucket"),
    ]:
        rep[name] = cohort_table(latest.assign(**{col: latest[col].fillna("?")}),
                                 [col], "real_edge", n_boot, rng, min_markets=5)
        rep[name] = rep[name].to_dict("records")

    # ---- F. gate value-add (latest read per market-side, like cells) ----
    gate = latest[
        latest["passed_edge_gate"].isin([0, 1, "0", "1", True, False])
    ].copy()
    if len(gate):
        gate["passed_edge_gate"] = gate["passed_edge_gate"].astype(int)
        rep["by_edge_gate"] = cohort_table(gate, ["passed_edge_gate"],
                                           "real_edge", n_boot, rng, min_markets=3)
        rep["by_edge_gate"] = rep["by_edge_gate"].to_dict("records")
        # all-evals version for volume context
        gate_all = settled[
            settled["passed_edge_gate"].isin([0, 1, "0", "1", True, False])
        ].copy()
        gate_all["passed_edge_gate"] = gate_all["passed_edge_gate"].astype(int)
        rep["by_edge_gate_all_evals"] = cohort_table(
            gate_all, ["passed_edge_gate"], "real_edge", n_boot, rng,
            min_markets=3)
        rep["by_edge_gate_all_evals"] = rep["by_edge_gate_all_evals"].to_dict("records")

    # ---- F2. cell persistence: H1 edge -> H2 edge (memory skill test) ----
    med_ts = float(settled["decision_ts"].median())
    h1 = cell_df[cell_df["decision_ts"] <= med_ts]
    h2 = cell_df[cell_df["decision_ts"] > med_ts]
    h1c = h1.groupby("cell")["real_edge"].agg(["mean", "count"])
    h2c = h2.groupby("cell")["real_edge"].agg(["mean", "count"])
    both = h1c.join(h2c, lsuffix="_h1", rsuffix="_h2", how="inner")
    both = both[(both["count_h1"] >= 3) & (both["count_h2"] >= 3)]
    if len(both) >= 5:
        from scipy.stats import spearmanr
        rho, p = spearmanr(both["mean_h1"], both["mean_h2"])
        rep["cell_persistence"] = {
            "n_cells": int(len(both)),
            "spearman_h1_h2": float(rho), "p": float(p),
            "sign_agreement": float(
                ((both["mean_h1"] > 0) == (both["mean_h2"] > 0)).mean()
            ),
            "h1_mean": float(both["mean_h1"].mean()),
            "h2_mean": float(both["mean_h2"].mean()),
        }
    else:
        rep["cell_persistence"] = {"n_cells": int(len(both)),
                                   "note": "insufficient overlap"}

    # ---- G. ENTER (traded-intent) cohort ----
    enters = settled[settled["is_enter"] == 1].copy()
    rep["enter_population"] = {
        "n_enter_evals": int(len(enters)),
        "n_markets": int(enters["ticker"].nunique()),
    }
    if len(enters):
        rep["enter_overall"] = cluster_boot(enters, "real_edge", n_boot, rng)
        if enters["lane"].notna().any():
            el = enters[enters["lane"].notna()]
            rep["enter_by_lane"] = cohort_table(
                el.assign(lane=el["lane"].fillna("?")), ["lane"],
                "real_edge", n_boot, rng, min_markets=3)
            rep["enter_by_lane"] = rep["enter_by_lane"].to_dict("records")
        # claimed vs realized for ENTER rows with net_ev
        ec = enters.dropna(subset=["claim_net_ev_c"])
        if len(ec):
            rep["enter_claim_vs_real"] = {
                "mean_claim_c": float(ec["claim_net_ev_c"].mean()),
                "mean_real_c": float(ec["real_edge"].mean()),
                "gap_c": float(ec["claim_net_ev_c"].mean() - ec["real_edge"].mean()),
                "n": int(len(ec)),
            }
            el_latest = ec.sort_values("decision_ts").groupby(
                "mkey", as_index=False).tail(1)
            st = cluster_boot(el_latest, "real_edge", n_boot, rng)
            rep["enter_latest"] = {**st,
                                   "mean_claim_c": float(el_latest["claim_net_ev_c"].mean())}

    return rep


def analyze_attribution(db_path: str) -> dict:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=60)
    df = pd.read_sql_query(
        "SELECT event_ts, ticker, asset, side, price_cents, count_fp, "
        "realized_pnl_cents, settlement_outcome, settlement_price_cents, "
        "fee_cost_cents, source FROM trade_attribution_fact "
        "WHERE event_type='settlement' AND realized_pnl_cents IS NOT NULL",
        conn,
    )
    conn.close()
    if len(df) == 0:
        return {"n": 0}
    df["month"] = df["event_ts"].str[:7]
    # settlement rows lack asset/side; recover asset from series ticker
    df["asset"] = df["ticker"].str.extract(r"KX([A-Z]+)15M", expand=False)
    rep = {
        "n_settlements": int(len(df)),
        "total_pnl_cents": float(df["realized_pnl_cents"].sum()),
        "mean_pnl_cents": float(df["realized_pnl_cents"].mean()),
        "win_rate": float((df["realized_pnl_cents"] > 0).mean()),
        "by_month": df.groupby("month")["realized_pnl_cents"]
        .agg(["count", "sum", "mean"]).reset_index().to_dict("records"),
        "by_asset": df.groupby("asset")["realized_pnl_cents"]
        .agg(["count", "sum", "mean"]).reset_index().to_dict("records"),
    }
    # per-contract view where count_fp is populated
    cnt = pd.to_numeric(df["count_fp"], errors="coerce")
    per_ct = df["realized_pnl_cents"] / cnt.where(cnt > 0)
    rep["per_contract"] = {
        "n_with_count": int(per_ct.notna().sum()),
        "mean_pnl_cents_per_contract": float(per_ct.mean()),
        "total_pnl_cents": float(df["realized_pnl_cents"].sum()),
        "total_contracts": float(cnt.sum()),
    }
    # price band via settlement_price (0/100) is meaningless; use entry price
    # when present else skip
    pc = pd.to_numeric(df["price_cents"], errors="coerce")
    if pc.notna().sum() > 100:
        df["price_bucket"] = pc.map(price_bucket)
        rep["by_price_bucket"] = df.groupby("price_bucket")["realized_pnl_cents"] \
            .agg(["count", "sum", "mean"]).reset_index().to_dict("records")
    else:
        rep["by_price_bucket"] = {"note": "entry price not populated on settlement rows"}
    return rep


def analyze_memory_artifact(evidence_path: str, ev: pd.DataFrame) -> dict:
    """Compare live_entry_evidence cell claims vs store-window realized."""
    try:
        art = json.load(open(evidence_path))
    except Exception as exc:
        return {"error": str(exc)}
    cells = art.get("cells", {})
    # use the longest-horizon cell map (key '21' or first)
    cellmap = None
    for k in sorted(cells.keys(), key=lambda x: -int(x)):
        cellmap = cells[k]
        break
    if not cellmap:
        return {"error": "no cells"}
    # realized per cell from store.  Mirror the artifact's per-market
    # normalization: one observation per (cell, market-side) -- the mean edge
    # across that market-side's evals inside the cell.
    settled = ev[ev["real_net_taker_c"].notna() | ev["real_cf_pc"].notna()].copy()
    settled["real_edge"] = settled["real_net_taker_c"].fillna(settled["real_cf_pc"])
    settled["cell"] = [
        cell_key(a, s, p, t)
        for a, s, p, t in zip(settled["asset"], settled["side"],
                              settled["entry_cents"], settled["seconds_to_close"])
    ]
    per_mkt = (
        settled.groupby(["cell", "mkey"], as_index=False)
        .agg(real_edge=("real_edge", "mean"),
             win=("win", "first"), ticker=("ticker", "first"))
    )
    real_by_cell = per_mkt.groupby("cell")["real_edge"].agg(["mean", "count"])
    real_by_cell["win_rate"] = per_mkt.groupby("cell")["win"].mean()
    real_by_cell["n_markets"] = per_mkt.groupby("cell")["ticker"].nunique()
    rows = []
    for ck, claim in cellmap.items():
        if ck not in real_by_cell.index:
            continue
        r = real_by_cell.loc[ck]
        w, l = claim.get("w", 0.0), claim.get("l", 0.0)
        claim_wr = w / (w + l) if (w + l) > 0 else None
        rows.append({
            "cell": ck,
            "artifact_w": w, "artifact_l": l,
            "artifact_win_rate_proxy": claim_wr,
            "artifact_n_eff": claim.get("n_eff"),
            "artifact_n_raw": claim.get("n_raw"),
            "artifact_n_markets": claim.get("n_markets"),
            "realized_mean_edge_c": float(r["mean"]),
            "realized_n_mkeys": int(r["count"]),
            "realized_n_markets": int(r["n_markets"]),
            "realized_win_rate": float(r["win_rate"]) if pd.notna(r["win_rate"]) else None,
        })
    # aggregate agreement: artifact win-rate proxy vs realized win rate,
    # restricted to cells with >=5 realized market-sides
    rdf = pd.DataFrame(rows)
    agree = {}
    if len(rdf):
        sub = rdf[(rdf["realized_n_mkeys"] >= 5) &
                  rdf["artifact_win_rate_proxy"].notna() &
                  rdf["realized_win_rate"].notna()]
        if len(sub) >= 5:
            from scipy.stats import spearmanr
            rho, p = spearmanr(sub["artifact_win_rate_proxy"],
                               sub["realized_win_rate"])
            agree = {
                "n_cells": int(len(sub)),
                "spearman_wr": float(rho), "p": float(p),
                "mean_abs_wr_gap": float(
                    (sub["artifact_win_rate_proxy"]
                     - sub["realized_win_rate"]).abs().mean()
                ),
            }
    return {"n_cells_compared": len(rows), "agreement": agree, "cells": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/decision_audit_evidence_outcomes.db")
    ap.add_argument("--attribution", default="data/trade_attribution_fact.db")
    ap.add_argument("--evidence", default="data/live_entry_evidence.json")
    ap.add_argument("--out", default="reports/edge_vs_memory_audit.json")
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=20261119)
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    print(f"[audit] loading evals from {args.db} ...", flush=True)
    raw = load_evals(args.db)
    print(f"[audit] {len(raw)} settled-source rows; unioning ...", flush=True)
    ev = union_evals(raw)
    ev = add_realized(ev)
    print(f"[audit] {len(ev)} unioned evals; running analyses ...", flush=True)

    report = {"config": vars(args), "evals": analyze_evals(ev, args.boot, rng)}

    print("[audit] attribution ...", flush=True)
    report["attribution"] = analyze_attribution(args.attribution)

    print("[audit] memory artifact ...", flush=True)
    report["memory"] = analyze_memory_artifact(args.evidence, ev)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"[audit] wrote {out}")

    # console digest
    e = report["evals"]
    print("\n=== REALIZED EDGE (net of taker fee, cents/contract) ===")
    for k in ["overall_all_evals", "overall_latest_per_mkey", "overall_first_tte600"]:
        v = e.get(k, {})
        print(f"{k:32s} mean={v.get('mean', float('nan')):+.2f} "
              f"CI[{v.get('ci_lo', float('nan')):+.2f},{v.get('ci_hi', float('nan')):+.2f}] "
              f"n={v.get('n',0)} mkts={v.get('n_markets',0)}")
    if "cells_summary" in e:
        print("cells:", e["cells_summary"])
    if "overclaim_gap" in e:
        print("overclaim:", e["overclaim_gap"])
    a = report.get("attribution", {})
    print(f"\n=== REAL MONEY === total={a.get('total_pnl_cents',0):+.0f}c "
          f"n={a.get('n_settlements',0)} mean={a.get('mean_pnl_cents',0):+.2f}c")
    return 0


if __name__ == "__main__":
    sys.exit(main())
