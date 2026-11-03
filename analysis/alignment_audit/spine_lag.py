"""Decision-row commit lag: created_at vs decision_ts, ENTER vs NO_TRADE."""
import sqlite3
from datetime import datetime

RUN = "20261101202100_13076_42914002"
db = sqlite3.connect("file:data/decision_audit.db?mode=ro", uri=True)
db.row_factory = sqlite3.Row

def ts(s):
    if s is None:
        return None
    try:
        return float(s)  # epoch
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None

print("=== decision rows: commit lag by decision type ===")
for r in db.execute(
    "SELECT decision, decision_ts, created_at, COUNT(*) n FROM "
    "strategy_decisions WHERE run_id=? GROUP BY decision", (RUN,)):
    pass  # need row-level

stats = {}
for r in db.execute(
    "SELECT decision, decision_ts, created_at FROM strategy_decisions "
    "WHERE run_id=?", (RUN,)):
    lag = None
    c = ts(r["created_at"]) if r["created_at"] else None
    if c and r["decision_ts"]:
        lag = c - r["decision_ts"]
    s = stats.setdefault(r["decision"], [])
    if lag is not None:
        s.append(lag)

for k, v in stats.items():
    if not v:
        print(f"  {k:10s} n=0 (no created_at)")
        continue
    v.sort()
    n = len(v)
    print(f"  {k:10s} n={n:5d} med={v[n//2]:7.1f} p95={v[int(n*0.95)]:7.1f} "
          f"max={v[-1]:8.1f}")

print("\n=== ENTER rows: individual lag ===")
for r in db.execute(
    "SELECT asset, decision_ts, created_at FROM strategy_decisions WHERE "
    "run_id=? AND decision='ENTER'", (RUN,)):
    c = ts(r["created_at"]) if r["created_at"] else 0
    print(f"  {r['asset']} decision={datetime.fromtimestamp(r['decision_ts']).strftime('%H:%M:%S')} "
          f"commit={str(r['created_at'])[11:19]} lag={c - r['decision_ts']:.1f}s")

print("\n=== side_ev commit lag (ENTER only) ===")
for r in db.execute(
    "SELECT s.side, e.created_at, d.decision_ts FROM "
    "strategy_decision_side_ev e JOIN strategy_decisions d ON "
    "e.decision_id=d.decision_id WHERE d.run_id=? AND d.decision='ENTER'",
    (RUN,)):
    c = ts(r["created_at"]) if r["created_at"] else None
    lag = (c - r["decision_ts"]) if c else None
    print(f"  {r['side']} lag={lag}")

db.close()
print("DONE")
