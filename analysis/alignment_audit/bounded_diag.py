"""Bounded writer-stall diagnostics — fresh ro conn, no scans."""
import os
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
db = ROOT / "data" / "decision_audit.db"

print("== file/disk ==")
for suf in ("", "-wal", "-shm"):
    p = Path(str(db) + suf)
    if p.exists():
        print(p.name, "MB:", round(p.stat().st_size / 1e6, 1), "mtime:", time.ctime(p.stat().st_mtime))
print("disk free GB:", round(__import__("shutil").disk_usage(db.parent).free / 1e9, 1))

con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
con.execute("PRAGMA busy_timeout=2000")
print("== fresh commit watermark ==")
r = con.execute("SELECT MAX(decision_ts) FROM strategy_decisions").fetchone()
print("newest decision_ts:", r[0], "lag_s:", round(time.time() - (r[0] or 0)))
print("== plans ==")
cut = time.time() - 7 * 86400
print("-- parent select:")
for row in con.execute(
    "EXPLAIN QUERY PLAN SELECT decision_id FROM strategy_decisions WHERE decision_ts < ? ORDER BY decision_ts LIMIT 5",
    (cut,),
):
    print("  ", row[3])
print("-- child delete (side_ev):")
for row in con.execute(
    "EXPLAIN QUERY PLAN DELETE FROM strategy_decision_side_ev WHERE decision_id IN (?,?,?)",
    ("a", "b", "c"),
):
    print("  ", row[3])
print("-- child delete (events):")
for row in con.execute(
    "EXPLAIN QUERY PLAN DELETE FROM strategy_decision_events WHERE decision_id IN (?,?,?)",
    ("a", "b", "c"),
):
    print("  ", row[3])
print("-- heartbeat prune:")
for row in con.execute(
    "EXPLAIN QUERY PLAN DELETE FROM decision_audit_heartbeats WHERE created_at < ?", (cut,)
):
    print("  ", row[3])
print("-- settlement join:")
for row in con.execute(
    "EXPLAIN QUERY PLAN SELECT d.decision_id FROM strategy_decisions d "
    "JOIN strategy_decision_outcomes o ON d.decision_id=o.decision_id "
    "WHERE d.ticker='X' AND o.outcome_status='PENDING' AND ABS(d.close_ts - 1.0) <= 900.0"
):
    print("  ", row[3])
con.close()
