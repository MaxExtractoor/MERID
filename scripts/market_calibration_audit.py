"""Is the Kalshi 15m price itself miscalibrated?  (structural edge source)

Uses the long history in logs/rejected_candidates.jsonl: every record is a
(ticker, side, executable held price, TTE) observation.  Deduplicate to the
first observation per (ticker, side, TTE bucket), join to settlement, and
compare realized win rate to the price paid.

    edge_c = 100 * win_rate - avg_price - fee

A consistent positive edge in some price/TTE cell (e.g. favorites winning
more than their price implies — the favorite-longshot bias) is information
the market price does NOT contain, independent of the Bachelier model.

Also fits the optimal logit blend weight w of model vs market on decision
telemetry: p = sigmoid((1-w) logit(mkt) + w logit(model)).  w*~0 means the
model adds nothing beyond the price.

Usage: .\\.venv\\Scripts\\python.exe scripts\\market_calibration_audit.py [--since 2026-09-20]
"""
import argparse
import collections
import json
import math
import os
from datetime import datetime, timezone

ap = argparse.ArgumentParser()
ap.add_argument("--since", default="2026-09-20")
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
        return "?"
    return "<5m" if s < 300 else "5-10m" if s < 600 else "10-15m"


def px_b(c):
    lo = int(c // 10) * 10
    return f"{lo:02d}-{lo + 9:02d}"


seen = set()
cells = collections.defaultdict(lambda: [0, 0, 0.0])  # n, wins, sum_price
for line in open("logs/rejected_candidates.jsonl", "r", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get("type") != "rejected_candidate" or (d.get("event_ts_utc") or "") < args.since:
        continue
    t, side, px = d.get("ticker"), (d.get("side") or "").lower(), d.get("held_price_cents")
    if t not in outcomes or side not in ("yes", "no") or px is None or not (1 <= px <= 99):
        continue
    tb = tte_b(d.get("tte_seconds"))
    k = (t, side, tb)
    if k in seen:
        continue
    seen.add(k)
    won = outcomes[t] == side
    for key in ((px_b(px), "ALL"), (px_b(px), tb), (px_b(px), f"side={side}")):
        c = cells[key]
        c[0] += 1
        c[1] += won
        c[2] += px

print(f"observations: {len(seen)} (since {args.since})")
print(f"{'price':<7}{'slice':<10}{'n':>6}{'win%':>8}{'avg_px':>8}{'edge c':>8}{'+/-95%':>8}")
for pb in sorted({k[0] for k in cells}):
    for sl in ("ALL", "<5m", "5-10m", "10-15m", "side=yes", "side=no"):
        if (pb, sl) not in cells:
            continue
        n, w, sp = cells[(pb, sl)]
        if n < 30:
            continue
        wr = w / n
        avg = sp / n
        edge = 100 * wr - avg - FEE
        ci = 196 * math.sqrt(max(wr * (1 - wr), 1e-6) / n)
        flag = "  <== significant" if abs(edge) > ci and sl == "ALL" else ""
        print(f"{pb:<7}{sl:<10}{n:>6}{wr:>8.1%}{avg:>8.1f}{edge:>+8.1f}{ci:>8.1f}{flag}")
    print()

# ---- optimal model/market blend on decision telemetry -----------------
PATH = "logs/decision_telemetry.jsonl"
obs = {}
for p in [f"{PATH}.{i}" for i in range(9, 0, -1)] + [PATH]:
    if not os.path.exists(p):
        continue
    for raw in open(p, "rb"):
        try:
            r = json.loads(raw)
        except Exception:
            continue
        if r.get("type") != "decision_record" or r.get("ticker") not in outcomes:
            continue
        yb, ya, pr = r.get("yes_bid_cents"), r.get("yes_ask_cents"), r.get("p_yes_raw")
        m = r.get("minutes_to_expiry")
        if None in (yb, ya, pr, m) or not (1 <= yb < ya <= 99):
            continue
        k = (r["ticker"], int(m // 3))
        if k in obs:
            continue
        obs[k] = ((yb + ya) / 200.0, min(max(float(pr), 1e-3), 1 - 1e-3),
                  1.0 if outcomes[r["ticker"]] == "yes" else 0.0)


def lg(p):
    return math.log(p / (1 - p))


def brier_w(w):
    s = 0.0
    for mkt, mod, y in obs.values():
        z = (1 - w) * lg(mkt) + w * lg(mod)
        s += (1 / (1 + math.exp(-z)) - y) ** 2
    return s / len(obs)


if obs:
    grid = [i / 20 for i in range(0, 21)]
    res = [(w, brier_w(w)) for w in grid]
    best = min(res, key=lambda x: x[1])
    print(f"blend fit on {len(obs)} decision observations (raw Bachelier vs market mid):")
    print("  " + "  ".join(f"w={w:.2f}:{b:.4f}" for w, b in res[::4]))
    print(f"  optimal w*={best[0]:.2f} Brier={best[1]:.4f} (market-only w=0: {res[0][1]:.4f})")
