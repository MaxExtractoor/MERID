"""Walk-forward validation of the favorite-longshot (price-calibration) edge.

Fit an empirical win-rate table on (price bucket x TTE bucket x side) over a
TRAIN period, then on a disjoint later TEST period trade only the cells the
TRAIN table says are +EV by at least --min-edge cents.  Reports TEST P&L,
win rate, and a 95% CI — the out-of-sample evidence bar.

Dedup: first observation per (ticker, side, TTE bucket) to avoid weighting
long-lived observations.  One trade per (ticker) in the test policy (the
first qualifying observation), matching one-entry-per-window execution.

Usage:
  .\\.venv\\Scripts\\python.exe scripts\\flb_walkforward.py --split 2026-09-24
"""
import argparse
import collections
import json
import math

ap = argparse.ArgumentParser()
ap.add_argument("--start", default="2026-09-01")
ap.add_argument("--split", default="2026-09-24")
ap.add_argument("--min-edge", type=float, default=1.5)
ap.add_argument("--min-n", type=int, default=60)
ap.add_argument("--px-width", type=int, default=10)
args = ap.parse_args()
FEE = 1.5

outcomes = {}
for line in open("logs/settlement_outcomes.jsonl", "r", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get("event_type") == "settlement_outcome" and d.get("ticker") and d.get("outcome"):
        outcomes[d["ticker"]] = str(d["outcome"]).lower()


def tte_b(s):
    if s is None:
        return None
    return "<5m" if s < 300 else "5-10m" if s < 600 else "10-15m"


def cell(px, tb, side):
    lo = int(px // args.px_width) * args.px_width
    return (lo, tb, side)


obs = []
seen = set()
for line in open("logs/rejected_candidates.jsonl", "r", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    ts = d.get("event_ts_utc") or ""
    if d.get("type") != "rejected_candidate" or ts < args.start:
        continue
    t, side, px = d.get("ticker"), (d.get("side") or "").lower(), d.get("held_price_cents")
    tb = tte_b(d.get("tte_seconds"))
    if t not in outcomes or side not in ("yes", "no") or px is None or tb is None or not (1 <= px <= 99):
        continue
    k = (t, side, tb)
    if k in seen:
        continue
    seen.add(k)
    obs.append((ts, t, side, float(px), tb, outcomes[t] == side))
obs.sort()

train = [o for o in obs if o[0] < args.split]
test = [o for o in obs if o[0] >= args.split]
tab = collections.defaultdict(lambda: [0, 0, 0.0])
for ts, t, side, px, tb, won in train:
    c = tab[cell(px, tb, side)]
    c[0] += 1
    c[1] += won
    c[2] += px

good = {}
for k, (n, w, sp) in tab.items():
    if n < args.min_n:
        continue
    edge = 100 * w / n - sp / n - FEE
    se = 100 * math.sqrt(max((w / n) * (1 - w / n), 1e-6) / n)
    # Require the TRAIN edge to clear the threshold by one standard error.
    if edge - se >= args.min_edge:
        good[k] = (n, edge, se)

print(f"train={len(train)} obs ({args.start}..{args.split})  test={len(test)} obs ({args.split}..)")
print(f"cells selected on TRAIN (edge - 1se >= {args.min_edge}c, n>={args.min_n}):")
for k, (n, e, se) in sorted(good.items()):
    print(f"   px {k[0]:02d}-{k[0] + args.px_width - 1:02d} {k[1]:<7} {k[2]:<4} n={n:4d} edge={e:+5.1f}c se={se:.1f}")

traded = {}
for ts, t, side, px, tb, won in test:
    if t in traded:
        continue
    if cell(px, tb, side) in good:
        traded[t] = ((100 - px) if won else -px) - FEE, won, px, cell(px, tb, side)

n = len(traded)
if not n:
    print("no TEST trades")
    raise SystemExit
pnl = [v[0] for v in traded.values()]
m = sum(pnl) / n
sd = math.sqrt(sum((x - m) ** 2 for x in pnl) / max(1, n - 1))
ci = 1.96 * sd / math.sqrt(n)
days = len({o[0][:10] for o in test})
print(f"\nTEST: trades={n} over {days} days ({n / max(days, 1):.1f}/day) win={sum(v[1] for v in traded.values()) / n:.1%} "
      f"avg_px={sum(v[2] for v in traded.values()) / n:.1f}c net={m:+.2f}c/trade +/-{ci:.2f}c (95%) total={sum(pnl):+.0f}c")
by = collections.defaultdict(list)
for v in traded.values():
    by[v[3]].append(v[0])
for k, xs in sorted(by.items()):
    print(f"   px {k[0]:02d} {k[1]:<7} {k[2]:<4} n={len(xs):4d} net={sum(xs) / len(xs):+6.2f}c")
print("\nVerdict: OOS edge is credible only if the TEST lower bound (net - CI) > 0.")
