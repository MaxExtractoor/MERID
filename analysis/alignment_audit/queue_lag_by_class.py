"""Per-class queue lag: created_at_utc - event_ts = queue residency of committed
writes, last 3h, grouped by event_type. Bounded by run_id index."""
import sqlite3
from datetime import datetime, timezone

RUN = "20261101202100_13076_42914002"
db = sqlite3.connect("file:data/decision_audit.db?mode=ro", uri=True)
db.row_factory = sqlite3.Row

def parse(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None

print("=== events: lag by event_type (queue residency s) ===")
stats = {}
for r in db.execute(
    "SELECT event_type, reason_code, event_ts, created_at_utc FROM "
    "strategy_decision_events WHERE run_id=?", (RUN,)):
    lag = None
    if r["event_ts"] and r["created_at_utc"]:
        c = parse(r["created_at_utc"])
        if c:
            lag = c - r["event_ts"]
    k = (r["event_type"], str(r["reason_code"])[:40])
    s = stats.setdefault(k, [])
    if lag is not None:
        s.append(lag)

for k in sorted(stats, key=lambda x: -len(stats[x])):
    v = sorted(stats[k])
    n = len(v)
    med = v[n // 2]
    p95 = v[int(n * 0.95)] if n > 4 else v[-1]
    print(f"  {k[0]:26s} {k[1]:42s} n={n:5d} med={med:7.1f} "
          f"p95={p95:7.1f} max={v[-1]:7.1f}")

print("\n=== per-5min arrival vs completion rate (events) ===")
for r in db.execute(
    "SELECT CAST((event_ts-?)/300 AS INT) bucket, COUNT(*) n, "
    "MIN(event_ts) mn, MAX(event_ts) mx FROM strategy_decision_events "
    "WHERE run_id=? AND event_type != 'SETTLEMENT_RESOLVED' "
    "GROUP BY bucket ORDER BY bucket DESC LIMIT 10", (0, RUN)):
    dt = datetime.fromtimestamp(r["mn"], tz=timezone.utc).strftime("%H:%M")
    dt2 = datetime.fromtimestamp(r["mx"], tz=timezone.utc).strftime("%H:%M")
    print(f"  {dt}-{dt2}Z  n={r['n']}")
db.close()
print("DONE")
