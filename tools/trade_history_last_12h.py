#!/usr/bin/env python3
"""Pull last 12 hours of Kalshi fills, match to order decisions and telemetry,
and flag side mismatches. Output: console summary + reports/trade_history_last_12h.csv"""

import csv
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).parent.parent
DB = ROOT / "data" / "kalshi_fills.db"
OD_DIR = ROOT / "logs"
REPORT_DIR = ROOT / "reports"
REPORT = REPORT_DIR / "trade_history_last_12h.csv"

WINDOW_HOURS = 12


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        # ISO string?
        return datetime.fromisoformat(str(v)).timestamp()
    except Exception:
        try:
            return float(v)
        except (ValueError, TypeError):
            return None


def money_cents(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(round(Decimal(str(v)) * 100))
    except (InvalidOperation, ValueError):
        return None


def held_outcome_from_trade(side: str, action: str) -> Optional[str]:
    """Given the executed contract side and action, return the outcome the position is long."""
    s = (side or "").lower()
    a = (action or "").lower()
    if not s or not a:
        return None
    if a == "buy":
        return s
    # sell YES -> long NO; sell NO -> long YES
    return "no" if s == "yes" else "yes"


def canonical_action_for_held(held_side: str, action: str) -> str:
    """Return the canonical action (buy or sell) in held-side space.

    BUY NO and SELL YES both mean long NO; the canonical form is BUY held_side.
    """
    a = (action or "").lower()
    if a == "buy":
        return "buy"
    # sell original_side -> buy held_side
    return "buy"


def held_leg_price_cents(ledger_side: str, action: str, yes_price_d: Any, no_price_d: Any) -> Optional[int]:
    """Return the cost basis (cents) for the held outcome, not the traded contract."""
    s = (ledger_side or "").lower()
    a = (action or "").lower()
    if not s or not a:
        return None
    try:
        if s == "yes":
            price = Decimal(str(yes_price_d)) if yes_price_d is not None else None
        else:
            price = Decimal(str(no_price_d)) if no_price_d is not None else None
        if price is None:
            return None
        price_cents = int(round(price * 100))
        if a == "buy":
            return price_cents
        # sell: long the opposite, cost basis is 100 - traded price
        return 100 - price_cents
    except (InvalidOperation, ValueError, TypeError):
        return None


def signed_yes_delta(held_side: str, qty_cc: int, action: str) -> int:
    """Canonical signed-YES exposure: + = long YES, - = long NO."""
    h = (held_side or "").lower()
    a = (action or "").lower()
    sign = -1 if a == "sell" else 1
    # This is only used after we already know held_side, so the sign must reflect that.
    if h == "yes":
        return qty_cc
    return -qty_cc


def qty_cc_from_row(row: sqlite3.Row) -> int:
    for col in ["quantity_cc", "count_fp", "count"]:
        if col in row.keys():
            v = row[col]
            if v is not None:
                try:
                    return int(v)
                except (ValueError, TypeError):
                    pass
    return 0


def decision_held_side(od: Dict[str, Any]) -> Optional[str]:
    """The outcome the order decision is actually exposed to."""
    contract = (od.get("contract") or "").lower()
    action = (od.get("action") or "").lower()
    if not contract or not action:
        return None
    if action == "buy":
        return contract
    return "no" if contract == "yes" else "yes"


def find_closest_telemetry(ticker: str, fill_ts: float, telemetry_by_ticker: Dict[str, List[Dict]]) -> Optional[Dict]:
    candidates = telemetry_by_ticker.get(ticker, [])
    best = None
    best_gap = None
    for rec in candidates:
        ts = parse_ts(rec.get("event_ts_utc") or rec.get("ts"))
        if ts is None:
            continue
        gap = abs(ts - fill_ts)
        if best_gap is None or gap < best_gap:
            best = rec
            best_gap = gap
    return best


def load_order_decisions(coids: set, since: float, until: float) -> Dict[str, Dict]:
    """Load order_decisions jsonl (and rotated logs) for the given client_order_ids."""
    paths = [OD_DIR / "order_decisions.jsonl"]
    paths += sorted(OD_DIR.glob("order_decisions.jsonl.*"), key=lambda p: p.suffix, reverse=True)
    out: Dict[str, Dict] = {}
    for p in paths:
        if not p.exists():
            continue
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = parse_ts(rec.get("ts") or rec.get("created_time"))
                if ts is None or ts < since or ts > until:
                    continue
                coid = rec.get("client_order_id")
                if coid and coid in coids and coid not in out:
                    out[coid] = rec
    return out


def load_telemetry(tickers: set, since: float, until: float) -> Dict[str, List[Dict]]:
    """Load decision_telemetry jsonl records for the given tickers."""
    paths = [OD_DIR / "decision_telemetry.jsonl"]
    paths += sorted(OD_DIR.glob("decision_telemetry.jsonl.*"), key=lambda p: p.suffix, reverse=True)
    out: Dict[str, List[Dict]] = defaultdict(list)
    for p in paths:
        if not p.exists():
            continue
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = parse_ts(rec.get("event_ts_utc") or rec.get("ts"))
                if ts is None or ts < since or ts > until:
                    continue
                ticker = rec.get("ticker") or rec.get("market_id") or rec.get("market_ticker")
                if ticker and ticker in tickers:
                    out[ticker].append(rec)
    return out


def main() -> int:
    now = now_utc()
    since = now - timedelta(hours=WINDOW_HOURS)
    since_iso = since.isoformat()
    since_ts = since.timestamp()
    until_ts = now.timestamp()

    print(f"Pulling trade history from {since_iso} to {now.isoformat()}")

    if not DB.exists():
        print(f"Database not found: {DB}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM kalshi_fills WHERE created_time >= ? ORDER BY created_time", (since_iso,))
    rows = cur.fetchall()
    print(f"Found {len(rows)} fill rows in DB")

    if not rows:
        print("No fills in the last 12 hours.")
        return 0

    coids = {r["client_order_id"] for r in rows if r["client_order_id"]}
    tickers = {r["market_ticker"] or r["market_id"] for r in rows if (r["market_ticker"] or r["market_id"])}

    od_by_coid = load_order_decisions(coids, since_ts, until_ts)
    telemetry_by_ticker = load_telemetry(tickers, since_ts, until_ts)
    print(f"Matched {len(od_by_coid)} order_decisions and telemetry for {len(telemetry_by_ticker)} tickers")

    REPORT_DIR.mkdir(exist_ok=True)
    fieldnames = [
        "created_time", "fill_id", "client_order_id", "order_id", "market_ticker", "market_id",
        "ledger_side", "ledger_action", "qty_cc", "count_fp",
        "yes_price_dollars", "no_price_dollars", "proceeds_dollars", "fee_cost",
        "db_canonical_position_side", "db_canonical_position_action", "db_canonical_leg_price_cents", "db_canonical_yes_delta_cc",
        "computed_held_side", "computed_canonical_action", "computed_leg_price_cents", "computed_signed_yes_delta_cc",
        "canonical_side_matches_db", "canonical_action_matches_db", "leg_price_matches_db",
        "od_contract", "od_action", "od_held_side", "od_allowed", "od_reason", "od_reject_reason",
        "od_side_matches_fill", "od_side_matches_computed",
        "dt_selected_side", "dt_p_yes", "dt_p_no", "dt_edge_pct", "dt_signal_side", "dt_strategy",
        "dt_side_matches_computed",
    ]

    summary: Dict[str, int] = {
        "total_fills": 0,
        "wrong_canonical_side": 0,
        "wrong_leg_price": 0,
        "fill_differs_from_order_decision": 0,
        "fill_differs_from_telemetry": 0,
        "exits": 0,
        "entries": 0,
    }

    with open(REPORT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for r in rows:
            summary["total_fills"] += 1
            created_time = r["created_time"]
            fill_ts = parse_ts(created_time) or 0.0
            ticker = r["market_ticker"] or r["market_id"]
            side = r["side"] or ""
            action = r["action"] or ""
            qty = qty_cc_from_row(r)

            yes_price = r["yes_price_dollars"]
            no_price = r["no_price_dollars"]

            computed_held = held_outcome_from_trade(side, action)
            computed_action = canonical_action_for_held(computed_held or "", action)
            computed_leg = held_leg_price_cents(side, action, yes_price, no_price)
            computed_signed = signed_yes_delta(computed_held, qty, action) if computed_held else None

            db_can_side = r["canonical_position_side"]
            db_can_action = r["canonical_position_action"]
            db_can_leg = r["canonical_leg_price_cents"]
            db_can_delta = r["canonical_yes_delta_cc"]

            can_side_match = (db_can_side or "").lower() == (computed_held or "").lower()
            can_action_match = (db_can_action or "").lower() == (computed_action or "").lower()
            leg_match = db_can_leg == computed_leg

            if not can_side_match:
                summary["wrong_canonical_side"] += 1
            if not leg_match:
                summary["wrong_leg_price"] += 1

            is_exit = bool(r["is_exit"]) or (r["entry_or_exit"] or "").lower() == "exit" or bool(r["reduce_only"])
            if is_exit:
                summary["exits"] += 1
            else:
                summary["entries"] += 1

            od = od_by_coid.get(r["client_order_id"]) if r["client_order_id"] else None
            od_contract = od.get("contract") if od else None
            od_action = od.get("action") if od else None
            od_held = decision_held_side(od) if od else None
            od_allowed = od.get("allowed") if od else None
            od_reason = od.get("reason") if od else None
            od_reject = od.get("reject_reason") if od else None

            od_side_match_fill = (od_held or "").lower() == (computed_held or "").lower()
            od_side_match_computed = (od_held or "").lower() == (computed_held or "").lower()
            if od and not od_side_match_fill:
                summary["fill_differs_from_order_decision"] += 1

            dt = find_closest_telemetry(ticker, fill_ts, telemetry_by_ticker)
            dt_selected = dt.get("selected_side") if dt else None
            dt_p_yes = dt.get("p_yes") or dt.get("prob_yes") if dt else None
            dt_p_no = dt.get("p_no") or dt.get("prob_no") if dt else None
            dt_edge = dt.get("edge_pct") or dt.get("edge") if dt else None
            dt_signal = dt.get("signal_side") if dt else None
            dt_strategy = dt.get("strategy") if dt else None

            dt_side_match = (dt_selected or "").lower() == (computed_held or "").lower()
            if dt and not dt_side_match:
                summary["fill_differs_from_telemetry"] += 1

            row_out = {
                "created_time": created_time,
                "fill_id": r["fill_id"],
                "client_order_id": r["client_order_id"],
                "order_id": r["order_id"],
                "market_ticker": r["market_ticker"],
                "market_id": r["market_id"],
                "ledger_side": side,
                "ledger_action": action,
                "qty_cc": qty,
                "count_fp": r["count_fp"],
                "yes_price_dollars": yes_price,
                "no_price_dollars": no_price,
                "proceeds_dollars": r["proceeds_dollars"],
                "fee_cost": r["fee_cost"],
                "db_canonical_position_side": db_can_side,
                "db_canonical_position_action": db_can_action,
                "db_canonical_leg_price_cents": db_can_leg,
                "db_canonical_yes_delta_cc": db_can_delta,
                "computed_held_side": computed_held,
                "computed_canonical_action": computed_action,
                "computed_leg_price_cents": computed_leg,
                "computed_signed_yes_delta_cc": computed_signed,
                "canonical_side_matches_db": can_side_match,
                "canonical_action_matches_db": can_action_match,
                "leg_price_matches_db": leg_match,
                "od_contract": od_contract,
                "od_action": od_action,
                "od_held_side": od_held,
                "od_allowed": od_allowed,
                "od_reason": od_reason,
                "od_reject_reason": od_reject,
                "od_side_matches_fill": od_side_match_fill,
                "od_side_matches_computed": od_side_match_computed,
                "dt_selected_side": dt_selected,
                "dt_p_yes": dt_p_yes,
                "dt_p_no": dt_p_no,
                "dt_edge_pct": dt_edge,
                "dt_signal_side": dt_signal,
                "dt_strategy": dt_strategy,
                "dt_side_matches_computed": dt_side_match,
            }
            writer.writerow(row_out)

    print(f"\nReport written to {REPORT}")
    print("\nSummary:")
    for k, v in summary.items():
        print(f"  {k}: {v}")

    if summary["wrong_canonical_side"]:
        print("\nALERT: canonical_position_side in the ledger does not match the actual held outcome for some fills.")
    if summary["fill_differs_from_order_decision"]:
        print("ALERT: some executed fills are on a different side than the order_decision that generated them.")
    if summary["fill_differs_from_telemetry"]:
        print("ALERT: some executed fills are on a different side than the telemetry's selected_side.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
