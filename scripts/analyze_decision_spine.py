"""Executable-edge audit on the decision spine (data/decision_spine.pkl).

For every side_evaluation row: reconstruct realized hold-to-settlement
edge at the system's own executable_entry_price_cents (book-derived at
decision time), net of modeled fees, joined to settled_yes from
strategy_decision_outcomes. Then measure the claim->realized
calibration on expected_net_ev_cents cohorts, broken by lane, depth,
execution-status counterfactuals, and actual fills.

    python scripts/analyze_decision_spine.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_edge_vs_memory import bh_fdr  # noqa: E402

PKL = "data/decision_spine.pkl"
OUT_JSON = "reports/decision_spine_edge_audit.json"

MONTHS = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
     "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def expiry_utc(ticker: str) -> float | None:
    """KXBTC15M-26NOV191300-00 -> epoch UTC. Ticker time is US Eastern;
    Nov = EST = UTC-5."""
    try:
        core = str(ticker).split("-")[1]          # 26NOV191300
        yy = 2000 + int(core[:2])
        mo = MONTHS[core[2:5]]
        dd = int(core[5:7])
        hh = int(core[7:9]); mm = int(core[9:11])
        # ET -> UTC: November is EST (UTC-5); July-Oct EDT handled by
        # approximate +5 (audit tolerance +-1h is fine for TTE buckets)
        import datetime as _dt
        et = _dt.datetime(yy, mo, dd, hh, mm, tzinfo=_dt.timezone(
            _dt.timedelta(hours=-5)))
        return et.timestamp()
    except Exception:
        return None


def cboot(d: pd.DataFrame, col: str, n: int = 400,
          seed: int = 17) -> dict:
    d = d.dropna(subset=[col])
    if len(d) < 10:
        return {"mean": float(d[col].mean()) if len(d) else np.nan,
                "ci_lo": np.nan, "ci_hi": np.nan, "n": int(len(d)),
                "mk": int(d["ticker"].nunique()) if len(d) else 0}
    g = d.groupby("ticker")[col].agg(["sum", "count"])
    s = g["sum"].to_numpy(); cn = g["count"].to_numpy(); nc = len(g)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, nc, (n, nc))
    bm = s[idx].sum(1) / np.maximum(cn[idx].sum(1), 1)
    return {"mean": float(d[col].mean()),
            "ci_lo": float(np.percentile(bm, 2.5)),
            "ci_hi": float(np.percentile(bm, 97.5)),
            "p_le_0": float(np.mean(bm <= 0)),
            "n": int(len(d)), "mk": nc}


def main() -> int:
    df = pd.read_pickle(PKL)
    print(f"spine rows: {len(df)}, tickers: {df['ticker'].nunique()}")

    # --- realized edge at executable price ---
    df = df[df["settled_yes"].notna()].copy()
    side = df["side"].astype(str).str.lower()
    df["held_yes"] = side == "yes"
    df["win"] = np.where(df["held_yes"], df["settled_yes"] == 1,
                         df["settled_yes"] == 0)
    df["payout"] = np.where(df["win"], 100.0, 0.0)
    px = pd.to_numeric(df["executable_entry_price_cents"], errors="coerce")
    fee_in = pd.to_numeric(df["entry_fee_cents"], errors="coerce")
    fee_out = pd.to_numeric(df["exit_or_settlement_fee_cents"],
                            errors="coerce")
    df["exec_px"] = px
    df["fees"] = (fee_in.fillna(0) + fee_out.fillna(0))
    df["real_edge"] = df["payout"] - df["exec_px"] - df["fees"]
    df["claim"] = pd.to_numeric(df["expected_net_ev_cents"], errors="coerce")
    df["tte"] = df["ticker"].map(expiry_utc) - pd.to_numeric(
        df["decision_ts"], errors="coerce")
    df.loc[df["tte"] < 0, "tte"] = np.nan

    rep = {"n_rows": int(len(df)),
           "n_markets": int(df["ticker"].nunique()),
           "ts_span": [float(df["decision_ts"].min()),
                       float(df["decision_ts"].max())],
           "note": "real_edge = payout - executable_entry_price - "
                   "model fees; claim = expected_net_ev_cents"}

    # --- overall + claim cohorts ---
    rep["overall"] = cboot(df, "real_edge")
    cohorts = {}
    for thr in [-1e9, -3, 0, 1, 2, 3, 5]:
        hi = df[df["claim"] >= thr]
        cohorts[f"claim_ge_{thr if thr > -1e8 else 'all'}"] = {
            **cboot(hi, "real_edge"),
            "claim_mean": float(hi["claim"].mean()) if len(hi) else None,
        }
    rep["claim_cohorts"] = cohorts

    # claim deciles
    d2 = df.dropna(subset=["claim"]).copy()
    d2["dec"] = pd.qcut(d2["claim"], 10, duplicates="drop")
    dec_rows = []
    for dec, g in d2.groupby("dec", observed=True):
        st = cboot(g, "real_edge", 200)
        dec_rows.append({"decile": str(dec), "claim_mean":
                         float(g["claim"].mean()), **st})
    rep["claim_deciles"] = dec_rows

    # --- by execution status / depth for claim>=2 ---
    hi = df[df["claim"] >= 2.0].copy()
    rep["claim_ge2"] = {"n": int(len(hi)),
                        "mk": int(hi["ticker"].nunique())}
    for col in ["counterfactual_execution_status",
                "counterfactual_entry_source", "decision_lane",
                "admission_owner"]:
        rep[f"ge2_by_{col}"] = {}
        for k, g in hi.groupby(col, dropna=False):
            if len(g) < 5:
                continue
            rep[f"ge2_by_{col}"][str(k)] = {
                **cboot(g, "real_edge", 200),
                "depth_med": float(pd.to_numeric(
                    g["top_of_book_executable_contracts"],
                    errors="coerce").median()),
            }
    # depth buckets on claim>=2
    hi["depth"] = pd.to_numeric(hi["top_of_book_executable_contracts"],
                                errors="coerce")
    for lo, hib in [(0, 1), (1, 10), (10, 100), (100, 1e9)]:
        g = hi[(hi["depth"] >= lo) & (hi["depth"] < hib)]
        if len(g) >= 10:
            rep.setdefault("ge2_by_depth", {})[f"{lo}-{hib}"] = cboot(
                g, "real_edge", 200)
    # TTE buckets
    hi["tte_b"] = pd.cut(hi["tte"], [0, 120, 300, 600, 900],
                         labels=["final", "late", "mid", "early"])
    rep["ge2_by_tte"] = {}
    for k, g in hi.groupby("tte_b", observed=True):
        if len(g) >= 5:
            rep["ge2_by_tte"][str(k)] = cboot(g, "real_edge", 200)

    # --- fills: actual vs executable price ---
    fills = df[df["actual_fill_price_cents"].notna()].copy()
    rep["fills"] = {"n": int(len(fills))}
    if len(fills):
        af = pd.to_numeric(fills["actual_fill_price_cents"],
                           errors="coerce")
        rep["fills"]["slip_vs_exec_mean"] = float(
            (af - fills["exec_px"]).mean())
        rep["fills"]["slip_vs_exec_p50"] = float(
            (af - fills["exec_px"]).median())
        rep["fills"]["realized_pnl_sum_cents"] = float(
            pd.to_numeric(fills["realized_net_pnl_cents"],
                          errors="coerce").sum())
        rep["fills"]["capital_pnl_sum_cents"] = float(
            pd.to_numeric(fills["capital_realized_pnl_cents"],
                          errors="coerce").sum())
        # edge at ACTUAL fill price
        fside = fills["side"].astype(str).str.lower()
        fwin = np.where(fside == "yes", fills["settled_yes"] == 1,
                        fills["settled_yes"] == 0)
        fedge = np.where(fwin, 100.0, 0.0) - af - fills["fees"]
        rep["fills"]["edge_at_actual_fill"] = {
            "mean": float(np.nanmean(fedge)),
            "p50": float(np.nanmedian(fedge)),
            "n": int(np.isfinite(fedge).sum()),
        }
        # high-claim fills
        fh = fills[fills["claim"] >= 2.0].copy()
        if len(fh):
            fh_side = fh["side"].astype(str).str.lower()
            fh_win = np.where(fh_side == "yes", fh["settled_yes"] == 1,
                              fh["settled_yes"] == 0)
            fh_edge = (np.where(fh_win, 100.0, 0.0)
                       - pd.to_numeric(fh["actual_fill_price_cents"],
                                       errors="coerce") - fh["fees"])
            rep["fills"]["claim_ge2"] = {
                "n": int(len(fh)),
                **cboot(fh.assign(_e=fh_edge), "_e", 200),
            }

    # --- dedup check: rows per decision ---
    rep["rows_per_decision"] = float(
        len(df) / max(df["decision_id"].nunique(), 1))

    Path(OUT_JSON).parent.mkdir(exist_ok=True)
    Path(OUT_JSON).write_text(json.dumps(rep, indent=2, default=str))
    print(json.dumps(rep, indent=2, default=str)[:6000])
    print(f"wrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
