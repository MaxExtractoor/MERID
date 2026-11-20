"""Eval->fill join: does the model's claim-tail edge survive execution?

Joins model_calibration_observations evals to kalshi_fills entry fills
on (ticker, held side, time proximity), then measures:
  * match rate (how many evals ever became fills — the harvest rate)
  * slippage = actual held-side fill price - eval-time entry price
  * realized edge at ACTUAL fill price vs at eval price

    python scripts/audit_fill_slippage.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_edge_v2 import load_panel, prep, causal_snapshots, parabolic_fee_cents  # noqa: E402
from audit_edge_vs_memory import tte_bucket  # noqa: E402

CAL = "logs/model_calibration_observations.jsonl"
OUT = "logs/settlement_outcomes.jsonl"
FILLS = "data/kalshi_fills.db"
OUT_JSON = "reports/fill_slippage_audit.json"

# match window: eval precedes fill by up to MATCH_BACK seconds (decision->
# order->fill latency); fills may also slightly precede the logged eval
# when the eval row is written after submission.
MATCH_BACK_S = 300.0
MATCH_FWD_S = 10.0


def load_entry_fills() -> pd.DataFrame:
    conn = sqlite3.connect(f"file:{FILLS}?mode=ro", uri=True, timeout=60)
    df = pd.read_sql_query(
        "SELECT market_ticker, canonical_leg_price_cents, "
        "canonical_yes_delta_cc, fee_cost, liquidity_role, fill_source, "
        "is_exit, entry_or_exit, created_time, client_order_id, "
        "decision_trace_id, intent_id FROM kalshi_fills", conn)
    conn.close()
    df = df[df["liquidity_role"].ne("settlement")
            & df["fill_source"].ne("settlement")].copy()
    # entries only: is_exit flag or entry_or_exit label
    is_exit = df["is_exit"].fillna(0).astype(int).eq(1)
    labelled_exit = df["entry_or_exit"].astype(str).str.lower().eq("exit")
    df = df[~(is_exit | labelled_exit)].copy()
    df["d"] = df["canonical_yes_delta_cc"] / 100.0
    # held side: short YES (d<0) == long NO; long YES (d>0) == YES
    df["held_side"] = np.where(df["d"] < 0, "no", "yes")
    leg = df["canonical_leg_price_cents"].astype(float)
    df["held_price"] = np.where(df["held_side"] == "yes", leg, 100.0 - leg)
    df["held_contracts"] = df["d"].abs()
    df["ts"] = pd.to_datetime(
        df["created_time"], utc=True, format="mixed"
    ).map(lambda t: t.timestamp())
    df["wkey"] = df["market_ticker"].astype(str).str.split("-").str[1]
    return df


def nearest_prior_evals(evals: pd.DataFrame, fills: pd.DataFrame) -> pd.DataFrame:
    """For each fill, nearest eval (same ticker+side) with
    eval_ts - MATCH_BACK <= fill_ts <= eval_ts + MATCH_FWD."""
    # index evals by (ticker, side)
    ev = evals.sort_values("ts")
    matches = []
    # group fills by (ticker, side) to keep search local
    for (tk, sd), fg in fills.groupby(["market_ticker", "held_side"],
                                      sort=False):
        eg = ev[(ev["ticker"] == tk) & (ev["side"] == sd)]
        if len(eg) == 0:
            continue
        ets = eg["ts"].to_numpy()
        for idx, fr in fg.iterrows():
            lo = np.searchsorted(ets, fr["ts"] - MATCH_FWD_S, "left")
            hi = np.searchsorted(ets, fr["ts"] + MATCH_BACK_S, "right")
            if hi <= lo:
                continue
            # nearest eval ts to the fill within the window
            cand = eg.iloc[lo:hi]
            dt = (cand["ts"] - fr["ts"]).abs()
            j = dt.idxmin()
            e = eg.loc[j]
            matches.append({
                "fill_idx": idx, "ticker": tk, "side": sd,
                "fill_ts": fr["ts"], "eval_ts": float(e["ts"]),
                "dt_s": float(fr["ts"] - e["ts"]),
                "eval_entry": float(e["entry_price_cents"]),
                "eval_claim": float(e["claim_gap"]),
                "eval_p": float(e["p_model"]),
                "fill_price": float(fr["held_price"]),
                "contracts": float(fr["held_contracts"]),
                "fee_cost_usd": float(fr["fee_cost"] or 0.0),
                "liquidity_role": fr["liquidity_role"],
                "lane_hint": str(fr["decision_trace_id"] or ""),
                "resolved_yes": float(e["resolved_yes"]),
                "asset": e["asset"],
                "tte_s": float(e["seconds_to_expiry"]),
                "price_bucket": e["price_bucket"],
                "tte_bucket": e["tte_bucket"],
            })
    return pd.DataFrame(matches)


def realized_edge(row_payout_win: pd.Series, entry: pd.Series,
                  fee_c: pd.Series) -> pd.Series:
    return row_payout_win * 100.0 - entry - fee_c


def main() -> int:
    print("[slip] loading evals ...", flush=True)
    df = prep(load_panel(CAL, OUT))
    snaps = causal_snapshots(df)
    fp = snaps["first_per_tte_bucket"].dropna(subset=["claim_gap"]).copy()
    print(f"[slip] causal evals: {len(fp)}", flush=True)

    fills = load_entry_fills()
    print(f"[slip] entry fills: {len(fills)} across "
          f"{fills.market_ticker.nunique()} markets", flush=True)

    m = nearest_prior_evals(fp, fills)
    print(f"[slip] matched fills: {len(m)}", flush=True)
    if len(m) == 0:
        print("no matches — check side/time conventions")
        return 1

    m["slip_c"] = m["fill_price"] - m["eval_entry"]  # + = paid more (adverse)
    m["win"] = np.where(m["side"] == "yes",
                        m["resolved_yes"] == 1.0,
                        m["resolved_yes"] == 0.0)
    m["payout"] = np.where(m["win"], 100.0, 0.0)
    m["fee_eval"] = m["eval_entry"].map(parabolic_fee_cents)
    m["fee_fill"] = m["fill_price"].map(parabolic_fee_cents)
    m["edge_at_eval"] = m["payout"] - m["eval_entry"] - m["fee_eval"]
    m["edge_at_fill"] = m["payout"] - m["fill_price"] - m["fee_fill"]
    m["edge_at_fill_net_venue_fee"] = (
        m["payout"] - m["fill_price"] - m["fee_fill"]
        - m["fee_cost_usd"] * 100.0)
    m["claim_bucket"] = pd.cut(
        m["eval_claim"], [-1e9, 0, 1, 2, 3, 5, 1e9],
        labels=["<0", "0-1", "1-2", "2-3", "3-5", ">=5"])

    rep = {"n_evals": int(len(fp)), "n_fills": int(len(fills)),
           "n_matched": int(len(m)),
           "match_rate_fills": float(len(m) / max(len(fills), 1))}

    # --- slippage distribution overall + by claim bucket ---
    slip = {}
    for b, g in m.groupby("claim_bucket", observed=True):
        slip[str(b)] = {
            "n": int(len(g)),
            "slip_mean": float(g["slip_c"].mean()),
            "slip_p50": float(g["slip_c"].median()),
            "slip_p90": float(g["slip_c"].quantile(0.9)),
            "slip_p10": float(g["slip_c"].quantile(0.1)),
            "edge_eval": float(g["edge_at_eval"].mean()),
            "edge_fill": float(g["edge_at_fill"].mean()),
            "edge_fill_venuefee": float(
                g["edge_at_fill_net_venue_fee"].mean()),
            "winrate": float(g["win"].mean()),
        }
    rep["by_claim_bucket"] = slip

    # --- the >=+2c cohort specifically ---
    hi = m[m["eval_claim"] >= 2.0]
    rep["claim_ge2"] = {
        "n_fills_matched": int(len(hi)),
        "n_markets": int(hi["ticker"].nunique()),
        "slip_mean": float(hi["slip_c"].mean()) if len(hi) else None,
        "slip_p50": float(hi["slip_c"].median()) if len(hi) else None,
        "edge_eval_mean": float(hi["edge_at_eval"].mean()) if len(hi) else None,
        "edge_fill_mean": float(hi["edge_at_fill"].mean()) if len(hi) else None,
        "edge_fill_venuefee_mean": float(
            hi["edge_at_fill_net_venue_fee"].mean()) if len(hi) else None,
        "winrate": float(hi["win"].mean()) if len(hi) else None,
    }

    # --- harvest rate: how many >=2c evals produced any fill? ---
    ev_hi = fp[fp["claim_gap"] >= 2.0]
    ev_hi_keys = set(zip(ev_hi["ticker"], ev_hi["side"]))
    fill_keys = set(zip(m["ticker"], m["side"]))
    rep["claim_ge2_evals"] = int(len(ev_hi))
    rep["claim_ge2_evals_with_fill"] = int(
        len(ev_hi_keys & fill_keys))

    # all evals harvest rate for context
    rep["all_evals_with_fill"] = int(
        len(set(zip(fp["ticker"], fp["side"])) & fill_keys))
    rep["all_eval_keys"] = int(len(set(zip(fp["ticker"], fp["side"]))))

    # by lane hint for matched fills
    rep["by_lane"] = (m.assign(lane=m["lane_hint"].str.split(":").str[-1])
                      .groupby("lane")
                      .agg(n=("slip_c", "size"),
                           slip_mean=("slip_c", "mean"),
                           edge_fill=("edge_at_fill", "mean"),
                           claim_mean=("eval_claim", "mean"))
                      .query("n>=3").round(3).to_dict("index"))

    m.to_json("data/fill_slippage_matches.jsonl", orient="records",
              lines=True)
    Path(OUT_JSON).parent.mkdir(exist_ok=True)
    Path(OUT_JSON).write_text(json.dumps(rep, indent=2, default=str))

    print(json.dumps(rep, indent=2, default=str)[:4000])
    print(f"[slip] wrote {OUT_JSON} + data/fill_slippage_matches.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
