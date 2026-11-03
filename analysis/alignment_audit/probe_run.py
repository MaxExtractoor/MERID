"""Bounded read-only probe of decision_audit for a given run_id."""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = sys.argv[1] if len(sys.argv) > 1 else "20261101170353_14620_4f4ea1f9"


def ro(db_rel: str) -> sqlite3.Connection:
    p = (ROOT / db_rel).resolve()
    con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=1")
    return con


con = ro("data/decision_audit.db")
con.execute("PRAGMA temp_store=MEMORY")

print(f"--- strategy_decisions for run {RUN_ID} ---")
q = """SELECT decision, primary_reason_code, COUNT(*)
FROM strategy_decisions WHERE run_id=?
GROUP BY decision, primary_reason_code ORDER BY 3 DESC"""
for row in con.execute(q, (RUN_ID,)):
    print(row)

print("--- per-asset counts ---")
for row in con.execute(
    "SELECT asset, COUNT(*), MIN(decision_ts), MAX(decision_ts) FROM strategy_decisions WHERE run_id=? GROUP BY asset",
    (RUN_ID,),
):
    print(row)

print("--- join coverage ---")
for row in con.execute(
    """SELECT
      (SELECT COUNT(*) FROM strategy_decisions WHERE run_id=?) AS decisions,
      (SELECT COUNT(*) FROM strategy_decision_side_ev se JOIN strategy_decisions d ON se.decision_id=d.decision_id WHERE d.run_id=?) AS side_ev,
      (SELECT COUNT(*) FROM strategy_decision_snapshots s JOIN strategy_decisions d ON s.decision_id=d.decision_id WHERE d.run_id=?) AS snapshots,
      (SELECT COUNT(*) FROM strategy_decision_outcomes o JOIN strategy_decisions d ON o.decision_id=d.decision_id WHERE d.run_id=?) AS outcomes,
      (SELECT COUNT(*) FROM strategy_decision_events e WHERE e.run_id=?) AS events""",
    (RUN_ID,) * 5,
):
    print("decisions=%s side_ev=%s snapshots=%s outcomes=%s events=%s" % row)

print("--- admission lanes this run ---")
for row in con.execute(
    "SELECT admission_lane, admission_owner, COUNT(*) FROM strategy_decisions WHERE run_id=? GROUP BY 1,2 ORDER BY 3 DESC",
    (RUN_ID,),
):
    print(row)

print("--- outcome status this run ---")
for row in con.execute(
    """SELECT o.outcome_status, COUNT(*) FROM strategy_decision_outcomes o
       JOIN strategy_decisions d ON o.decision_id=d.decision_id WHERE d.run_id=? GROUP BY 1""",
    (RUN_ID,),
):
    print(row)
con.close()
