"""Wire-vs-intent sanity: attempt payload order vs durable fields + fill join."""
import json
import sqlite3
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "audit_output_alignment_20261101"
cutoff = time.time() - 5 * 86400

att = sqlite3.connect(f"file:{(ROOT / 'data/kalshi_order_attempts.db').as_posix()}?mode=ro", uri=True)
fil = sqlite3.connect(f"file:{(ROOT / 'data/kalshi_fills.db').as_posix()}?mode=ro", uri=True)

rows = att.execute(
    "SELECT order_attempt_id, client_order_id, decision_id, intent_id, status, "
    "created_at, payload_json FROM order_attempts WHERE created_at > ? ORDER BY created_at",
    (cutoff,),
).fetchall()

issues = []
side_map = Counter()
lane_wire = Counter()
status_order_presence = Counter()
qty_hist = Counter()
for r in rows:
    oa, coid, dec, intent, st, c_at, pl = r
    try:
        d = json.loads(pl or "{}")
    except Exception:
        continue
    o = d.get("order") or {}
    ec = d.get("execution_contract") or {}
    lane_wire[(ec.get("admission_lane") or "none", o.get("side"))] += 1
    side_map[o.get("side")] += 1
    if o.get("count_fp"):
        qty_hist[o["count_fp"]] += 1
    # mapping checks
    side = o.get("side")
    action = o.get("action")
    if side not in ("buy_yes", "buy_no", "sell_yes", "sell_no"):
        issues.append((oa, "unmapped_side", side))
    if st == "FILLED" and not (d.get("expired_market_sweep") or {}).get("order_id"):
        f = fil.execute(
            "SELECT order_id FROM kalshi_fills WHERE client_order_id=? LIMIT 1", (coid,)
        ).fetchone()
        status_order_presence["FILLED_" + ("fill_order" if f else "no_fill_order")] += 1
    if st == "FILLED":
        f2 = fil.execute(
            "SELECT canonical_leg_price_cents, quantity_cc FROM kalshi_fills WHERE client_order_id=? LIMIT 1",
            (coid,),
        ).fetchone()
        if f2 and o.get("price_cents") and abs(f2[0] - o["price_cents"]) > 2:
            issues.append((oa, "fill_price_deviation", o["price_cents"], f2[0]))

print("wire side counts:", dict(side_map))
print("qty_fp histogram:", dict(qty_hist))
print("lane|side:", {f"{k[0]}|{k[1]}": v for k, v in lane_wire.most_common(15)})
print("filled-order presence:", dict(status_order_presence))
print("issues:", issues[:30])
(OUT / "wire_vs_intent.json").write_text(json.dumps({
    "side_map": dict(side_map), "qty_hist": dict(qty_hist),
    "lane_side": {f"{k[0]}|{k[1]}": v for k, v in lane_wire.items()},
    "issues": issues,
}, indent=1))
att.close(); fil.close()
