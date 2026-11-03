import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
con = sqlite3.connect(f"file:{(ROOT / 'data/kalshi_order_attempts.db').as_posix()}?mode=ro", uri=True)
r = con.execute(
    "SELECT payload_json FROM order_attempts WHERE status='FILLED' "
    "AND payload_json LIKE '%pinned_fav%' ORDER BY created_at DESC LIMIT 1"
).fetchone()
d = json.loads(r[0])
print(json.dumps(d, indent=1)[:8000])
con.close()
