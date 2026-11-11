from __future__ import annotations

import argparse
import bisect
import json
import math
import os
import sqlite3
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from merid.prediction.window_plan import execution_profile_settings
from merid.event_venues.kalshi.parabolic_fees import kalshi_fee_cents_exact


def quote_path_trade(quotes, decision_ts, *, latency_s, target_cents, stop_cents=5, horizon_s=60, max_gap_s=15):
    times = [q[0] for q in quotes]
    index = bisect.bisect_left(times, decision_ts + latency_s)
    if index >= len(quotes) or times[index] - decision_ts - latency_s > max_gap_s:
        return None
    start, bid, ask = quotes[index]
    deadline = start + horizon_s
    last = start
    for ts, bid, _ in quotes[index + 1:]:
        if ts - last > max_gap_s:
            return None
        if ts > deadline:
            return (start, ask, last, previous_bid, "timeout") if last >= deadline - max_gap_s else None
        last = ts
        previous_bid = bid
        if bid - ask >= target_cents:
            return start, ask, ts, bid, "target"
        if bid - ask <= -stop_cents:
            return start, ask, ts, bid, "stop"
        if ts == deadline:
            return start, ask, ts, bid, "timeout"
    return None


def compare(candidates, books, *, latency_s=21, targets=(5, 10, 20)):
    result = {}
    for profile in ("conservative", "mixed", "aggressive"):
        settings = execution_profile_settings(profile)
        for target in targets:
            spent = defaultdict(float)
            contracts = defaultdict(int)
            seen = set()
            trades = []
            skipped = defaultdict(int)
            for c in sorted(candidates, key=lambda c: (c["ts"], -c["edge"], c["ticker"], c["side"])):
                ticker, side = c["ticker"], c["side"]
                window = ticker.split("-")[1]
                if ticker in seen:
                    continue
                if latency_s * 1000 > settings["refresh_ms"]:
                    skipped["refresh_ceiling"] += 1
                    continue
                if c["tte"] - latency_s <= 150 + 60:
                    skipped["closeout_room"] += 1
                    continue
                trade = quote_path_trade(books.get((ticker, side), []), c["ts"],
                                         latency_s=latency_s, target_cents=target)
                if trade is None:
                    skipped["incomplete_quote_path"] += 1
                    continue
                entry_ts, entry, exit_ts, exit_price, reason = trade
                if c["edge"] + c["price"] - entry < max(0, c["required"]) - 1e-9:
                    skipped["price_edge_decayed"] += 1
                    continue
                quantity = min(settings["order_contracts"], 6 - contracts[window])
                while quantity > 0:
                    fee = float(kalshi_fee_cents_exact(entry / 100, Decimal(quantity), "taker"))
                    cost = entry * quantity + fee
                    if spent[window] + cost <= 600:
                        break
                    quantity -= 1
                if quantity <= 0:
                    skipped["window_budget_or_contract_cap"] += 1
                    continue
                seen.add(ticker)
                contracts[window] += quantity
                spent[window] += cost
                exit_fee = float(kalshi_fee_cents_exact(exit_price / 100, Decimal(quantity), "taker"))
                trades.append({"ticker": ticker, "side": side, "quantity": quantity,
                               "entry_ts": entry_ts, "exit_ts": exit_ts, "reason": reason,
                               "net_cents": (exit_price - entry) * quantity - fee - exit_fee})
            result[f"{profile}:target_{target}c"] = {
                "trades": len(trades), "assets": sorted({t["ticker"].split("-")[0] for t in trades}),
                "windows": len(contracts), "contracts": sum(contracts.values()),
                "quote_path_upper_bound_net_cents": round(sum(t["net_cents"] for t in trades), 4),
                "wins": sum(t["net_cents"] > 0 for t in trades),
                "exit_reasons": dict((reason, sum(t["reason"] == reason for t in trades))
                                     for reason in ("target", "stop", "timeout")),
                "skipped": dict(skipped),
            }
    return result


def load_data(db, days, limit=100000):
    conn = sqlite3.connect(f"file:{Path(db).resolve().as_posix()}?mode=ro", uri=True, timeout=30)
    try:
        hi = conn.execute("SELECT MAX(decision_ts) FROM strategy_decisions").fetchone()[0]
        if hi is None:
            return [], {}
        rows = conn.execute(
            "SELECT d.decision_id,d.decision_ts,d.ticker,d.seconds_to_close,"
            "s.yes_bid_cents,s.yes_ask_cents,s.no_bid_cents,s.no_ask_cents,"
            "s.book_is_executable,s.book_is_crossed,s.book_age_ms "
            "FROM strategy_decisions d JOIN strategy_decision_snapshots s USING(decision_id) "
            "WHERE d.decision_ts>=? AND d.record_source='live' ORDER BY d.decision_ts LIMIT ?",
            (hi - days * 86400, limit + 1),
        ).fetchall()
        if len(rows) > limit:
            raise ValueError("Comparison row limit exceeded; use a smaller --days window")
        books = defaultdict(dict)
        candidates = []
        for did, ts, ticker, tte, yb, ya, nb, na, executable, crossed, age in rows:
            if not executable or crossed or age is None or age < 0 or age > 3000:
                continue
            for side, bid, ask in (("yes", yb, ya), ("no", nb, na)):
                if bid is not None and ask is not None and 0 < bid <= ask < 100:
                    books[(ticker, side)][ts] = (ts, float(bid), float(ask))
            if not did.endswith(":taker"):
                continue
            for side, px, edge, required in conn.execute(
                "SELECT side,executable_entry_price_cents,expected_net_ev_cents,required_edge_cents "
                "FROM strategy_decision_side_ev WHERE decision_id=? AND executable=1 "
                "AND policy_eligible=1 AND model_evaluated=1", (did,),
            ):
                if side not in ("yes", "no") or any(v is None or not math.isfinite(v) for v in (px, edge, required, tte)):
                    continue
                if edge >= max(0, required) and 0 < px < 100:
                    candidates.append({"ts": ts, "ticker": ticker, "side": side, "price": px,
                                       "edge": edge, "required": required, "tte": tte})
        return candidates, {key: sorted(quotes.values()) for key, quotes in books.items()}
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/decision_audit.db")
    parser.add_argument("--days", type=float, default=0.1)
    parser.add_argument("--latency-s", type=float, default=21)
    parser.add_argument("--snapshot", help="Backup-copy the live audit DB first; never open the live DB read-only during comparison")
    args = parser.parse_args()
    if not math.isfinite(args.days) or args.days <= 0 or not math.isfinite(args.latency_s) or args.latency_s < 0:
        parser.error("days must be positive and latency must be nonnegative")
    from scripts.window_funnel_report import _snapshot
    db = _snapshot(args.db) if args.snapshot else args.db
    candidates, books = load_data(db, args.days)
    print(json.dumps({
        "interpretation": "Quote-path upper bounds, NOT fills, account P&L, or promotion evidence. Taker fees on both legs; full displayed fills assumed without queue/depth or impact modeling. Model refresh, basket and other live vetoes are NOT replayed. Missing quote paths excluded. Budgets are cumulative and not recycled within a window.",
        "eligible_taker_evaluations": len(candidates), "latency_s": args.latency_s,
        "comparison": compare(candidates, books, latency_s=args.latency_s),
    }, indent=2))
    if args.snapshot:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(db + suffix)
            except OSError:
                pass


if __name__ == "__main__":
    main()
