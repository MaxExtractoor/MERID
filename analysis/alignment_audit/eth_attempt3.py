"""Full reason_detail_json for the ETH ROUTER_REJECTED event + order attempt row."""
import json
import sqlite3

DID = "cand_1e80b87e7a6751664499bf1f:maker_bid"

conn = sqlite3.connect("file:data/decision_audit.db?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
print("=== ROUTER_REJECTED full detail ===")
for r in conn.execute(
    "SELECT event_ts_utc, event_type, reason_code, reason_detail_json FROM "
    "strategy_decision_events WHERE decision_id=? AND event_type=?",
    (DID, "ROUTER_REJECTED")):
    print(r["event_ts_utc"], r["reason_code"])
    try:
        print(json.dumps(json.loads(r["reason_detail_json"]), indent=2))
    except Exception:
        print(r["reason_detail_json"])
conn.close()

print("\n=== order attempts db ===")
conn2 = sqlite3.connect("file:data/kalshi_order_attempts.db?mode=ro", uri=True)
conn2.row_factory = sqlite3.Row
tables = [r[0] for r in conn2.execute(
    "SELECT name FROM sqlite_master WHERE type='table'")]
print("tables:", tables)
for t in tables:
    cols = [r[1] for r in conn2.execute(f"PRAGMA table_info({t})")]
    hit = None
    for c in ("ticker", "market_ticker", "symbol"):
        if c in cols:
            hit = c
            break
    if hit:
        q = (f"SELECT * FROM {t} WHERE {hit}='KXETH15M-26NOV011545-45' "
             f"ORDER BY rowid DESC LIMIT 5")
        try:
            for r in conn2.execute(q):
                d = dict(r)
                print({k: (v[:500] if isinstance(v, str) and len(v) > 500 else v)
                       for k, v in d.items()})
        except Exception as e:
            print(t, "query err:", e)
conn2.close()
print("DONE")
