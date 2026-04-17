"""List all silent except:pass locations from the audit results."""
import json
import os

with open(os.path.join("data", "audit_sweep_results.json")) as f:
    data = json.load(f)

print("=== SILENT_EXCEPT_PASS ===")
for item in data.get("SILENT_EXCEPT_PASS", []):
    print(f"  {item['file']}:{item['line']}  {item['detail'][:90]}")

print(f"\nTotal: {len(data.get('SILENT_EXCEPT_PASS', []))}")

print("\n=== UNBOUNDED_COLLECTION ===")
for item in data.get("UNBOUNDED_COLLECTION", []):
    print(f"  {item['file']}:{item['line']}  {item['detail'][:90]}")

print(f"\nTotal: {len(data.get('UNBOUNDED_COLLECTION', []))}")

print("\n=== MEMORY_NO_EVICTION ===")
for item in data.get("MEMORY_NO_EVICTION", []):
    print(f"  {item['file']}:{item['line']}  {item['detail'][:90]}")

print(f"\nTotal: {len(data.get('MEMORY_NO_EVICTION', []))}")

print("\n=== OVER_AUTONOMY ===")
for item in data.get("OVER_AUTONOMY", []):
    print(f"  {item['file']}:{item['line']}  {item['detail'][:90]}")

print(f"\nTotal: {len(data.get('OVER_AUTONOMY', []))}")

print("\n=== NO_CROSS_VALIDATION ===")
for item in data.get("NO_CROSS_VALIDATION", []):
    print(f"  {item['file']}:{item['line']}  {item['detail'][:90]}")

print(f"\nTotal: {len(data.get('NO_CROSS_VALIDATION', []))}")
