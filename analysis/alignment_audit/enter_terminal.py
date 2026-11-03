"""Terminal events for the 13 ENTER decisions in the current run."""
import json
import sqlite3

RUN = "20261101202100_13076_42914002"
db = sqlite3.connect("file:data/decision_audit.db?mode=ro", uri=True)
db.row_factory = sqlite3.Row

ids = [r[0] for r in db.execute(
    "SELECT decision_id FROM strategy_decisions WHERE run_id=? AND decision='ENTER'",
    (RUN,))]
print(f"{len(ids)} ENTER decisions")

for did in ids:
    d = db.execute(
        "SELECT decision_ts_iso, asset, ticker, selected_side, admission_lane "
        "FROM strategy_decisions WHERE decision_id=?", (did,)).fetchone()
    evs = db.execute(
        "SELECT event_ts_utc, event_type, reason_code FROM "
        "strategy_decision_events WHERE decision_id=? ORDER BY event_ts",
        (did,)).fetchall()
    print(f"\n{d['decision_ts_iso'][:19]} {d['asset']} {d['selected_side']} "
          f"{d['admission_lane']} {d['ticker']}")
    for e in evs:
        print(f"   {e['event_ts_utc'][11:23]} {e['event_type']:22s} "
              f"{str(e['reason_code'])[:70]}")
db.close()
print("DONE")
