"""FLB decomposition audit on the decision spine (data/decision_spine.pkl).

Splits every side-evaluation's claimed edge into its economic components,
in held-side cents:

    claim ~= model_value - entry - costs
    model_value = calibrated_probability * 100        (P(held side wins))
    entry       = executable_entry_price_cents        (top-of-book exec px)

Market mid is reconstructed per decision from the TWO side rows' entry
prices (basis-invariant):

    mid_yes = (yes_entry + 100 - no_entry) / 2
    s = yes_entry + no_entry - 100   # >0 taker/ask basis, <0 maker/bid basis
                                   # |s| = YES spread in cents

Components reported per cohort:
    model_vs_mid = p_held*100 - mid_held     (model's disagreement w/ mid)
    mid_vs_entry = mid_held - entry          (<0 taker pays spread, >0 maker)
    costs        = claim - (model_value - entry)  (fees + reserves + haircuts)
    real_edge    = payout - entry - modeled fees          (eval-price edge)
    fill_edge    = payout - actual_fill - actual fee      (filled subset)

    python scripts/analyze_flb_decomposition.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_decision_spine import cboot, expiry_utc  # noqa: E402

PKL = "data/decision_spine.pkl"
OUT_JSON = "reports/flb_decomposition.json"

BANDS = [(-1, 9, "01-09"), (9, 24, "10-24"), (24, 49, "25-49"),
         (49, 74, "50-74"), (74, 89, "75-89"), (89, 93, "90-93"),
         (93, 96, "94-96"), (96, 98, "97-98"), (98, 101, "99-100")]


def band_of(px: pd.Series) -> pd.Series:
    out = pd.Series("out", index=px.index, dtype=object)
    for lo, hi, name in BANDS:
        out[(px > lo) & (px <= hi)] = name
    return out


def agg(g: pd.DataFrame, col: str, boot: int = 200) -> dict:
    r = cboot(g, col, boot)
    r["n"] = int(len(g))
    r["mk"] = int(g["ticker"].nunique()) if len(g) else 0
    return r


def cohort_row(g: pd.DataFrame) -> dict:
    """One summary row: counts + means of every decomposition component."""
    if len(g) == 0:
        return {"n": 0}
    row = {
        "n": int(len(g)),
        "mk": int(g["ticker"].nunique()),
        "px": float(g["exec_px"].mean()),
        "p_held": float(g["p_held"].mean()),
        "winrate": float(g["win"].mean()),
        "mid_held": float(g["mid_held"].mean()),
        "claim": float(g["claim"].mean()),
        "model_vs_mid": float(g["model_vs_mid"].mean()),
        "mid_vs_entry": float(g["mid_vs_entry"].mean()),
        "costs": float(g["costs"].mean()),
        "real_edge": agg(g, "real_edge", 200),
    }
    # FLB ratio: model p vs realized winrate (held side)
    row["flb_ratio"] = (row["p_held"] / row["winrate"]
                        if row["winrate"] > 0 else np.nan)
    return row


def main() -> int:
    df = pd.read_pickle(PKL)
    df = df[df["settled_yes"].notna()].copy()
    side = df["side"].astype(str).str.lower()
    df["held_yes"] = side == "yes"
    df["win"] = np.where(df["held_yes"], df["settled_yes"] == 1,
                         df["settled_yes"] == 0).astype(float)
    df["payout"] = np.where(df["win"] == 1, 100.0, 0.0)
    df["exec_px"] = pd.to_numeric(df["executable_entry_price_cents"],
                                  errors="coerce")
    df["claim"] = pd.to_numeric(df["expected_net_ev_cents"],
                                errors="coerce")
    df["cal_p"] = pd.to_numeric(df["calibrated_probability"],
                                errors="coerce")
    df["entry_fee"] = pd.to_numeric(df["entry_fee_cents"],
                                    errors="coerce").fillna(0)
    df["exit_fee"] = pd.to_numeric(df["exit_or_settlement_fee_cents"],
                                   errors="coerce").fillna(0)
    df["fees"] = df["entry_fee"] + df["exit_fee"]
    df["real_edge"] = df["payout"] - df["exec_px"] - df["fees"]

    # --- semantics check: is calibrated_probability held-side? ---
    sem = {}
    for s in ["yes", "no"]:
        g = df[side == s]
        sem[s] = {
            "n": int(len(g)),
            "corr_calp_win": float(g[["cal_p", "win"]].corr().iloc[0, 1]),
            "mean_calp": float(g["cal_p"].mean()),
            "mean_win": float(g["win"].mean()),
        }
    # held-side if both sides correlate positively with win
    held_side = (sem["yes"]["corr_calp_win"] > 0.3
                 and sem["no"]["corr_calp_win"] > 0.3)

    # --- mid reconstruction from paired side rows ---
    px_ok = df[(df["exec_px"] >= 1) & (df["exec_px"] <= 99)].copy()
    piv = px_ok.pivot_table(index="decision_id", columns="side",
                            values="exec_px", aggfunc="first")
    if {"yes", "no"}.issubset(piv.columns):
        both = piv.dropna(subset=["yes", "no"])
        mid_yes = (both["yes"] + 100.0 - both["no"]) / 2.0
        spread = both["yes"] + both["no"] - 100.0   # signed, = YES spread
        mid = pd.DataFrame(index=both.index)
        mid["mid_yes"] = mid_yes
        mid["yes_spread_c"] = spread.abs()
        mid["basis"] = np.where(spread > 0.5, "ask",
                                np.where(spread < -0.5, "bid", "flat"))
    else:
        mid = pd.DataFrame(columns=["mid_yes", "yes_spread_c", "basis"])
    df = df.join(mid, on="decision_id")
    df["mid_yes"] = pd.to_numeric(df["mid_yes"], errors="coerce")
    df["mid_held"] = np.where(df["held_yes"], df["mid_yes"],
                              100.0 - df["mid_yes"])

    # p_held: calibrated_probability is P(held side) if semantics check
    # passes; otherwise convert assuming it is P(yes).
    if held_side:
        df["p_held"] = df["cal_p"]
        df["p_semantics"] = "held_side"
    else:
        df["p_held"] = np.where(df["held_yes"], df["cal_p"],
                                1.0 - df["cal_p"])
        df["p_semantics"] = "converted_from_p_yes"

    df["model_value"] = df["p_held"] * 100.0
    df["model_vs_mid"] = df["model_value"] - df["mid_held"]
    df["mid_vs_entry"] = df["mid_held"] - df["exec_px"]
    df["costs"] = df["claim"] - (df["model_value"] - df["exec_px"])
    df["tte"] = df["ticker"].map(expiry_utc) - pd.to_numeric(
        df["decision_ts"], errors="coerce")
    df.loc[df["tte"] < 0, "tte"] = np.nan
    df["tte_b"] = pd.cut(df["tte"], [0, 120, 300, 600, 900],
                         labels=["final", "late", "mid", "early"])
    df["band"] = band_of(df["exec_px"])
    df["depth"] = pd.to_numeric(df["top_of_book_executable_contracts"],
                                errors="coerce")
    df["day"] = pd.to_datetime(df["decision_ts"], unit="s").dt.date

    rep = {
        "n_rows": int(len(df)),
        "n_markets": int(df["ticker"].nunique()),
        "p_semantics": df["p_semantics"].iloc[0],
        "semantics_check": sem,
        "mid_coverage": {
            "rows_with_mid": int(df["mid_yes"].notna().sum()),
            "frac": float(df["mid_yes"].notna().mean()),
            "basis_counts": df["basis"].value_counts().to_dict()
            if "basis" in df else {},
        },
        "note": "all cents, held-side; mid reconstructed from paired "
                "side entry prices; costs = claim - (model_value - entry)",
    }

    # --- 1. overall decomposition (rows with mid) ---
    dm = df[df["mid_yes"].notna()].copy()
    rep["overall_with_mid"] = cohort_row(dm)
    rep["overall_no_mid"] = cohort_row(df[df["mid_yes"].isna()])

    # --- 2. pinned_fav lane by price band (the FLB table) ---
    pf = df[df["decision_lane"] == "pinned_fav"].copy()
    pf_dm = pf[pf["mid_yes"].notna()]
    rep["pinned_fav_by_band"] = {}
    for b in ["01-09", "10-24", "25-49", "50-74", "75-89",
              "90-93", "94-96", "97-98", "99-100"]:
        g = pf_dm[pf_dm["band"] == b]
        if len(g) >= 5:
            rep["pinned_fav_by_band"][b] = cohort_row(g)
    # cheap + favorite pooled
    for name, m in [("cheap_le9", pf_dm["exec_px"] <= 9),
                    ("fav_ge90", pf_dm["exec_px"] >= 90)]:
        g = pf_dm[m]
        if len(g) >= 5:
            rep[f"pinned_fav_{name}"] = cohort_row(g)

    # --- 3. stability splits on pinned_fav favorite+cheap ---
    fav = pf_dm[pf_dm["exec_px"] >= 90].copy()
    cheap = pf_dm[pf_dm["exec_px"] <= 9].copy()
    for tag, sub in [("fav", fav), ("cheap", cheap)]:
        splits = {}
        for col in ["held_yes", "counterfactual_execution_status",
                    "basis"]:
            splits[col] = {}
            for k, g in sub.groupby(col, dropna=False):
                if len(g) >= 10:
                    splits[col][str(k)] = cohort_row(g)
        # depth buckets
        splits["depth"] = {}
        for lo, hi in [(0, 1), (1, 10), (10, 100), (100, 1e9)]:
            g = sub[(sub["depth"] >= lo) & (sub["depth"] < hi)]
            if len(g) >= 10:
                splits["depth"][f"{lo}-{hi}"] = cohort_row(g)
        # TTE
        splits["tte"] = {}
        for k, g in sub.groupby("tte_b", observed=True):
            if len(g) >= 10:
                splits["tte"][str(k)] = cohort_row(g)
        rep[f"pinned_fav_{tag}_splits"] = splits

    # --- 4. favorite-lane tradeable residue ---
    # eval-edge vs ACTUAL-fill edge for pinned_fav favorites
    fav_fill = fav[fav["actual_fill_price_cents"].notna()].copy()
    rep["pinned_fav_fav_fills"] = {"n": int(len(fav_fill))}
    if len(fav_fill):
        af = pd.to_numeric(fav_fill["actual_fill_price_cents"],
                           errors="coerce")
        # realized_net_pnl_cents is the authoritative ledger net P&L
        rnp = pd.to_numeric(fav_fill["realized_net_pnl_cents"],
                            errors="coerce")
        rep["pinned_fav_fav_fills"].update({
            "slip_vs_exec_mean": float((af - fav_fill["exec_px"]).mean()),
            "realized_net_pnl_sum": float(rnp.sum()),
            "realized_net_pnl_mean": float(rnp.mean()),
            "n_pnl": int(rnp.notna().sum()),
            "winrate": float(fav_fill["win"].mean()),
            "px_mean": float(af.mean()),
            "eval_edge_mean": float(fav_fill["real_edge"].mean()),
        })
        # per-band fill edge
        rep["pinned_fav_fav_fills"]["by_band"] = {}
        for b in ["90-93", "94-96", "97-98"]:
            g = fav_fill[fav_fill["band"] == b]
            if len(g) >= 3:
                rep["pinned_fav_fav_fills"]["by_band"][b] = {
                    "n": int(len(g)),
                    "eval_edge": float(g["real_edge"].mean()),
                    "realized_pnl_mean": float(
                        pd.to_numeric(g["realized_net_pnl_cents"],
                                      errors="coerce").mean()),
                    "winrate": float(g["win"].mean()),
                }

    # --- 5. all-lane claim>=2 executable cohort (context) ---
    hi = df[(df["claim"] >= 2.0) & df["mid_yes"].notna()].copy()
    rep["claim_ge2_with_mid"] = {"n": int(len(hi))}
    if len(hi):
        rep["claim_ge2_with_mid"]["overall"] = cohort_row(hi)
        rep["claim_ge2_with_mid"]["by_exec_status"] = {}
        for k, g in hi.groupby("counterfactual_execution_status",
                               dropna=False):
            if len(g) >= 10:
                rep["claim_ge2_with_mid"]["by_exec_status"][str(k)] = \
                    cohort_row(g)
        rep["claim_ge2_with_mid"]["by_lane"] = {}
        for k, g in hi.groupby("decision_lane", dropna=False):
            if len(g) >= 10:
                rep["claim_ge2_with_mid"]["by_lane"][str(k)] = \
                    cohort_row(g)

    Path(OUT_JSON).parent.mkdir(exist_ok=True)
    Path(OUT_JSON).write_text(json.dumps(rep, indent=2, default=str))
    print(json.dumps({k: rep[k] for k in
                      ["n_rows", "p_semantics", "semantics_check",
                       "mid_coverage", "overall_with_mid",
                       "pinned_fav_cheap_le9", "pinned_fav_fav_ge90"]},
                     indent=2, default=str))
    print("\npinned_fav_by_band:")
    for b, r in rep["pinned_fav_by_band"].items():
        print(f"  {b}: n={r['n']} px={r['px']:.1f} p={r['p_held']:.3f} "
              f"wr={r['winrate']:.3f} mvm={r['model_vs_mid']:+.2f} "
              f"mve={r['mid_vs_entry']:+.2f} edge={r['real_edge']['mean']:+.2f} "
              f"CI[{r['real_edge']['ci_lo']:+.2f},{r['real_edge']['ci_hi']:+.2f}]")
    print(f"\nwrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
