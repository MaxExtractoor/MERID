"""Settled PnL by entry decision-lane, day x lane grid.

Joins settlement rows in data/trade_attribution_fact.db to the lane stamped
on the entry order attempt in data/kalshi_order_attempts.db (payload.order
.decision_lane, matched by ticker — 15m tickers are unique markets, so a
market's buy attempt is its entry).  Settles whose entry attempt predates
lane stamping (or was a same-ticker re-entry after the first attempt) report
as ``unmapped``.

Usage:
  .\\.venv\\Scripts\\python.exe scripts\\lane_settle_pnl.py [--days 14]
"""
import argparse
import collections
import json
import sqlite3
import time
from datetime import datetime, timezone

ap = argparse.ArgumentParser()
ap.add_argument("--days", type=int, default=14)
args = ap.parse_args()

ocon = sqlite3.connect("data/kalshi_order_attempts.db")
tick_lane = {}
for (pj,) in ocon.execute("SELECT payload_json FROM order_attempts"):
    try:
        d = json.loads(pj)
    except Exception:
        continue
    o = d.get("order") or {}
    lane = o.get("decision_lane") or d.get("decision_lane")
    tick = o.get("ticker")
    if tick and (o.get("action") or "").lower() == "buy" and lane:
        tick_lane.setdefault(tick, lane)
ocon.close()

acon = sqlite3.connect("data/trade_attribution_fact.db")
cut = time.time() - args.days * 86400
rows = []
for md, pnl, ts, tick in acon.execute(
    "SELECT metadata, realized_pnl_cents, event_ts, ticker "
    "FROM trade_attribution_fact "
    "WHERE event_type='settlement' AND realized_pnl_cents IS NOT NULL"
):
    try:
        ts_f = float(ts)
    except Exception:
        try:
            ts_f = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
        except Exception:
            continue
    if ts_f < cut:
        continue
    rows.append((ts_f, tick_lane.get(tick, "unmapped"), float(pnl)))
acon.close()

if not rows:
    print("no settled rows in window")
    raise SystemExit

tot = collections.defaultdict(lambda: [0.0, 0])
for ts_f, lane, pnl in rows:
    tot[lane][0] += pnl
    tot[lane][1] += 1
print(f"SETTLED PnL by lane — last {args.days}d")
for lane, (p, n) in sorted(tot.items(), key=lambda kv: kv[1][0]):
    print(f"  {lane:28s} {p:+10.1f}c  n={n:4d}  {p / n:+.2f}c/tr")
print(f"  {'TOTAL':28s} {sum(v[0] for v in tot.values()):+10.1f}c  n={sum(v[1] for v in tot.values())}")

day_lane = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0]))
for ts_f, lane, pnl in rows:
    day = datetime.fromtimestamp(ts_f, tz=timezone.utc).strftime("%m-%d")
    day_lane[day][lane][0] += pnl
    day_lane[day][lane][1] += 1
lanes = [l for l, _ in sorted(tot.items(), key=lambda kv: kv[1][0])]
print("\nday x lane (PnL c, n in parens):")
print("  day   total   " + "  ".join(f"{l[:12]:>12s}" for l in lanes))
for day in sorted(day_lane, reverse=True):
    cells = day_lane[day]
    line = f"  {day}  {sum(v[0] for v in cells.values()):+7.0f}c "
    for l in lanes:
        p, n = cells.get(l, (0.0, 0))
        line += f"  {p:+6.0f}({n:2d})" if n else f"  {'':>10s}"
    print(line)
