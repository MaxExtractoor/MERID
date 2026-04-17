"""One-shot script to parse bug audit JSON and print HIGH findings by category."""
import json, sys

with open("docs/bug_audit_2026-03-14.json") as f:
    data = json.load(f)

# Structure: {generated, summary, findings: {category: [...]}}
findings_by_cat = data.get("findings", data)

for cat, findings in findings_by_cat.items():
    if not isinstance(findings, list):
        continue
    by_sev = {}
    for item in findings:
        s = item.get("severity", "?")
        by_sev[s] = by_sev.get(s, 0) + 1
    print(f"{cat}: {by_sev}")

print("\n--- HIGH/CRITICAL findings (excluding mandelbug complexity) ---\n")

for cat, findings in findings_by_cat.items():
    if not isinstance(findings, list):
        continue
    high = [f for f in findings if f.get("severity") in ("CRITICAL", "HIGH")]
    if not high:
        continue
    # Skip mandelbug complexity (not actionable bugs) — show count only
    if cat == "mandelbug":
        print(f"=== {cat}: {len(high)} HIGH (complexity warnings, skipping detail) ===")
        continue
    print(f"\n=== {cat} ({len(high)} HIGH/CRITICAL) ===")
    for h in high[:50]:
        print(f"  {h['severity']:8} | {h.get('file','?')}:{h.get('line',0)} | {h.get('title','')[:90]}")
