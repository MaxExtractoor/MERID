"""Quick realized check: exit fills + entry markouts for high-price entries."""
import json
import os
from collections import defaultdict

LOGS = r"C:\Dev\MERID\logs"


def tail_lines(path, nbytes):
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - nbytes))
        data = f.read()
    idx = data.find(b"\n")
    if idx >= 0:
        data = data[idx + 1:]
    for raw in data.split(b"\n"):
        raw = raw.strip()
        if raw:
            yield raw


# 1) exits from high-price entries: realized pnl per close
by_bucket = defaultdict(lambda: {"n": 0, "pnl": 0.0, "net": 0.0})
n_close = 0
for raw in tail_lines(os.path.join(LOGS, "order_decisions.jsonl"), 70_000_000):
    try:
        d = json.loads(raw)
    except Exception:
        continue
    if d.get("purpose") == "close" and d.get("allowed"):
        px = d.get("position_avg_price_cents")
        side = d.get("position_side")
        pnl = d.get("expected_realized_pnl_cents")
        if px is None or pnl is None:
            continue
        n_close += 1
        b = "90+" if px >= 88 else ("60-87" if px >= 60 else "<60")
        rec = by_bucket[f"{side}@{b}c"]
        rec["n"] += 1
        rec["pnl"] += float(pnl)

print(f"=== closes with realized pnl: {n_close} ===")
for k, r in sorted(by_bucket.items()):
    print(f"  {k}: n={r['n']} realized_sum={r['pnl']:.1f}c avg={r['pnl']/r['n']:.2f}c")

# 2) settlement_outcomes joined to entry prices isn't available; instead
#    count settled outcomes by asset in the window (market directional mix)
outcomes = defaultdict(int)
for raw in tail_lines(os.path.join(LOGS, "settlement_outcomes.jsonl"), 60_000_000):
    try:
        d = json.loads(raw)
    except Exception:
        continue
    if d.get("event_type") == "settlement_outcome":
        outcomes[d.get("outcome")] += 1
print("\n=== settlement outcomes in window ===", dict(outcomes))
