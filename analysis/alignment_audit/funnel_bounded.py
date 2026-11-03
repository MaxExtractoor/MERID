"""Bounded funnel — indexed columns only, scoped to current run + aggregates."""
import json
import sqlite3
from collections import Counter

RUN = "20261101202100_13076_42914002"  # entries-enabled process
db = sqlite3.connect("file:data/decision_audit.db?mode=ro", uri=True)
db.row_factory = sqlite3.Row

print("=== current-run decisions by reason_code ===")
for r in db.execute(
    "SELECT decision, primary_reason_code, COUNT(*) n FROM strategy_decisions "
    "WHERE run_id=? GROUP BY decision, primary_reason_code ORDER BY n DESC", (RUN,)):
    print(f"  {str(r['decision']):12s} {str(r['primary_reason_code']):52s} {r['n']}")

print("\n=== current-run ENTER by asset x side x lane ===")
for r in db.execute(
    "SELECT asset, selected_side, admission_lane, COUNT(*) n FROM "
    "strategy_decisions WHERE run_id=? AND decision='ENTER' GROUP BY asset, "
    "selected_side, admission_lane ORDER BY n DESC", (RUN,)):
    print(f"  {str(r['asset']):5s} {str(r['selected_side']):5s} "
          f"{str(r['admission_lane']):30s} {r['n']}")

print("\n=== current-run events (indexed idx_sde_run_type) ===")
for r in db.execute(
    "SELECT event_type, reason_code, COUNT(*) n FROM strategy_decision_events "
    "WHERE run_id=? GROUP BY event_type, reason_code ORDER BY n DESC LIMIT 30",
    (RUN,)):
    print(f"  {str(r['event_type']):28s} {str(r['reason_code']):52s} {r['n']}")

print("\n=== failed-gate mix, current run (bounded rows) ===")
fc = Counter()
n = 0
for r in db.execute(
    "SELECT all_failed_gates_json FROM strategy_decisions WHERE run_id=?",
    (RUN,)):
    n += 1
    try:
        for g in json.loads(r["all_failed_gates_json"] or "[]"):
            fc[g] += 1
    except Exception:
        pass
print(f"  rows: {n}")
for g, c in fc.most_common(25):
    print(f"  {g:46s} {c}")
db.close()
print("DONE")
