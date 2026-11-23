"""Phase 2 — executable-edge waterfall + NO_EDGE reconciliation.

Builds on the frozen claim-tail definition (claim = expected_net_ev_cents
>= 2.0, decision-spine extract data/decision_spine.pkl) and the Phase 0
reconciliation findings:

- claim>=+2c cohort is dominated by *non-selected-side* evals and by
  evals that never become order attempts (emission die-off upstream of
  the router).
- The side edge gate compares gate_ev_cents to required_edge_cents; the
  decision-level NO_EDGE is a separate, stricter evaluation.

Waterfall stages (per evaluated opportunity, cents/contract):
  A  reproduced legacy eval-price result      -> real_edge @ exec_px
  B  executable purchase price at eval receipt -> executable_entry_price_cents
  C  modeled fill price (slippage-adverse)     -> expected_entry_fill_cents
  D  post-latency executable price             -> NOT measurable without
     book-archive replay; reported as a coverage gap, not estimated.
  E  feasible quantity                        -> counterfactual_fill_ratio,
     top_of_book_executable_contracts,
     counterfactual_full_fill_possible
  F  net settlement P&L after modeled fees    -> real_edge variants
  G  policy P&L incl. nonfills/skips          -> funnel counts +
     market-deduped means (evals are correlated within a market)

NO_EDGE classification for the claim cohort (advisor taxonomy):
  1 correct_rejection      gate_ev < required_edge (costs/uncertainty
                           eliminate the eval-price edge)
  2 decision_level_veto    side gate passed, decision=NO_TRADE
                           (primary_reason_code=NO_EDGE / DQ_VETO)
  3 non_selected_side      decision=ENTER but eval side != selected_side
                           (the claim described the OTHER side of the trade)
  4 selected_enter_dead    selected side + ENTER + zero order attempts
                           (emission die-off before router persistence)
  5 unresolved             remainder

    python scripts/audit_directional_edge_phase02.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PKL = "data/decision_spine.pkl"
OUT = "reports/directional_edge_phase02.json"
CLAIM_THR = 2.0


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _expiry_ts(ticker: str) -> float:
    """KX*15M-26NOV170945-45 -> settlement close epoch.

    The ticker time IS the window close label (US Eastern), verified
    against strategy_decisions.close_ts and live fills — do NOT add 15m.
    """
    try:
        from zoneinfo import ZoneInfo
        parts = str(ticker).split("-")
        return datetime.strptime(parts[1], "%y%b%d%H%M").replace(
            tzinfo=ZoneInfo("America/New_York")
        ).timestamp()
    except Exception:
        return np.nan


def _cboot(g: pd.DataFrame, col: str, B: int = 400, seed: int = 11):
    """Market-clustered bootstrap CI for mean of col."""
    keys = g["ticker"].unique()
    if len(keys) < 2 or g[col].notna().sum() < 2:
        v = g[col].dropna()
        m = float(v.mean()) if len(v) else None
        return {"mean": m, "ci_lo": None, "ci_hi": None,
                "p_le_0": None, "n": int(len(g)), "mk": int(len(keys))}
    rng = np.random.default_rng(seed)
    gmk = {k: v[col].values for k, v in g.groupby("ticker")}
    vals = []
    for _ in range(B):
        pick = rng.choice(keys, size=len(keys), replace=True)
        vals.append(np.concatenate([gmk[k] for k in pick]).mean())
    arr = np.asarray(vals)
    return {
        "mean": float(np.nanmean(g[col])),
        "ci_lo": float(np.nanpercentile(arr, 2.5)),
        "ci_hi": float(np.nanpercentile(arr, 97.5)),
        "p_le_0": float(np.mean(arr <= 0)),
        "n": int(len(g)),
        "mk": int(len(keys)),
    }


def _decorate(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    side = df["side"].astype(str).str.lower()
    sel = df["selected_side"].astype(str).str.lower()
    df["held_yes"] = side == "yes"
    df["win"] = np.where(df["held_yes"], df["settled_yes"] == 1,
                         df["settled_yes"] == 0)
    df["payout"] = np.where(df["win"], 100.0, 0.0)
    df["exec_px"] = _num(df["executable_entry_price_cents"])
    df["fill_px"] = _num(df["expected_entry_fill_cents"])
    df["fees"] = (_num(df["entry_fee_cents"]).fillna(0)
                  + _num(df["exit_or_settlement_fee_cents"]).fillna(0))
    df["real_edge_exec"] = df["payout"] - df["exec_px"] - df["fees"]
    df["real_edge_fill"] = df["payout"] - df["fill_px"] - df["fees"]
    df["claim"] = _num(df["expected_net_ev_cents"])
    df["gate_ev"] = _num(df["gate_ev_cents"])
    df["req_edge"] = _num(df["required_edge_cents"])
    df["lcb"] = _num(df["lower_confidence_bound_ev_cents"])
    df["gross"] = _num(df["gross_edge_cents"])
    df["sel_side"] = sel
    df["is_sel_side"] = side == sel
    df["cand"] = df["decision_id"].astype(str).str.split(":").str[0]
    df["asset"] = df["ticker"].astype(str).str.extract(r"KX([A-Z]+)15M")[0]
    exp = df["ticker"].map(_expiry_ts)
    dts = _num(df["decision_ts"])
    df["tte"] = exp - dts
    df.loc[df["tte"] < 0, "tte"] = np.nan
    df["tte_b"] = pd.cut(
        df["tte"], [0, 60, 150, 300, 600, 900, 1e9],
        labels=["<60", "60-150", "150-300", "300-600", "600-900",
                ">900_preopen"])
    df["pb"] = pd.cut(df["exec_px"], [0, 10, 25, 50, 75, 90, 94, 98, 100],
                      labels=["01-10", "11-25", "26-50", "51-75",
                              "76-90", "91-94", "95-98", "99-100"])
    return df


def _waterfall(df: pd.DataFrame) -> dict:
    """Stage A-G summary for a cohort (eval-weighted + market-deduped)."""
    out = {
        "n_evals": int(len(df)),
        "n_markets": int(df["ticker"].nunique()),
        "n_candidates": int(df["cand"].nunique()),
    }
    for c in ["claim", "gate_ev", "req_edge", "lcb", "gross",
              "exec_px", "fill_px", "fees", "real_edge_exec",
              "real_edge_fill"]:
        v = df[c].dropna()
        out[f"{c}_mean"] = float(v.mean()) if len(v) else None
        out[f"{c}_p50"] = float(v.median()) if len(v) else None
    for c in ["passed_edge_gate", "counterfactual_full_fill_possible"]:
        v = pd.to_numeric(df[c], errors="coerce")
        out[f"{c}_rate"] = float(v.mean()) if v.notna().any() else None
    for c in ["counterfactual_fill_ratio",
              "top_of_book_executable_contracts",
              "counterfactual_assumed_filled_contracts"]:
        v = _num(df[c])
        out[f"{c}_mean"] = float(v.mean()) if v.notna().any() else None
        out[f"{c}_p50"] = float(v.median()) if v.notna().any() else None
    out["edge_at_exec_px_cboot"] = _cboot(df, "real_edge_exec")
    out["edge_at_fill_px_cboot"] = _cboot(df, "real_edge_fill")
    # market-deduped: one mean per market (removes eval-frequency bias)
    mk = (df.groupby("ticker", dropna=False)[
              ["real_edge_exec", "real_edge_fill", "claim"]]
          .mean().reset_index()
          .rename(columns={"real_edge_exec": "e_exec",
                           "real_edge_fill": "e_fill",
                           "claim": "claim_m"}))
    mk["real_edge_exec"] = mk["e_exec"]
    out["market_dedup"] = {
        "n_markets": int(len(mk)),
        "edge_exec_mean": float(mk["e_exec"].mean()),
        "edge_exec_ci": _cboot(mk[["ticker", "real_edge_exec"]],
                               "real_edge_exec"),
        "edge_fill_mean": float(mk["e_fill"].mean()),
        "claim_mean": float(mk["claim_m"].mean()),
    }
    return out


def _funnel(df: pd.DataFrame) -> dict:
    """Phase-0 funnel + NO_EDGE disagreement classes for the claim cohort."""
    n = len(df)
    rep = {"cohort_n": int(n)}
    rep["by_decision"] = df["decision"].value_counts(dropna=False).to_dict()
    rep["by_passed_edge_gate"] = (
        df["passed_edge_gate"].value_counts(dropna=False).to_dict())
    rep["by_exclusion_reason"] = (
        df["exclusion_reason"].value_counts(dropna=False)
        .head(12).to_dict())
    # NO_EDGE classes
    gate_fail = (df["gate_ev"].notna() & df["req_edge"].notna()
                 & (df["gate_ev"] < df["req_edge"]))
    classes = {
        "1_correct_rejection_gate": int((df["passed_edge_gate"] == 0).sum()),
        "2_decision_level_veto": int(
            ((df["passed_edge_gate"] == 1) & (df["decision"] == "NO_TRADE"))
            .sum()),
        "3_non_selected_side_enter": int(
            ((df["decision"] == "ENTER") & (~df["is_sel_side"])).sum()),
        "4_selected_enter": int(
            ((df["decision"] == "ENTER") & (df["is_sel_side"])).sum()),
    }
    classes["gate_ev_lt_req_edge"] = int(gate_fail.sum())
    rep["no_edge_classes"] = classes
    rep["selected_enter_by_lane"] = (
        df[(df["decision"] == "ENTER") & (df["is_sel_side"])]
        ["decision_lane"].value_counts(dropna=False).to_dict())
    rep["selected_enter_fills"] = int(
        df[(df["decision"] == "ENTER") & (df["is_sel_side"])]
        ["actual_fill_price_cents"].notna().sum())
    return rep


def main() -> int:
    df = pd.read_pickle(PKL)
    df = df[df["settled_yes"].notna()].copy()
    df = _decorate(df)
    hi = df[df["claim"] >= CLAIM_THR].copy()

    rep = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "source": PKL,
        "claim_threshold_cents": CLAIM_THR,
        "stage_D_note": ("post-latency executable price requires "
                         "book-archive replay at decision+latency; not "
                         "estimated here — coverage gap, not zero"),
        "all_evals": _waterfall(df),
        "claim_ge2": {"waterfall": _waterfall(hi), "funnel": _funnel(hi)},
        "claim_ge2_by_asset": {},
        "claim_ge2_by_tte": {},
        "claim_ge2_by_lane": {},
        "claim_ge2_by_price_band": {},
        "actual_fills_all": _waterfall(
            df[df["actual_fill_price_cents"].notna()]),
    }

    for dim, col, key in [
        ("asset", "asset", "claim_ge2_by_asset"),
        ("tte", "tte_b", "claim_ge2_by_tte"),
        ("lane", "decision_lane", "claim_ge2_by_lane"),
        ("price_band", "pb", "claim_ge2_by_price_band"),
    ]:
        store = rep[key]
        for k, g in hi.groupby(col, dropna=False):
            if len(g) < 10:
                continue
            store[str(k)] = _waterfall(g)

    Path(OUT).parent.mkdir(parents=True, exist_ok=True)
    Path(OUT).write_text(json.dumps(rep, indent=2, default=str))
    print(f"[p02] evals={len(df)} claim={len(hi)} "
          f"mk={df['ticker'].nunique()} -> {OUT}")
    w = rep["claim_ge2"]["waterfall"]
    print(f"[p02] claim cohort: exec-edge mean={w['real_edge_exec_mean']:.3f} "
          f"fill-edge mean={w['real_edge_fill_mean']:.3f} "
          f"fill_ratio={w['counterfactual_fill_ratio_mean']:.3f} "
          f"full_fill={w['counterfactual_full_fill_possible_rate']:.3f}")
    print(f"[p02] funnel: {rep['claim_ge2']['funnel']['no_edge_classes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
