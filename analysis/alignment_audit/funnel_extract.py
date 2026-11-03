"""Funnel extract v1 — decision stages, block reasons, submit outcomes.

Read-only. Aggregates durable audit stores into per-asset/side/lane counts:
decision reason mix, gate failures, lane admissions, order-attempt outcomes.
"""
import json
import sqlite3
from collections import Counter

OUT = []

def emit(s=""):
    OUT.append(s)
    print(s)

db = sqlite3.connect("file:data/decision_audit.db?mode=ro", uri=True)
db.row_factory = sqlite3.Row

# --- decision-level funnel ---------------------------------------------------
emit("=== decisions by primary_reason_code (all time) ===")
for r in db.execute(
    "SELECT primary_reason_code, decision, COUNT(*) n FROM strategy_decisions "
    "GROUP BY primary_reason_code, decision ORDER BY n DESC LIMIT 30"):
    emit(f"  {r['primary_reason_code']:50s} {r['decision']:10s} {r['n']}")

emit("\n=== decisions by asset x selected_side x admission_lane (ENTER only) ===")
for r in db.execute(
    "SELECT asset, selected_side, admission_lane, COUNT(*) n FROM strategy_decisions "
    "WHERE decision='ENTER' GROUP BY asset, selected_side, admission_lane ORDER BY n DESC"):
    emit(f"  {r['asset']:5s} {str(r['selected_side']):5s} {str(r['admission_lane']):28s} {r['n']}")

emit("\n=== top failed gates (all_failed_gates_json, exploded) ===")
fc = Counter()
seen = 0
for r in db.execute("SELECT all_failed_gates_json FROM strategy_decisions LIMIT 200000"):
    seen += 1
    try:
        for g in json.loads(r["all_failed_gates_json"] or "[]"):
            fc[g] += 1
    except Exception:
        pass
emit(f"  rows scanned: {seen}")
for g, n in fc.most_common(25):
    emit(f"  {g:45s} {n}")

# --- event-level funnel ------------------------------------------------------
emit("\n=== event_type counts ===")
for r in db.execute(
    "SELECT event_type, reason_code, COUNT(*) n FROM strategy_decision_events "
    "GROUP BY event_type, reason_code ORDER BY n DESC LIMIT 30"):
    emit(f"  {r['event_type']:24s} {str(r['reason_code']):55s} {r['n']}")

db.close()

# --- order attempts ----------------------------------------------------------
emit("\n=== order_attempts schema ===")
conn2 = sqlite3.connect("file:data/kalshi_order_attempts.db?mode=ro", uri=True)
conn2.row_factory = sqlite3.Row
cols = [r[1] for r in conn2.execute("PRAGMA table_info(order_attempts)")]
emit(f"  {cols}")
emit("\n=== order_attempts outcome mix ===")
outcol = next((c for c in cols if c in
               ("status", "outcome", "result", "state", "rejection_reason",
                "reason")), None)
if outcol:
    for r in conn2.execute(
        f"SELECT {outcol} k, COUNT(*) n FROM order_attempts GROUP BY {outcol} "
        f"ORDER BY n DESC LIMIT 20"):
        emit(f"  {str(r['k']):50s} {r['n']}")
conn2.close()
emit("\nDONE")
