"""Offline TRUNCATE checkpoint on the audit db — exclusive access, no
competing readers/writers. Reports result tuple and timing."""
import sqlite3
import time

t0 = time.time()
conn = sqlite3.connect("data/decision_audit.db", timeout=300)
print("opened", round(time.time() - t0, 1))
t1 = time.time()
res = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
print(f"checkpoint result (busy, log_frames, checkpointed): {res} "
      f"in {time.time() - t1:.1f}s")
# verify readable
n = conn.execute("SELECT COUNT(*) FROM strategy_decisions").fetchone()[0]
print(f"strategy_decisions rows: {n}  read_ok")
conn.close()
print("DONE", round(time.time() - t0, 1))
