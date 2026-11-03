"""Order-attempt outcome mix: status, run, lane, rejection reasons."""
import json
import sqlite3
from collections import Counter

c = sqlite3.connect("file:data/kalshi_order_attempts.db?mode=ro", uri=True)
print("total attempts:", c.execute("SELECT COUNT(*) FROM order_attempts").fetchone()[0])
for r in c.execute("SELECT status, COUNT(*) FROM order_attempts GROUP BY status"):
    print(" ", r)
print("--- by run_id x status ---")
for r in c.execute(
    "SELECT run_id, status, COUNT(*) FROM order_attempts GROUP BY run_id, "
    "status ORDER BY 1 DESC, 3 DESC"):
    print(" ", r)
print("--- lane x status ---")
cnt = Counter()
for (pj, st) in c.execute("SELECT payload_json, status FROM order_attempts"):
    try:
        lane = json.loads(pj).get("execution_contract", {}).get("admission_lane", "?")
    except Exception:
        lane = "?"
    cnt[(lane, st)] += 1
for k, v in cnt.most_common(20):
    print(" ", k, v)
print("--- rejection keys in payload ---")
rc = Counter()
rows = c.execute(
    "SELECT payload_json FROM order_attempts WHERE status='REJECTED'")
for (pj,) in rows:
    try:
        p = json.loads(pj)
        key = (p.get("rejection_reason") or p.get("reject_reason")
               or p.get("router_reason") or p.get("reason")
               or p.get("result", {}).get("reason")
               or "n/a")
    except Exception:
        key = "?"
    rc[str(key)[:90]] += 1
for k, v in rc.most_common(15):
    print(" ", k, v)
c.close()
print("DONE")
