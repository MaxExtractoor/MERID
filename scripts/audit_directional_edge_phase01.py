"""Directional-edge Phase 0+1 audit — market-relative probability skill.

Phase 0 (freeze): reproduces the >=+2c claim cohort exactly as
reports/EDGE_AUDIT_2026-11-19.md / scripts/audit_edge_v2.py defined it:
  panel   = logs/model_calibration_observations.jsonl
            joined to logs/settlement_outcomes.jsonl (resolved_yes)
  claim   = gross_edge_c - fee_cents   [fee_cents logged, else parabolic]
  snapshot= first obs per (ticker|side, tte_bucket)   [causal]
  buckets = tte_bucket/price_bucket from audit_edge_vs_memory.py

Phase 1: forecast-quality comparison, model vs market, on identical rows.
  p_model      = P(selected side wins)          [verified vs gross_edge_c]
  y            = 1 if selected side settled winner
  market prob  = paired YES/NO mid at same ts    [primary baseline]
               = (yes_entry + (100 - no_entry)) / 2  for YES;
                 complement for NO.  Rows without a same-ts pair are
                 excluded from the mid-baseline comparison (counted).
  Metrics      = Brier, log-loss (clip 1e-6), ECE (10 equal-width bins),
                 per asset x tte_bucket, eval-weighted AND market-balanced
                 (per-market-side mean, then unweighted across mkeys).
  Uncertainty  = cluster bootstrap over settlement windows
                 (wkey = ticker.split('-')[1], shared across the 5 assets).

    .venv/Scripts/python.exe scripts/audit_directional_edge_phase01.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_edge_vs_memory import tte_bucket, price_bucket  # noqa: E402

CAL = "logs/model_calibration_observations.jsonl"
OUTCOMES = "logs/settlement_outcomes.jsonl"
OUT = "reports/directional_edge_phase01.json"
N_BOOT = 1000
SEED = 20261123
EPS = 1e-6


def parabolic_fee_cents(price_cents: float) -> float:
    p = max(0.0, min(1.0, float(price_cents) / 100.0))
    return 0.07 * p * (1.0 - p) * 100.0


def load_panel() -> pd.DataFrame:
    rows = []
    with open(CAL, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    cal = pd.DataFrame(rows)
    outs = {}
    with open(OUTCOMES, encoding="utf-8") as f:
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
    df["side"] = df["side"].astype(str).str.lower()
    df["y"] = np.where(df["side"] == "yes", df["resolved_yes"] == 1,
                       df["resolved_yes"] == 0).astype(float)
    df["entry"] = pd.to_numeric(df["entry_price_cents"], errors="coerce")
    logged_fee = pd.to_numeric(df["fee_cents"], errors="coerce")
    df["fee"] = logged_fee.fillna(df["entry"].map(parabolic_fee_cents))
    df["payout"] = np.where(df["y"] == 1, 100.0, 0.0)
    df["real_edge"] = df["payout"] - df["entry"] - df["fee"]
    df["claim_gap"] = pd.to_numeric(df["gross_edge_c"], errors="coerce") - df["fee"]
    df["p_side"] = pd.to_numeric(df["p_model"], errors="coerce")
    df["mkey"] = df["ticker"].astype(str) + "|" + df["side"]
    df["wkey"] = df["ticker"].map(lambda t: str(t).split("-")[1])
    df["tte_bucket"] = df["seconds_to_expiry"].map(tte_bucket)
    df["price_bucket"] = df["entry"].map(price_bucket)
    return df


def causal_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    return (df.sort_values("ts")
              .groupby(["mkey", "tte_bucket"], as_index=False).head(1))


def attach_market_mid(df: pd.DataFrame) -> pd.DataFrame:
    """Pair YES/NO evals at identical ts per ticker -> market mid for the side.

    entry_price is treated as the side's executable ask:
      yes_ask = yes_entry ; no_ask = no_entry = 100 - yes_bid
      => yes_mid = (yes_entry + (100 - no_entry)) / 2
    p_mkt_side = yes_mid/100 for yes, (100 - yes_mid)/100 for no.
    """
    df = df.copy()
    df["ts_key"] = df["ts"].round(3)
    piv = (df.pivot_table(index=["ticker", "ts_key"], columns="side",
                          values="entry", aggfunc="first")
             .rename(columns={"yes": "yes_entry", "no": "no_entry"}))
    piv = piv.dropna(subset=["yes_entry", "no_entry"])
    piv["yes_mid"] = (piv["yes_entry"] + (100.0 - piv["no_entry"])) / 2.0
    piv["spread_c"] = piv["yes_entry"] + piv["no_entry"] - 100.0
    df = df.merge(piv[["yes_mid", "spread_c"]].reset_index(),
                  on=["ticker", "ts_key"], how="left")
    df["p_mkt"] = np.where(
        df["side"] == "yes",
        df["yes_mid"] / 100.0,
        (100.0 - df["yes_mid"]) / 100.0,
    )
    return df


def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def logloss(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(p, EPS, 1.0 - EPS)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def ece(p: np.ndarray, y: np.ndarray, n_bins: int = 10) -> float:
    edges = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, n_bins - 1)
    tot = 0.0
    for b in range(n_bins):
        m = idx == b
        if m.any():
            tot += m.mean() * abs(p[m].mean() - y[m].mean())
    return float(tot)


def paired_diff_boot(model_p: np.ndarray, mkt_p: np.ndarray, y: np.ndarray,
                     wkeys: np.ndarray, n_boot: int, rng) -> dict:
    """Bootstrap CI on (brier_model - brier_mkt) resampling windows."""
    codes, uniq = pd.factorize(pd.Series(wkeys))
    n_cl = len(uniq)
    diffs = np.empty(n_boot)
    ok = np.zeros(n_boot, dtype=bool)
    loss_m = (model_p - y) ** 2
    loss_k = (mkt_p - y) ** 2
    base = loss_m - loss_k
    for b in range(n_boot):
        cnt = np.bincount(rng.integers(0, n_cl, size=n_cl), minlength=n_cl)
        w = cnt[codes]
        if w.sum() >= 30:
            diffs[b] = np.average(base, weights=w)
            ok[b] = True
    diffs = diffs[ok]
    if len(diffs) == 0:
        return {"mean_diff": None, "ci": None}
    return {
        "mean_diff": float(np.mean(base)),
        "ci": [float(np.percentile(diffs, 2.5)),
               float(np.percentile(diffs, 97.5))],
        "p_le_0": float(np.mean(diffs <= 0)),
        "n_boot": int(len(diffs)),
    }


def score_block(name: str, d: pd.DataFrame, rng, n_boot: int) -> dict:
    """Score model vs market on rows that have a paired mid."""
    sub = d.dropna(subset=["p_mkt", "p_side"]).copy()
    sub = sub[(sub["p_mkt"] > 0) & (sub["p_mkt"] < 1)]
    sub = sub[(sub["p_side"] > 0) & (sub["p_side"] < 1)]
    rep = {"n_rows": int(len(sub)),
           "n_markets": int(sub["ticker"].nunique()),
           "n_market_sides": int(sub["mkey"].nunique())}
    if len(sub) < 50:
        rep["note"] = "insufficient paired rows"
        return rep
    pm, pk, y = (sub["p_side"].to_numpy(), sub["p_mkt"].to_numpy(),
                 sub["y"].to_numpy())
    rep["model"] = {"brier": brier(pm, y), "logloss": logloss(pm, y),
                    "ece": ece(pm, y)}
    rep["market_mid"] = {"brier": brier(pk, y), "logloss": logloss(pk, y),
                         "ece": ece(pk, y)}
    # eval-weighted paired diff
    rep["paired_diff_eval_weighted"] = paired_diff_boot(
        pm, pk, y, sub["wkey"].to_numpy(), n_boot, rng)
    # market-balanced: mean per mkey, then unweighted across mkeys
    per = sub.assign(
        lm=(sub["p_side"] - sub["y"]) ** 2,
        lk=(sub["p_mkt"] - sub["y"]) ** 2,
        llm=-(sub["y"] * np.log(np.clip(sub["p_side"], EPS, 1 - EPS)) +
              (1 - sub["y"]) * np.log(np.clip(1 - sub["p_side"], EPS, 1 - EPS))),
        llk=-(sub["y"] * np.log(np.clip(sub["p_mkt"], EPS, 1 - EPS)) +
              (1 - sub["y"]) * np.log(np.clip(1 - sub["p_mkt"], EPS, 1 - EPS))),
    ).groupby("mkey")[["lm", "lk", "llm", "llk"]].mean()
    rep["market_balanced"] = {
        "model_brier": float(per["lm"].mean()),
        "mkt_brier": float(per["lk"].mean()),
        "model_logloss": float(per["llm"].mean()),
        "mkt_logloss": float(per["llk"].mean()),
        "brier_diff": float((per["lm"] - per["lk"]).mean()),
    }
    return rep


def realized_edge_stats(d: pd.DataFrame, rng, n_boot: int) -> dict:
    """Window-clustered bootstrap on realized edge (cents/contract)."""
    sub = d.dropna(subset=["real_edge"])
    if len(sub) < 30:
        return {"n": int(len(sub))}
    codes, uniq = pd.factorize(sub["wkey"])
    n_cl = len(uniq)
    vals = sub["real_edge"].to_numpy()
    boots = np.empty(n_boot)
    ok = np.zeros(n_boot, dtype=bool)
    for b in range(n_boot):
        cnt = np.bincount(rng.integers(0, n_cl, size=n_cl), minlength=n_cl)
        w = cnt[codes]
        if w.sum() >= 30:
            boots[b] = np.average(vals, weights=w)
            ok[b] = True
    boots = boots[ok]
    return {
        "n": int(len(sub)), "n_markets": int(sub["ticker"].nunique()),
        "n_market_sides": int(sub["mkey"].nunique()),
        "mean_c": float(vals.mean()),
        "ci": [float(np.percentile(boots, 2.5)),
               float(np.percentile(boots, 97.5))] if len(boots) else None,
        "p_le_0": float(np.mean(boots <= 0)) if len(boots) else None,
    }


def main() -> int:
    rng = np.random.default_rng(SEED)
    print("[p01] loading panel ...", flush=True)
    df = prep(load_panel())
    df = attach_market_mid(df)
    snap = causal_snapshot(df)
    print(f"[p01] evals={len(df)} markets={df['ticker'].nunique()} "
          f"snapshot={len(snap)} paired_mid={df['p_mkt'].notna().sum()}",
          flush=True)

    rep = {"population": {
        "n_evals": int(len(df)),
        "n_markets": int(df["ticker"].nunique()),
        "n_market_sides": int(df["mkey"].nunique()),
        "ts_span": [float(df["ts"].min()), float(df["ts"].max())],
        "paired_mid_rows": int(df["p_mkt"].notna().sum()),
        "median_spread_c": float(df["spread_c"].median())
        if df["spread_c"].notna().any() else None,
    }}

    # ---- Phase 0: reproduce claim cohorts -------------------------------
    print("[p01] phase0 claim cohorts ...", flush=True)
    phase0 = {}
    for thr in [1.0, 2.0, 3.0, 5.0]:
        cohort = snap[snap["claim_gap"] >= thr]
        phase0[f"claim_ge_{thr:g}c"] = {
            "n_evals": int(len(cohort)),
            "n_markets": int(cohort["ticker"].nunique()),
            "claim_mean": float(cohort["claim_gap"].mean()),
            "realized": realized_edge_stats(cohort, rng, N_BOOT),
        }
        print(f"  claim>={thr}: n={len(cohort)} "
              f"real={phase0[f'claim_ge_{thr:g}c']['realized'].get('mean_c')}",
              flush=True)
    rep["phase0_claim_cohorts"] = phase0

    # ---- Phase 1: forecast skill -----------------------------------------
    print("[p01] phase1 scoring ...", flush=True)
    phase1 = {}
    for name, d in [("all_evals", df), ("causal_snapshot", snap),
                    ("claim_ge_2c_snapshot", snap[snap["claim_gap"] >= 2.0])]:
        phase1[name] = score_block(name, d, rng, N_BOOT)
        m = phase1[name].get("model", {})
        k = phase1[name].get("market_mid", {})
        print(f"  {name}: n={phase1[name]['n_rows']} "
              f"brier m={m.get('brier'):.4f} k={k.get('brier'):.4f} "
              f"ece m={m.get('ece'):.4f} k={k.get('ece'):.4f}", flush=True)
    # per-asset x tte on causal snapshot
    breakdown = {}
    for asset, ga in snap.groupby("asset"):
        breakdown[asset] = score_block(f"asset_{asset}", ga, rng, 400)
    for tb, gt in snap.groupby("tte_bucket"):
        breakdown[f"tte_{tb}"] = score_block(f"tte_{tb}", gt, rng, 400)
    rep["phase1_breakdowns"] = breakdown
    rep["phase1_all_evals"] = phase1["all_evals"]
    rep["phase1_causal_snapshot"] = phase1["causal_snapshot"]
    rep["phase1_claim_ge_2c"] = phase1["claim_ge_2c_snapshot"]

    out = Path(OUT)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2, default=str)
    print(f"[p01] wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
