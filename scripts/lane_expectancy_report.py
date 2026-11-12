"""Per-lane realized-expectancy report over trade_attribution_fact.

Joins entry order intents -> decision_lane, then settlement events ->
entry_intent_id -> realized_pnl_cents. Read-only; safe against live DB.

Usage: .venv/Scripts/python.exe scripts/lane_expectancy_report.py [days]
"""
import json
import sqlite3
import sys
from collections import defaultdict

DB = "data/trade_attribution_fact.db"
ASSET_PREFIX = {
    "KXBTC15M": "BTC", "KXETH15M": "ETH", "KXSOL15M": "SOL",
    "KXXRP15M": "XRP", "KXDOGE15M": "DOGE",
}


def _asset(ticker: str) -> str:
    for p, a in ASSET_PREFIX.items():
        if ticker.startswith(p):
            return a
    return "?"


def _lane(meta_json: str):
    if not meta_json:
        return None, None
    try:
        outer = json.loads(meta_json)
        inner = outer.get("metadata") or outer
        return inner.get("decision_lane"), inner.get("reason")
    except Exception:
        return None, None


def main() -> None:
    days = float(sys.argv[1]) if len(sys.argv) > 1 else 0  # 0 = all time
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

    # intent_id -> (lane, asset, side, price, qty, ts)  [latest buy order wins]
    intents = {}
    for intent_id, ticker, side, price, qty, meta, ets in con.execute(
        "SELECT intent_id, ticker, side, price_cents, count_fp, metadata, event_ts "
        "FROM trade_attribution_fact WHERE event_type='order' AND action='buy'"
    ):
        lane, _reason = _lane(meta)
        intents[intent_id] = (lane or "core", _asset(ticker or ""), side, price, qty, ets)

    # settlement events -> realized pnl per entry intent
    cohorts = defaultdict(lambda: [0, 0.0, 0.0, 0, 0.0])  # n, pnl_c, pnl_per_contract_sum, wins, qty_sum
    unsettled = 0
    for meta_json, pnl, outcome, qty, ets in con.execute(
        "SELECT metadata, realized_pnl_cents, settlement_outcome, count_fp, event_ts "
        "FROM trade_attribution_fact WHERE event_type='settlement'"
    ):
        try:
            meta = json.loads(meta_json or "{}")
        except Exception:
            meta = {}
        entry_intent = meta.get("entry_intent_id")
        rec = intents.get(entry_intent)
        if rec is None:
            unsettled += 1
            continue
        lane, asset, side, _p, _q, _ets = rec
        key = (lane, asset, side or "?")
        try:
            q = float(qty or 0) or 1.0
        except Exception:
            q = 1.0
        pnl_c = float(pnl or 0)
        agg = cohorts[key]
        agg[0] += 1
        agg[1] += pnl_c
        agg[2] += pnl_c / max(q, 1e-9)
        agg[3] += 1 if pnl_c > 0 else 0
        agg[4] += q

    print(f"{'lane':26s} {'asset':5s} {'side':4s} {'n':>5s} {'qty':>7s} {'pnl_c':>9s} {'avg_c/ct':>8s} {'win%':>6s}")
    print("-" * 80)
    for key in sorted(cohorts):
        n, pnl, per_ct_sum, wins, qty = cohorts[key]
        print(f"{key[0]:26s} {key[1]:5s} {key[2]:4s} {n:5d} {qty:7.1f} {pnl:9.1f} {per_ct_sum/max(n,1):8.2f} {100*wins/max(n,1):5.1f}%")
    print("-" * 80)
    print(f"settlements w/o entry-intent match (older rows): {unsettled}")
    con.close()


if __name__ == "__main__":
    main()
