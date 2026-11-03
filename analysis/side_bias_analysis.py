"""Analyze YES vs NO side distribution in entries and rejected candidates."""
import json
import os
import sys
from collections import Counter, defaultdict

LOGS = r"C:\Dev\MERID\logs"


def tail_lines(path, nbytes):
    """Yield decoded lines from the last nbytes of a file."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - nbytes))
        data = f.read()
    # drop partial first line
    idx = data.find(b"\n")
    if idx >= 0:
        data = data[idx + 1:]
    for raw in data.split(b"\n"):
        raw = raw.strip()
        if raw:
            yield raw


def analyze_entries():
    path = os.path.join(LOGS, "order_decisions.jsonl")
    entries = Counter()
    entry_routes = Counter()
    entry_assets = Counter()
    blocked = Counter()
    first_ts = last_ts = None
    for raw in tail_lines(path, 70_000_000):
        try:
            d = json.loads(raw)
        except Exception:
            continue
        ts = d.get("ts")
        if ts:
            first_ts = ts if first_ts is None else min(first_ts, ts)
            last_ts = ts if last_ts is None else max(last_ts, ts)
        if d.get("purpose") == "open" and d.get("action") == "buy":
            if d.get("allowed"):
                side = d.get("contract")
                entries[side] += 1
                dec = d.get("decision_id") or ""
                route = dec.split(":")[-1] if ":" in dec else (dec or "?")
                entry_routes[f"{side}:{route}"] += 1
                tk = d.get("ticker", "")
                asset = tk.split("-")[0].replace("KX", "").replace("15M", "") if tk else "?"
                entry_assets[f"{asset}:{side}"] += 1
            else:
                reason = d.get("reason", "?")
                blocked[reason.split(":")[0]] += 1
    print("=== order_decisions.jsonl: allowed OPEN entries ===")
    print(f"window: ts {first_ts} .. {last_ts}")
    for k, v in entries.most_common():
        print(f"  {k}: {v}")
    print("\n--- by route ---")
    for k, v in entry_routes.most_common(20):
        print(f"  {k}: {v}")
    print("\n--- by asset:side ---")
    for k, v in entry_assets.most_common(20):
        print(f"  {k}: {v}")
    print("\n--- blocked (allowed=false) top reasons ---")
    for k, v in blocked.most_common(15):
        print(f"  {k}: {v}")


def analyze_rejects(nbytes=400_000_000):
    path = os.path.join(LOGS, "rejected_candidates.jsonl")
    side_reason = Counter()
    side_route = Counter()
    side_asset = Counter()
    side_verdict_owner = Counter()
    no_price_buckets = Counter()
    yes_price_buckets = Counter()
    first_ts = last_ts = None
    n = 0
    for raw in tail_lines(path, nbytes):
        try:
            d = json.loads(raw)
        except Exception:
            continue
        if d.get("type") != "rejected_candidate":
            continue
        n += 1
        ts = d.get("event_ts_utc")
        if ts:
            first_ts = ts if first_ts is None else min(first_ts, ts)
            last_ts = ts if last_ts is None else max(last_ts, ts)
        side = d.get("side", "?")
        reason = d.get("canonical_reason") or d.get("reject_reason") or "?"
        subreason = d.get("reject_reason") or "?"
        side_reason[f"{side}|{reason}|{subreason}"] += 1
        side_route[f"{side}|{d.get('route','?')}"] += 1
        side_asset[f"{side}|{d.get('asset','?')}"] += 1
        hp = d.get("held_price_cents")
        pb = d.get("price_bucket", "?")
        if side == "no":
            no_price_buckets[pb] += 1
        elif side == "yes":
            yes_price_buckets[pb] += 1
        sv = d.get("side_verdicts") or {}
        svd = sv.get(side) or {}
        owner = svd.get("admission_owner")
        if owner:
            side_verdict_owner[f"{side}|{owner}|{svd.get('admission_decision','?')}"] += 1
    print(f"\n=== rejected_candidates.jsonl: {n} records ===")
    print(f"window: {first_ts} .. {last_ts}")
    print("\n--- side|canonical|reject_reason (top 30) ---")
    for k, v in side_reason.most_common(30):
        print(f"  {v:>8}  {k}")
    print("\n--- side|route ---")
    for k, v in side_route.most_common(20):
        print(f"  {v:>8}  {k}")
    print("\n--- side|asset ---")
    for k, v in side_asset.most_common(20):
        print(f"  {v:>8}  {k}")
    print("\n--- NO rejects by price bucket ---")
    for k, v in sorted(no_price_buckets.items()):
        print(f"  {v:>8}  {k}")
    print("\n--- YES rejects by price bucket ---")
    for k, v in sorted(yes_price_buckets.items()):
        print(f"  {v:>8}  {k}")
    print("\n--- side|admission_owner|decision ---")
    for k, v in side_verdict_owner.most_common(25):
        print(f"  {v:>8}  {k}")


if __name__ == "__main__":
    analyze_entries()
    analyze_rejects()
