import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
run_id = sys.argv[1] if len(sys.argv) > 1 else "20261101134017_8144_53724ae9"
con = sqlite3.connect(f"file:{(ROOT / 'data/decision_audit.db').as_posix()}?mode=ro", uri=True)
r = con.execute(
    "SELECT decision_id, asset, ticker, selected_side, primary_reason_code, "
    "gate_results_json, all_failed_gates_json, reason_codes "
    "FROM strategy_decisions WHERE run_id=? AND decision='NO_TRADE' "
    "ORDER BY decision_ts DESC LIMIT 1",
    (run_id,),
).fetchone()
print(r[:5])
g = json.loads(r[5] or "{}")
print("gates:", len(g))
for k, v in g.items():
    print(" ", k, "=", json.dumps(v)[:160])
print("failed:", r[6])
print("reason_codes:", r[7])
con.close()
