"""Targeted lookup for the ETH candidate's durable records by exact decision_id."""
import json
import sqlite3

DID = "cand_1e80b87e7a6751664499bf1f:maker_bid"
CID = "cid-0a08bfe910c6"

conn = sqlite3.connect("file:data/decision_audit.db?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

print("=== strategy_decisions by exact ids ===")
for r in conn.execute(
    "SELECT decision_id, candidate_id, decision_ts_iso, decision, primary_reason_code, "
    "admission_lane, admission_owner, selected_side, gate_results_json, all_failed_gates_json "
    "FROM strategy_decisions WHERE decision_id=? OR candidate_id=?", (DID, CID)):
    d = dict(r)
    for k in ("gate_results_json", "all_failed_gates_json"):
        if d.get(k):
            try:
                d[k] = json.dumps(json.loads(d[k]), indent=1)[:4000]
            except Exception:
                pass
    print(d)

for tbl, key in (("strategy_decision_side_ev", None), ("strategy_decision_events", None),
                 ("strategy_decision_snapshots", None)):
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({tbl})")]
    print(f"\n=== {tbl} cols={cols} ===")
    idcol = next((c for c in ("decision_id", "candidate_id") if c in cols), None)
    if idcol:
        for r in conn.execute(f"SELECT * FROM {tbl} WHERE {idcol}=? OR "
                              f"{'candidate_id' if 'candidate_id' in cols else idcol}=? LIMIT 10",
                              (DID, CID)):
            d = dict(r)
            print({k: (v[:400] if isinstance(v, str) and len(v) > 400 else v) for k, v in d.items()})
conn.close()
print("DONE")
