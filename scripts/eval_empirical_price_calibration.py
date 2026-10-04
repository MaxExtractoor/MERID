"""Out-of-sample evaluation of a frozen empirical price-calibration artifact.

Applies the artifact exactly as the live overlay would: for each test
observation in a validated cell, EV = 100*p_shrunk - held_price - fee; take
the trade when EV >= --min-ev.  One trade per ticker (first qualifying
observation), net settlement P&L, 95% CI, per-cell and per-day breakdown.

Usage:
  .\\.venv\\Scripts\\python.exe scripts\\eval_empirical_price_calibration.py --artifact data/epc_train_until_0924.json --start 2026-09-24
"""
import argparse
import collections
import json
import math

ap = argparse.ArgumentParser()
ap.add_argument("--artifact", required=True)
ap.add_argument("--start", required=True)
ap.add_argument("--end", default="9999")
ap.add_argument("--min-ev", type=float, default=2.0)
args = ap.parse_args()
FEE = 1.5

art = json.load(open(args.artifact))
cells = {(c["side"], c["price_lo_c"], c["tte_min_s"] // 60): c for c in art["cells"] if c["validated"]}
outcomes = {}
for line in open("logs/settlement_outcomes.jsonl", "r", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get("event_type") == "settlement_outcome" and d.get("ticker") and d.get("outcome"):
        outcomes[d["ticker"]] = str(d["outcome"]).lower()

rows = []
for line in open("logs/rejected_candidates.jsonl", "r", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    ts = d.get("event_ts_utc") or ""
    if d.get("type") != "rejected_candidate" or not (args.start <= ts < args.end):
        continue
    t, side, px, tte = d.get("ticker"), (d.get("side") or "").lower(), d.get("held_price_cents"), d.get("tte_seconds")
    if t not in outcomes or px is None or tte is None:
        continue
    c = cells.get((side, int(float(px) // 10) * 10, int(float(tte) // 60)))
    if c is None:
        continue
    ev = 100.0 * c["p_shrunk"] - float(px) - FEE
    if ev < args.min_ev:
        continue
    rows.append((ts, t, side, float(px), c["cell_id"], ev))
rows.sort()

taken = {}
for ts, t, side, px, cid, ev in rows:
    if t in taken:
        continue
    won = outcomes[t] == side
    taken[t] = (ts[:10], cid, px, ev, won, ((100 - px) if won else -px) - FEE)

n = len(taken)
print(f"artifact={args.artifact} validated_cells={len(cells)} test={args.start}..{args.end} min_ev={args.min_ev}")
if not n:
    print("no trades")
    raise SystemExit
pnl = [v[5] for v in taken.values()]
m = sum(pnl) / n
sd = math.sqrt(sum((x - m) ** 2 for x in pnl) / max(1, n - 1))
ci = 1.96 * sd / math.sqrt(n)
days = sorted({v[0] for v in taken.values()})
print(f"TRADES={n} days={len(days)} ({n / len(days):.1f}/day) win={sum(v[4] for v in taken.values()) / n:.1%} "
      f"avg_px={sum(v[2] for v in taken.values()) / n:.1f}c predicted_ev={sum(v[3] for v in taken.values()) / n:+.2f}c "
      f"REALIZED={m:+.2f}c/trade +/-{ci:.2f} total={sum(pnl):+.0f}c  lower_bound={m - ci:+.2f}c")
by = collections.defaultdict(list)
for v in taken.values():
    by[v[1]].append(v[5])
for k, xs in sorted(by.items()):
    print(f"  {k:<24} n={len(xs):4d} net={sum(xs) / len(xs):+6.2f}c")
byd = collections.defaultdict(list)
for v in taken.values():
    byd[v[0]].append(v[5])
print("  per day: " + "  ".join(f"{d[5:]}:{sum(x) / len(x):+.1f}({len(x)})" for d, x in sorted(byd.items())))
