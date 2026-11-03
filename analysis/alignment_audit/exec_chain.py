"""Execution-correctness ledger: approved intent -> wire -> exchange -> fill.

Read-only on the small stores; writes exec_chain tables + findings to the
audit output dir.  Covers the last N days of attempts.
"""
import json
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "audit_output_alignment_20261101"
DAYS = float(__import__("sys").argv[1]) if len(__import__("sys").argv) > 1 else 3.0
CUTOFF = time.time() - DAYS * 86400


def ro(rel):
    p = (ROOT / rel).resolve().as_posix()
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    c.execute("PRAGMA query_only=1")
    return c


att = ro("data/kalshi_order_attempts.db")
fil = ro("data/kalshi_fills.db")
fac = ro("data/trade_attribution_fact.db")

report = {"cutoff": CUTOFF, "days": DAYS}

# ---- attempt lifecycle ----
rows = att.execute(
    "SELECT order_attempt_id, client_order_id, decision_id, intent_id, "
    "client_tag, run_id, process_id, status, created_at, updated_at, payload_json "
    "FROM order_attempts WHERE created_at > ?",
    (CUTOFF,),
).fetchall()
report["attempts_in_window"] = len(rows)
status = Counter(r[7] for r in rows)
report["status_counts"] = dict(status)

by_run = Counter(r[5] for r in rows)
report["attempts_by_run"] = dict(by_run)

# ---- payload parse: execution_contract fields ----
lane_c = Counter()
postonly_c = Counter()
for r in rows:
    try:
        pl = json.loads(r[10] or "{}")
    except Exception:
        pl = {}
    ec = pl.get("execution_contract") or {}
    lane_c[ec.get("admission_lane") or "none"] += 1
    postonly_c[str(ec.get("post_only"))] += 1
report["attempts_by_admission_lane"] = dict(lane_c)
report["attempts_post_only"] = dict(postonly_c)

# ---- join attempts -> fills ----
fills_by_coid = {}
fills_by_oid = {}
for f in fil.execute(
    "SELECT fill_id, order_id, client_order_id, market_ticker, side, action, "
    "quantity_cc, canonical_leg_price_cents, created_time, ingestion_source, intent_id "
    "FROM kalshi_fills"
):
    if f[2]:
        fills_by_coid.setdefault(f[2], []).append(f)
    if f[1]:
        fills_by_oid.setdefault(f[1], []).append(f)

# ---- attribution order events ----
ord_events = defaultdict(list)
for e in fac.execute(
    "SELECT event_type, client_order_id, order_id, fill_id, order_status, "
    "ticker, side, price_cents, event_ts FROM trade_attribution_fact "
    "WHERE event_type IN ('order','fill')"
):
    key = e[1] or e[2] or e[3]
    if key:
        ord_events[key].append(e)

# ---- per-attempt resolution ----
chain = []
missing_fill = 0
filled = 0
unknown = []
for r in rows:
    oa_id, coid, dec_id, intent, tag, run, pid, st, c_at, u_at, pl = r
    f = fills_by_coid.get(coid) or []
    evs = ord_events.get(coid) or []
    ex_oid = None
    for e in evs:
        if e[2]:
            ex_oid = e[2]
    chain.append(
        {
            "order_attempt_id": oa_id,
            "client_order_id": coid,
            "decision_id": dec_id,
            "intent_id": intent,
            "run_id": run,
            "status": st,
            "created_at": c_at,
            "exchange_order_id": ex_oid,
            "n_fills": len(f),
            "fill_ids": [x[0] for x in f],
            "n_order_events": len(evs),
        }
    )
    if st == "FILLED":
        filled += 1
        if not f:
            missing_fill += 1
    if st in ("SUBMISSION_UNKNOWN", "SUBMITTING", "PERSISTED"):
        unknown.append(chain[-1])

report["filled_attempts"] = filled
report["filled_attempts_missing_fill_row"] = missing_fill
report["unresolved_attempts"] = {
    "count": len(unknown),
    "by_status": dict(Counter(u["status"] for u in unknown)),
    "by_run": dict(Counter(u["run_id"] for u in unknown)),
}

# fills with no attempt join (unmatched fills)
attempt_coids = {r[1] for r in rows}
fills_no_attempt = [
    coid for coid in fills_by_coid if coid and coid not in attempt_coids
]
report["fills_with_client_order_not_in_attempt_window"] = len(fills_no_attempt)

# ---- write the chain ----
(OUT / "exec_chain.json").write_text(json.dumps(chain, indent=1))
(OUT / "exec_chain_report.json").write_text(json.dumps(report, indent=1, default=str))
print(json.dumps(report, indent=1, default=str))
