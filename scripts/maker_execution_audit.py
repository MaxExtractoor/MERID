#!/usr/bin/env python3
"""Actual-order maker execution audit (independent research track).

Question: does the incumbent probability advantage survive conditioning on
ACTUAL maker fills?  Uses only existing order records — no new orders, no
simulator.  Read-only (mode=ro) on all databases.

Cohort: order_attempts entries with
    entry_or_exit='entry' AND
    admitting_economics.resolved_execution_mode='maker'

Per attempt reconstructs: side/limit/count, incumbent calibrated probs at
submission (admitting_economics), status lifecycle, fills (kalshi_fills by
client_order_id), settlement outcome (decision_audit settled_yes), fees,
realized net payoff per filled contract, and RTI reference movement at
fixed post-fill horizons (adverse-selection proxy; book-quote movement is
unavailable for most of the window — book archive was down).

Outputs: analysis/maker_audit_<date>/audit.json + report.md
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "analysis" / "maker_audit_2026-11-13"
ATTEMPTS_DB = ROOT / "data" / "kalshi_order_attempts.db"
FILLS_DB = ROOT / "data" / "kalshi_fills.db"
AUDIT_DB = ROOT / "data" / "decision_audit.db"
RTI_DB = ROOT / "data" / "cf_rti_ticks.db"
EPS = 1e-6
HORIZONS_S = (30, 60, 300)


def ro(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)


def iso_to_ts(s):
    if s is None:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def logit(p):
    p = min(1 - EPS, max(EPS, float(p)))
    return math.log(p / (1 - p))


def wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p = k / n
    den = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - h) / den), min(1.0, (c + h) / den))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    con = ro(ATTEMPTS_DB)
    attempts = []
    for (aid, coid, did, status, created, updated, pj) in con.execute(
        """select order_attempt_id, client_order_id, decision_id, status,
                  created_at, updated_at, payload_json
           from order_attempts
           where json_extract(payload_json,'$.entry_or_exit')='entry'
             and json_extract(payload_json,
                 '$.admitting_economics.resolved_execution_mode')='maker'"""
    ):
        try:
            p = json.loads(pj)
        except Exception:
            continue
        o = p.get("order") or {}
        ae = p.get("admitting_economics") or {}
        side = (o.get("side") or "")
        side = "yes" if "yes" in side else ("no" if "no" in side else None)
        attempts.append({
            "attempt_id": aid,
            "client_order_id": coid,
            "decision_id": did,
            "status": status,
            "created_at": float(created),
            "updated_at": float(updated) if updated else None,
            "ticker": o.get("ticker"),
            "side": side,
            "action": o.get("action"),
            "limit_px": (o.get("price_cents") or 0) / 100.0,
            "count_fp": float(o.get("count_fp") or 0),
            "post_only": bool(o.get("post_only", ae.get("post_only"))),
            "tif": o.get("tif") or ae.get("time_in_force"),
            "decision_lane": o.get("decision_lane") or ae.get("admitting_lane"),
            "admitting_lane": ae.get("admitting_lane"),
            "admitting_route": ae.get("admitting_route"),
            "regime": ae.get("directional_regime"),
            "p_yes_cal": ae.get("p_yes_calibrated"),
            "p_no_cal": ae.get("p_no_calibrated"),
            "p_selected": ae.get("selected_probability"),
            "entry_price_cents": ae.get("entry_price_cents"),
            "tte_s": ae.get("time_to_expiry_seconds"),
            "ev_net_c": ae.get("candidate_ev_net_cents_per_contract"),
            "min_edge": ae.get("min_required_edge"),
            "cell": ae.get("threshold_cell_id") or ae.get("provisional_cell_id"),
            "policy_epoch": ae.get("policy_epoch"),
            "degraded": bool(ae.get("degraded_mode")),
            "asset": (o.get("ticker") or "").split("-")[0]
                     .replace("KX", "").replace("15M", ""),
        })
    con.close()
    print(f"maker entry attempts: {len(attempts)}")

    # ---- fills ----
    fcon = ro(FILLS_DB)
    fills_by_coid = defaultdict(list)
    fills_by_oid = defaultdict(list)
    for (coid, oid, tk, side, action, qty_cc, px, fee, cts, role, eo) in fcon.execute(
        """select client_order_id, order_id, market_ticker, side, action,
                  quantity_cc, execution_price_cents, fee_cost, created_time,
                  liquidity_role, entry_or_exit
           from kalshi_fills where entry_or_exit='entry'"""
    ):
        ts = iso_to_ts(cts)
        rec = {"order_id": oid, "ticker": tk, "side": side, "action": action,
               "qty_cc": qty_cc or 0, "px": (px or 0) / 100.0,
               "fee_usd": float(fee or 0), "ts": ts, "role": role}
        if coid:
            fills_by_coid[coid].append(rec)
        if oid:
            fills_by_oid[oid].append(rec)
    fcon.close()
    print(f"entry fills loaded: {sum(len(v) for v in fills_by_coid.values())} "
          f"coids={len(fills_by_coid)}")

    # ---- settlement outcomes via decision audit ----
    # Fast path: order_attempts.decision_id IS the strategy decision id
    # (candidate:route) — look up outcomes directly by decision_id (PK
    # index).  Ticker fallback covers attempts whose decision row lacks an
    # outcome record.
    outcomes_by_did = {}
    outcomes = {}
    dids = sorted({a["decision_id"] for a in attempts if a["decision_id"]})
    tickers = sorted({a["ticker"] for a in attempts if a["ticker"]})
    try:
        acon = ro(AUDIT_DB)
        for i in range(0, len(dids), 200):
            chunk = dids[i:i + 200]
            ph = ",".join("?" * len(chunk))
            for did, sy in acon.execute(
                f"""select decision_id, settled_yes
                    from strategy_decision_outcomes
                    where decision_id in ({ph})
                      and settled_yes is not null""", chunk):
                outcomes_by_did[did] = int(sy)
        print(f"[outcomes] direct decision_id hits: {len(outcomes_by_did)}")
        # ticker fallback for misses, time-bounded
        miss_tickers = sorted({a["ticker"] for a in attempts
                               if a["decision_id"] not in outcomes_by_did
                               and a["ticker"]})
        if miss_tickers:
            t0 = min(a["created_at"] for a in attempts) - 86400
            t1 = max(a["created_at"] for a in attempts) + 86400
            for i in range(0, len(miss_tickers), 50):
                chunk = miss_tickers[i:i + 50]
                ph = ",".join("?" * len(chunk))
                for tk, sy in acon.execute(
                    f"""select d.ticker, o.settled_yes
                        from strategy_decisions d
                        join strategy_decision_outcomes o using(decision_id)
                        where d.decision_ts between ? and ?
                          and d.ticker in ({ph})
                          and o.settled_yes is not null
                        group by d.ticker""", (t0, t1, *chunk)):
                    outcomes[tk] = int(sy)
        acon.close()
    except Exception as exc:
        print(f"[warn] outcome join failed: {exc}")
    # Archive DBs hold pre-rotation decisions (active DB covers ~Nov 12+).
    # Resolve remaining tickers there, time-bounded.
    still_missing = {a["ticker"] for a in attempts
                     if a.get("_settled_yes") is None and a["ticker"]}
    if still_missing:
        t0 = min(a["created_at"] for a in attempts) - 86400
        t1 = max(a["created_at"] for a in attempts) + 86400
        for adb in sorted((ROOT / "data" / "archive").glob("decision_audit*.db")):
            if adb.suffix != ".db" or not still_missing:
                continue
            try:
                acon2 = ro(adb)
                tls = sorted(still_missing)
                for i in range(0, len(tls), 40):
                    chunk = tls[i:i + 40]
                    ph = ",".join("?" * len(chunk))
                    for tk, sy in acon2.execute(
                        f"""select d.ticker, o.settled_yes
                            from strategy_decisions d
                            join strategy_decision_outcomes o using(decision_id)
                            where d.decision_ts between ? and ?
                              and d.ticker in ({ph})
                              and o.settled_yes is not null
                            group by d.ticker""", (t0, t1, *chunk)):
                        if tk not in outcomes:
                            outcomes[tk] = int(sy)
                            still_missing.discard(tk)
                acon2.close()
                print(f"[outcomes] {adb.name}: resolved "
                      f"{len(outcomes)} tickers total, "
                      f"{len(still_missing)} still missing")
            except Exception as exc:
                print(f"[warn] archive {adb.name}: {exc}")
    # resolve per-attempt outcome
    for a in attempts:
        a["_settled_yes"] = outcomes_by_did.get(a["decision_id"],
                                              outcomes.get(a["ticker"]))
    print(f"outcomes resolved: "
          f"{sum(1 for a in attempts if a['_settled_yes'] is not None)}"
          f"/{len(attempts)} attempts "
          f"({len(outcomes_by_did)} did + {len(outcomes)} ticker)")

    # ---- RTI reference series for post-fill movement ----
    rcon = None
    rti = defaultdict(list)  # asset -> [(ts_s, value)]
    try:
        rcon = ro(RTI_DB)
        assets = sorted({a["asset"] for a in attempts if a["asset"]})
        lo = min(a["created_at"] for a in attempts) - 60
        hi = max((a["updated_at"] or a["created_at"]) for a in attempts) + 400
        for asset in assets:
            for ts_ms, val in rcon.execute(
                """select src_ts_ms, value from rti_ticks
                   where asset=? and src_ts_ms between ? and ?
                   order by src_ts_ms""",
                (asset, int(lo * 1000), int(hi * 1000))):
                if val is not None:
                    rti[asset].append((ts_ms / 1000.0, float(val)))
        rcon.close()
    except Exception as exc:
        print(f"[warn] rti load failed: {exc}")
        if rcon:
            try:
                rcon.close()
            except Exception:
                pass
    print({k: len(v) for k, v in rti.items()})

    def rti_at(asset, ts_s):
        arr = rti.get(asset) or []
        if not arr:
            return None
        # latest tick at or before ts_s (causal)
        lo_i, hi_i = 0, len(arr)
        while lo_i < hi_i:
            mid = (lo_i + hi_i) // 2
            if arr[mid][0] <= ts_s:
                lo_i = mid + 1
            else:
                hi_i = mid
        i = lo_i - 1
        if i < 0 or ts_s - arr[i][0] > 10:
            return None
        return arr[i][1]

    # ---- per-attempt records ----
    recs = []
    for a in attempts:
        fills = list(fills_by_coid.get(a["client_order_id"], []))
        # also try order_id join if payload recorded it
        if not fills:
            for f in fills_by_oid.values():
                pass  # order_id unknown pre-fill; skip
        fills.sort(key=lambda f: f["ts"] or 0)
        qty_cc = sum(f["qty_cc"] for f in fills)
        ordered_cc = int(round(a["count_fp"] * 100)) if a["count_fp"] else 0
        notional = sum(f["qty_cc"] * f["px"] for f in fills)
        vwap = (notional / qty_cc) if qty_cc else None
        fee_usd = sum(f["fee_usd"] for f in fills)
        fee_c_per_contract = (fee_usd * 100.0 / (qty_cc / 100.0)) if qty_cc else 0.0
        first_ts = fills[0]["ts"] if fills else None
        last_ts = fills[-1]["ts"] if fills else None
        settled_yes = a.get("_settled_yes")
        won = None
        payoff_c = None
        if settled_yes is not None and a["side"] in ("yes", "no") and qty_cc:
            side_won = (settled_yes == 1) if a["side"] == "yes" else (settled_yes == 0)
            won = bool(side_won)
            # payoff per contract in cents: win -> 100 - entry_px*100... px is
            # dollars fraction of $1; price_cents = px*100. Entry cost cents =
            # limit/fill px in cents. Use VWAP fill px.
            entry_c = (vwap or a["limit_px"]) * 100.0
            payoff_c = ((100.0 if won else 0.0) - entry_c
                        - fee_c_per_contract)
        # post-fill RTI movement (adverse selection proxy)
        moves = {}
        if first_ts and a["asset"] in rti:
            base = rti_at(a["asset"], first_ts)
            if base:
                for h in HORIZONS_S:
                    v = rti_at(a["asset"], first_ts + h)
                    if v is not None and base:
                        moves[f"rti_chg_{h}s_bp"] = round(
                            (v - base) / base * 1e4, 3)
        recs.append({**a, "n_fills": len(fills), "filled_qty_cc": qty_cc,
                     "ordered_qty_cc": ordered_cc,
                     "vwap_px": vwap, "fee_usd": fee_usd,
                     "fee_c_per_contract": fee_c_per_contract,
                     "first_fill_ts": first_ts, "last_fill_ts": last_ts,
                     "ttf_s": (first_ts - a["created_at"])
                     if first_ts else None,
                     "rested_s": (last_ts - a["created_at"])
                     if last_ts else None,
                     "settled_yes": settled_yes, "won": won,
                     "payoff_c_per_contract": payoff_c,
                     "rti_post_fill": moves})

    # ---- aggregates ----
    def band(px):
        if px is None:
            return "unknown"
        c = px * 100
        for lo, hi, name in ((0, 50, "0-49"), (50, 80, "50-79"),
                             (80, 90, "80-89"), (90, 95, "90-94"),
                             (95, 101, "95+")):
            if lo <= c < hi:
                return name
        return ">=100"

    live = [r for r in recs if r["status"] in
            ("ACKNOWLEDGED", "CANCELED", "FILLED", "SUBMISSION_UNKNOWN")]
    rejected = [r for r in recs if r["status"] == "REJECTED"]
    filled_any = [r for r in live if r["filled_qty_cc"] > 0]
    full = [r for r in live if r["ordered_qty_cc"]
            and r["filled_qty_cc"] >= r["ordered_qty_cc"]]
    partial = [r for r in live if 0 < r["filled_qty_cc"]
               < (r["ordered_qty_cc"] or 1)]
    unfilled = [r for r in live if r["filled_qty_cc"] == 0]

    def agg(rows, keyfn=None):
        out = []
        groups = defaultdict(list)
        for r in rows:
            groups[keyfn(r) if keyfn else "all"].append(r)
        for k, rs in sorted(groups.items(), key=lambda x: str(x[0])):
            n = len(rs)
            fr = sum(1 for r in rs if r["filled_qty_cc"] > 0) / n if n else 0
            fw = [r for r in rs if r["won"] is not None]
            wr = (sum(1 for r in fw if r["won"]) / len(fw)) if fw else None
            lo_, hi_ = wilson(sum(1 for r in fw if r["won"]), len(fw)) \
                if fw else (None, None)
            pay = [r["payoff_c_per_contract"] for r in rs
                   if r["payoff_c_per_contract"] is not None]
            mp = [r["p_selected"] for r in rs if r["p_selected"] is not None]
            out.append({
                "key": k, "n": n,
                "fill_any_rate": round(fr, 4),
                "win_rate": round(wr, 4) if wr is not None else None,
                "win_ci95": [round(lo_, 4), round(hi_, 4)]
                if lo_ is not None else None,
                "mean_p_selected": round(sum(mp) / len(mp), 4) if mp else None,
                "mean_payoff_c": round(sum(pay) / len(pay), 3)
                if pay else None,
                "total_payoff_c": round(sum(pay), 1) if pay else None,
            })
        return out

    report = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "cohort": "entry + resolved_execution_mode=maker",
        "n_attempts": len(attempts),
        "status_counts": {s: sum(1 for r in recs if r["status"] == s)
                          for s in sorted({r["status"] for r in recs})},
        "live_attempts": len(live),
        "rejected_attempts": len(rejected),
        "filled_any": len(filled_any),
        "full_fills": len(full),
        "partial_fills": len(partial),
        "unfilled": len(unfilled),
        "fill_rate_any": round(len(filled_any) / len(live), 4)
        if live else None,
        "fill_rate_full": round(len(full) / len(live), 4) if live else None,
        "outcomes_covered": len(outcomes),
        "by_side": agg(live, lambda r: r["side"]),
        "by_price_band": agg(live, lambda r: band(r["limit_px"])),
        "by_asset": agg(live, lambda r: r["asset"]),
        "by_lane": agg(live, lambda r: r["decision_lane"]),
        "by_p_selected_bucket": agg(
            live, lambda r: ("<0.90", "0.90-0.94", ">=0.95")
            [0 if (r["p_selected"] or 0) < 0.90
             else (1 if (r["p_selected"] or 0) < 0.95 else 2)]),
        "by_tte_bucket": agg(
            live, lambda r: ("<120s", "120-600s", ">=600s")
            [0 if (r["tte_s"] or 0) < 120
             else (1 if (r["tte_s"] or 0) < 600 else 2)]),
        "filled_only": {
            "n": len(filled_any),
            "win_rate": round(
                sum(1 for r in filled_any if r["won"]) /
                max(1, sum(1 for r in filled_any if r["won"] is not None)), 4),
            "mean_p_selected": round(
                sum(r["p_selected"] for r in filled_any
                    if r["p_selected"] is not None) /
                max(1, sum(1 for r in filled_any
                           if r["p_selected"] is not None)), 4),
            "mean_payoff_c": round(
                sum(r["payoff_c_per_contract"] for r in filled_any
                    if r["payoff_c_per_contract"] is not None) /
                max(1, sum(1 for r in filled_any
                           if r["payoff_c_per_contract"] is not None)), 3),
            "total_payoff_c": round(sum(
                r["payoff_c_per_contract"] * (r["filled_qty_cc"] / 100.0)
                for r in filled_any
                if r["payoff_c_per_contract"] is not None), 1),
        },
        "rti_post_fill_mean_bp": {},
        "limitations": [
            "book-quote post-fill movement unavailable: book archive was "
            "down for most of the cohort window (invalid intervals recorded "
            "in the lead-lag capture acceptance notes); RTI reference "
            "movement is the adverse-selection proxy used instead",
            "cancel request vs ack timing not separately persisted in "
            "order_attempts (status + updated_at only)",
            "quote state at submission not reconstructed (payload carries "
            "admitting economics, not book depth)",
        ],
    }
    # RTI post-fill aggregates (filled only)
    for h in HORIZONS_S:
        k = f"rti_chg_{h}s_bp"
        vals = [r["rti_post_fill"][k] for r in filled_any
                if k in r["rti_post_fill"]]
        if vals:
            report["rti_post_fill_mean_bp"][k] = {
                "n": len(vals), "mean": round(sum(vals) / len(vals), 3),
                "median": round(sorted(vals)[len(vals) // 2], 3)}

    (OUT / "audit.json").write_text(json.dumps(
        {"report": report, "attempts": recs}, indent=1, default=str))

    # ---- markdown ----
    md = ["# Maker execution audit — actual orders only", "",
          f"Generated: {report['generated_utc']}", "",
          f"Cohort: entry orders, `resolved_execution_mode=maker` "
          f"({report['n_attempts']} attempts, "
          f"{report['outcomes_covered']} markets with settled outcomes)", "",
          "## Headline", "",
          f"- Live attempts (excl. REJECTED): {report['live_attempts']}",
          f"- Any fill: {report['filled_any']} "
          f"({report['fill_rate_any']:.1%} of live)",
          f"- Full fill: {report['full_fills']} "
          f"({report['fill_rate_full']:.1%})",
          f"- Partial: {report['partial_fills']}  Unfilled: {report['unfilled']}",
          f"- Filled-cohort win rate: "
          f"{report['filled_only']['win_rate']:.1%} vs mean p_selected "
          f"{report['filled_only']['mean_p_selected']:.3f}",
          f"- Mean net payoff per filled contract: "
          f"{report['filled_only']['mean_payoff_c']:.2f}c  "
          f"(total {report['filled_only']['total_payoff_c']:.1f}c)", "",
          "## Fill rate by segment", "",
          "| segment | n | fill_any | win_rate | mean_p | payoff_c |",
          "|---|---|---|---|---|---|"]
    for sec in ("by_side", "by_price_band", "by_asset", "by_lane",
                "by_p_selected_bucket", "by_tte_bucket"):
        for row in report[sec]:
            md.append(
                f"| {sec}:{row['key']} | {row['n']} | "
                f"{row['fill_any_rate']:.1%} | "
                f"{(row['win_rate'] if row['win_rate'] is not None else float('nan')):.1%} | "
                f"{(row['mean_p_selected'] if row['mean_p_selected'] is not None else float('nan')):.3f} | "
                f"{(row['mean_payoff_c'] if row['mean_payoff_c'] is not None else float('nan')):.2f} |")
    md += ["", "## Post-fill RTI reference movement (filled cohort)", ""]
    for k, v in report["rti_post_fill_mean_bp"].items():
        md.append(f"- {k}: mean {v['mean']:+.1f}bp median {v['median']:+.1f}bp "
                  f"(n={v['n']})")
    md += ["", "## Limitations", ""]
    md += [f"- {x}" for x in report["limitations"]]
    (OUT / "report.md").write_text("\n".join(md))
    print(f"[done] {OUT}/audit.json + report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
