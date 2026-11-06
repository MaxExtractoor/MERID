"""Observational monitor v2: maker/taker route-parity + sizing evidence.

For every pinned_fav_maker_only taker veto, looks for the maker-side
evaluation of the same opportunity (same ticker, +/-45s) and emits a paired
record — or `maker_sibling_not_observed` when none exists. Records exact
minutes_to_expiry for threshold checks (lane floor 300s / maker 90s /
global 180s are config-dependent, not inferred here).

Polls decision-feed API (read-only) + kalshi_order_attempts.db. Writes JSONL
to logs/_exec_monitor.jsonl. Never submits.
"""
import json, os, sqlite3, sys, time, urllib.request
from collections import defaultdict, deque
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
FEED = "http://127.0.0.1:8011/api/v1/kalshi-grid/decision-feed?limit=60"
OUT = BASE / "logs" / "_exec_monitor.jsonl"
ATTEMPTS = BASE / "data" / "kalshi_order_attempts.db"
POLL = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0

seen_attempt_rowid = 0
seen_events = set()
recent = defaultdict(lambda: deque(maxlen=400))  # ticker -> deque of events


def emit(kind, rec):
    rec["monitor_ts"] = time.time()
    rec["kind"] = kind
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    print(f"[{time.strftime('%H:%M:%S')}] {kind}: {json.dumps(rec, default=str)[:240]}", flush=True)


def poll_feed():
    try:
        with urllib.request.urlopen(FEED, timeout=10) as r:
            return json.load(r).get("events") or []
    except Exception:
        return []


def poll_attempts():
    global seen_attempt_rowid
    if not ATTEMPTS.exists():
        return
    try:
        con = sqlite3.connect(f"file:{ATTEMPTS}?mode=ro", uri=True, timeout=5)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT rowid,* FROM order_attempts WHERE rowid>? ORDER BY rowid",
            (seen_attempt_rowid,)).fetchall()
        con.close()
    except Exception:
        return
    for r in rows:
        seen_attempt_rowid = r["rowid"]
        try:
            pl = json.loads(r["payload_json"])
        except Exception:
            pl = {}
        o = pl.get("order") or {}
        req = o.get("stake_cap_clipped_from_count_fp") or o.get("count_fp")
        wire = o.get("count_fp")
        path = ("clipped_below_six" if o.get("stake_cap_clipped_from_count_fp")
                else ("six_unchanged" if str(wire).rstrip("0.") in ("6", "")
                      else "other"))
        emit("order_attempt", {
            "rowid": r["rowid"], "status": r["status"], "created_at": r["created_at"],
            "ticker": o.get("ticker"), "side": o.get("side"), "action": o.get("action"),
            "price_cents": o.get("price_cents") or o.get("yes_price"),
            "decision_lane": pl.get("decision_lane") or o.get("decision_lane"),
            "requested_count_fp": req, "wire_count_fp": wire,
            "clipped_from": o.get("stake_cap_clipped_from_count_fp"),
            "sizing_path": path,
            "route_reason": pl.get("route_reason") or pl.get("reason"),
            "acknowledged_count_fp": o.get("acknowledged_count_fp"),
        })


def process_feed():
    for e in poll_feed():
        sig = (e.get("candidate_id"), e.get("ts"), e.get("reason"))
        if sig in seen_events:
            continue
        seen_events.add(sig)
        t = e.get("ticker") or ""
        lane = e.get("decision_lane") or (e.get("detail") or {}).get("decision_lane")
        reason = e.get("reason") or ""
        det = e.get("detail") or {}
        is_pf = lane == "pinned_fav" or "pinned_fav" in reason or "maker_bid" in str(lane)
        if not is_pf:
            continue
        rec = {
            "ts": e.get("ts"), "ticker": t, "asset": e.get("asset"),
            "lane": lane, "reason": reason, "kind_e": e.get("kind"),
            "candidate_id": e.get("candidate_id"),
            "yes_bid": det.get("yes_bid_cents"), "yes_ask": det.get("yes_ask_cents"),
            "no_bid": det.get("no_bid_cents"), "no_ask": det.get("no_ask_cents"),
            "mte": det.get("minutes_to_expiry"),
            "book_state": det.get("book_state") or det.get("book_health"),
        }
        recent[t].append(rec)

        if reason == "pinned_fav_maker_only":
            # Look for a maker-side sibling eval of the same opportunity.
            # Match precedence: (1) exact shared candidate_id when both events
            # carry one; (2) heuristic same-ticker within +/-45s.  The method
            # and time delta are recorded — a heuristic pair is a hypothesis,
            # not proof both routes saw one opportunity.
            try:
                ts_e = time.mktime(time.strptime(e["ts"][:19], "%Y-%m-%dT%H:%M:%S"))
            except Exception:
                ts_e = None
            sibling = None
            match_method = None
            time_delta = None
            cid = e.get("candidate_id")
            if cid:
                for r2 in list(recent[t]):
                    if r2 is not rec and r2.get("candidate_id") == cid:
                        sibling, match_method = r2, "exact_candidate_id"
                        break
            if sibling is None:
                for r2 in list(recent[t]):
                    if r2 is rec:
                        continue
                    if "maker" in str(r2.get("reason", "")) + str(r2.get("lane", "")) \
                            and r2.get("reason") != "pinned_fav_maker_only":
                        try:
                            ts2 = time.mktime(time.strptime(r2["ts"][:19], "%Y-%m-%dT%H:%M:%S"))
                        except Exception:
                            ts2 = None
                        if ts_e is None or ts2 is None or abs(ts2 - ts_e) <= 45:
                            sibling = r2
                            match_method = "heuristic_ticker_time"
                            time_delta = (round(ts2 - ts_e, 2)
                                          if (ts_e and ts2) else None)
                            break
            rec2 = dict(rec)
            rec2["maker_sibling"] = sibling if sibling else "maker_sibling_not_observed"
            rec2["match_method"] = match_method
            rec2["sibling_time_delta_s"] = time_delta
            emit("taker_veto_parity", rec2)
        elif lane == "pinned_fav" or "maker_bid" in str(lane):
            emit("pf_eval", rec)


if __name__ == "__main__":
    print(f"[monitor v2] polling {POLL}s -> {OUT}", flush=True)
    try:
        con = sqlite3.connect(f"file:{ATTEMPTS}?mode=ro", uri=True, timeout=5)
        seen_attempt_rowid = con.execute("SELECT COALESCE(MAX(rowid),0) FROM order_attempts").fetchone()[0]
        con.close()
        print(f"[monitor v2] attempt baseline rowid={seen_attempt_rowid}", flush=True)
    except Exception as ex:
        print(f"[monitor v2] baseline failed: {ex}", flush=True)
    while True:
        poll_attempts()
        process_feed()
        time.sleep(POLL)
