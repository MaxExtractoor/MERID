"""Fast funnel: indexed columns only — decision reasons, event mix, lane cohorts."""
import sqlite3

db = sqlite3.connect("file:data/decision_audit.db?mode=ro", uri=True)
db.row_factory = sqlite3.Row

print("=== decisions by decision x primary_reason_code ===")
for r in db.execute(
    "SELECT decision, primary_reason_code, COUNT(*) n FROM strategy_decisions "
    "GROUP BY decision, primary_reason_code ORDER BY n DESC LIMIT 40"):
    print(f"  {str(r['decision']):10s} {str(r['primary_reason_code']):52s} {r['n']}")

print("\n=== ENTER by asset x side x lane ===")
for r in db.execute(
    "SELECT asset, selected_side, admission_lane, COUNT(*) n FROM "
    "strategy_decisions WHERE decision='ENTER' GROUP BY asset, selected_side, "
    "admission_lane ORDER BY n DESC"):
    print(f"  {str(r['asset']):5s} {str(r['selected_side']):5s} "
          f"{str(r['admission_lane']):32s} {r['n']}")

print("\n=== ROUTER_REJECTED reason mix ===")
for r in db.execute(
    "SELECT reason_code, COUNT(*) n FROM strategy_decision_events WHERE "
    "event_type='ROUTER_REJECTED' GROUP BY reason_code ORDER BY n DESC LIMIT 20"):
    print(f"  {str(r['reason_code']):64s} {r['n']}")

print("\n=== ROUTER_REJECTED by asset x lane ===")
for r in db.execute(
    "SELECT asset, json_extract(reason_detail_json,'$.decision_lane') lane, "
    "COUNT(*) n FROM strategy_decision_events WHERE event_type='ROUTER_REJECTED' "
    "GROUP BY asset, lane ORDER BY n DESC LIMIT 20"):
    print(f"  {str(r['asset']):5s} {str(r['lane']):32s} {r['n']}")

print("\n=== event_type totals ===")
for r in db.execute(
    "SELECT event_type, COUNT(*) n FROM strategy_decision_events GROUP BY "
    "event_type ORDER BY n DESC"):
    print(f"  {str(r['event_type']):30s} {r['n']}")

print("\n=== outcomes ===")
cols = [r[1] for r in db.execute("PRAGMA table_info(strategy_decision_outcomes)")]
print("outcome cols:", cols)
db.close()
print("DONE")
