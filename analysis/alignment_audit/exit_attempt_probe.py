import sqlite3, json

db = sqlite3.connect('file:data/kalshi_order_attempts.db?mode=ro', uri=True, timeout=10)
db.execute('PRAGMA query_only=1')

print('=== exit_order_attempts schema ===')
print([r[1] for r in db.execute('PRAGMA table_info(exit_order_attempts)').fetchall()])

print('=== latest exit attempts ===')
cur = db.execute('SELECT * FROM exit_order_attempts ORDER BY rowid DESC LIMIT 4')
cols = [d[0] for d in cur.description]
for row in cur.fetchall():
    rec = dict(zip(cols, row))
    print(json.dumps(rec, default=str)[:900])

print('=== exit_order_attempt_events schema ===')
print([r[1] for r in db.execute('PRAGMA table_info(exit_order_attempt_events)').fetchall()])
cur = db.execute('SELECT * FROM exit_order_attempt_events ORDER BY rowid DESC LIMIT 6')
cols = [d[0] for d in cur.description]
for row in cur.fetchall():
    print(json.dumps(dict(zip(cols, row)), default=str)[:700])

print('=== payloads of 3 newest order_attempts ===')
for cid in ('exit_4c396e550d0b43455041', 'merid_41bfaf0362024815a3e7', 'merid_5c27b03a43084208bfdc'):
    r = db.execute('SELECT status, payload_json FROM order_attempts WHERE client_order_id=?', (cid,)).fetchone()
    if r:
        print(f'--- {cid} status={r[0]}')
        print(r[1][:1200])
