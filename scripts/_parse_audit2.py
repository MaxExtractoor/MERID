"""Extract HIGH schrodinbug and memory_leak findings."""
import json

with open("docs/bug_audit_2026-03-14.json") as f:
    data = json.load(f)

for cat in ["schrodinbug", "memory_leak"]:
    findings = data["findings"].get(cat, [])
    high = [f for f in findings if f["severity"] == "HIGH"]
    print(f"\n=== {cat} ({len(high)} HIGH) ===")
    for h in high:
        print(f"  {h['file']}:{h['line']} | {h['title'][:100]}")
