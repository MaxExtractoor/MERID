#!/usr/bin/env python3
"""Exit-decision ledger: one row per closed position, with trigger attribution
and a four-policy counterfactual replay.

Data sources (all read-only):
  data/kalshi_fills.db          kalshi_fills        entry + exit executions
  data/kalshi_order_attempts.db order_attempts      intent -> decision_id
                                exit_order_attempts trigger, limit, entry link
  data/decision_audit.db        strategy_decisions  entry decision context
                                strategy_decision_side_ev   model fair (replay)
                                strategy_decision_snapshots book series (markouts)
                                strategy_decision_outcomes  settlement + realized

Row identity: one entry fill = one closed-position unit ("lot").  Exit fills
are matched to entries first via exit_order_attempts.payload_json
.parent_entry_fill_id, then FIFO within (ticker, held side) for orphans
(pre-durable-store exits and the stop_candidate path).  Entry fills whose
market settled without an exit fill are emitted with trigger=settlement.

Counterfactuals:
  realized_pnl_c       exit proceeds - entry cost - all fees
  cf_hold_pnl_c        hold-to-settlement P&L (settle value - entry - entry fee)
  exit_value_added_c   realized - cf_hold  (>0: exit added value)

Replays (post-entry decision snapshots only, ~5s cadence):
  current             what happened
  hold_to_settlement  never exit interim
  economic            exit when executable held bid - est fee > model fair
  invalidation        exit only when model fair < entry price (thesis dead)

Windows note: SQLite URIs need forward slashes; _connect normalizes.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import orjson as _json
    def _loads(b): return _json.loads(b)
except ImportError:
    def _loads(b): return json.loads(b)

REPO = Path(__file__).resolve().parents[1]

# Reuse the funnel report's crash-consistent snapshot helper so long analytic
# reads never compete with the live audit writer (or pin the WAL read-mark).
sys.path.insert(0, str(REPO / "scripts"))
try:
    from window_funnel_report import _snapshot as _audit_snapshot
except Exception:  # pragma: no cover
    _audit_snapshot = None

# ---- trigger normalization into the audit taxonomy -------------------------
TRIGGER_MAP = {
    "take_profit": "take_profit", "hard_profit_lock": "take_profit",
    "auto_exit_99c": "take_profit", "dynamic_take_profit": "take_profit",
    "ratchet_trim": "take_profit", "ratchet_floor": "take_profit",
    "extreme_profit": "take_profit",
    "stop_loss": "stop", "trail": "stop", "trailing_stop": "stop",
    "stop_candidate": "stop",
    "time_stop": "time", "settlement_guard": "time", "stale_data": "time",
    "edge_decay": "evidence_invalidated", "current_edge_reversal": "evidence_invalidated",
    "model_invalidation_loss_exit": "evidence_invalidated",
    "candle_reversal": "evidence_invalidated", "adaptive_timing": "evidence_invalidated",
    "manual": "manual", "risk": "manual", "opportunity_cost": "manual",
}
MARKOUT_HORIZONS = (5.0, 15.0, 60.0)


def _connect(path: Path, ro: bool = True) -> sqlite3.Connection:
    p = str(path).replace("\\", "/")
    uri = f"file:///{p}?mode=ro" if ro else f"file:///{p}"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def _iso_ts(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _fee_cents(price_c: float, contracts: float = 1.0) -> float:
    """Kalshi fee estimate per contract group, cents (0.0175*C*P*(1-P), ceil)."""
    import math
    p = max(0.01, min(0.99, price_c / 100.0))
    return math.ceil(contracts * 100 * 0.0175 * p * (1 - p)) / 100.0 * contracts


def _held_bid_ask(snap_yes_bid, snap_yes_ask, snap_no_bid, snap_no_ask, side):
    if side == "yes":
        return snap_yes_bid, snap_yes_ask
    return snap_no_bid, snap_no_ask


def load_fills(fills_db: Path, since_ts: float):
    conn = _connect(fills_db)
    rows = conn.execute(
        "SELECT fill_id, order_id, market_ticker, side, action, quantity_cc, "
        "execution_price_cents, fee_cost, liquidity_role, intent_id, "
        "client_order_id, decision_trace_id, canonical_position_side, "
        "canonical_position_action, canonical_leg_price_cents, "
        "canonical_yes_delta_cc, "
        "created_time, is_exit, entry_or_exit FROM kalshi_fills"
    ).fetchall()
    conn.close()
    entries, exits = [], []
    for r in rows:
        d = dict(r)
        d["ts"] = _iso_ts(d.get("created_time"))
        d["qty"] = (d.get("quantity_cc") or 0) / 100.0
        d["fee_c"] = (d.get("fee_cost") or 0.0) * 100.0
        _ds = held_side_from_entry(d) or ""
        _is_exit = d.get("is_exit") == 1 or d.get("entry_or_exit") == "exit"
        # An exit reduces the held side, so its YES-delta sign is inverted.
        d["held_side"] = ({"yes": "no", "no": "yes"}.get(_ds, "") if _is_exit else _ds)
        if d["ts"] is None:
            continue
        (exits if d.get("is_exit") == 1 or d.get("entry_or_exit") == "exit" else entries).append(d)
    exits = [e for e in exits if e["ts"] >= since_ts - 900]
    entries = [e for e in entries if e["ts"] >= since_ts - 32 * 86400]
    entries.sort(key=lambda e: e["ts"])
    exits.sort(key=lambda e: e["ts"])
    return entries, exits


def yes_price(fill):
    """YES-equivalent price of a fill.

    The fills ledger's canonical fields are in YES-delta space: a long-NO
    entry at 73c is stored as ``yes/sell @ 27`` and selling a held YES at 68c
    as ``yes/buy @ 32``-style complements.  ``canonical_position_side`` is
    therefore NOT the held side — hold-side must come from the entry's
    ``canonical_yes_delta_cc`` sign (or the decision's selected_side).
    """
    leg = fill.get("canonical_leg_price_cents")
    if leg is None:
        leg = fill.get("execution_price_cents")
    if leg is None:
        return None
    side = (fill.get("canonical_position_side") or "").lower()
    return float(leg) if side == "yes" else 100.0 - float(leg)


def held_side_from_entry(fill):
    d = fill.get("canonical_yes_delta_cc")
    if d:
        return "yes" if d > 0 else "no"
    return None


def held_side_price(fill, held: str, economic_action: str = ""):
    """Price of ``fill`` in the held side's terms (see ``yes_price``)."""
    yp = yes_price(fill)
    if yp is None:
        return None
    return yp if held == "yes" else 100.0 - yp


def load_attempts(attempts_db: Path):
    conn = _connect(attempts_db)
    exit_atts = [dict(r) for r in conn.execute("SELECT * FROM exit_order_attempts")]
    order_atts = [dict(r) for r in conn.execute(
        "SELECT client_order_id, intent_id, decision_id FROM order_attempts")]
    conn.close()
    for a in exit_atts:
        try:
            a["payload"] = _loads(a.get("payload_json") or "{}")
        except Exception:
            a["payload"] = {}
    ea_by_client = {a["client_order_id"]: a for a in exit_atts}
    ea_by_xo = {a["exchange_order_id"]: a for a in exit_atts
                if a.get("exchange_order_id")}
    dec_by_intent = {o["intent_id"]: o["decision_id"] for o in order_atts
                     if o.get("decision_id")}
    dec_by_client = {o["client_order_id"]: o["decision_id"] for o in order_atts
                     if o.get("decision_id")}
    return ea_by_client, ea_by_xo, dec_by_intent, dec_by_client


def load_decisions_for_tickers(audit_db: Path, tickers: set, t_lo: float, t_hi: float):
    """Single streaming scan of strategy_decisions; keep needed tickers.
    Returns {decision_id: row} and per-ticker sorted eval series for
    markout/replay enrichment (filled later with snapshots + side_ev)."""
    conn = _connect(audit_db)
    decs, series = {}, defaultdict(list)
    n = 0
    # idx_decisions_ticker lets the IN-list resolve as per-ticker range scans
    for i in range(0, len(tickers), 100):
        tchunk = sorted(tickers)[i:i + 100]
        ph = ",".join("?" * len(tchunk))
        for r in conn.execute(
            "SELECT decision_id, candidate_id, decision_ts, ticker, asset, "
            "seconds_to_close, close_ts, dir_regime, admission_lane, "
            "selected_side, decision, primary_reason_code FROM "
            f"strategy_decisions WHERE ticker IN ({ph}) AND decision_ts >= ? "
            "AND decision_ts <= ?",
            (*tchunk, t_lo, t_hi),
        ):
            n += 1
            d = dict(r)
            decs[d["decision_id"]] = d
            series[d["ticker"]].append(d["decision_id"])
    for t in series:
        series[t].sort(key=lambda i: decs[i]["decision_ts"])
    print(f"  decisions scanned={n} kept={len(decs)} tickers={len(series)}",
          file=sys.stderr)
    # snapshots + fair via a temp-table join: one sequential scan per table
    # instead of ~100k random PK probes (orders of magnitude faster on cold
    # disk; the snapshot file has no page-cache warmth).
    kept_ids = list(decs)
    conn.execute("CREATE TEMP TABLE _kept (decision_id TEXT PRIMARY KEY)")
    conn.executemany(
        "INSERT OR IGNORE INTO _kept VALUES (?)",
        ((i,) for i in kept_ids),
    )
    snaps, fair = {}, {}
    for r in conn.execute(
        "SELECT s.decision_id, s.yes_bid_cents, s.yes_ask_cents, "
        "s.no_bid_cents, s.no_ask_cents FROM strategy_decision_snapshots s "
        "JOIN _kept k ON s.decision_id = k.decision_id"
    ):
        snaps[r["decision_id"]] = dict(r)
    for r in conn.execute(
        "SELECT e.decision_id, e.side, e.calibrated_probability, "
        "e.executable_entry_price_cents FROM strategy_decision_side_ev e "
        "JOIN _kept k ON e.decision_id = k.decision_id"
    ):
        fair[(r["decision_id"], r["side"])] = r["calibrated_probability"]
    conn.close()
    return decs, series, snaps, fair


def load_outcomes(audit_db: Path, decision_ids: List[str]):
    conn = _connect(audit_db)
    out = {}
    for i in range(0, len(decision_ids), 500):
        chunk = decision_ids[i:i + 500]
        for r in conn.execute(
            "SELECT decision_id, settled_at, settled_yes, settlement_value_cents, "
            "actual_fill_price_cents, actual_exit_price_cents, "
            "realized_net_pnl_cents, outcome_status FROM "
            "strategy_decision_outcomes WHERE decision_id IN (%s)"
            % ",".join("?" * len(chunk)), chunk,
        ):
            out[r["decision_id"]] = dict(r)
    conn.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=30.0)
    ap.add_argument("--db", default=str(REPO / "data" / "decision_audit.db"))
    ap.add_argument("--fills-db", default=str(REPO / "data" / "kalshi_fills.db"))
    ap.add_argument("--attempts-db",
                    default=str(REPO / "data" / "kalshi_order_attempts.db"))
    ap.add_argument("--out", default=str(REPO / "data" / "exit_decision_ledger.json"))
    ap.add_argument("--rows-out",
                    default=str(REPO / "data" / "exit_decision_ledger_rows.jsonl"))
    ap.add_argument("--snapshot", action="store_true",
                    help="copy the audit DB (+wal) to a temp file first; "
                         "required for long reads while the server writes")
    args = ap.parse_args()

    since_ts = time.time() - args.days * 86400
    print(f"[exit-ledger] window last {args.days}d", file=sys.stderr)

    entries, exits = load_fills(Path(args.fills_db), since_ts)
    print(f"  fills: {len(entries)} entry, {len(exits)} exit", file=sys.stderr)
    ea_by_client, ea_by_xo, dec_by_intent, dec_by_client = load_attempts(
        Path(args.attempts_db))

    # --- match exit fills to attempts + entries -----------------------------
    by_fill_id = {e["fill_id"]: e for e in entries}
    fifo: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    for e in entries:
        fifo[(e["market_ticker"], e["held_side"])].append(e)

    entry_exits: Dict[str, List[dict]] = defaultdict(list)   # entry fill_id -> [exit fills]
    entry_remaining: Dict[str, float] = {e["fill_id"]: e["qty"] for e in entries}
    orphan_exits = []
    for xf in exits:
        att = ea_by_client.get(xf.get("client_order_id")) or \
            ea_by_xo.get(xf.get("order_id"))
        xf["attempt"] = att
        targets: List[Tuple[dict, float, str]] = []  # (entry, alloc_qty, how)
        if att:
            parent = (att.get("payload") or {}).get("parent_entry_fill_id")
            if parent and parent in by_fill_id:
                e = by_fill_id[parent]
                targets.append((e, min(e["qty"], xf["qty"]), "parent_fill_id"))
        if not targets:
            # qty-aware FIFO: consume earlier unmatched entries on the same
            # ticker+side until the exit quantity is covered
            key = (xf["market_ticker"], xf["held_side"])
            need = xf["qty"]
            for cand in fifo.get(key, []):
                rem = entry_remaining.get(cand["fill_id"], 0.0)
                if rem <= 0 or cand["ts"] > xf["ts"]:
                    continue
                alloc = min(rem, need)
                targets.append((cand, alloc, "fifo"))
                need -= alloc
                if need <= 0:
                    break
        if not targets:
            orphan_exits.append(xf)
            continue
        alloc_map = xf.setdefault("alloc_map", {})
        for entry, alloc, how in targets:
            entry_remaining[entry["fill_id"]] = \
                max(0.0, entry_remaining[entry["fill_id"]] - alloc)
            alloc_map[entry["fill_id"]] = alloc
            xf["match_how"] = how
            entry_exits[entry["fill_id"]].append(xf)

    tickers = {e["market_ticker"] for e in entries} | \
        {x["market_ticker"] for x in exits}
    # Decision-scan window: bounded to the report window.  Entries older than
    # --days still emit ledger rows (fills + outcomes carry them), they just
    # skip the decision-row enrichment and markout series.
    t_lo = since_ts - 900
    t_hi = max([x["ts"] for x in exits] + [time.time()])
    print(f"  scanning decisions for {len(tickers)} tickers "
          f"{datetime.fromtimestamp(t_lo, timezone.utc):%m-%d %H:%M}.."
          f"{datetime.fromtimestamp(t_hi, timezone.utc):%m-%d %H:%M}",
          file=sys.stderr)
    db_path = args.db
    snap_tmp = None
    if args.snapshot and _audit_snapshot is not None:
        snap_tmp = _audit_snapshot(db_path)
        db_path = snap_tmp
    decs, series, snaps, fair = load_decisions_for_tickers(
        Path(db_path), tickers, t_lo, t_hi)

    # entry decision lookup for the specific entry fills
    def _entry_decision_id(ef):
        return ef.get("decision_trace_id") \
            or dec_by_intent.get(ef.get("intent_id")) \
            or dec_by_client.get(ef.get("client_order_id"))

    entry_dec_ids = {_entry_decision_id(e) for e in entries}
    entry_dec_ids.discard(None)
    outcomes = load_outcomes(Path(db_path), sorted(entry_dec_ids))
    if snap_tmp:
        try:
            os.unlink(snap_tmp)
            os.unlink(snap_tmp + "-wal")
        except OSError:
            pass

    def _held_value_at_settle(held_side, oc):
        if not oc or oc.get("settled_yes") is None:
            return None
        yes_v = 100 if oc["settled_yes"] else 0
        return yes_v if held_side == "yes" else 100 - yes_v

    def _series_point(ticker, ts):
        """first decision snapshot at/after ts on ticker -> (bid,ask,fair) held-agnostic"""
        for did in series.get(ticker, []):
            d = decs[did]
            if d["decision_ts"] >= ts:
                return did, d
        return None, None

    def _markouts(ticker, held_side, exec_c, exit_ts):
        res = {}
        for h in MARKOUT_HORIZONS:
            did, d = _series_point(ticker, exit_ts + h)
            mk = None
            if did:
                s = snaps.get(did)
                if s:
                    b, a = _held_bid_ask(s["yes_bid_cents"], s["yes_ask_cents"],
                                         s["no_bid_cents"], s["no_ask_cents"], held_side)
                    if b and a:
                        held_mid = (b + a) / 2.0
                        mk = exec_c - held_mid  # >0: price fell after exit = exit helped
            res[f"exit_markout_{int(h)}s_c"] = mk
        return res

    # --- build rows ----------------------------------------------------------
    rows = []
    for ef in entries:
        did = _entry_decision_id(ef)
        dec = decs.get(did) if did else None
        oc = outcomes.get(did) if did else None
        side = ef["held_side"] or (dec["selected_side"] if dec else None)
        asset = dec["asset"] if dec else (
            next((a for a in ("BTC", "ETH", "SOL", "XRP", "DOGE")
                  if a in (ef["market_ticker"] or "")), "unknown"))
        xfills = entry_exits.get(ef["fill_id"], [])
        entry_px = held_side_price(ef, side, "buy") if side else ef["execution_price_cents"]
        entry_fee = ef["fee_c"]
        qty = ef["qty"]
        settle_v = _held_value_at_settle(side, oc)
        cf_hold = None
        if settle_v is not None:
            cf_hold = settle_v * qty - entry_px * qty - entry_fee

        if xfills:
            # aggregate this lot's allocated exit slices (usually a single fill)
            tot_px = sum(
                held_side_price(x, side, "sell") * x.get("alloc_map", {}).get(ef["fill_id"], x["qty"])
                for x in xfills)
            tot_qty = sum(
                x.get("alloc_map", {}).get(ef["fill_id"], x["qty"]) for x in xfills)
            tot_fee = sum(
                x["fee_c"] * (x.get("alloc_map", {}).get(ef["fill_id"], x["qty"]) / max(x["qty"], 1e-9))
                for x in xfills)
            xw = tot_px / tot_qty if tot_qty else None
            first_x = xfills[0]
            att = first_x.get("attempt")
            raw_reason = (att["reason"] if att else
                          ("stop_candidate" if "stop_candidate" in str(first_x.get("intent_id")) else "unknown"))
            limit_c = att.get("requested_limit_cents") if att else None
            exit_ts = first_x["ts"]
            realized = tot_px - entry_px * tot_qty - entry_fee - tot_fee
            slip = (xw - limit_c) if (xw is not None and limit_c is not None) else None
            mks = _markouts(ef["market_ticker"], side, xw, exit_ts)
            settle_mk = (xw - settle_v) if (xw is not None and settle_v is not None) else None
            rows.append({
                "decision_id": did, "candidate_id": (dec or {}).get("candidate_id"),
                "ticker": ef["market_ticker"], "asset": asset, "side": side,
                "route": (dec or {}).get("admission_lane")
                          or (did.split(":")[-1] if did and ":" in did else None),
                "dir_regime": (dec or {}).get("dir_regime"),
                "entry_fill_id": ef["fill_id"], "entry_ts": ef["ts"],
                "entry_price_c": entry_px, "qty_contracts": qty,
                "entry_fee_c": entry_fee,
                "tte_at_entry_s": (dec or {}).get("seconds_to_close"),
                "exit_trigger": TRIGGER_MAP.get(raw_reason, "unknown"),
                "exit_reason_raw": raw_reason,
                "exit_match": first_x.get("match_how"),
                "exit_ts": exit_ts, "hold_s": exit_ts - ef["ts"],
                "exit_quote_c": limit_c, "exit_exec_c": xw,
                "exit_fee_c": tot_fee, "exit_slippage_c": slip,
                "n_exit_fills": len(xfills),
                **mks, "exit_markout_settle_c": settle_mk,
                "settled_yes": oc.get("settled_yes") if oc else None,
                "settle_value_held_c": settle_v,
                "realized_pnl_c": realized,
                "cf_hold_pnl_c": cf_hold,
                "exit_value_added_c": (realized - cf_hold) if cf_hold is not None else None,
                "closed_by": "exit",
            })
        else:
            # settlement-closed or still-open
            closed = settle_v is not None
            realized = (settle_v * qty - entry_px * qty - entry_fee) if closed else None
            rows.append({
                "decision_id": did, "candidate_id": (dec or {}).get("candidate_id"),
                "ticker": ef["market_ticker"], "asset": asset, "side": side,
                "route": (dec or {}).get("admission_lane")
                          or (did.split(":")[-1] if did and ":" in did else None),
                "dir_regime": (dec or {}).get("dir_regime"),
                "entry_fill_id": ef["fill_id"], "entry_ts": ef["ts"],
                "entry_price_c": entry_px, "qty_contracts": qty,
                "entry_fee_c": entry_fee,
                "tte_at_entry_s": (dec or {}).get("seconds_to_close"),
                "exit_trigger": "settlement" if closed else "open_unresolved",
                "exit_reason_raw": "held_to_settlement" if closed else None,
                "exit_match": None, "exit_ts": oc.get("settled_at") if oc else None,
                "hold_s": ((oc["settled_at"] - ef["ts"]) if (oc and oc.get("settled_at")) else None),
                "exit_quote_c": settle_v, "exit_exec_c": settle_v,
                "exit_fee_c": 0.0, "exit_slippage_c": 0.0,
                "n_exit_fills": 0,
                "exit_markout_5s_c": None, "exit_markout_15s_c": None,
                "exit_markout_60s_c": None, "exit_markout_settle_c": 0.0 if closed else None,
                "settled_yes": oc.get("settled_yes") if oc else None,
                "settle_value_held_c": settle_v,
                "realized_pnl_c": realized, "cf_hold_pnl_c": realized if closed else None,
                "exit_value_added_c": 0.0 if closed else None,
                "closed_by": "settlement" if closed else "open",
            })

    # --- four-policy replay --------------------------------------------------
    def _replay(rows):
        """Return policy->pnl over closed rows using the decision-time series."""
        pol = {"current": 0.0, "hold_to_settlement": 0.0,
               "economic": 0.0, "invalidation": 0.0}
        detail = defaultdict(list)
        for r in rows:
            if r["closed_by"] != "exit" or r["settle_value_held_c"] is None:
                # settlement rows: identical under every policy
                for k in pol:
                    if r["realized_pnl_c"] is not None:
                        pol[k] += r["realized_pnl_c"]
                continue
            pol["current"] += r["realized_pnl_c"]
            pol["hold_to_settlement"] += r["cf_hold_pnl_c"]
            side = r["side"]
            econ_exit = inv_exit = None
            for didx in series.get(r["ticker"], []):
                d = decs[didx]
                if d["decision_ts"] <= r["entry_ts"]:
                    continue
                s = snaps.get(didx)
                if not s:
                    continue
                hb, ha = _held_bid_ask(s["yes_bid_cents"], s["yes_ask_cents"],
                                       s["no_bid_cents"], s["no_ask_cents"], side)
                f = fair.get((didx, side))
                if hb is None or f is None:
                    continue
                fair_c = f * 100.0
                if econ_exit is None and (hb - _fee_cents(hb)) > fair_c:
                    econ_exit = hb
                if inv_exit is None and fair_c < r["entry_price_c"]:
                    inv_exit = hb
            for name, px in (("economic", econ_exit), ("invalidation", inv_exit)):
                if px is not None:
                    proceeds = px * r["qty_contracts"] - _fee_cents(px, r["qty_contracts"])
                    pnl = proceeds - r["entry_price_c"] * r["qty_contracts"] - r["entry_fee_c"]
                else:
                    pnl = r["cf_hold_pnl_c"]
                pol[name] += pnl
                detail[name].append({"ticker": r["ticker"], "exited": px is not None})
        return pol, detail

    closed = [r for r in rows if r["closed_by"] in ("exit", "settlement")]
    policy_pnl, policy_detail = _replay(closed)

    # --- aggregation ---------------------------------------------------------
    def _band(p):
        if p is None: return "?"
        for lo in range(0, 100, 10):
            if p < lo + 10: return f"{lo}-{lo+10}"
        return "90-100"

    def _tte_b(s):
        if s is None: return "?"
        for b in (180, 300, 450, 600, 900):
            if s <= b: return f"<= {b}s"
        return ">900s"

    by_trig = defaultdict(list)
    for r in closed:
        by_trig[r["exit_trigger"]].append(r)

    def _avg(xs):
        xs = [x for x in xs if x is not None]
        return round(sum(xs) / len(xs), 2) if xs else None

    trig_table = {}
    for trig, rs in sorted(by_trig.items(), key=lambda kv: -len(kv[1])):
        n = len(rs)
        wins = sum(1 for r in rs if (r["realized_pnl_c"] or 0) > 0)
        trig_table[trig] = {
            "n": n, "win_rate": round(wins / n, 3),
            "avg_realized_c": _avg([r["realized_pnl_c"] for r in rs]),
            "avg_cf_hold_c": _avg([r["cf_hold_pnl_c"] for r in rs]),
            "exit_value_added_total_c": _avg([
                r["exit_value_added_c"] for r in rs]) or 0.0,
            "exit_value_added_sum_c": round(sum(
                r["exit_value_added_c"] or 0 for r in rs), 1),
            "avg_slippage_c": _avg([r["exit_slippage_c"] for r in rs]),
            "avg_markout_5s_c": _avg([r["exit_markout_5s_c"] for r in rs]),
            "avg_markout_15s_c": _avg([r["exit_markout_15s_c"] for r in rs]),
            "avg_markout_60s_c": _avg([r["exit_markout_60s_c"] for r in rs]),
            "avg_markout_settle_c": _avg([r["exit_markout_settle_c"] for r in rs]),
            "by_asset": {a: sum(1 for r in rs if r["asset"] == a)
                         for a in ("BTC", "ETH", "SOL", "XRP", "DOGE")},
            "by_side": {s: sum(1 for r in rs if r["side"] == s) for s in ("yes", "no")},
        }

    report = {
        "generated_at": time.time(),
        "window_days": args.days,
        "counts": {
            "entry_fills": len(entries), "exit_fills": len(exits),
            "closed_rows": len(closed),
            "closed_by_exit": sum(1 for r in closed if r["closed_by"] == "exit"),
            "closed_by_settlement": sum(1 for r in closed if r["closed_by"] == "settlement"),
            "open_unresolved": sum(1 for r in rows if r["closed_by"] == "open"),
            "orphan_exit_fills": len(orphan_exits),
            "exit_match_parent_id": sum(1 for x in exits if x.get("match_how") == "parent_fill_id"),
            "exit_match_fifo": sum(1 for x in exits if x.get("match_how") == "fifo"),
        },
        "by_trigger": trig_table,
        "policy_replay": {k: round(v, 1) for k, v in policy_pnl.items()},
        "replay_exit_counts": {
            k: sum(1 for d in v if d["exited"]) for k, v in policy_detail.items()
        },
    }

    Path(args.rows_out).write_text(
        "\n".join(json.dumps(r, default=str) for r in closed) + "\n")
    Path(args.out).write_text(json.dumps(report, indent=2, default=str))

    # --- console report ------------------------------------------------------
    print("\n=== EXIT DECISION LEDGER ===")
    c = report["counts"]
    print(f"closed positions: {c['closed_rows']} "
          f"(exit fills: {c['closed_by_exit']}, settlement: {c['closed_by_settlement']}, "
          f"open/unresolved: {c['open_unresolved']})")
    print(f"exit linkage: parent_id={c['exit_match_parent_id']} "
          f"fifo={c['exit_match_fifo']} orphans={c['orphan_exit_fills']}")
    print("\nper-trigger:")
    print(f"{'trigger':<22}{'n':>5}{'win%':>7}{'real':>8}{'cf_hold':>9}"
          f"{'eva_sum':>9}{'slip':>7}{'mk5':>7}{'mk60':>7}{'mk_stl':>8}")
    for trig, t in trig_table.items():
        print(f"{trig:<22}{t['n']:>5}{t['win_rate']:>7.2f}"
              f"{t['avg_realized_c'] or 0:>8.1f}{t['avg_cf_hold_c'] or 0:>9.1f}"
              f"{t['exit_value_added_sum_c']:>9.1f}{t['avg_slippage_c'] or 0:>7.2f}"
              f"{t['avg_markout_5s_c'] or 0:>7.1f}{t['avg_markout_60s_c'] or 0:>7.1f}"
              f"{t['avg_markout_settle_c'] or 0:>8.1f}")
    print("\nfour-policy replay (net P&L cents over closed positions):")
    for k, v in report["policy_replay"].items():
        extra = f"  (exits: {report['replay_exit_counts'].get(k)})" if k in report["replay_exit_counts"] else ""
        print(f"  {k:<20}{v:>10.1f}{extra}")
    print(f"\nrows -> {args.rows_out}\nreport -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
