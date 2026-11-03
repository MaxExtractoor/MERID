"""Confirm pinned_fav_moneyness_cap kills NO favorites; check NO vs dual p."""
import json
import os
from collections import Counter

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


no_90_reasons = Counter()
no_90_owner = Counter()
no_90_assets = Counter()
p_gap = []
n_no90 = 0
for raw in tail_lines(os.path.join(LOGS, "rejected_candidates.jsonl"), 300_000_000):
    try:
        d = json.loads(raw)
    except Exception:
        continue
    if d.get("type") != "rejected_candidate":
        continue
    side = d.get("side")
    hp = d.get("held_price_cents")
    if side == "no" and hp is not None and hp >= 88:
        n_no90 += 1
        sv = (d.get("side_verdicts") or {}).get("no") or {}
        no_90_reasons[d.get("reject_reason") or d.get("canonical_reason")] += 1
        no_90_owner[sv.get("admission_reason") or sv.get("admission_owner")] += 1
        no_90_assets[d.get("asset")] += 1
        # calibration duality check: compare model p_no vs (1 - implied p_yes)
        yv = (d.get("side_verdicts") or {}).get("yes") or {}
        yg = yv.get("gross_edge_cents")
        yp = d.get("yes_price_cents")
        p_no = d.get("model_p_selected")
        if yg is not None and yp is not None and p_no is not None:
            p_yes_implied = (yp + yg) / 100.0
            p_gap.append(round(p_no - (1.0 - p_yes_implied), 4))

print(f"NO rejects with held_price>=88c: {n_no90}")
print("\n--- reject_reason ---")
for k, v in no_90_reasons.most_common(15):
    print(f"  {v:>7}  {k}")
print("\n--- admission_reason/owner ---")
for k, v in no_90_owner.most_common(15):
    print(f"  {v:>7}  {k}")
print("\n--- assets ---")
for k, v in no_90_assets.most_common():
    print(f"  {v:>7}  {k}")
if p_gap:
    p_gap.sort()
    n = len(p_gap)
    print(f"\ncalibration duality gap p_no - (1-p_yes): n={n} "
          f"median={p_gap[n//2]:+.4f} mean={sum(p_gap)/n:+.4f} "
          f"p10={p_gap[n//10]:+.4f} p90={p_gap[9*n//10]:+.4f}")
