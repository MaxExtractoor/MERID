import sqlite3

db = sqlite3.connect('file:data/decision_audit.db?mode=ro', uri=True, timeout=10)
db.execute('PRAGMA query_only=1')
mx_ev = db.execute("SELECT MAX(rowid) FROM strategy_decision_events").fetchone()[0]

print('=== last 6k event commits (current backlog composition) ===')
for et, r, c in db.execute(
    "SELECT event_type, reason_code, COUNT(*) FROM strategy_decision_events "
    "WHERE rowid > ? GROUP BY 1,2 ORDER BY 3 DESC LIMIT 15", (mx_ev-6000,)).fetchall():
    print(f'  {c:6d}  {et} / {r}')

print('=== residency: created_at_utc - event_ts_utc, last 6k ===')
for et, r, avg, mx, n in db.execute(
    "SELECT event_type, reason_code, "
    "CAST(AVG((julianday(created_at_utc)-julianday(event_ts_utc))*86400) AS INT), "
    "CAST(MAX((julianday(created_at_utc)-julianday(event_ts_utc))*86400) AS INT), COUNT(*) "
    "FROM strategy_decision_events WHERE rowid > ? "
    "GROUP BY 1,2 ORDER BY 5 DESC LIMIT 12", (mx_ev-6000,)).fetchall():
    print(f'  {n:6d}  mean={avg}s max={mx}s  {et}/{r}')

print('=== rowid tail: commit wall-clock span for last 3k ===')
row = db.execute(
    "SELECT MIN(created_at_utc), MAX(created_at_utc) FROM strategy_decision_events "
    "WHERE rowid > ?", (mx_ev-3000,)).fetchone()
print(' ', row)
