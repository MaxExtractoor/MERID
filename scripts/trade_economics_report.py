"""Complete trade-economics report: pairs entry fills -> exit fills ->
settlement residuals per position episode, attributed to admission lane.

Replaces the settlement-only view: scalp exits (TP/SL/trail/stop_candidate/
settlement_guard) are included, so lane expectancy reflects ALL realized
cash, not just held-to-expiry positions.

Cash model (verified against raw fill payloads):
  net_cash = SUM(proceeds_dollars) - SUM(fee_cost) + settlement_payout
  proceeds_dollars is signed exchange cash (negative = debit) at actual
  average fill price; fee_cost is the actual charged fee in dollars.
  Position tracked in canonical_yes_delta_cc; settlement pays $1/contract
  to the winning side on the residual.

Read-only against data/trade_attribution_fact.db.

Usage: .venv/Scripts/python.exe scripts/trade_economics_report.py [--jsonl out.jsonl]
"""
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone

DB = "data/trade_attribution_fact.db"
ASSET_PREFIX = {
    "KXBTC15M": "BTC", "KXETH15M": "ETH", "KXSOL15M": "SOL",
    "KXXRP15M": "XRP", "KXDOGE15M": "DOGE",
}
TRUSTED = "TRUSTED_LIVE_V1"


def _asset(ticker: str) -> str:
    for p, a in ASSET_PREFIX.items():
        if (ticker or "").startswith(p):
            return a
    return "?"


def _ts(s: str) -> float:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def main() -> None:
    jsonl_path = None
    if "--jsonl" in sys.argv:
        jsonl_path = sys.argv[sys.argv.index("--jsonl") + 1]
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

    # ---- orders: intent_id -> lane/deploy ; client_order_id -> exit reason ----
    intent_lane, coid_reason = {}, {}
    intent_deploy = {}
    for intent_id, client_order_id, meta in con.execute(
        "SELECT intent_id, client_order_id, metadata FROM trade_attribution_fact "
        "WHERE event_type='order'"
    ):
        try:
            outer = json.loads(meta or "{}")
            inner = outer.get("metadata") or outer
        except Exception:
            continue
        lane = inner.get("decision_lane")
        if intent_id and lane:
            intent_lane[intent_id] = lane
        run_id = inner.get("run_id") or outer.get("run_id")
        if intent_id and run_id:
            intent_deploy[intent_id] = str(run_id)
        reason = inner.get("reason") or inner.get("source")
        if client_order_id and reason:
            coid_reason[client_order_id] = str(reason)

    # ---- settlements: ticker -> outcome ----
    settlements = {}
    for ticker, outcome, px, ts in con.execute(
        "SELECT ticker, settlement_outcome, settlement_price_cents, event_ts "
        "FROM trade_attribution_fact WHERE event_type='settlement'"
    ):
        settlements[ticker] = (outcome, px, _ts(ts))

    # ---- fills -> per-ticker chronological series ----
    fills_by_ticker = defaultdict(list)
    skipped = defaultdict(int)
    for meta, ets in con.execute(
        "SELECT metadata, event_ts FROM trade_attribution_fact WHERE event_type='fill'"
    ):
        try:
            d = json.loads(meta or "{}")
        except Exception:
            skipped["bad_json"] += 1
            continue
        if d.get("is_live") is False:
            skipped["not_live"] += 1
            continue
        if d.get("canonicalization_state") != TRUSTED:
            skipped["untrusted"] += 1
            continue
        ticker = d.get("market_ticker") or d.get("market_id")
        if not ticker:
            skipped["no_ticker"] += 1
            continue
        try:
            delta_cc = int(d.get("canonical_yes_delta_cc") or 0)
            proceeds = float(d.get("proceeds_dollars") or 0.0)
            fee = float(d.get("fee_cost") or 0.0)
            qty = float(d.get("count_fp") or 0.0)
        except Exception:
            skipped["bad_numbers"] += 1
            continue
        if delta_cc == 0:
            skipped["zero_delta"] += 1
            continue
        fills_by_ticker[ticker].append({
            "ts": _ts(d.get("created_time") or ets),
            "ets": ets,
            "delta_cc": delta_cc,
            "proceeds": proceeds,
            "fee": fee,
            "qty": qty,
            "eo": d.get("entry_or_exit"),
            "econ": d.get("economic_side"),
            "exec_px": d.get("execution_price_cents"),
            "leg_px": d.get("canonical_leg_price_cents"),
            "intent": d.get("intent_id"),
            "coid": d.get("client_order_id"),
            "agent": d.get("agent_id"),
            "fill_id": d.get("fill_id"),
            "exec_mode": d.get("entry_execution_mode"),
            "config_hash": (d.get("config_hash") or "")[:12] or None,
            "liq_role": d.get("liquidity_role"),
        })

    # ---- build episodes: accumulate yes-delta; close at zero crossing ----
    # An episode starts from flat (first fill must be an entry), ends when
    # cumulative delta returns to ~0.  A sign flip closes the episode and
    # the flipping fill opens the next (its full size is attributed to the
    # new episode — overshoot slivers are negligible at this granularity).
    episodes = []
    for ticker, fl in fills_by_ticker.items():
        fl.sort(key=lambda f: f["ts"])
        pos_cc = 0
        ep = None
        for f in fl:
            new_cc = pos_cc + f["delta_cc"]
            flipping = pos_cc != 0 and (pos_cc > 0) != (new_cc > 0) and new_cc != 0
            if ep is None or flipping:
                if ep is not None:
                    episodes.append(ep)
                ep = {"ticker": ticker, "fills": [], "delta_cc": 0}
            ep["fills"].append(f)
            ep["delta_cc"] = new_cc
            pos_cc = new_cc
            if pos_cc == 0:
                episodes.append(ep)
                ep = None
        if ep is not None and ep["fills"]:
            episodes.append(ep)  # residual -> settlement handles

    # ---- settle residuals & compute economics ----
    out_rows = []
    for ep in episodes:
        ticker = ep["ticker"]
        resid_cc = ep["delta_cc"]
        # Episode direction = sign of the first fill's delta (episodes
        # start from flat, so the first fill is necessarily an entry).
        direction = 1 if ep["fills"][0]["delta_cc"] > 0 else -1
        entries = [f for f in ep["fills"] if (f["delta_cc"] > 0) == (direction > 0)]
        exits = [f for f in ep["fills"] if f not in entries]

        proceeds = sum(f["proceeds"] for f in ep["fills"])
        fees = sum(f["fee"] for f in ep["fills"])
        qty_contracts = sum(abs(f["delta_cc"]) for f in entries) / 100.0

        # settlement residual payout
        settle_payout = 0.0
        settle_outcome = None
        st = settlements.get(ticker)
        last_ts = max(f["ts"] for f in ep["fills"])
        if resid_cc != 0 and st:
            outcome, _px, sts = st
            settle_outcome = outcome
            resid_contracts = abs(resid_cc) / 100.0
            won = (resid_cc > 0 and outcome == "yes") or (resid_cc < 0 and outcome == "no")
            if won:
                settle_payout = resid_contracts * 1.0
        elif resid_cc != 0:
            settle_outcome = "NO_SETTLEMENT_DATA"

        net_cents = (proceeds - fees + settle_payout) * 100.0

        # lane + deployment cohort from first entry intent/order
        lane = "external"
        deploy = None
        exec_modes = set()
        config_hashes = set()
        for f in entries:
            if f.get("exec_mode"):
                exec_modes.add(str(f["exec_mode"]))
            if f.get("config_hash"):
                config_hashes.add(f["config_hash"])
            if deploy is None:
                deploy = intent_deploy.get(f["intent"]) or intent_deploy.get(f["coid"])
            lane = intent_lane.get(f["intent"]) or intent_lane.get(f["coid"]) or lane
            if lane != "external":
                break
        if lane == "external" and entries:
            lane = "core" if entries[0]["intent"] else "external"
        # run_id embeds process start ts (YYYYMMDDHHMMSS_pid_rand) — cohort key
        deploy_cohort = (deploy or "unknown")[:15] if deploy else "unknown"
        exec_mode = "+".join(sorted(exec_modes)) if exec_modes else "unknown"

        # exit reason mix
        reasons = defaultdict(float)
        for f in exits:
            r = coid_reason.get(f["coid"]) or coid_reason.get(f["intent"]) or f["agent"] or "unknown"
            reasons[r] += abs(f["proceeds"])
        primary_reason = max(reasons.items(), key=lambda kv: kv[1])[0] if reasons else ("settlement" if resid_cc != 0 else "flat")

        side = "YES" if direction > 0 else "NO"
        # position-side VWAP: YES entries pay leg_px; NO entries (yes-leg
        # sells) pay 100-leg_px.  Exits receive the complement analogously.
        def _pos_px(f):
            leg = f["leg_px"] if f["leg_px"] is not None else f["exec_px"]
            if leg is None:
                return None
            return float(leg) if direction > 0 else 100.0 - float(leg)
        ep_px = [_pos_px(f) for f in entries if _pos_px(f) is not None]
        xp_px = [_pos_px(f) for f in exits if _pos_px(f) is not None]
        entry_vwap = sum(ep_px) / len(ep_px) if ep_px else None
        exit_vwap = sum(xp_px) / len(xp_px) if xp_px else None
        # entry cash committed (position-side cents) for return-on-capital
        entry_notional_c = (qty_contracts * entry_vwap) if entry_vwap is not None else None
        entry_ts = min(f["ts"] for f in entries) if entries else first["ts"]
        last_fill_ts = max(f["ts"] for f in ep["fills"])
        hold_s = (st[2] if (resid_cc != 0 and st) else last_fill_ts) - entry_ts

        out_rows.append({
            "ticker": ticker, "asset": _asset(ticker), "side": side, "lane": lane,
            "qty_contracts": round(qty_contracts, 2), "n_entries": len(entries),
            "n_exits": len(exits), "resid_contracts": round(abs(resid_cc) / 100.0, 2),
            "net_cents": round(net_cents, 2),
            "proceeds_c": round(proceeds * 100, 2), "fees_c": round(fees * 100, 2),
            "settle_payout_c": round(settle_payout * 100, 2),
            "settle_outcome": settle_outcome, "exit_reason": primary_reason,
            "hold_s": round(hold_s, 1), "entry_ts": entries[0]["ets"] if entries else first["ets"],
            "entry_vwap_c": round(entry_vwap, 1) if entry_vwap is not None else None,
            "exit_vwap_c": round(exit_vwap, 1) if exit_vwap is not None else None,
            "deploy_cohort": deploy_cohort, "exec_mode": exec_mode,
            "config_hash": sorted(config_hashes)[0] if config_hashes else None,
            "entry_notional_c": round(entry_notional_c, 1) if entry_notional_c is not None else None,
            "net_per_contract_c": round(net_cents / qty_contracts, 2) if qty_contracts else None,
            "return_on_entry_pct": round(100.0 * net_cents / entry_notional_c, 2)
            if entry_notional_c else None,
        })

    # ---- aggregate: deploy x lane x asset x side (version-aware) ----
    agg = defaultdict(lambda: [0, 0.0, 0, 0.0, 0.0])
    reason_agg = defaultdict(lambda: [0, 0.0])
    exec_agg = defaultdict(lambda: [0, 0.0])
    day_set = defaultdict(set)
    for r in out_rows:
        k = (r["deploy_cohort"], r["lane"], r["asset"], r["side"])
        a = agg[k]
        a[0] += 1
        a[1] += r["net_cents"]
        a[2] += 1 if r["net_cents"] > 0 else 0
        a[3] += r["hold_s"]
        a[4] += r["qty_contracts"]
        if r.get("entry_ts"):
            day_set[k].add(str(r["entry_ts"])[:10])
        ra = reason_agg[(r["lane"], r["exit_reason"])]
        ra[0] += 1
        ra[1] += r["net_cents"]
        ea = exec_agg[(r["side"], r["exec_mode"])]
        ea[0] += 1
        ea[1] += r["net_cents"]

    print(f"episodes={len(out_rows)} skipped={dict(skipped)}")
    print(f"\n{'deploy':16s} {'lane':22s} {'asset':5s} {'side':4s} {'n':>4s} {'qty':>7s} {'net_c':>9s} {'net/ct':>7s} {'ret%':>7s} {'win%':>6s} {'days':>4s}")
    print("-" * 110)
    for k in sorted(agg):
        n, net, wins, hold, qty = agg[k]
        sub = [r for r in out_rows if (r["deploy_cohort"], r["lane"], r["asset"], r["side"]) == k]
        npc = sum(r["net_cents"] for r in sub) / max(sum(r["qty_contracts"] for r in sub), 1e-9)
        notional = sum(r["entry_notional_c"] or 0 for r in sub)
        ret = 100.0 * net / notional if notional else 0.0
        print(f"{k[0]:16s} {k[1]:22s} {k[2]:5s} {k[3]:4s} {n:4d} {qty:7.1f} {net:9.1f} {npc:7.2f} {ret:6.2f}% {100*wins/n:5.1f}% {len(day_set[k]):4d}")

    print(f"\n{'side':4s} {'exec_mode':12s} {'n':>4s} {'net_c':>9s} {'avg_c':>7s}")
    print("-" * 40)
    for k in sorted(exec_agg):
        n, net = exec_agg[k]
        print(f"{k[0]:4s} {k[1]:12s} {n:4d} {net:9.1f} {net/n:7.2f}")

    print(f"\n{'lane':24s} {'exit_reason':38s} {'n':>4s} {'net_c':>9s} {'avg_c':>7s}")
    print("-" * 82)
    for k in sorted(reason_agg):
        n, net = reason_agg[k]
        print(f"{k[0]:24s} {k[1]:38s} {n:4d} {net:9.1f} {net/n:7.2f}")

    if jsonl_path:
        with open(jsonl_path, "w") as fh:
            for r in sorted(out_rows, key=lambda x: x["entry_ts"] or ""):
                fh.write(json.dumps(r) + "\n")
        print(f"\nwrote {len(out_rows)} episodes -> {jsonl_path}")
    con.close()


if __name__ == "__main__":
    main()
