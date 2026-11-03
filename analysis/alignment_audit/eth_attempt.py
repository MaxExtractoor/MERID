"""Extract all durable records for ETH candidate cid-0a08bfe910c6 / trace b9dcd87e."""
import json
import sqlite3

conn = sqlite3.connect("file:data/decision_audit.db?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

print("=== strategy_decisions ===")
for r in conn.execute(
    "SELECT * FROM strategy_decisions WHERE candidate_id LIKE ? OR decision_id LIKE ?",
    ("%0a08bfe%", "%b9dcd87e%"),
):
    print(dict(r))

for tbl in ("strategy_decision_events", "strategy_decision_snapshots",
            "strategy_decision_side_ev", "strategy_decision_outcomes"):
    try:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({tbl})")]
        key = "decision_id" if "decision_id" in cols else cols[0]
        print(f"\n=== {tbl} (cols={cols[:12]}) ===")
        q = (f"SELECT * FROM {tbl} WHERE decision_id IN "
             f"(SELECT decision_id FROM strategy_decisions "
             f"WHERE candidate_id LIKE '%0a08bfe%' OR decision_id LIKE '%b9dcd87e%') "
             f"LIMIT 20")
        for r in conn.execute(q):
            d = dict(r)
            print({k: (v[:300] if isinstance(v, str) and len(v) > 300 else v)
                   for k, v in d.items()})
    except Exception as e:
        print(f"{tbl}: {e}")
conn.close()
