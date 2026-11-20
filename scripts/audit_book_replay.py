"""Book-archive depth replay for the claim-tail cohort.

For each model-calibration eval with claim_gap >= threshold whose market
is covered by kalshi_book_archive_live3.db, reconstruct the YES/NO bid
ladders at the eval timestamp (latest snapshot + deltas, receipt-time
aligned), derive the held-side executable ask ladder, simulate taker
fills, and measure realized settlement edge at the simulated fill price.

    python scripts/audit_book_replay.py --min-claim 2.0
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_edge_v2 import (  # noqa: E402
    load_panel, prep, causal_snapshots, parabolic_fee_cents,
)

CAL = "logs/model_calibration_observations.jsonl"
OUT = "logs/settlement_outcomes.jsonl"
BOOK_DB = "data/kalshi_book_archive_live3.db"
OUT_JSON = "reports/book_replay_audit.json"


def load_claim_evals(min_claim: float, since: str | None) -> pd.DataFrame:
    df = prep(load_panel(CAL, OUT))
    fp = causal_snapshots(df)["first_per_tte_bucket"].dropna(
        subset=["claim_gap"]).copy()
    if since:
        fp = fp[pd.to_datetime(fp["ts"], unit="s", utc=True)
                >= pd.Timestamp(since, tz="UTC")]
    return fp[fp["claim_gap"] >= min_claim].sort_values("ts")


def covered_tickers() -> set[str]:
    conn = sqlite3.connect(f"file:{BOOK_DB}?mode=ro", uri=True, timeout=60)
    rows = conn.execute(
        "SELECT market_ticker FROM archive_coverage "
        "WHERE state IN ('covering','closed')").fetchall()
    conn.close()
    return {r[0] for r in rows}


def fetch_events(conn: sqlite3.Connection, ticker: str,
                 t0_ns: int, t1_ns: int) -> list[tuple[int, int, str]]:
    """(recv_ns, seq, raw_payload) for one market in the window."""
    cur = conn.execute(
        "SELECT received_at_utc_ns, sequence_number, raw_payload "
        "FROM book_events WHERE market_ticker=? "
        "AND received_at_utc_ns BETWEEN ? AND ? "
        "ORDER BY received_at_utc_ns, sequence_number",
        (ticker, t0_ns, t1_ns))
    return cur.fetchall()


def parse_ladders(events: list[tuple[int, int, str]],
                  eval_times: list[float]) -> dict[float, dict]:
    """Replay events once; capture bid ladders at each eval ts.

    Returns {eval_ts: {'yes': {px: sz}, 'no': {px: sz}, 'n_ev': int,
    'had_snap': bool}}."""
    yes: dict[float, float] = {}
    no: dict[float, float] = {}
    use_yes_price = False
    out: dict[float, dict] = {}
    ei = 0
    n_ev = 0
    had_snap = False
    pending = sorted(eval_times)

    def capture(ts: float) -> None:
        out[ts] = {
            "yes": dict(yes), "no": dict(no),
            "n_ev": n_ev, "had_snap": had_snap,
        }

    for recv_ns, seq, raw in events:
        ts_s = recv_ns / 1e9
        # capture all evals at or before this event's receipt
        while ei < len(pending) and pending[ei] <= ts_s:
            capture(pending[ei]); ei += 1
        try:
            msg = json.loads(raw)
        except Exception:
            continue
        m = msg.get("msg") or {}
        mtype = msg.get("type")
        n_ev += 1
        if mtype == "orderbook_snapshot" and ("yes_dollars_fp" in m
                                              or "no_dollars_fp" in m):
            yes.clear(); no.clear()
            for arr, tgt in ((m.get("yes_dollars_fp"), yes),
                             (m.get("no_dollars_fp"), no)):
                if not arr:
                    continue
                for px, sz in arr:
                    try:
                        p = round(float(px) * 100.0, 4)
                        s = float(sz)
                    except Exception:
                        continue
                    if 0 < p < 100 and s > 0:
                        tgt[p] = tgt.get(p, 0.0) + s
            if "use_yes_price" in m:
                use_yes_price = bool(m["use_yes_price"])
            had_snap = True
            continue
        if mtype != "orderbook_delta":
            continue
        try:
            side = m.get("side")
            px = round(float(m["price_dollars"]) * 100.0, 4)
            d = float(m["delta_fp"])
        except Exception:
            continue
        if "use_yes_price" in m:
            use_yes_price = bool(m["use_yes_price"])
        if side == "no" and use_yes_price:
            px = 100.0 - px
        if not (0 < px < 100):
            continue
        tgt = yes if side == "yes" else no
        new = tgt.get(px, 0.0) + d
        if new <= 0:
            tgt.pop(px, None)
        else:
            tgt[px] = round(new, 4)
    while ei < len(pending):
        capture(pending[ei]); ei += 1
    return out


def ask_ladder(opposite_bids: dict[float, float]) -> list[tuple[float, float]]:
    """Executable asks for the held side = complement of opposite bids,
    sorted ascending by price."""
    return sorted(((100.0 - p, s) for p, s in opposite_bids.items()
                   if 0 < 100.0 - p < 100 and s > 0))


def vwap_walk(ladder: list[tuple[float, float]], qty: float,
              cap_price: float | None = None) -> tuple[float, float, bool]:
    """Walk ask ladder for up to qty contracts, never paying above
    cap_price. Returns (vwap_of_filled_portion, filled_qty, full)."""
    need = qty
    cost = 0.0
    filled = 0.0
    for px, sz in ladder:
        if cap_price is not None and px > cap_price:
            break
        take = min(need, sz)
        cost += take * px
        filled += take
        need -= take
        if need <= 1e-9:
            return cost / qty, qty, True
    vwap = cost / filled if filled > 0 else float("nan")
    return vwap, filled, False


def analyze_state(state: dict, side: str, entry_eval: float,
                  resolved_yes: float, fee_fn) -> dict:
    """Executable-edge stats for one eval's book state."""
    if not state["had_snap"]:
        return {"book": "no_snapshot"}
    # held side asks: buying 'yes' lifts YES asks = 100 - no bids;
    # buying 'no' lifts NO asks = 100 - yes bids.
    opp = state["no"] if side == "yes" else state["yes"]
    own = state["yes"] if side == "yes" else state["no"]
    asks = ask_ladder(opp)
    if not asks:
        return {"book": "empty_ask_side"}
    best_ask, best_sz = asks[0]
    # own-side bid for spread (held side bid = 100 - opp best... actually
    # held-side bid = complement of opposite side's ask; simpler: held bid
    # is own-side top bid)
    own_bid = max(own.keys()) if own else None
    spread = (best_ask - own_bid) if own_bid is not None else None
    win = (resolved_yes == 1.0) if side == "yes" else (resolved_yes == 0.0)
    payout = 100.0 if win else 0.0
    res = {"book": "ok", "best_ask": best_ask, "best_ask_sz": best_sz,
           "spread": spread, "n_ask_levels": len(asks),
           "eval_entry": entry_eval,
           "ask_minus_eval": best_ask - entry_eval}
    for qty in (1.0, 5.0):
        for stress in (0.0, 1.0, 2.0, 3.0):
            cap = None if stress == 0 else best_ask + stress
            vwap, filled, full = vwap_walk(asks, qty, cap_price=cap)
            key = f"q{int(qty)}_s{int(stress)}"
            res[key + "_full"] = bool(full)
            res[key + "_px"] = vwap if full else float("nan")
            res[key + "_edge"] = (payout - vwap - fee_fn(vwap)
                                  if full else float("nan"))
            res[key + "_filled"] = filled
    # depth within best+2c for capacity note
    res["depth_within_2c"] = sum(s for p, s in asks if p <= best_ask + 2.0)
    res["depth_within_5c"] = sum(s for p, s in asks if p <= best_ask + 5.0)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-claim", type=float, default=2.0)
    ap.add_argument("--since", default="2026-11-17")
    ap.add_argument("--control-frac", type=float, default=0.0,
                    help="fraction of claim<0 evals to include as control")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    print("[replay] loading claim evals ...", flush=True)
    ev = load_claim_evals(args.min_claim, args.since)
    cov = covered_tickers()
    ev = ev[ev["ticker"].isin(cov)].copy()
    print(f"[replay] {len(ev)} claim>={args.min_claim} evals in covered "
          f"markets ({ev['ticker'].nunique()} tickers)", flush=True)

    rng = np.random.default_rng(args.seed)
    all_fp = None
    if args.control_frac > 0:
        df = prep(load_panel(CAL, OUT))
        all_fp = causal_snapshots(df)["first_per_tte_bucket"].dropna(
            subset=["claim_gap"])
        all_fp = all_fp[(all_fp["claim_gap"] < 0)
                        & all_fp["ticker"].isin(cov)
                        & (pd.to_datetime(all_fp["ts"], unit="s", utc=True)
                           >= pd.Timestamp(args.since, tz="UTC"))]
        ctrl = all_fp.sample(frac=args.control_frac, random_state=args.seed)
        ev = pd.concat([ev, ctrl], ignore_index=True)
        print(f"[replay] +{len(ctrl)} control evals", flush=True)

    if len(ev) == 0:
        print("no evals in covered window")
        return 1

    conn = sqlite3.connect(f"file:{BOOK_DB}?mode=ro", uri=True, timeout=300)
    results = []
    by_ticker = {tk: g.sort_values("ts") for tk, g in ev.groupby("ticker")}
    done = 0
    for tk, g in by_ticker.items():
        t0 = int((g["ts"].min() - 120.0) * 1e9)
        t1 = int((g["ts"].max() + 5.0) * 1e9)
        events = fetch_events(conn, tk, t0, t1)
        if not events:
            for _, r in g.iterrows():
                results.append({"ticker": tk, "side": r["side"],
                                "ts": r["ts"], "claim_gap": r["claim_gap"],
                                "book": "no_events"})
            continue
        states = parse_ladders(events, list(g["ts"].unique()))
        for _, r in g.iterrows():
            st = states.get(float(r["ts"]))
            if st is None:
                results.append({"ticker": tk, "side": r["side"],
                                "ts": r["ts"], "claim_gap": r["claim_gap"],
                                "book": "no_state"})
                continue
            rec = analyze_state(st, str(r["side"]).lower(),
                                float(r["entry_price_cents"]),
                                float(r["resolved_yes"]),
                                parabolic_fee_cents)
            rec.update({"ticker": tk, "side": str(r["side"]).lower(),
                        "ts": float(r["ts"]),
                        "claim_gap": float(r["claim_gap"]),
                        "eval_entry": float(r["entry_price_cents"]),
                        "resolved_yes": float(r["resolved_yes"]),
                        "tte_s": float(r["seconds_to_expiry"]),
                        "asset": r["asset"],
                        "price_bucket": r["price_bucket"],
                        "win": float((r["resolved_yes"] == 1)
                                     if str(r["side"]).lower() == "yes"
                                     else (r["resolved_yes"] == 0))})
            results.append(rec)
        done += 1
        if done % 20 == 0:
            print(f"[replay] {done}/{len(by_ticker)} markets", flush=True)
    conn.close()

    res = pd.DataFrame(results)
    res.to_json("data/book_replay_results.jsonl", orient="records",
                lines=True)

    rep = {"n_evals": int(len(ev)), "n_markets": int(ev["ticker"].nunique()),
           "min_claim": args.min_claim, "since": args.since,
           "book_status": res["book"].value_counts().to_dict() if len(res) else {}}
    ok = res[res["book"] == "ok"].copy()
    rep["n_book_ok"] = int(len(ok))
    if len(ok):
        rep["ask_vs_eval"] = {
            "mean_diff": float(ok["ask_minus_eval"].mean()),
            "p50_diff": float(ok["ask_minus_eval"].median()),
            "mean_spread": float(ok["spread"].mean()),
            "median_spread": float(ok["spread"].median()),
        }
        for qty in (1, 5):
            for stress in (0, 1, 2, 3):
                col = f"q{qty}_s{stress}_edge"
                full_col = f"q{qty}_s{stress}_full"
                sub = ok[ok[full_col] == True] if full_col in ok else ok
                vals = pd.to_numeric(sub[col], errors="coerce").dropna()
                rep[f"edge_{col}"] = {
                    "n": int(len(vals)),
                    "mean": float(vals.mean()) if len(vals) else None,
                    "p25": float(vals.quantile(0.25)) if len(vals) else None,
                    "p50": float(vals.median()) if len(vals) else None,
                    "p75": float(vals.quantile(0.75)) if len(vals) else None,
                    "winrate": float((vals > 0).mean()) if len(vals) else None,
                }
        # eval-price edge for the same rows (counterfactual benchmark)
        ev_edge = np.where(ok["win"] == 1, 100.0, 0.0) - ok["eval_entry"] \
            - ok["eval_entry"].map(parabolic_fee_cents)
        rep["edge_at_eval_price"] = {
            "n": int(len(ev_edge)), "mean": float(np.mean(ev_edge)),
            "p50": float(np.median(ev_edge)),
        }
        rep["claim_mean"] = float(ok["claim_gap"].mean())
        # by price bucket
        rep["by_price_bucket"] = {}
        for pb, g in ok.groupby("price_bucket"):
            e = pd.to_numeric(g["q1_s2_edge"], errors="coerce").dropna()
            rep["by_price_bucket"][str(pb)] = {
                "n": int(len(g)),
                "edge_q1_s2_mean": float(e.mean()) if len(e) else None,
                "edge_eval_mean": float(np.mean(
                    np.where(g["win"] == 1, 100.0, 0.0)
                    - g["eval_entry"]
                    - g["eval_entry"].map(parabolic_fee_cents))),
            }
    Path(OUT_JSON).write_text(json.dumps(rep, indent=2, default=str))
    print(json.dumps(rep, indent=2, default=str)[:5000])
    print(f"[replay] wrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
