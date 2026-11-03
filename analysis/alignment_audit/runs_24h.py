import json
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "audit_output_alignment_20261101"

con = sqlite3.connect(f"file:{(ROOT / 'data/decision_audit.db').as_posix()}?mode=ro", uri=True)
con.execute("PRAGMA query_only=1")
now = time.time()
rows = con.execute(
    "SELECT run_id, COUNT(*), MIN(decision_ts), MAX(decision_ts), "
    "SUM(CASE WHEN decision='ENTER' THEN 1 ELSE 0 END) "
    "FROM strategy_decisions WHERE decision_ts > ? GROUP BY run_id ORDER BY 3",
    (now - 30 * 3600,),
).fetchall()
(OUT / "runs_last30h.json").write_text(json.dumps(rows, indent=1))
for r in rows:
    print(r)
