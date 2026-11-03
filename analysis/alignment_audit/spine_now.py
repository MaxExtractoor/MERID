import sqlite3

db = sqlite3.connect('file:data/decision_audit.db?mode=ro', uri=True, timeout=10)
db.execute('PRAGMA query_only=1')
mx = db.execute("SELECT MAX(rowid) FROM strategy_decisions").fetchone()[0]

print('=== last 4k decisions: lag by decision ===')
for d, prc, avg, mx2, n in db.execute(
    "SELECT decision, primary_reason_code, "
    "CAST(AVG((julianday(created_at)-julianday(decision_ts))*86400) AS INT), "
    "CAST(MAX((julianday(created_at)-julianday(decision_ts))*86400) AS INT), COUNT(*) "
    "FROM strategy_decisions WHERE rowid > ? "
    "GROUP BY 1,2 ORDER BY 5 DESC LIMIT 10", (mx-4000,)).fetchall():
    print(f'  {n:6d}  mean={avg}s max={mx2}s  {d}/{prc}')

print('=== freshest decision_ts vs now ===')
row = db.execute("SELECT MAX(decision_ts), MAX(created_at), datetime('now') FROM strategy_decisions").fetchone()
print('  max_decision_ts:', row[0])
print('  max_created_at :', row[1])
print('  db now         :', row[2])
