import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
con = sqlite3.connect(f"file:{(ROOT / 'data/decision_audit.db').as_posix()}?mode=ro", uri=True)
con.execute("PRAGMA query_only=1")
now = time.time()
for r in con.execute(
    "SELECT cycle_id, tick, decisions_expected, decisions_persisted, "
    "side_ev_expected, side_ev_persisted, ledger_write_latency_ms, "
    "ledger_error_count, created_at FROM decision_audit_heartbeats "
    "WHERE created_at > ? ORDER BY created_at DESC LIMIT 15",
    (now - 3 * 3600,),
):
    print(r)
con.close()
