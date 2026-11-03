import sqlite3, time

c = sqlite3.connect(':memory:')
c.execute('CREATE TABLE t (id INTEGER PRIMARY KEY, v INT)')
c.executemany('INSERT INTO t VALUES (?,?)', [(i, i) for i in range(50)])
c.commit()

seen = []
dl = time.monotonic()
def ph():
    m = time.monotonic()
    seen.append((m, dl, m > dl))
    return 1 if m > dl else 0

c.set_progress_handler(ph, 1)
try:
    c.execute('SELECT id FROM t').fetchall()
    print('select ok')
except Exception as e:
    print('select raised:', repr(e))
print('first calls:', seen[:3])
print('last calls:', seen[-3:])
print('n calls:', len(seen))
