"""Order-attempt lane x status and rejection-reason breakdown."""
import json
import sqlite3
from collections import Counter

c = sqlite3.connect("file:data/kalshi_order_attempts.db?mode=ro", uri=True)
cnt = Counter()
reasons = Counter()
sample = {}
for (pj, st) in c.execute("SELECT payload_json, status FROM order_attempts"):
    try:
        p = json.loads(pj)
    except Exception:
        cnt[("?", st)] += 1
        continue
    ec = p.get("execution_contract", {})
    lane = ec.get("admission_lane") or p.get("admission_lane") or "?"
    cnt[(lane, st)] += 1
    if st == "REJECTED":
        key = (p.get("rejection_reason") or p.get("reject_reason")
               or p.get("router_reason") or p.get("reason")
               or (p.get("result") or {}).get("reason")
               or p.get("error") or "n/a")
        reasons[str(key)[:90]] += 1
        sample.setdefault(str(key)[:90], pj[:600])

print("--- lane x status ---")
for k, v in cnt.most_common(25):
    print(" ", k, v)
print("--- rejection reasons ---")
for k, v in reasons.most_common(15):
    print(" ", k, v)
print("--- payload keys on REJECTED (first sample) ---")
if sample:
    first = next(iter(sample.values()))
    try:
        print(sorted(json.loads(first).keys()))
    except Exception:
        print(first[:400])
c.close()
print("DONE")
