"""Claim-tail split audit — route x basis x lane x fill-through.

The pooled claim>=+2c counterfactual (+0.57c, CI incl. 0 on the
~40h/309-mkt evidence-outcomes extract) may be a pooling artifact:
maker fills already run -5..-9.5c worse than eval prices while the
taker-fillable subset may carry the edge.  This script splits the
claim>=+2c cohort on data/decision_spine.pkl by:

  - evaluation route   : decision_id suffix (cand_<id>:<route>)
  - price basis        : counterfactual_entry_source (*_ask = taker-
                         crossing eval price, *_bid_complement = maker-
                         style bid-priced eval)
  - lane provenance    : decision_lane / admission_owner / evidence_state
  - execution status   : counterfactual_execution_status
  - fill-through       : counterfactual_fill_ratio / full_fill_possible /
                         top-of-book depth / actual fills

and splits the decision-time stress reserves the same way
(adverse_selection_haircut, slippage, edge_bias, fees).  True 5s
markout is NOT in the spine — it needs book-archive replay
(scripts/audit_book_replay.py) joined on decision_id; the reserves
below are what the decision actually charged, which is the quantity
the gates consumed.

    python scripts/audit_claim_tail_splits.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_edge_vs_memory import bh_fdr  # noqa: E402
from analyze_decision_spine import cboot, expiry_utc  # noqa: E402

PKL = "data/decision_spine.pkl"
OUT_JSON = "reports/claim_tail_splits.json"
CLAIM_THR = 2.0

STRESS_COLS = [
    "adverse_selection_haircut_cents",
    "model_uncertainty_haircut_cents",
    "edge_bias_correction_c",
    "expected_entry_slippage_cents",
    "entry_fee_cents",
    "exit_or_settlement_fee_cents",
    "gross_edge_cents",
    "required_edge_cents",
    "lower_confidence_bound_ev_cents",
]


def route_of(decision_id) -> str:
    """Evaluation-route suffix of a cand_ decision id (see
    decision_audit_ledger._route_from_decision_id)."""
    s = str(decision_id or "")
    if s.startswith("cand_") and ":" in s:
        return s.rsplit(":", 1)[1] or "empty_suffix"
    return "no_route_suffix"


def basis_of(entry_source) -> str:
    s = str(entry_source or "")
    if "ask" in s:
        return "ask_taker_basis"
    if "bid" in s:
        return "bid_complement_basis"
    return "unknown"


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def split_table(hi: pd.DataFrame, dim: str, min_n: int = 5,
                value_col: str = "real_edge") -> dict:
    out = {}
    for k, g in hi.groupby(dim, dropna=False):
        if len(g) < min_n:
            continue
        out[str(k)] = {
            **cboot(g, value_col, 200),
            "claim_mean": float(g["claim"].mean()),
            "exec_px_med": float(g["exec_px"].median()),
            "fill_ratio_med": float(
                _num(g["counterfactual_fill_ratio"]).median()),
            "depth_med": float(
                _num(g["top_of_book_executable_contracts"]).median()),
            "n_full_fill_possible": int(
                _num(g["counterfactual_full_fill_possible"]).sum()),
            "n_actual_fills": int(g["actual_fill_price_cents"].notna().sum()),
        }
    return out


def stress_table(hi: pd.DataFrame, dim: str) -> dict:
    out = {}
    for k, g in hi.groupby(dim, dropna=False):
        if len(g) < 5:
            continue
        row = {"n": int(len(g))}
        for c in STRESS_COLS:
            v = _num(g[c])
            row[c] = float(v.mean()) if v.notna().any() else None
        out[str(k)] = row
    return out


def main() -> int:
    df = pd.read_pickle(PKL)
    df = df[df["settled_yes"].notna()].copy()
    side = df["side"].astype(str).str.lower()
    df["held_yes"] = side == "yes"
    df["win"] = np.where(df["held_yes"], df["settled_yes"] == 1,
                         df["settled_yes"] == 0)
    df["payout"] = np.where(df["win"], 100.0, 0.0)
    df["exec_px"] = _num(df["executable_entry_price_cents"])
    df["fees"] = (_num(df["entry_fee_cents"]).fillna(0)
                  + _num(df["exit_or_settlement_fee_cents"]).fillna(0))
    df["real_edge"] = df["payout"] - df["exec_px"] - df["fees"]
    df["claim"] = _num(df["expected_net_ev_cents"])
    df["route"] = df["decision_id"].map(route_of)
    df["basis"] = df["counterfactual_entry_source"].map(basis_of)
    df["tte"] = df["ticker"].map(expiry_utc) - _num(df["decision_ts"])
    df.loc[df["tte"] < 0, "tte"] = np.nan
    df["week"] = (_num(df["decision_ts"]) // (7 * 86400)).astype("Int64")

    hi = df[df["claim"] >= CLAIM_THR].copy()
    rep = {
        "n_spine_settled": int(len(df)),
        "n_markets": int(df["ticker"].nunique()),
        "claim_threshold": CLAIM_THR,
        "n_claim_ge2": int(len(hi)),
        "n_markets_ge2": int(hi["ticker"].nunique()),
        "ts_span": [float(df["decision_ts"].min()),
                    float(df["decision_ts"].max())],
        "route_values": hi["route"].value_counts().to_dict(),
        "basis_values": hi["basis"].value_counts().to_dict(),
        "note": "real_edge = payout - executable_entry_price - modeled "
                "fees; claim = expected_net_ev_cents; route = decision_id "
                "suffix; basis = counterfactual_entry_source",
    }

    # --- primary splits ---
    for dim in ["route", "basis", "decision_lane", "admission_owner",
                "evidence_state", "counterfactual_execution_status"]:
        rep[f"ge2_by_{dim}"] = split_table(hi, dim)

    # route x basis cross — the pooling-artifact test
    rep["ge2_route_x_basis"] = {}
    for (r, b), g in hi.groupby(["route", "basis"], dropna=False):
        if len(g) < 5:
            continue
        rep["ge2_route_x_basis"][f"{r}|{b}"] = {
            **cboot(g, "real_edge", 200),
            "claim_mean": float(g["claim"].mean()),
            "n_actual_fills": int(
                g["actual_fill_price_cents"].notna().sum()),
        }

    # --- fill-through / harvest rate ---
    ffr = _num(hi["counterfactual_fill_ratio"])
    rep["fill_through"] = {
        "evals": int(len(hi)),
        "full_fill_possible_rate": float(
            _num(hi["counterfactual_full_fill_possible"]).mean()),
        "fill_ratio_mean": float(ffr.mean()),
        "fill_ratio_p10": float(ffr.quantile(0.10)),
        "fill_ratio_p50": float(ffr.quantile(0.50)),
        "fill_ratio_p90": float(ffr.quantile(0.90)),
        "actual_fills": int(hi["actual_fill_price_cents"].notna().sum()),
        "actual_fill_rate": float(
            hi["actual_fill_price_cents"].notna().mean()),
    }
    rep["fill_through_by_route"] = {}
    rep["fill_through_by_basis"] = {}
    for dim, store in [("route", rep["fill_through_by_route"]),
                       ("basis", rep["fill_through_by_basis"])]:
        for k, g in hi.groupby(dim, dropna=False):
            if len(g) < 5:
                continue
            store[str(k)] = {
                "n": int(len(g)),
                "full_fill_rate": float(
                    _num(g["counterfactual_full_fill_possible"]).mean()),
                "fill_ratio_med": float(
                    _num(g["counterfactual_fill_ratio"]).median()),
                "actual_fill_rate": float(
                    g["actual_fill_price_cents"].notna().mean()),
            }

    # --- stress reserves split (markout proxy) ---
    for dim in ["route", "basis"]:
        rep[f"stress_by_{dim}"] = stress_table(hi, dim)

    # --- actual fills at actual price, split ---
    fh = hi[hi["actual_fill_price_cents"].notna()].copy()
    rep["actual_fills_ge2"] = {"n": int(len(fh))}
    if len(fh):
        af = _num(fh["actual_fill_price_cents"])
        fside = fh["side"].astype(str).str.lower()
        fwin = np.where(fside == "yes", fh["settled_yes"] == 1,
                        fh["settled_yes"] == 0)
        fh["_edge"] = (np.where(fwin, 100.0, 0.0) - af - fh["fees"])
        rep["actual_fills_ge2"]["edge_at_actual_fill"] = {
            "mean": float(np.nanmean(fh["_edge"])),
            "p50": float(np.nanmedian(fh["_edge"])),
        }
        rep["actual_fills_ge2_by_route"] = split_table(
            fh, "route", 3, "_edge")
        rep["actual_fills_ge2_by_basis"] = split_table(
            fh, "basis", 3, "_edge")
        rep["actual_fills_ge2_by_lane"] = split_table(
            fh, "decision_lane", 3, "_edge")

    # --- weekly stability for headline splits ---
    for dim in ["route", "basis"]:
        rep[f"weekly_ge2_by_{dim}"] = {}
        for k, g in hi.groupby(dim, dropna=False):
            if len(g) < 10:
                continue
            wk = {}
            for w, gw in g.groupby("week", dropna=False):
                if len(gw) >= 3:
                    wk[str(w)] = cboot(gw, "real_edge", 100)
            rep[f"weekly_ge2_by_{dim}"][str(k)] = wk

    # --- BH-FDR across route x basis cells (multiplicity guard) ---
    cells = []
    for name, row in rep["ge2_route_x_basis"].items():
        cells.append({"cell": name, "mean": row.get("mean"),
                      "p": row.get("p_le_0"), "n": row.get("n"),
                      "mk": row.get("mk")})
    if cells:
        ps = np.array([c["p"] if c["p"] is not None else 1.0
                       for c in cells])
        q = bh_fdr(ps)
        for c, qv in zip(cells, q):
            c["bh_q"] = float(qv)
            c["bh_fdr_pass"] = bool(qv < 0.05)
        rep["route_x_basis_fdr"] = cells

    Path(OUT_JSON).parent.mkdir(exist_ok=True)
    Path(OUT_JSON).write_text(json.dumps(rep, indent=2, default=str))
    print(json.dumps(rep, indent=2, default=str)[:8000])
    print(f"wrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
