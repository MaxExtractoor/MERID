"""Sanity check: realized performance of pinned_fav-lane entries by side."""
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


# settlement_outcomes: find fields mentioning pinned_fav / lane / side / pnl
n = 0
by_side = defaultdict(lambda: {"n": 0, "wins": 0, "pnl_cents": 0.0})
sample = None
for raw in tail_lines(os.path.join(LOGS, "settlement_outcomes.jsonl"), 200_000_000):
    try:
        d = json.loads(raw)
    except Exception:
        continue
    blob = json.dumps(d)
    if "pinned_fav" not in blob:
        continue
    n += 1
    if sample is None:
        sample = d
    # try to extract side + pnl generically
    side = d.get("side") or d.get("held_side") or d.get("contract") or "?"
    pnl = None
    for k in ("realized_pnl_cents", "net_pnl_cents", "pnl_cents", "realized_pnl_usd",
              "net_pnl_usd", "pnl_usd"):
        if isinstance(d.get(k), (int, float)):
            pnl = float(d[k])
            break
    won = d.get("won")
    if won is None:
        st = str(d.get("settlement") or d.get("outcome") or "").lower()
        if st in ("win", "won", "yes", "settled_win"):
            won = True
    if won is None and pnl is not None:
        won = pnl > 0
    rec = by_side[side]
    rec["n"] += 1
    if won:
        rec["wins"] += 1
    if pnl is not None:
        rec["pnl_cents"] += pnl

print(f"pinned_fav settlement_outcome rows: {n}")
if sample:
    print("sample keys:", sorted(sample.keys()))
    print("sample:", json.dumps(sample)[:1200])
for s, r in sorted(by_side.items()):
    wr = (r["wins"] / r["n"]) if r["n"] else 0
    print(f"  {s}: n={r['n']} win_rate={wr:.1%} pnl_sum={r['pnl_cents']:.1f}")
