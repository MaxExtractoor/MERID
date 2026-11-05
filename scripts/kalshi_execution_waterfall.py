#!/usr/bin/env python3
"""Execution waterfall: decision -> order -> fills -> fees -> outcome.

Reconciles what the strategy expected against what the venue delivered,
using ONLY existing durable ledgers.  One parent row per decision-side
opportunity; child order attempts and fills attach without duplicating
expected edge or settlement P&L.

Parent grain
    (candidate_id, side) -- one decision-side opportunity.  Each candidate
    produces multiple per-lane decision rows ({candidate}:{taker|maker|
    maker_bid|empirical_marginal_maker|pre}); attempts carry the stage-
    specific decision_id, so parent attachment is by candidate prefix.
    Expected-EV columns come from the side_ev row of the stage that
    produced attempts, else the highest-EV stage row for that candidate.

Terminal categories (mutually exclusive, first match wins):
    never_submitted           ENTER-able opportunity, no attempt rows
    rejected_locally          every attempt rejected before the wire
    submitted_no_fill         attempts reached the venue, zero fills
    partial_fill              0 < filled_qty < submitted_qty
    filled_exit_early         filled + exit evidence before settlement
    filled_held_to_settlement filled + settled outcome, no exit evidence
    unresolved                outcome missing/PENDING/UNRESOLVED

Columns available NOW (existing inventory): decision-time edge
decomposition, actual fills+fees, submitted/filled qty, exit/settlement
outcome.  Columns deliberately absent (require additional evidence):
estimated arrival-time repricing, counterfactual depth at arrival,
queue-conditioned counterfactual fills, latency-vs-selection attribution.

Usage:
    python scripts/kalshi_execution_waterfall.py --hours 48
        [--since ISO] [--until ISO] [--asset BTC] [--limit 5000]
        [--out-dir reports] [--audit-db data/decision_audit.db]
        [--attempts-db data/kalshi_order_attempts.db]
        [--fills-db data/kalshi_fills.db] [--15m-db data/kalshi_15m_audit.db]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

_FILL_BATCH = 800          # IN() chunk sizes for child lookups
_EXEC_STAGES = (":taker", ":maker", ":maker_bid", ":empirical_marginal_maker")


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _parse_dt(s: str) -> float:
    s = s.strip().replace("Z", "+00:00")
    return datetime.fromisoformat(s).timestamp()


def _fp(v: Any) -> Optional[float]:
    """Fixed-point string/int -> float contracts."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _side_norm(order_side: Optional[str]) -> Optional[str]:
    """'buy_no'/'sell_yes'/'no'/'yes' -> 'yes'/'no' (side_ev case)."""
    if not order_side:
        return None
    s = order_side.lower()
    if "yes" in s:
        return "yes"
    if "no" in s:
        return "no"
    return None


_PARENT_COLS = [
    "decision_id", "side", "ticker", "asset", "decision_ts",
    "decision", "selected_side", "admission_lane", "policy_epoch",
    "seconds_to_close",
    "selected", "executable", "passed_net_ev",
    "expected_entry_price_cents", "expected_fill_cents",
    "raw_p", "cal_p",
    "gross_edge_c", "entry_fee_exp_c", "exit_fee_exp_c",
    "adv_sel_haircut_c", "model_unc_haircut_c",
    "net_ev_exp_c", "lcb_ev_c",
    "requested_contracts", "top_of_book_contracts",
]


def load_parents(
    con: sqlite3.Connection, t0: float, t1: float, limit: int
) -> List[Dict[str, Any]]:
    """Decision-side opportunities in [t0, t1).  Indexed by decision_ts."""
    rows = con.execute(
        """
        WITH dd AS (
            SELECT decision_id
            FROM strategy_decisions
            WHERE decision_ts >= ? AND decision_ts < ?
            ORDER BY decision_ts DESC
            LIMIT ?
        )
        SELECT se.decision_id, se.side, d.ticker, d.asset, d.decision_ts,
               d.decision, d.selected_side, d.admission_lane, d.policy_epoch,
               d.seconds_to_close,
               se.selected, se.executable, se.passed_net_ev,
               se.executable_entry_price_cents, se.expected_entry_fill_cents,
               se.raw_probability, se.calibrated_probability,
               se.gross_edge_cents, se.entry_fee_cents,
               se.exit_or_settlement_fee_cents,
               se.adverse_selection_haircut_cents,
               se.model_uncertainty_haircut_cents,
               se.expected_net_ev_cents, se.lower_confidence_bound_ev_cents,
               se.requested_contracts,
               se.top_of_book_executable_contracts
        FROM dd
        JOIN strategy_decisions d ON d.decision_id = dd.decision_id
        CROSS JOIN strategy_decision_side_ev se
               ON se.decision_id = d.decision_id
        ORDER BY d.decision_ts DESC
        """,
        (t0, t1, limit),
    ).fetchall()
    parents = [dict(zip(_PARENT_COLS, r)) for r in rows]
    # side_ev exists only on execution-stage ids; drop anything else for safety
    parents = [
        p for p in parents
        if any(p["decision_id"].endswith(sfx) for sfx in _EXEC_STAGES)
    ]
    return parents


def load_parents_by_candidates(
    con: sqlite3.Connection, candidate_ids: List[str]
) -> List[Dict[str, Any]]:
    """Exact parents for attempt-referenced candidates — fetched regardless of
    the context-cohort limit so every attempt can attach."""
    out: List[Dict[str, Any]] = []
    for ch in _chunks(candidate_ids, _FILL_BATCH):
        ph = ",".join("?" for _ in ch)
        rows = con.execute(
            f"""
            SELECT se.decision_id, se.side, d.ticker, d.asset, d.decision_ts,
                   d.decision, d.selected_side, d.admission_lane,
                   d.policy_epoch, d.seconds_to_close,
                   se.selected, se.executable, se.passed_net_ev,
                   se.executable_entry_price_cents,
                   se.expected_entry_fill_cents,
                   se.raw_probability, se.calibrated_probability,
                   se.gross_edge_cents, se.entry_fee_cents,
                   se.exit_or_settlement_fee_cents,
                   se.adverse_selection_haircut_cents,
                   se.model_uncertainty_haircut_cents,
                   se.expected_net_ev_cents,
                   se.lower_confidence_bound_ev_cents,
                   se.requested_contracts,
                   se.top_of_book_executable_contracts
            FROM strategy_decisions d
            CROSS JOIN strategy_decision_side_ev se
                   ON se.decision_id = d.decision_id
            WHERE d.candidate_id IN ({ph})
            """,
            ch,
        ).fetchall()
        out.extend(
            p for p in (dict(zip(_PARENT_COLS, r)) for r in rows)
            if any(p["decision_id"].endswith(sfx) for sfx in _EXEC_STAGES)
        )
    return out


def _chunks(seq: List[str], n: int):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def load_attempts(
    con: sqlite3.Connection, t0: float, t1: float
) -> List[Dict[str, Any]]:
    """All attempts in the window (keyed later by candidate prefix)."""
    out: List[Dict[str, Any]] = []
    for r in con.execute(
        """
        SELECT order_attempt_id, decision_id, intent_id, client_order_id,
               replaces_order_attempt_id, status, created_at, updated_at,
               payload_json
        FROM oa.order_attempts WHERE created_at >= ? AND created_at < ?
        """,
        (t0, t1),
    ).fetchall():
        (
            attempt_id, did, intent_id, coid, replaces, status,
            created, updated, payload,
        ) = r
        order = contract = {}
        try:
            p = json.loads(payload or "{}")
            order = p.get("order") or {}
            contract = p.get("execution_contract") or {}
            route_status = p.get("route_result_status")
        except Exception:
            route_status = None
        # Attempt decision_ids are "{candidate}:{stage}" in the current era;
        # test/legacy ids (test-*, merid-*, 15m_*) get cand=None.
        cand = did.split(":")[0] if did and did.startswith("cand_") else None
        out.append({
            "attempt_id": attempt_id,
            "decision_id": did,
            "cand": cand,
            "intent_id": intent_id,
            "client_order_id": coid,
            "replaces": replaces,
            "status": status,
            "route_status": route_status,
            "created_at": created,
            "updated_at": updated,
            "side": _side_norm(order.get("side")),
            "action": order.get("action"),
            "limit_cents": order.get("price_cents"),
            "count_fp": _fp(order.get("count_fp")),
            "tif": order.get("tif"),
            "exec_mode": contract.get("resolved_execution_mode"),
            "exec_role": order.get("liquidity_role")
                       or contract.get("required_liquidity_role"),
            "post_only": contract.get("post_only")
                         or contract.get("required_post_only"),
        })
    return out


def load_fills(
    con: sqlite3.Connection, client_order_ids: List[str]
) -> Dict[str, List[Dict[str, Any]]]:
    """fills keyed by client_order_id (attempt linkage)."""
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    if not client_order_ids:
        return out
    for ch in _chunks(client_order_ids, _FILL_BATCH):
        ph = ",".join("?" * len(ch))
        for r in con.execute(
            f"""
            SELECT fill_id, order_id, client_order_id, intent_id,
                   market_ticker, side, action, count_fp, quantity_cc,
                   execution_price_cents, fee_cost, liquidity_role,
                   entry_or_exit, is_exit, created_time
            FROM f.kalshi_fills WHERE client_order_id IN ({ph})
            """,
            ch,
        ).fetchall():
            (
                fid, oid, coid, intent, ticker, side, action, count_fp,
                qty_cc, px_c, fee, role, eoe, is_exit, cts,
            ) = r
            out[coid].append({
                "fill_id": fid, "order_id": oid, "intent_id": intent,
                "ticker": ticker, "side": _side_norm(side) or side,
                "action": action,
                "contracts": _fp(count_fp)
                            or (qty_cc / 100.0 if qty_cc is not None else None),
                "price_cents": px_c,
                "fee_dollars": fee,
                "role": role,
                "entry_or_exit": eoe,
                "is_exit": is_exit,
                "created_time": cts,
            })
    return out


def load_outcomes(
    con: sqlite3.Connection, decision_ids: List[str]
) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for ch in _chunks(decision_ids, _FILL_BATCH):
        ph = ",".join("?" * len(ch))
        for r in con.execute(
            f"""
            SELECT decision_id, outcome_status, settled_at, settled_yes,
                   settlement_value_cents, actual_fill_price_cents,
                   actual_entry_fee_cents, actual_exit_price_cents,
                   actual_exit_fee_cents, realized_net_pnl_cents,
                   capital_realized_pnl_cents, exit_attribution,
                   unresolved_reason, fill_id, exchange_order_id
            FROM strategy_decision_outcomes WHERE decision_id IN ({ph})
            """,
            ch,
        ).fetchall():
            out[r[0]] = {
                "status": r[1], "settled_at": r[2], "settled_yes": r[3],
                "settlement_value_c": r[4], "actual_fill_px_c": r[5],
                "actual_entry_fee_c": r[6], "actual_exit_px_c": r[7],
                "actual_exit_fee_c": r[8], "realized_pnl_c": r[9],
                "capital_realized_c": r[10], "exit_attribution": r[11],
                "unresolved_reason": r[12], "fill_id": r[13], "order_id": r[14],
            }
    return out


def load_settlement(
    con: sqlite3.Connection, tickers: List[str],
    cand_to_ticker: Optional[Dict[str, str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Settlement truth per ticker, with explicit provenance.

    Primary: `a15.kalshi_15m_markets` (bounded audit extraction — stale
    after its build window, currently ends ~Oct 14).
    Fallback: `strategy_decision_outcomes.settled_yes` — the live
    authoritative verdict written by settlement resolution; 1.5M+ rows
    and current.  Outcome decision_ids are `cand_<id>:<route>`; mapped to
    tickers through the report's own parents (cand prefix -> ticker).
    `settle_source` records which source supplied the verdict; conflicting
    verdicts within a ticker are surfaced via `verdict_conflicts`.
    """
    out: Dict[str, Dict[str, Any]] = {}
    tickset = sorted(set(tickers))
    for ch in _chunks(tickset, _FILL_BATCH):
        ph = ",".join("?" * len(ch))
        for r in con.execute(
            f"""
            SELECT market_ticker, yes_outcome, close_twap_60s, outcome_error
            FROM a15.kalshi_15m_markets WHERE market_ticker IN ({ph})
            """,
            ch,
        ).fetchall():
            out[r[0]] = {"yes_outcome": r[1], "close_twap": r[2],
                         "outcome_error": r[3],
                         "settle_source": "a15_audit",
                         "verdict_conflicts": 0}

    # Fallback: live outcomes table for tickers the audit snapshot missed.
    missing = [t for t in tickset if t not in out]
    if missing and cand_to_ticker:
        cands = [c for c, t in cand_to_ticker.items() if t in set(missing)]
        verdicts: Dict[str, List[int]] = defaultdict(list)
        # Outcome decision_ids carry route suffixes unknown to us — use
        # indexed prefix ranges per candidate instead of an IN list.
        for cand in cands:
            lo, hi = f"{cand}:", f"{cand};"
            for did, sy in con.execute(
                "SELECT decision_id, settled_yes "
                "FROM strategy_decision_outcomes "
                "WHERE outcome_status = 'SETTLED' AND settled_yes IS NOT NULL "
                "  AND decision_id >= ? AND decision_id < ?",
                (lo, hi),
            ).fetchall():
                verdicts[cand_to_ticker[cand]].append(int(sy))
        for ticker in missing:
            vs = verdicts.get(ticker)
            if not vs:
                continue
            yes_ct = sum(1 for v in vs if v == 1)
            no_ct = len(vs) - yes_ct
            out[ticker] = {
                "yes_outcome": 1 if yes_ct > no_ct else 0,
                "close_twap": None,
                "outcome_error": None,
                "settle_source": "outcomes_table",
                "verdict_conflicts": min(yes_ct, no_ct),
                "verdict_n": len(vs),
            }
    return out


def classify(p: Dict[str, Any], attempts: List[Dict[str, Any]],
             fills: List[Dict[str, Any]], outcome: Optional[Dict[str, Any]]
             ) -> Tuple[str, str]:
    """(terminal_category, detail)."""
    if not attempts:
        return "never_submitted", "no attempt rows for decision"
    submitted = [a for a in attempts
                 if a["status"] != "REJECTED"
                 and a["route_status"] != "rejected"]
    if not submitted:
        why = ";".join(sorted({str(a["status"]) for a in attempts}))
        return "rejected_locally", f"all attempts {why}"
    if not fills:
        return "submitted_no_fill", f"{len(submitted)} wire attempt(s)"
    req = sum(a["count_fp"] or 0 for a in submitted if a["count_fp"])
    got = sum(f["contracts"] or 0 for f in fills)
    partial = got < req - 1e-9 if req else False
    cat = "partial_fill" if partial else "full_fill"
    exits = [f for f in fills if f["is_exit"] or f["entry_or_exit"] == "exit"]
    has_out = outcome is not None and outcome["status"] in (
        "SETTLED", "EXITED", "RESOLVED")
    if exits or (outcome and outcome["actual_exit_px_c"] is not None):
        return f"{cat}_exit_early", "exit evidence"
    if outcome and outcome["status"] == "SETTLED":
        return f"{cat}_held_to_settlement", "settled"
    if outcome and outcome["status"] == "PENDING":
        return f"{cat}_unresolved", "outcome PENDING"
    if outcome and outcome["status"] == "UNRESOLVED":
        return f"{cat}_unresolved", (
            f"UNRESOLVED:{outcome['unresolved_reason']}")
    if has_out:
        return f"{cat}_held_to_settlement", outcome["status"]
    return f"{cat}_unresolved", "no outcome row"


def build_rows(parents, all_attempts, fills_m, outcomes_m, settle_m):
    """Collapse stage-level parents into (candidate_id, side) grain."""
    # group side_ev rows by (cand, side)
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for p in parents:
        groups[(p["decision_id"].split(":")[0], p["side"])].append(p)

    # attach attempts by (cand, side); side-unknown attempts attach when
    # the candidate has exactly one side evaluated, else marked ambiguous
    att_by_key: Dict[Tuple[str, str], List[Dict[str, Any]]] = \
        defaultdict(list)
    orphan_attempts: List[Dict[str, Any]] = []
    for a in all_attempts:
        if not a["cand"]:
            orphan_attempts.append(a)
            continue
        key = (a["cand"], a["side"])
        if a["side"] and key in groups:
            att_by_key[key].append(a)
        elif not a["side"]:
            sides = [k for k in groups if k[0] == a["cand"]]
            if len(sides) == 1:
                att_by_key[sides[0]].append(a)
            elif sides:
                a = {**a, "attach_ambiguous": True}
                orphan_attempts.append(a)
            else:
                orphan_attempts.append(a)
        else:
            orphan_attempts.append(a)

    parents_rows, fill_rows = [], []
    for (cand, side), stage_rows in sorted(groups.items()):
        atts = sorted(att_by_key.get((cand, side), []),
                      key=lambda a: a["created_at"] or 0)
        # EV source: the stage whose decision_id an attempt used, else the
        # stage row with the highest expected net EV.
        att_dids = {a["decision_id"] for a in atts}
        ev_rows = [p for p in stage_rows if p["decision_id"] in att_dids]
        if not ev_rows:
            ev_rows = [max(
                stage_rows,
                key=lambda p: (p["net_ev_exp_c"] is not None,
                               p["net_ev_exp_c"] or -1e18),
            )]
        p = ev_rows[0]
        did = p["decision_id"]
        stages = sorted({r["decision_id"].split(":")[-1]
                         for r in stage_rows})
        # outcome: prefer attempt-stage row, else a resolved stage row
        outc = outcomes_m.get(did)
        if outc is None or outc["status"] in ("PENDING", "UNRESOLVED"):
            for r in stage_rows:
                alt = outcomes_m.get(r["decision_id"])
                if alt and alt["status"] not in ("PENDING", "UNRESOLVED"):
                    outc = alt
                    break
        coids = [a["client_order_id"] for a in atts if a["client_order_id"]]
        fills = [f for coid in coids for f in fills_m.get(coid, [])]
        seen = set()
        fills = [f for f in fills
                 if not (f["fill_id"] in seen or seen.add(f["fill_id"]))]
        cat, detail = classify(p, atts, fills, outc)
        submitted = [a for a in atts if a["status"] != "REJECTED"
                     and a["route_status"] != "rejected"]
        req_qty = sum(a["count_fp"] or 0 for a in submitted if a["count_fp"])
        fill_qty = sum(f["contracts"] or 0 for f in fills)
        # side-normalize fill prices into the parent side's cent space
        side_fills = [f for f in fills if f["side"] in (None, side)]
        vw = sum((f["contracts"] or 0) * (f["price_cents"] or 0)
                 for f in side_fills)
        vw_n = sum(f["contracts"] or 0 for f in side_fills)
        avg_px = vw / vw_n if vw_n else None
        fee_total_c = sum((f["fee_dollars"] or 0) * 100.0 for f in fills)
        sm = settle_m.get(p["ticker"], {})
        parents_rows.append({
            "category": cat,
            "category_detail": detail,
            "decision_id": did,
            "candidate_id": cand,
            "ev_stage": did.split(":")[-1],
            "stages_evaluated": "|".join(stages),
            "ticker": p["ticker"], "asset": p["asset"], "side": side,
            "decision_ts": p["decision_ts"],
            "decision_ts_utc": _iso(p["decision_ts"]),
            "seconds_to_close": p["seconds_to_close"],
            "decision": p["decision"], "selected_side": p["selected_side"],
            "admission_lane": p["admission_lane"],
            "policy_epoch": p["policy_epoch"],
            # --- expected side (AVAILABLE NOW: decision-time edge decomp)
            "exp_entry_px_c": p["expected_entry_price_cents"],
            "exp_fill_px_c": p["expected_fill_cents"],
            "gross_edge_c": p["gross_edge_c"],
            "exp_entry_fee_c": p["entry_fee_exp_c"],
            "exp_exit_fee_c": p["exit_fee_exp_c"],
            "adv_sel_haircut_c": p["adv_sel_haircut_c"],
            "model_unc_haircut_c": p["model_unc_haircut_c"],
            "net_ev_exp_c": p["net_ev_exp_c"],
            "lcb_ev_c": p["lcb_ev_c"],
            "requested_contracts": p["requested_contracts"],
            # --- execution facts (AVAILABLE NOW: actual fills/fees/qty)
            "n_attempts": len(atts),
            "n_submitted": len(submitted),
            "attempt_statuses": "|".join(
                str(a["status"]) for a in atts),
            "exec_mode": next((a["exec_mode"] for a in submitted
                               if a["exec_mode"]), None),
            "exec_role": next((a["exec_role"] for a in submitted
                               if a["exec_role"]), None),
            "post_only": next((a["post_only"] for a in submitted
                               if a["post_only"] is not None), None),
            "submitted_limit_c": next(
                (a["limit_cents"] for a in reversed(submitted)
                 if a["limit_cents"] is not None), None),
            "submitted_qty": req_qty,
            "filled_qty": fill_qty,
            "fill_ratio": (fill_qty / req_qty) if req_qty else None,
            "actual_fill_px_c": avg_px,
            "actual_entry_fee_c": fee_total_c,
            "n_fills": len(fills),
            # --- outcome (AVAILABLE NOW: exit/settlement cash flows)
            "outcome_status": outc["status"] if outc else None,
            "settled_yes": outc["settled_yes"] if outc else None,
            "settlement_value_c": outc["settlement_value_c"] if outc else None,
            "actual_exit_px_c": outc["actual_exit_px_c"] if outc else None,
            "actual_exit_fee_c": outc["actual_exit_fee_c"] if outc else None,
            "exit_attribution": outc["exit_attribution"] if outc else None,
            "realized_pnl_c": outc["realized_pnl_c"] if outc else None,
            "capital_realized_c": outc["capital_realized_c"] if outc else None,
            "unresolved_reason": outc["unresolved_reason"] if outc else None,
            "mkt_yes_outcome": sm.get("yes_outcome"),
            "mkt_outcome_error": sm.get("outcome_error"),
            "settle_source": sm.get("settle_source"),
            "settle_verdict_conflicts": sm.get("verdict_conflicts"),
            # --- flags
            "has_ev": 1, "has_attempt": int(bool(atts)),
            "has_fill": int(bool(fills)), "has_outcome": int(bool(outc)),
            "has_settle_truth": int(bool(sm)),
        })
        for f in fills:
            fill_rows.append({
                "decision_id": did, "candidate_id": cand,
                "fill_id": f["fill_id"], "ticker": f["ticker"],
                "side": f["side"], "action": f["action"],
                "contracts": f["contracts"], "price_cents": f["price_cents"],
                "fee_dollars": f["fee_dollars"], "role": f["role"],
                "entry_or_exit": f["entry_or_exit"], "is_exit": f["is_exit"],
                "created_time": f["created_time"],
            })
    return parents_rows, fill_rows, orphan_attempts


def funnel_summary(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    agg: Dict[Tuple, Dict[str, Any]] = {}
    for r in rows:
        k = (r["category"], r["asset"], r["side"], r["ev_stage"])
        a = agg.setdefault(k, {"n": 0, "submitted": 0.0, "filled": 0.0,
                               "exp_ev": 0.0, "pnl": 0.0, "fees": 0.0,
                               "pnl_n": 0})
        a["n"] += 1
        a["submitted"] += r["submitted_qty"] or 0
        a["filled"] += r["filled_qty"] or 0
        a["exp_ev"] += r["net_ev_exp_c"] or 0
        a["fees"] += r["actual_entry_fee_c"] or 0
        if r["realized_pnl_c"] is not None:
            a["pnl"] += r["realized_pnl_c"]
            a["pnl_n"] += 1
    return [
        {"category": k[0], "asset": k[1], "side": k[2], "ev_stage": k[3], **v}
        for k, v in sorted(agg.items(), key=lambda kv: (-kv[1]["n"], kv[0]))
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hours", type=float, default=48.0)
    ap.add_argument("--since", default=None, help="ISO UTC lower bound")
    ap.add_argument("--until", default=None, help="ISO UTC upper bound")
    ap.add_argument("--asset", default=None)
    ap.add_argument("--side", default=None, choices=["YES", "NO"])
    ap.add_argument("--limit", type=int, default=5000)
    ap.add_argument("--out-dir", default="reports")
    ap.add_argument("--audit-db", default="data/decision_audit.db")
    ap.add_argument("--attempts-db", default="data/kalshi_order_attempts.db")
    ap.add_argument("--fills-db", default="data/kalshi_fills.db")
    ap.add_argument("--15m-db", dest="db15", default="data/kalshi_15m_audit.db")
    args = ap.parse_args()

    t1 = _parse_dt(args.until) if args.until else time.time()
    t0 = (_parse_dt(args.since) if args.since
          else t1 - args.hours * 3600.0)

    con = sqlite3.connect(
        f"file:{args.audit_db}?mode=ro", uri=True, timeout=30)
    con.execute(
        f"ATTACH 'file:{args.attempts_db}?mode=ro' AS oa")
    con.execute(f"ATTACH 'file:{args.fills_db}?mode=ro' AS f")
    con.execute(f"ATTACH 'file:{args.db15}?mode=ro' AS a15")

    t_start = time.time()
    # Context cohort: newest --limit decision rows in the window.
    parents = load_parents(con, t0, t1, args.limit)
    all_attempts = load_attempts(con, t0, t1)
    # Attempt-anchored parents: fetched by indexed candidate_id regardless of
    # the cohort limit, so every attempt can attach to its parent even when the
    # window is clipped to the newest decision rows.
    att_cands = sorted({a["cand"] for a in all_attempts if a["cand"]})
    att_parents = load_parents_by_candidates(con, att_cands)
    if args.asset:
        parents = [p for p in parents
                   if (p["asset"] or "").upper() == args.asset.upper()]
    if args.side:
        parents = [p for p in parents if p["side"] == args.side]
    seen = {(p["decision_id"], p["side"]) for p in parents}
    parents += [p for p in att_parents
                if (p["decision_id"], p["side"]) not in seen]
    dids = [p["decision_id"] for p in parents]
    print(f"[waterfall] parents={len(parents)} "
          f"(+{len(att_parents)} attempt-anchored) window "
          f"{_iso(t0)}..{_iso(t1)} ({time.time()-t_start:.1f}s)")

    coids = [a["client_order_id"] for a in all_attempts
             if a["client_order_id"]]
    fills_m = load_fills(con, coids)
    outcomes_m = load_outcomes(con, dids)
    cand_to_ticker = {}
    for p in parents:
        cand_to_ticker.setdefault(
            p["decision_id"].split(":")[0], p["ticker"])
    settle_m = load_settlement(
        con, [p["ticker"] for p in parents], cand_to_ticker)
    print(f"[waterfall] attempts={len(all_attempts)} "
          f"fills={sum(len(v) for v in fills_m.values())} "
          f"outcomes={len(outcomes_m)} settle_markets={len(settle_m)} "
          f"({time.time()-t_start:.1f}s)")

    parents_rows, fill_rows, orphan_attempts = build_rows(
        parents, all_attempts, fills_m, outcomes_m, settle_m)
    funnel = funnel_summary(parents_rows)

    os.makedirs(args.out_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    p_csv = os.path.join(args.out_dir, f"execution_waterfall_{stamp}.csv")
    f_csv = os.path.join(args.out_dir,
                         f"execution_waterfall_fills_{stamp}.csv")
    j_path = os.path.join(args.out_dir,
                          f"execution_waterfall_{stamp}.json")
    if parents_rows:
        with open(p_csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(parents_rows[0].keys()))
            w.writeheader()
            w.writerows(parents_rows)
    if fill_rows:
        with open(f_csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(fill_rows[0].keys()))
            w.writeheader()
            w.writerows(fill_rows)
    covered_t0 = min(
        (p["decision_ts"] for p in parents), default=None)
    n_decisions_in_window = con.execute(
        "SELECT COUNT(*) FROM strategy_decisions "
        "WHERE decision_ts >= ? AND decision_ts < ?", (t0, t1)
    ).fetchone()[0]
    truncated = n_decisions_in_window > args.limit
    with open(j_path, "w") as fh:
        json.dump({
            "generated_utc": _iso(time.time()),
            "window": {"t0": t0, "t1": t1},
            "window_truncated_by_limit": truncated,
            "decisions_in_window": n_decisions_in_window,
            "decisions_loaded_limit": args.limit,
            "window_covered": (
                None if covered_t0 is None
                else {"t0": covered_t0, "t1": t1,
                      "note": ("parents clipped to newest --limit decision "
                               "rows; earlier candidates in [t0, covered_t0) "
                               "are missing and their attempts show as "
                               "orphans") if truncated else None}
            ),
            "parents": len(parents_rows),
            "settlement_coverage": {
                "rows_with_settle_truth": sum(
                    r["has_settle_truth"] for r in parents_rows),
                "by_source": {
                    src: sum(1 for r in parents_rows
                             if r["settle_source"] == src)
                    for src in sorted(
                        {r["settle_source"] for r in parents_rows}
                        - {None})
                },
                "note": ("a15_audit = bounded audit extraction (ends "
                         "~Oct 14); outcomes_table = live authoritative "
                         "strategy_decision_outcomes verdict. Rows "
                         "without settle truth are excluded from any "
                         "settlement-P&L reading, not counted as losses."),
            },
            "orphan_attempts": len(orphan_attempts),
            "orphan_attempt_ids": [
                a["attempt_id"] for a in orphan_attempts[:200]
            ],
            "funnel": funnel,
            "evidence_available_now": [
                "decision-time edge decomposition",
                "actual fills and fees", "submitted/filled quantity",
                "exit/settlement outcome",
            ],
            "evidence_requires_more": [
                "estimated arrival-time repricing",
                "counterfactual depth at estimated arrival",
                "queue-conditioned counterfactual fills",
                "latency-vs-selection attribution",
            ],
        }, fh, indent=2)

    # console funnel
    print(f"\n{'category':<28}{'asset':<6}{'side':<5}{'ev_stage':<26}"
          f"{'n':>6}{'subm':>8}{'fill':>8}{'exp_ev_c':>12}"
          f"{'fees_c':>10}{'pnl_c':>12}")
    for r in funnel:
        print(f"{r['category']:<28}{r['asset'] or '?':<6}"
              f"{r['side'] or '?':<5}{r['ev_stage']:<26}"
              f"{r['n']:>6}{r['submitted']:>8.1f}{r['filled']:>8.1f}"
              f"{r['exp_ev']:>12.1f}{r['fees']:>10.1f}{r['pnl']:>12.1f}")
    print(f"\n[waterfall] wrote {p_csv}")
    if fill_rows:
        print(f"[waterfall] wrote {f_csv}")
    print(f"[waterfall] wrote {j_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
