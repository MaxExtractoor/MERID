"""Recent-window side analysis: entries by lane/price, NO reject deep-dive."""
import json
import os
import time
from collections import Counter

LOGS = r"C:\Dev\MERID\logs"
NOW = time.time()
H24 = NOW - 24 * 3600
H6 = NOW - 6 * 3600


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


# --- recent entries ---------------------------------------------------------
path = os.path.join(LOGS, "order_decisions.jsonl")
entries_24h = Counter()
entries_6h = Counter()
entry_px_24h = Counter()
entry_reason_24h = Counter()
n_24 = n_6 = 0
for raw in tail_lines(path, 70_000_000):
    try:
        d = json.loads(raw)
    except Exception:
        continue
    ts = d.get("ts") or 0
    if ts < H24:
        continue
    if d.get("purpose") == "open" and d.get("action") == "buy" and d.get("allowed"):
        n_24 += 1
        if ts >= H6:
            n_6 += 1
        side = d.get("contract")
        entries_24h[side] += 1
        if ts >= H6:
            entries_6h[side] += 1
        reason = d.get("reason") or ""
        lane = "?"
        for tok in ("pinned_fav", "settlement", "cheap_no", "mband", "cbp", "drift",
                    "taker", "maker_bid", "maker", "empirical"):
            if tok in reason or tok in (d.get("decision_id") or ""):
                lane = tok
                break
        entry_reason_24h[f"{side}|{lane}"] += 1
        px = d.get("limit_cents")
        if px is not None:
            b = f"{int(px // 10) * 10}s"
            entry_px_24h[f"{side}|{b}c"] += 1

print(f"=== allowed entries last 24h: {n_24} | last 6h: {n_6} ===")
print("24h by side:", dict(entries_24h))
print("6h  by side:", dict(entries_6h))
print("\n--- 24h side|lane ---")
for k, v in entry_reason_24h.most_common(20):
    print(f"  {v:>6}  {k}")
print("\n--- 24h side|price_bucket (limit_cents) ---")
for k, v in sorted(entry_px_24h.items()):
    print(f"  {v:>6}  {k}")

# --- NO reject deep-dive on recent window ------------------------------------
path = os.path.join(LOGS, "rejected_candidates.jsonl")
no_block_axis = Counter()
yes_block_axis = Counter()
no_ev_fail_but_econ_pass = 0
no_econ_fail = 0
no_rows = 0
no_px_when_econ_fail = Counter()
asset_no_fade = Counter()
for raw in tail_lines(path, 400_000_000):
    try:
        d = json.loads(raw)
    except Exception:
        continue
    if d.get("type") != "rejected_candidate":
        continue
    side = d.get("side")
    sv = (d.get("side_verdicts") or {}).get(side) or {}
    econ = sv.get("economics_verdict")
    ev = sv.get("evidence_verdict")
    hard = sv.get("hard_safety_flag")
    adm = sv.get("admission_verdict")
    # effective block axis
    if adm == "HARD_SAFETY_BLOCK" or hard:
        axis = "hard_block"
    elif adm == "ECONOMICS_FAIL":
        axis = "economics_fail"
    elif adm in ("EXPLORATION_AUTHORIZED", "ECONOMICS_PASS_EVIDENCE_INSUFFICIENT"):
        axis = f"admitted_but_rejected:{sv.get('admission_owner')}"
    elif adm:
        axis = adm
    else:
        axis = "no_verdict"
    if side == "no":
        no_rows += 1
        no_block_axis[axis] += 1
        if adm == "ECONOMICS_FAIL":
            no_econ_fail += 1
            hp = d.get("held_price_cents")
            if hp is not None:
                b = f"{int(hp // 10) * 10}s"
                no_px_when_econ_fail[b] += 1
        rr = d.get("reject_reason") or ""
        if rr.startswith("market_fade"):
            asset_no_fade[d.get("asset", "?")] += 1
    elif side == "yes":
        yes_block_axis[axis] += 1

print(f"\n=== NO-side rejected rows: {no_rows} ===")
print("--- NO block axis ---")
for k, v in no_block_axis.most_common(15):
    print(f"  {v:>8}  {k}")
print("\n--- YES block axis ---")
for k, v in yes_block_axis.most_common(15):
    print(f"  {v:>8}  {k}")
print("\n--- NO economics_fail by held-price bucket ---")
for k, v in sorted(no_px_when_econ_fail.items()):
    print(f"  {v:>8}  {k}")
print("\n--- market_fade_blocked_no by asset ---")
for k, v in asset_no_fade.most_common():
    print(f"  {v:>8}  {k}")
