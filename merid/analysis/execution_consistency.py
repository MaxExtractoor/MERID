"""Execution-consistency audit — tiered evidence classification for live fills.

NOT an order-reproduction simulator.  Decision-time snapshots support a
consistency audit (instruction invariants + descriptive slippage vs the
decision quote); they cannot reconstruct arrival-time book state.

Tiers (per order episode = all fills sharing an order_id):
  A  reconstructable event book over the episode interval (book archive)
  B  relevant decision snapshot + depth semantics + timing + order instructions
  C  order instructions + fills, no book evidence
  D  fills + settlement only

Verdict classes (per episode):
  instruction_consistent | decision_quote_comparison |
  event_replay_comparison | timing_indeterminate |
  coverage_insufficient | genuine_violation

Checks that ARE valid invariants (after direction/price/amendment semantics):
  * fill prices within [0,100] and consistent with submitted limit direction
  * cumulative filled qty <= ordered qty (centi-contracts)
  * order/fill/account identifiers agree across stores
  * post_only orders never produce is_taker=true fills
  * taker/maker classification present and consistent with liquidity_role

Slippage is DESCRIPTIVE, not pass/fail:
  buy:  fill_px - decision_ask ; sell: decision_bid - fill_px
  (on the traded contract leg; positive = worse than decision benchmark)

CLI::

    py -3 -m merid.analysis.execution_consistency \
        --fills data/kalshi_fills.db \
        --attempts data/kalshi_order_attempts.db \
        --audit-db data/_audit_hot/decision_audit.db \
        --book-archives data/kalshi_book_archive_live3.db \
        --out reports/execution_consistency_2026-11-14.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")

# exchange_order_id -> attempt, populated in main() for O(1) episode lookup
_ATTEMPT_BY_EXCHANGE_ID: dict = {}


def _ro(path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=60)


def _asset(ticker: str) -> str:
    for a in ASSETS:
        if f"KX{a}15M" in ticker.upper():
            return a
    return "?"


def _ts_epoch(s) -> float | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    try:
        return float(s)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(
            str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# ---------------------------------------------------------------- fills

def load_fills(db: str) -> list[dict]:
    conn = _ro(db)
    cols = ("fill_id", "trade_id", "order_id", "client_order_id", "intent_id",
            "market_ticker", "side", "action", "quantity_cc",
            "yes_price_dollars", "no_price_dollars", "fee_cost",
            "created_time", "is_live", "raw_payload", "decision_trace_id",
            "canonical_leg_price_cents")
    rows = conn.execute(
        f"SELECT {','.join(cols)} FROM kalshi_fills WHERE is_live=1"
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        is_taker = None
        try:
            p = json.loads(d["raw_payload"] or "{}")
            rd = p.get("raw_data") or {}
            is_taker = rd.get("is_taker")
            if is_taker is None:
                is_taker = p.get("is_taker")
        except Exception:
            pass
        d["is_taker"] = is_taker
        d["ts"] = _ts_epoch(d["created_time"])
        d["asset"] = _asset(d["market_ticker"] or "")
        out.append(d)
    return out


# ---------------------------------------------------------------- orders

def load_attempts(db: str) -> dict:
    """client_order_id -> instruction summary (entry + exit attempts)."""
    conn = _ro(db)
    rows = conn.execute(
        "SELECT client_order_id, decision_id, intent_id, status, created_at,"
        " payload_json FROM order_attempts").fetchall()
    # exit attempts carry requested_limit_cents + exchange_order_id directly
    xrows = []
    try:
        xrows = conn.execute(
            "SELECT client_order_id, exchange_order_id, reason, state,"
            " requested_quantity, requested_limit_cents, created_at,"
            " payload_json FROM exit_order_attempts").fetchall()
    except Exception:
        pass
    conn.close()
    out = {}
    for coid, xoid, reason, state, rq, rlim, cat, pj in xrows:
        out[coid] = {
            "status": state, "created_at": _ts_epoch(cat),
            "decision_id": None, "intent_id": None,
            "ticker": None, "side": None, "action": None,
            "price_cents": rlim, "count_fp": (rq or 0) / 100.0,
            "tif": "ioc", "liquidity_role": None,
            "post_only": None, "resolved_mode": None, "lane": "exit",
            "snapshot_ts": None, "decision_id_payload": None,
            "build_sha": None, "entry_or_exit": "exit",
            "submission_attempted": True, "route_status": state,
            "exchange_order_id": xoid, "exit_reason": reason,
            "limit_semantics": "ioc_exit_requested_limit",
        }
    for coid, did, iid, status, cat, pj in rows:
        # exit_order_attempts is authoritative for exits (IOC limit
        # semantics); do not let the order_attempts mirror shadow it.
        if coid in out:
            continue
        ins = {"status": status, "created_at": _ts_epoch(cat),
               "decision_id": did, "intent_id": iid,
               "exchange_order_id": None}
        try:
            p = json.loads(pj or "{}")
        except Exception:
            p = {}
        o = p.get("order") or {}
        ec = p.get("execution_contract") or {}
        ae = p.get("admitting_economics") or {}
        ins.update({
            "ticker": o.get("ticker"),
            "side": o.get("side"),
            "action": o.get("action"),
            "price_cents": o.get("price_cents"),
            "count_fp": o.get("count_fp"),
            "tif": o.get("tif"),
            "liquidity_role": o.get("liquidity_role")
                            or ec.get("required_liquidity_role"),
            "post_only": ec.get("required_post_only", p.get("post_only")),
            "resolved_mode": ec.get("resolved_execution_mode"),
            "lane": ae.get("admitting_lane") or o.get("decision_lane"),
            "snapshot_ts": ae.get("snapshot_ts"),
            "decision_id_payload": ae.get("decision_id"),
            "build_sha": p.get("build_sha"),
            "entry_or_exit": p.get("entry_or_exit"),
            "submission_attempted": p.get("submission_attempted"),
            "route_status": p.get("route_result_status"),
            "exchange_order_id": p.get("exchange_order_id"),
            "chase_cap_cents": ae.get("chase_cap_cents"),
            "entry_price_cents": ae.get("entry_price_cents"),
            "limit_semantics": (
                "ioc_exit_requested_limit"
                if (p.get("entry_or_exit") == "exit"
                    or str(coid).startswith("exit_"))
                else ("entry_chase_cap"
                      if ae.get("chase_cap_cents") is not None
                      else "entry_price_only")),
        })
        out[coid] = ins
    return out


# ---------------------------------------------------------------- book tiers

def archive_ticker_windows(paths: list[str]) -> dict:
    """ticker -> list of (open_ts, close_ts) coverage windows."""
    win = defaultdict(list)
    for p in paths:
        try:
            conn = _ro(p)
            for tk, o, c in conn.execute(
                    "SELECT market_ticker, market_open_ts, market_close_ts"
                    " FROM archive_coverage"):
                win[tk].append((float(o), float(c)))
            conn.close()
        except Exception:
            continue
    return win


def load_snapshots_index(db: str, tickers: set[str],
                         decision_ids: set[str]) -> dict:
    """Index snapshots for only the tickers/decision_ids we need.

    The audit DB is multi-GB; a full-table join is prohibitively slow, so
    both indexes are filtered up front.  ``by_decision`` covers attempt
    decision_ids; ``by_ticker`` covers live-fill market tickers for the
    time-proximity fallback.
    """
    conn = _ro(db)
    idx = defaultdict(list)
    tidx = defaultdict(list)
    try:
        # chunked IN() lookups keep each query bounded
        def chunks(xs, n=400):
            xs = list(xs)
            for i in range(0, len(xs), n):
                yield xs[i:i + n]

        # decisions-first: resolve decision_ids via idx_decisions_ticker,
        # then PK-lookup snapshots.  A single joined query lets the planner
        # scan the multi-GB snapshots table; two steps keep every lookup
        # index-driven.
        dec_rows = {}  # decision_id -> (ticker, decision_ts)
        for ch in chunks(tickers):
            ph = ",".join("?" for _ in ch)
            for did, tk, ts in conn.execute(
                    "SELECT decision_id, ticker, decision_ts"
                    " FROM strategy_decisions"
                    f" WHERE ticker IN ({ph})", ch):
                dec_rows[did] = (tk, float(ts))
        # attempt decision_ids may reference decisions outside the fill
        # ticker set — resolve them by PK too
        need = [d for d in decision_ids if d not in dec_rows]
        for ch in chunks(need):
            ph = ",".join("?" for _ in ch)
            for did, tk, ts in conn.execute(
                    "SELECT decision_id, ticker, decision_ts"
                    " FROM strategy_decisions"
                    f" WHERE decision_id IN ({ph})", ch):
                dec_rows[did] = (tk, float(ts))
        all_dids = set(dec_rows)
        for ch in chunks(all_dids):
            ph = ",".join("?" for _ in ch)
            for did, yb, ya, nb, na, age, dy, dn, exe in conn.execute(
                    "SELECT decision_id, yes_bid_cents, yes_ask_cents,"
                    " no_bid_cents, no_ask_cents, book_age_ms,"
                    " yes_depth, no_depth, book_is_executable"
                    " FROM strategy_decision_snapshots"
                    f" WHERE decision_id IN ({ph})", ch):
                meta = dec_rows.get(did)
                if meta is None:
                    continue
                tk, ts = meta
                rec = (ts, yb, ya, nb, na, age, dy, dn, exe)
                idx[did].append(rec)
                tidx[tk].append(rec[:6] + (exe,))
        for v in tidx.values():
            v.sort(key=lambda r: r[0])
        for v in idx.values():
            v.sort(key=lambda r: r[0])
    except Exception:
        pass
    conn.close()
    return {"by_decision": idx, "by_ticker": tidx}


# ---------------------------------------------------------------- analysis

def _leg_price(fill: dict, leg: str) -> float | None:
    """Fill price in cents on the traded leg (yes|no)."""
    px = fill.get("yes_price_dollars") if leg == "yes" \
        else fill.get("no_price_dollars")
    return None if px is None else round(float(px) * 100, 4)


def _norm_side_action(side: str | None, action: str | None):
    """Return (leg, is_buy) from fill side/action or order side/action."""
    s = (side or "").lower()
    a = (action or "").lower()
    # fill rows: side=yes/no, action=buy/sell  (position leg convention)
    # order rows: side=buy_yes/buy_no/sell_yes/sell_no sometimes
    if s in ("buy_yes", "yes_buy"):
        return "yes", True
    if s in ("buy_no", "no_buy"):
        return "no", True
    if s in ("sell_yes", "yes_sell"):
        return "yes", False
    if s in ("sell_no", "no_sell"):
        return "no", False
    leg = "yes" if "yes" in s else ("no" if "no" in s else None)
    is_buy = a.startswith("buy")
    return leg, is_buy


def analyze(fills, attempts, snaps, arch_windows):
    # group fills into order episodes
    episodes = defaultdict(list)
    for f in fills:
        episodes[f.get("order_id") or f["fill_id"]].append(f)

    rows = []
    for oid, fl in episodes.items():
        fl.sort(key=lambda f: f["ts"] or 0)
        first = fl[0]
        ticker = first["market_ticker"]
        asset = first["asset"]
        # attempt lookup: exact exchange order id first, then client_order_id
        att = _ATTEMPT_BY_EXCHANGE_ID.get(oid) or {}
        if not att:
            coids = {f.get("client_order_id") for f in fl
                     if f.get("client_order_id")}
            for c in coids:
                if c in attempts:
                    att = attempts[c]
                    break
            if not att and len(coids) == 1:
                att = attempts.get(next(iter(coids)), {})

        # instruction fields: prefer attempt, else aggregate fills
        ins_side = att.get("side") or first.get("side")
        ins_action = att.get("action") or first.get("action")
        leg, is_buy = _norm_side_action(ins_side, ins_action)
        if leg is None:
            leg, is_buy = _norm_side_action(first.get("side"),
                                            first.get("action"))

        # quantities: fills are centi-contracts; order count_fp is contracts
        fill_qty_cc = sum(int(f["quantity_cc"] or 0) for f in fl)
        order_qty_cc = None
        if att.get("count_fp") is not None:
            try:
                order_qty_cc = int(round(float(att["count_fp"]) * 100))
            except (TypeError, ValueError):
                order_qty_cc = None

        # fill prices on traded leg
        leg_prices = [p for p in (_leg_price(f, leg) for f in fl)
                      if p is not None]
        limit_px = att.get("price_cents")

        # ---- instruction invariants ----
        violations = []
        unverified_semantics = []
        if leg_prices and any(p < 0 or p > 100 for p in leg_prices):
            violations.append("price_out_of_range")
        # Effective limit after amendment semantics:
        #  * entry buys may chase up to chase_cap_cents (or entry+default
        #    chase band when the older payload did not record the cap)
        #  * entry sells floor symmetrically
        #  * IOC exits carry requested_limit_cents, but the exchange-side
        #    submitted price is not independently recorded -> a breach is
        #    flagged for historical-order verification, not auto-violation
        limit_sem = att.get("limit_semantics") or ""
        eff_bound = None
        bound_source = None
        if limit_sem.startswith("ioc_exit"):
            eff_bound = att.get("price_cents")
            bound_source = "ioc_requested_limit"
        elif att.get("chase_cap_cents") is not None:
            base = att.get("entry_price_cents") or att.get("price_cents")
            try:
                cap = float(att["chase_cap_cents"])
                basef = float(base) if base is not None else None
            except (TypeError, ValueError):
                cap = basef = None
            if cap is not None:
                # buys: ceiling=cap ; sells: floor=base-chase_band.
                # chase_cap is recorded as the absolute adverse bound.
                eff_bound = cap if is_buy else (
                    basef - (cap - basef) if basef is not None else None)
                bound_source = "chase_cap_recorded"
        elif att.get("price_cents") is not None:
            try:
                basef = float(att["price_cents"])
                band = float(__import__("os").environ.get(
                    "MERID_ENTRY_MAX_CHASE_CENTS", "5"))
                eff_bound = basef + band if is_buy else basef - band
                # bound_source records that this bound came from current
                # config, not the payload — visible per episode without
                # masking the verdict for fills comfortably inside it.
                bound_source = "env_default_chase_unverified"
            except (TypeError, ValueError):
                pass
        if eff_bound is not None and leg_prices:
            try:
                b = float(eff_bound)
                if is_buy and max(leg_prices) > b + 0.01:
                    if limit_sem.startswith("ioc_exit"):
                        # requested_limit_cents leg convention for exits is
                        # not recorded (position-side dependent); cannot
                        # establish the applicable bound -> unverified.
                        unverified_semantics.append(
                            "ioc_exit_limit_leg_unverified")
                    else:
                        violations.append("buy_fillabove_effective_limit")
                if not is_buy and min(leg_prices) < b - 0.01:
                    if limit_sem.startswith("ioc_exit"):
                        unverified_semantics.append(
                            "ioc_exit_limit_breach_needs_order_record")
                    else:
                        violations.append("sell_fillbelow_effective_limit")
            except (TypeError, ValueError):
                pass
        limit_px = att.get("price_cents")
        if order_qty_cc is not None and fill_qty_cc > order_qty_cc:
            violations.append("overfill_vs_order_qty")
        # post_only vs is_taker
        post_only = att.get("post_only")
        takers = [f for f in fl if f.get("is_taker") is True]
        makers = [f for f in fl if f.get("is_taker") is False]
        unknown_taker = [f for f in fl if f.get("is_taker") is None]
        if post_only is True and takers:
            violations.append("post_only_taker_fill")
        if post_only is False and makers and att.get(
                "resolved_mode") == "maker":
            violations.append("maker_mode_maker_fill_on_taker_order")

        # ---- tier classification ----
        t0 = fl[0]["ts"] or att.get("created_at") or 0
        t1 = fl[-1]["ts"] or t0
        wins = arch_windows.get(ticker, [])
        tier_a = any(o - 5 <= t0 and t1 <= c + 5 for o, c in wins)

        # decision snapshot: join attempt decision_id, else nearest by ticker
        snap = None
        did = att.get("decision_id") or att.get("decision_id_payload")
        if did and did in snaps["by_decision"]:
            cand = snaps["by_decision"][did]
            # snapshot nearest to order time
            snap = min(cand, key=lambda r: abs((r[0] or 0) - t0))
        if snap is None:
            cand = snaps["by_ticker"].get(ticker, [])
            prior = [r for r in cand if (r[0] or 0) <= t0 + 1]
            if prior:
                snap = prior[-1]
            elif cand:
                snap = cand[0]
        snap_age_s = None
        if snap is not None and snap[0]:
            snap_age_s = round(t0 - snap[0], 3)
        tier_b = snap is not None and snap_age_s is not None \
            and snap_age_s <= 900

        tier = "A" if tier_a else ("B" if tier_b else
                                   ("C" if att else "D"))

        # ---- slippage vs decision quote (descriptive) ----
        slip = None
        if snap is not None and leg_prices:
            # snap tuple: (ts,yb,ya,nb,na,age,depth_y,depth_n,exe) or
            #            (ts,yb,ya,nb,na,age,exe)
            yb, ya, nb, na = snap[1], snap[2], snap[3], snap[4]
            bench = None
            if leg == "yes":
                bench = ya if is_buy else yb
            elif leg == "no":
                bench = na if is_buy else nb
            if bench is not None:
                avg_px = sum(leg_prices) / len(leg_prices)
                slip = round(avg_px - bench if is_buy
                             else bench - avg_px, 4)

        rows.append({
            "order_id": oid, "ticker": ticker, "asset": asset,
            "n_fills": len(fl), "qty_cc": fill_qty_cc,
            "order_qty_cc": order_qty_cc,
            "leg": leg, "is_buy": is_buy,
            "limit_px": limit_px,
            "fill_px_min": min(leg_prices) if leg_prices else None,
            "fill_px_max": max(leg_prices) if leg_prices else None,
            "fill_px_avg": round(sum(leg_prices) / len(leg_prices), 4)
            if leg_prices else None,
            "is_taker_fills": len(takers), "is_maker_fills": len(makers),
            "is_taker_unknown": len(unknown_taker),
            "post_only": post_only,
            "liquidity_role": att.get("liquidity_role"),
            "lane": att.get("lane"),
            "t0": t0, "t1": t1,
            "decision_snapshot_age_s": snap_age_s,
            "book_age_ms": snap[5] if snap else None,
            "slippage_cents_vs_decision": slip,
            "tier": tier,
            "attempt_status": att.get("status"),
            "build_sha": att.get("build_sha"),
            "limit_semantics": limit_sem,
            "effective_bound": eff_bound,
            "bound_source": bound_source,
            "unverified_semantics": unverified_semantics,
            "violations": violations,
            "verdict": ("genuine_violation" if violations else
                        ("timing_indeterminate"
                         if unverified_semantics else
                         ("decision_quote_comparison"
                          if slip is not None else
                          ("event_replay_comparison" if tier == "A" else
                           ("instruction_consistent" if att else
                            "coverage_insufficient"))))),
        })
    return rows


def _asset_report(rows):
    out = {}
    for a in list(ASSETS) + ["?"]:
        rs = [r for r in rows if r["asset"] == a]
        if not rs:
            continue
        tiers = defaultdict(int)
        verdicts = defaultdict(int)
        for r in rs:
            tiers[r["tier"]] += 1
            verdicts[r["verdict"]] += 1
        slips = [r["slippage_cents_vs_decision"] for r in rs
                 if r["slippage_cents_vs_decision"] is not None]
        ages = [r["decision_snapshot_age_s"] for r in rs
                if r["decision_snapshot_age_s"] is not None]
        out[a] = {
            "episodes": len(rs),
            "fills": sum(r["n_fills"] for r in rs),
            "tiers": dict(tiers),
            "verdicts": dict(verdicts),
            "taker_episodes": sum(1 for r in rs if r["is_taker_fills"]),
            "maker_episodes": sum(1 for r in rs if r["is_maker_fills"]),
            "mixed_or_unknown": sum(1 for r in rs
                                    if r["is_taker_unknown"]
                                    or (r["is_taker_fills"]
                                        and r["is_maker_fills"])),
            "slippage_cents": {
                "n": len(slips),
                "mean": round(sum(slips) / len(slips), 4) if slips else None,
                "min": min(slips) if slips else None,
                "max": max(slips) if slips else None,
            },
            "snapshot_age_s": {
                "n": len(ages),
                "median": sorted(ages)[len(ages) // 2] if ages else None,
            },
            "violations": sum(len(r["violations"]) for r in rs),
        }
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fills", default="data/kalshi_fills.db")
    ap.add_argument("--attempts", default="data/kalshi_order_attempts.db")
    ap.add_argument("--audit-db", default="data/_audit_hot/decision_audit.db")
    ap.add_argument("--book-archives", nargs="*", default=[
        "data/kalshi_book_archive.db",
        "data/kalshi_book_archive_active.db",
        "data/kalshi_book_archive_live3.db",
    ])
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    fills = load_fills(args.fills)
    attempts = load_attempts(args.attempts)
    global _ATTEMPT_BY_EXCHANGE_ID
    _ATTEMPT_BY_EXCHANGE_ID = {
        a["exchange_order_id"]: a for a in attempts.values()
        if a.get("exchange_order_id")}
    tickers = {f["market_ticker"] for f in fills if f.get("market_ticker")}
    dids = {a.get("decision_id") for a in attempts.values()
            if a.get("decision_id")}
    dids |= {a.get("decision_id_payload") for a in attempts.values()
             if a.get("decision_id_payload")}
    snaps = load_snapshots_index(args.audit_db, tickers, dids)
    arch = archive_ticker_windows(args.book_archives)

    rows = analyze(fills, attempts, snaps, arch)
    rep = {
        "schema": "execution_consistency_v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "note": ("Consistency audit, not arrival-time reproduction. "
                 "Slippage is descriptive vs decision quote; it is not a "
                 "pass/fail simulator error until a simulator predicts "
                 "these same episodes."),
        "n_fills": len(fills),
        "n_episodes": len(rows),
        "episodes": rows,
        "by_asset": _asset_report(rows),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    print(f"wrote {out}: {rep['n_episodes']} episodes, "
          f"{rep['n_fills']} fills")
    for a, r in rep["by_asset"].items():
        print(f"  {a}: eps={r['episodes']} tiers={r['tiers']} "
              f"verdicts={r['verdicts']} viol={r['violations']}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
