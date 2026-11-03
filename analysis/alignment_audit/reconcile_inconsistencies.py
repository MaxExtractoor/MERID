"""Resolve the 99c fill lane + the attempt-count arithmetic."""
import json
import sqlite3
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
att = sqlite3.connect(f"file:{(ROOT / 'data/kalshi_order_attempts.db').as_posix()}?mode=ro", uri=True)
fil = sqlite3.connect(f"file:{(ROOT / 'data/kalshi_fills.db').as_posix()}?mode=ro", uri=True)

print("=== 99c fills -> attempt lane ===")
for fr in fil.execute(
    "SELECT client_order_id, order_id, action, side, execution_price_cents FROM kalshi_fills "
    "WHERE market_ticker='KXXRP15M-26OCT312100-00' AND execution_price_cents=99"
):
    print("fill:", fr)
    row = att.execute(
        "SELECT status, payload_json, decision_id, intent_id FROM order_attempts WHERE client_order_id=?",
        (fr[0],),
    ).fetchone()
    if row:
        d = json.loads(row[1] or "{}")
        print("  status:", row[0], "order:", d.get("order"), "ec:", (d.get("execution_contract") or {}).get("admission_lane"))
        print("  decision_id:", row[2], "intent:", row[3])
    else:
        print("  no attempt row")

print("=== count reconciliation (5d) ===")
cut = time.time() - 5 * 86400
rows = att.execute(
    "SELECT payload_json FROM order_attempts WHERE created_at > ?", (cut,)
).fetchall()
total = len(rows)
has_order = 0
side = Counter()
is_exit = 0
for (pl,) in rows:
    try:
        d = json.loads(pl or "{}")
    except Exception:
        continue
    o = d.get("order")
    if not o:
        continue
    has_order += 1
    side[o.get("side")] += 1
    if str(o.get("client_order_id", "")).startswith("exit_") or "exit" in str(d.get("kind", "")):
        is_exit += 1
print("total attempts:", total, "| with order payload:", has_order, "| side-count sum:", sum(side.values()))
print("side:", dict(side))
# entries vs exits by client_order_id prefix
coid_pref = Counter()
for (coid,) in att.execute("SELECT client_order_id FROM order_attempts WHERE created_at > ?", (cut,)):
    coid_pref["exit" if str(coid).startswith("exit_") else "entry/other"] += 1
print("client_order_id prefixes:", dict(coid_pref))
att.close(); fil.close()
