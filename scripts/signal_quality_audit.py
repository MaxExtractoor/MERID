"""Signal-quality audit: is the model's probability better than the market's?

For each settled (asset, window) and TTE checkpoint, compare:
  - market implied p (YES mid)
  - model raw p (p_yes_raw)
  - model calibrated p (p_yes_calibrated)
against the binary outcome.  Reports Brier / log-loss, the disagreement
distribution |model - market|, and whether disagreement predicts the
outcome (slope of (y - mkt) on (model - mkt): 1.0 = model fully right
where it disagrees, 0 = disagreement is pure noise, <0 = anti-signal).

Usage: .\\.venv\\Scripts\\python.exe scripts\\signal_quality_audit.py
"""
import collections
import json
import math
import os

PATH = "logs/decision_telemetry.jsonl"
outcomes = {}
for line in open("logs/settlement_outcomes.jsonl", "r", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get("event_type") == "settlement_outcome" and d.get("ticker") and d.get("outcome"):
        outcomes[d["ticker"]] = 1.0 if str(d["outcome"]).lower() == "yes" else 0.0

# Keep one observation per (ticker, TTE bucket): the first record in bucket.
BUCKETS = [(12, 15), (9, 12), (6, 9), (3, 6)]


def bucket(m):
    for lo, hi in BUCKETS:
        if lo <= m < hi:
            return f"{lo}-{hi}m"
    return None


obs = {}
for p in [f"{PATH}.{i}" for i in range(9, 0, -1)] + [PATH]:
    if not os.path.exists(p):
        continue
    for raw in open(p, "rb"):
        try:
            r = json.loads(raw)
        except Exception:
            continue
        if r.get("type") != "decision_record":
            continue
        t = r.get("ticker")
        if t not in outcomes:
            continue
        m = r.get("minutes_to_expiry")
        b = bucket(m) if m is not None else None
        yb, ya = r.get("yes_bid_cents"), r.get("yes_ask_cents")
        pr, pc = r.get("p_yes_raw"), r.get("p_yes_calibrated")
        if b is None or yb is None or ya is None or pr is None or pc is None:
            continue
        if not (1 <= yb < ya <= 99):
            continue
        k = (t, b)
        if k in obs:
            continue
        obs[k] = dict(asset=r.get("asset"), b=b, y=outcomes[t], mkt=(yb + ya) / 200.0,
                      raw=float(pr), cal=float(pc), spread=(ya - yb))


def brier(rows, key):
    return sum((x[key] - x["y"]) ** 2 for x in rows) / len(rows)


def logloss(rows, key):
    e = 1e-4
    return -sum(x["y"] * math.log(max(e, x[key])) + (1 - x["y"]) * math.log(max(e, 1 - x[key])) for x in rows) / len(rows)


def slope(rows, key):
    xs = [x[key] - x["mkt"] for x in rows]
    ys = [x["y"] - x["mkt"] for x in rows]
    sxx = sum(v * v for v in xs)
    return (sum(a * b for a, b in zip(xs, ys)) / sxx) if sxx > 0 else float("nan")


def report(name, rows):
    if len(rows) < 10:
        return
    dis = [abs(x["cal"] - x["mkt"]) for x in rows]
    big = sum(1 for d in dis if d >= 0.05) / len(rows)
    print(
        f"{name:<12} n={len(rows):4d} | Brier mkt={brier(rows, 'mkt'):.4f} raw={brier(rows, 'raw'):.4f} "
        f"cal={brier(rows, 'cal'):.4f} | LL mkt={logloss(rows, 'mkt'):.3f} cal={logloss(rows, 'cal'):.3f} | "
        f"|cal-mkt| med={sorted(dis)[len(dis) // 2] * 100:4.1f}pp >=5pp={big:5.1%} | "
        f"slope raw={slope(rows, 'raw'):+.2f} cal={slope(rows, 'cal'):+.2f}"
    )


rows = list(obs.values())
print(f"settled observations: {len(rows)}  (windows={len({k[0] for k in obs})})")
report("ALL", rows)
print("\n-- by TTE bucket --")
for lo, hi in BUCKETS:
    report(f"{lo}-{hi}m", [x for x in rows if x["b"] == f"{lo}-{hi}m"])
print("\n-- by asset --")
for a in sorted({x["asset"] for x in rows}):
    report(a, [x for x in rows if x["asset"] == a])

# Where the model disagrees by >= 5pp, who wins?
print("\n-- disagreement cohorts (cal vs mkt) --")
for lo, hi in ((0.0, 0.03), (0.03, 0.05), (0.05, 0.10), (0.10, 1.0)):
    sub = [x for x in rows if lo <= abs(x["cal"] - x["mkt"]) < hi]
    if not sub:
        continue
    # Signed: does reality move in the model's direction relative to market?
    right = sum(1 for x in sub if (x["cal"] - x["mkt"]) * (x["y"] - x["mkt"]) > 0)
    print(f"  |cal-mkt| {lo * 100:4.0f}-{hi * 100:3.0f}pp n={len(sub):4d} model-direction-correct={right / len(sub):5.1%} "
          f"Brier mkt={brier(sub, 'mkt'):.4f} cal={brier(sub, 'cal'):.4f}")
print(
    "\nRead: Brier/log-loss lower = better.  If cal >= mkt, the model adds no "
    "information beyond the price and no gate tuning can create edge.  Slope "
    "near 0 means disagreements are noise; ~1 means the model is right where it disagrees."
)
